"""Crypto C1: walk-forward evaluation of the discovery procedure (genetic re-optimised per window, top-K frozen and traded
in the next 6 months), a matched random-timing control and buy & hold benchmarks. Everything is driven by the committed
pre-registration (configs/crypto_c1_*.yaml); this module holds no thresholds.
"""
from __future__ import annotations

import math
from collections.abc import Callable

import numpy as np
import pandas as pd

from sqxf.backtest.evaluator import Market, evaluate_rich
from sqxf.funnel.pipeline import daily_returns, window
from sqxf.funnel.wf_procedure import day_dates, generate, select_top_k


# ------------------------------------------------------------------ folds
def crypto_folds(market: Market, cfg: dict) -> list[dict]:
    f = cfg["folds"]
    out = []
    for i, (a, b) in enumerate(f["oos_windows"]):
        a_ts = pd.Timestamp(a)
        start = a_ts - pd.DateOffset(months=f["train_months"])
        edges = [start + (a_ts - start) * k / f["train_blocks"] for k in range(f["train_blocks"] + 1)]
        edges = [e.normalize() for e in edges]
        blocks = [window(market, str(x), str(y)) for x, y in zip(edges[:-1], edges[1:], strict=True)]
        out.append({"fold": i, "year": i, "label": f"{a}..{b}", "train_blocks": blocks,
                    "train": (blocks[0][0], blocks[-1][1]), "oos": window(market, a, b), "oos_dates": (a, b)})
    return out


# ------------------------------------------------------------------ one variant
def trade_window(market: Market, chosen: list, fold: dict, coin: str, tf: str) -> tuple[pd.DataFrame, np.ndarray]:
    """OOS trades of the frozen strategies (costs and funding x1 and x2) and the equal-weight daily return of the coin."""
    rows = []
    w = fold["oos"]
    daily = None
    for s in chosen:
        r1 = evaluate_rich(market, s, exec_tf=tf, window=w).trades
        r2 = evaluate_rich(market, s, exec_tf=tf, window=w, cost_multiplier=2.0, funding_multiplier=2.0).trades
        if len(r1):
            df = r1[["signal_idx", "entry_idx", "exit_idx", "bars_held", "entry_price", "exit_price", "risk", "r",
                     "funding", "frac", "entry_time"]].copy()
            df["r_x2"] = r2["r"].to_numpy()
            df["direction"] = s.sign
            df["strategy"] = s.canonical_hash
            df["coin"] = coin
            df["fold"] = fold["fold"]
            rows.append(df)
        d = daily_returns(market, s, tf, w)
        daily = d if daily is None else daily + d
    ex = market.execs[tf]
    first = int(ex.day_id[ex.h1_start[w[0]]])
    n_days = int(ex.day_id[ex.h1_end[w[1] - 1] - 1]) - first + 1
    daily = np.zeros(n_days) if daily is None else daily / len(chosen)
    trades = pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()
    return trades, pd.Series(daily, index=day_dates(market)[first:first + n_days])


def run_variant(markets: dict[str, Market], cfg: dict, variant: dict, log: Callable[[str], None] | None = None) -> dict:
    """Genetic procedure on every coin and OOS window. Returns trades, the 8-coin equal-weight daily portfolio and counts."""
    run_cfg = {**cfg, "exec_timeframe_train": variant["exec_timeframe_train"],
               "exec_timeframe_oos": variant["exec_timeframe_oos"]}
    all_trades, coin_daily, evaluated, selected, chosen_map = [], {}, 0, {}, {}
    for coin, mk in markets.items():
        series = []
        for fold in crypto_folds(mk, cfg):
            seed = cfg["seed"] + cfg["coin_seed_offsets"][coin] + fold["fold"]
            strategies, fit = generate(mk, fold, run_cfg, "genetic", seed)
            evaluated += len(strategies)
            chosen = select_top_k(mk, fold, strategies, fit, run_cfg)
            selected[(coin, fold["fold"])] = [s.canonical_hash for s in chosen]
            chosen_map[(coin, fold["fold"])] = chosen
            tr, daily = trade_window(mk, chosen, fold, coin, variant["exec_timeframe_oos"])
            if len(tr):
                all_trades.append(tr)
            series.append(daily)
            if log:
                log(f"{coin} {fold['label']}: selected {len(chosen)} trades {len(tr)} "
                    f"mean R {tr['r'].mean() if len(tr) else float('nan'):+.4f}")
        coin_daily[coin] = pd.concat(series)
    trades = pd.concat(all_trades, ignore_index=True) if all_trades else pd.DataFrame()
    port = pd.concat(coin_daily, axis=1).sort_index().fillna(0.0).mean(axis=1)  # cash when a coin has nothing selected
    return {"trades": trades, "portfolio_daily": port, "evaluated": evaluated, "selected": selected,
            "strategies": chosen_map}


def summarize(res: dict, cfg: dict) -> dict:
    t, port = res["trades"], res["portfolio_daily"]
    dpy = float(cfg["days_per_year"])

    def stats(x: pd.DataFrame) -> dict:
        if len(x) == 0:
            return {"trades": 0, "mean_r_x1": None, "mean_r_x2": None}
        r = x["r"].to_numpy()
        return {"trades": int(len(x)), "mean_r_x1": float(r.mean()), "mean_r_x2": float(x["r_x2"].mean()),
                "t_x1": float(r.mean() / r.std() * math.sqrt(len(r))) if len(r) > 1 and r.std() > 0 else None,
                "win_rate": float((r > 0).mean()), "mean_funding_r": float((x["funding"] / x["risk"]).mean())}

    eq = np.cumprod(1 + port.to_numpy())
    peak = np.maximum.accumulate(np.r_[1.0, eq])[1:]
    sd = port.std(ddof=0)
    yr = pd.to_datetime(t["entry_time"]).dt.year if len(t) else pd.Series(dtype=int)
    out = {"evaluated": res["evaluated"], "pooled": stats(t),
           "excluding_2021": stats(t[yr != 2021]) if len(t) else stats(t),
           "by_direction": {d: stats(t[t["direction"] == s]) for d, s in (("long", 1), ("short", -1))} if len(t) else {},
           "by_coin": {c: stats(t[t["coin"] == c]) for c in cfg["universe"]["per_coin"] + cfg["universe"]["aggregate_only"]}
           if len(t) else {},
           "by_window": {w[0]: stats(t[t["fold"] == i]) for i, w in enumerate(cfg["folds"]["oos_windows"])}
           if len(t) else {},
           "portfolio": {"days": int(len(port)), "sharpe": float(port.mean() / sd * math.sqrt(dpy)) if sd > 0 else 0.0,
                         "return": float(eq[-1] - 1) if len(eq) else 0.0,
                         "max_dd": float((1 - eq / peak).max()) if len(eq) else 0.0}}
    return out


# ------------------------------------------------------------------ matched random-timing control
def _funding_cumsums(ex) -> dict:
    fr, fr_abs = ex.funding_arrays()
    out = {}
    for d in (1, -1):
        pay = -d * fr * ex.o - fr_abs * ex.o
        out[d] = np.cumsum(pay)
    return out


def matched_control(markets: dict[str, Market], trades: pd.DataFrame, cfg: dict, replicas: int, seed: int,
                    tf: str = "M15") -> dict:
    """Replicate every selected strategy's OOS trades with random, non-overlapping entry bars among the tradable signal
    bars of the same window: same count, direction, bars held and stop distance (as a fraction of the entry price); time
    exit at the close of the last held bar; same relative costs and funding (x1). Returns pooled mean R per replica."""
    rng = np.random.default_rng(seed)
    if len(trades) == 0:
        return {"pooled_mean_r_x1": np.full(replicas, np.nan), "placed_share": 0.0}
    prep = {}
    for coin, mk in markets.items():
        ex = mk.execs[tf]
        prep[coin] = (mk, ex, _funding_cumsums(ex), mk.cost_rel_array())
    groups = []
    for (coin, fold, _strat), g in trades.groupby(["coin", "fold", "strategy"], sort=True):
        mk = prep[coin][0]
        w = crypto_folds(mk, cfg)[fold]["oos"]
        allowed = np.flatnonzero(mk.tradable[w[0]:w[1]]) + w[0]  # signal bars t; entry e = t + 1
        groups.append((coin, w, allowed, g["bars_held"].to_numpy(), g["direction"].to_numpy(),
                       (g["risk"] / g["entry_price"]).to_numpy()))
    sums = np.zeros(replicas)
    counts = np.zeros(replicas)
    placed = attempted = 0
    for rep in range(replicas):
        for coin, w, allowed, held, dirs, stop_pct in groups:
            mk, ex, fcs, cost_rel = prep[coin]
            busy = np.zeros(w[1] - w[0] + 1, dtype=bool)
            order = rng.permutation(len(held))
            for j in order:
                attempted += 1
                hb = int(held[j])
                for _ in range(50):
                    t = int(allowed[rng.integers(len(allowed))]) if len(allowed) else -1
                    e = t + 1
                    last = e + hb - 1
                    if t < 0 or last > w[1] - 1 or busy[t - w[0]:last - w[0] + 1].any():
                        continue
                    busy[t - w[0]:last - w[0] + 1] = True
                    k0, kx = int(ex.h1_start[e]), int(ex.h1_end[last]) - 1
                    entry, px, d = ex.o[k0], ex.c[kx], int(dirs[j])
                    fund = fcs[d][kx] - fcs[d][k0]
                    risk = stop_pct[j] * entry
                    r = (d * (px - entry) - cost_rel[t] * entry + fund) / risk
                    sums[rep] += r
                    counts[rep] += 1
                    placed += 1
                    break
    return {"pooled_mean_r_x1": sums / np.maximum(counts, 1), "placed_share": placed / max(attempted, 1)}


# ------------------------------------------------------------------ buy & hold
def buy_and_hold(markets: dict[str, Market], spot_m15: dict[str, pd.DataFrame], cfg: dict) -> pd.DataFrame:
    """Per coin and OOS window: long 1x from the first M15 open to the last M15 close of the window, one round trip of
    costs (fee + liquidity-band slippage at the first signal bar). Spot: spot prices, no funding. Perp: perpetual prices and
    funding paid while held."""
    rows = []
    fee = cfg["instrument"]["taker_fee_per_side"]
    for coin, mk in markets.items():
        ex = mk.execs["M15"]
        fr, fr_abs = ex.funding_arrays()
        spot = spot_m15[coin]
        for fold in crypto_folds(mk, cfg):
            t0, t1 = fold["oos"]
            k0, kx = int(ex.h1_start[t0]), int(ex.h1_end[t1 - 1]) - 1
            cost = float(mk.cost_rel_array()[t0]) if mk.tradable[t0] else 2 * (fee + 0.0005)
            perp_ret = ex.c[kx] / ex.o[k0] - 1 - cost - float(((fr[k0 + 1:kx + 1] + fr_abs[k0 + 1:kx + 1])
                                                               * ex.o[k0 + 1:kx + 1]).sum()) / ex.o[k0]
            a, b = fold["oos_dates"]
            sp = spot[(spot["ts_local"] >= pd.Timestamp(a)) & (spot["ts_local"] < pd.Timestamp(b))]
            spot_ret = sp["close"].iat[-1] / sp["open"].iat[0] - 1 - cost
            rows.append({"coin": coin, "window": a, "spot": float(spot_ret), "perp": float(perp_ret)})
    return pd.DataFrame(rows)
