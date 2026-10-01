"""Phase S Part 2 machinery: forex markets on local-anchored bars, custom-signal evaluation (kernel), state-conditional
forward returns, circular block bootstrap, Holm, matched random control and the pre-registered calibration / rule signals.
No thresholds live here; everything comes from configs/states_ribbon.yaml.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from sqxf.backtest.evaluator import Costs, ExecData, Market, trades_frame
from sqxf.backtest.kernels import simulate_rich
from sqxf.backtest.swap import forex_swap_arrays
from sqxf.data.m15 import trading_date, utc_int_ns
from sqxf.features.bank import adx
from sqxf.features.bank import atr as atr_sma
from sqxf.features.predicates import pack_bits
from sqxf.states.bars import build_local_bars


# ------------------------------------------------------------------ markets
def bars_market(pair: str, m15: pd.DataFrame, tf: str, costs: Costs, swap_long: float, swap_short: float,
                atr_period: int = 14) -> Market:
    bars = build_local_bars(m15, tf)
    a = atr_sma(bars["high"].to_numpy(float), bars["low"].to_numpy(float), bars["close"].to_numpy(float), atr_period)
    with np.errstate(invalid="ignore"):
        tradable = bars["complete"].to_numpy() & ~bars["no_trade"].to_numpy() & np.isfinite(a) & (a > 0)
    starts, ends = bars["m15_start"].to_numpy(np.int64), bars["m15_end"].to_numpy(np.int64)
    idx = np.arange(len(bars), dtype=np.int64)
    fr, fr_abs = forex_swap_arrays(m15["ts_local"], m15["open"].to_numpy(), swap_long, swap_short, costs.pip)
    ex = ExecData(*(m15[k].to_numpy(np.float64) for k in ("open", "high", "low", "close")),
                  day_id=m15["day_id"].to_numpy(np.int64), h1_of=np.repeat(idx, ends - starts), h1_start=starts,
                  h1_end=ends, fr=fr, fr_abs=fr_abs)
    dates = trading_date(m15["ts_local"]).to_numpy().astype("datetime64[D]")
    day_dates = np.empty(int(m15["day_id"].max()) + 1, dtype="datetime64[D]")
    day_dates[m15["day_id"].to_numpy()] = dates
    return Market(pair=pair, h1=bars, features={"atr": a}, atr=a, tradable=tradable,
                  pred_bool=np.zeros((1, len(bars)), bool), pred_bits=pack_bits(np.zeros((1, len(bars)), bool)),
                  base_bits=pack_bits(tradable), execs={"M15": ex}, costs=costs, t0=0, t1=len(bars),
                  risk_per_trade=0.005, days_per_year=260.0,
                  meta={"tf": tf, "day_dates": day_dates, "pip": costs.pip, **m15.attrs},
                  ts_utc=utc_int_ns(bars["ts_utc"].dt.tz_localize("UTC") if bars["ts_utc"].dt.tz is None else bars["ts_utc"])
                  .astype("datetime64[ns]"))


def window_of(market: Market, start: str, end: str) -> tuple[int, int]:
    ts = market.h1["ts_local"].to_numpy()
    return int(np.searchsorted(ts, np.datetime64(start))), int(np.searchsorted(ts, np.datetime64(end)))


def run_signal(market: Market, signal: np.ndarray, direction: int, sl_atr: float, max_bars: int, trail_atr: float,
               exit_signal: np.ndarray | None, window: tuple[int, int], cost_mult: float = 1.0, swap_mult: float = 1.0
               ) -> tuple[pd.DataFrame, np.ndarray]:
    """Evaluate a boolean entry signal (one direction) with the Numba kernel on the M15 path. No target."""
    ex = market.execs["M15"]
    n = market.n_h1
    xs = np.zeros(n, np.bool_) if exit_signal is None else np.asarray(exit_signal, np.bool_)
    fr, fr_abs = ex.funding_arrays()
    rec, agg = simulate_rich(pack_bits(np.asarray(signal, bool)[None, :]), np.array([0, -1, -1, -1], dtype=np.int64), 1,
                             market.base_bits, market.atr, ex.h1_start, ex.h1_end, ex.h1_of, ex.o, ex.h, ex.l, ex.c,
                             ex.day_id, int(direction), float(sl_atr), math.inf, int(max_bars), 0,
                             market.costs.round_trip * cost_mult, market.risk_per_trade, market.days_per_year,
                             int(window[0]), int(window[1]), np.zeros(n), fr, fr_abs, float(swap_mult), math.inf,
                             float(trail_atr), xs)
    df = trades_frame(market, rec)
    if len(df):
        df["entry_local"] = market.h1["ts_local"].to_numpy()[df["entry_idx"].to_numpy()]
        df["exit_day"] = ex.day_id[df["exit_exec"].to_numpy()]
        df["direction"] = int(direction)
        df["pips"] = df["r"] * df["risk"] / market.costs.pip
    return df, agg


def daily_series(market: Market, trades: pd.DataFrame, window: tuple[int, int]) -> pd.Series:
    """Daily returns (trading dates) of the closed-trade equity of one sub-account over the window (0 on flat days)."""
    ex = market.execs["M15"]
    first = int(ex.day_id[ex.h1_start[window[0]]])
    last = int(ex.day_id[ex.h1_end[window[1] - 1] - 1])
    idx = market.meta["day_dates"][first:last + 1]
    out = pd.Series(0.0, index=pd.DatetimeIndex(idx))
    if len(trades):
        t = trades.sort_values("exit_exec")
        eq = t["equity_after"].to_numpy()
        days = t["exit_day"].to_numpy()
        lasts = np.r_[np.flatnonzero(np.diff(days) != 0), len(days) - 1]
        prev = np.r_[1.0, eq[lasts][:-1]]
        vals = eq[lasts] / prev - 1.0
        out.loc[pd.DatetimeIndex(market.meta["day_dates"][days[lasts]])] = vals
    return out


# ------------------------------------------------------------------ predictive test
def forward_net(bars: pd.DataFrame, direction: np.ndarray, horizon: int, pip: float, cost_pips: float) -> np.ndarray:
    """Net pips of entering at the open of bar t+1 and exiting at the close of bar t+h, signed by ``direction`` (NaN when
    the direction is 0/NaN or bar t+h does not exist)."""
    o, c = bars["open"].to_numpy(float), bars["close"].to_numpy(float)
    n = len(o)
    out = np.full(n, np.nan)
    t = np.arange(n - horizon)
    raw = (c[t + horizon] - o[t + 1]) / pip
    d = direction[t]
    ok = np.isfinite(d) & (d != 0)
    out[t[ok]] = d[ok] * raw[ok] - cost_pips
    return out


def block_bootstrap_means(state: np.ndarray, net: np.ndarray, n_states: int, block: int, resamples: int, seed: int
                          ) -> np.ndarray:
    """Circular block bootstrap over the time-ordered valid bars: ``(resamples, n_states)`` mean net per state (NaN if a
    state is absent from a resample)."""
    ok = np.isfinite(net) & np.isfinite(state)
    s, x = state[ok].astype(np.int64), net[ok]
    n = len(x)
    rng = np.random.default_rng(seed)
    n_blocks = int(math.ceil(n / block))
    out = np.full((resamples, n_states), np.nan)
    offs = np.arange(block)
    for b in range(resamples):
        starts = rng.integers(0, n, n_blocks)
        idx = ((starts[:, None] + offs[None, :]) % n).ravel()[:n]
        cnt = np.bincount(s[idx], minlength=n_states)
        tot = np.bincount(s[idx], weights=x[idx], minlength=n_states)
        with np.errstate(invalid="ignore", divide="ignore"):
            out[b] = np.where(cnt > 0, tot / cnt, np.nan)
    return out


def holm(p: np.ndarray) -> np.ndarray:
    p = np.asarray(p, float)
    m = len(p)
    order = np.argsort(p, kind="stable")
    adj = np.empty(m)
    running = 0.0
    for rank, i in enumerate(order):
        running = max(running, min(1.0, (m - rank) * p[i]))
        adj[i] = running
    return adj


# ------------------------------------------------------------------ matched random control (report-only)
def matched_control(market: Market, trades: pd.DataFrame, window: tuple[int, int], replicas: int, seed: int,
                    swap_mult: float = 1.0) -> np.ndarray:
    """Pooled mean R per replica: random non-overlapping entries among tradable bars of the window with the same number of
    trades, directions, bars held and stop distance (fraction of price); time exit; same costs and swap."""
    if len(trades) == 0:
        return np.full(replicas, np.nan)
    ex = market.execs["M15"]
    fr, fr_abs = ex.funding_arrays()
    cum = {}
    for d in (1, -1):
        pay = -d * fr * ex.o - fr_abs * ex.o
        pay = np.where(pay < 0, pay * swap_mult, pay)
        cum[d] = np.cumsum(pay)
    allowed = np.flatnonzero(market.tradable[window[0]:window[1]]) + window[0]
    held = trades["bars_held"].to_numpy()
    dirs = trades["direction"].to_numpy()
    stop_pct = (trades["risk"] / trades["entry_price"]).to_numpy()
    cost = market.costs.round_trip
    rng = np.random.default_rng(seed)
    res = np.full(replicas, np.nan)
    for r in range(replicas):
        busy = np.zeros(window[1] - window[0] + 1, dtype=bool)
        tot = cnt = 0.0
        for j in rng.permutation(len(held)):
            hb = int(held[j])
            for _ in range(50):
                t = int(allowed[rng.integers(len(allowed))])
                e, last = t + 1, t + hb
                if last > window[1] - 1 or busy[t - window[0]:last - window[0] + 1].any():
                    continue
                busy[t - window[0]:last - window[0] + 1] = True
                k0, kx = int(ex.h1_start[e]), int(ex.h1_end[last]) - 1
                d = int(dirs[j])
                entry = ex.o[k0]
                tot += (d * (ex.c[kx] - entry) - cost + (cum[d][kx] - cum[d][k0])) / (stop_pct[j] * entry)
                cnt += 1
                break
        res[r] = tot / cnt if cnt else np.nan
    return res


# ------------------------------------------------------------------ pre-registered signals
def _prev(x: np.ndarray) -> np.ndarray:
    return np.r_[np.nan, x[:-1]]


def calibration_signals(market: Market) -> dict:
    """H4: long if EMA50 > EMA200 and ADX14 > 25 (short mirrored); exit when EMA50 crosses back."""
    b = market.h1
    c = pd.Series(b["close"].to_numpy(float))
    e50 = c.ewm(span=50, adjust=False, min_periods=50).mean().to_numpy()
    e200 = c.ewm(span=200, adjust=False, min_periods=200).mean().to_numpy()
    ax = adx(b["high"].to_numpy(float), b["low"].to_numpy(float), b["close"].to_numpy(float), 14)
    with np.errstate(invalid="ignore"):
        return {1: (e50 > e200) & (ax > 25), -1: (e50 < e200) & (ax > 25), "exit_1": e50 < e200, "exit_-1": e50 > e200}


def rule_signals(combined: pd.DataFrame, aligned_h4: pd.DataFrame, rule: str) -> dict:
    """Entry and exit-signal arrays for R1..R4 on H1 bars (long = 1, short = -1, mirrored)."""
    reg, h4s, h1o = (combined[k].to_numpy(float) for k in ("regime", "h4_slope", "h1_order"))
    h4w, h4o = aligned_h4["width_level"].to_numpy(float), aligned_h4["order"].to_numpy(float)
    out = {}
    with np.errstate(invalid="ignore"):
        for d in (1, -1):
            if rule == "R1_trend_continuation":
                ent = (reg == d) & (h4s == d) & (h1o == d) & np.isfinite(_prev(h1o)) & (_prev(h1o) != d)
                ext = (reg != d) | (h4s == -d)
            elif rule == "R2_pullback_end":
                ent = (reg == d) & (h4s == d) & (_prev(h1o) == -d) & np.isfinite(h1o) & (h1o != -d)
                ext = reg != d
            elif rule == "R3_compression_release":
                ent = (_prev(h4w) == 0) & np.isfinite(h4w) & (h4w != 0) & (h4o == d) & np.isfinite(reg) & (reg != -d)
                ext = None
            elif rule == "R4_regime_change":
                ent = (reg == d) & np.isfinite(_prev(reg)) & (_prev(reg) != d)
                ext = reg != d
            else:
                raise ValueError(rule)
            out[d] = ent
            out[f"exit_{d}"] = ext
    return out
