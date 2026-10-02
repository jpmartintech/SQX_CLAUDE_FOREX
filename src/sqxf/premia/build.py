"""Data panels and target weights of the 5 C2 hypotheses (configs/premia_c2.yaml). Every target at row d only uses data
known at the close of day d (closes <= d, funding events <= the close of d, liquidity median up to d-1)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from sqxf.crypto.data import CryptoConfig, build_bars, daily_liquidity, load_hybrid_m15, read_funding, slippage_for
from sqxf.data.m15 import load_m15_period
from sqxf.provenance import load_config
from sqxf.states.bars import build_local_bars

HIST_DAYS, VOL_DAYS = 120, 60
LOOKBACKS = (20, 60, 120)
SWAP_NIGHTS = {0: 0, 1: 1, 2: 1, 3: 3, 4: 1, 5: 0, 6: 0}


def _align(close: pd.Series, cal: pd.DatetimeIndex) -> tuple[np.ndarray, int]:
    """Close on the calendar, last close carried over days without a bar (counted, inside the asset's span only)."""
    s = close.reindex(cal)
    first, last = close.index.min(), close.index.max()
    span = (cal >= first) & (cal <= last)
    missing = int((s.isna() & span).sum())
    return s.ffill().to_numpy(float), missing


def _returns(close: np.ndarray) -> np.ndarray:
    r = np.zeros_like(close)
    with np.errstate(invalid="ignore", divide="ignore"):
        r[1:] = close[1:] / close[:-1] - 1.0
    return np.nan_to_num(r)


def _vol(close: np.ndarray, per_year: float) -> np.ndarray:
    with np.errstate(invalid="ignore", divide="ignore"):
        lr = pd.DataFrame(np.log(close)).diff()
    return (lr.rolling(VOL_DAYS, min_periods=VOL_DAYS).std() * np.sqrt(per_year)).to_numpy()


def _history(close: np.ndarray) -> np.ndarray:
    valid = np.isfinite(close)
    return np.cumsum(valid, axis=0)


# ------------------------------------------------------------------ crypto
def crypto_panel(c2: dict, c1: dict) -> dict:
    ccfg = CryptoConfig.load()
    coins = c2["data"]["crypto_universe"]
    switch = c1["prices"]["perp_from_utc"]
    frames = {}
    for c in coins:
        hyb, spot = load_hybrid_m15(c, switch[c], ccfg, until="development")
        frames[c] = (build_bars(hyb, "1D"), build_bars(spot, "1D"), daily_liquidity(spot, ccfg["liquidity"]["window_days"]),
                     read_funding(c, ccfg, ccfg.selection_start))
    start = min(f[0]["ts_local"].min() for f in frames.values())
    end = max(f[0]["ts_local"].max() for f in frames.values())
    cal = pd.date_range(start, end, freq="D")
    n, k = len(cal), len(coins)
    out = {"cal": cal, "coins": coins, "missing": {}, "funding_unplaced": {}}
    hyb_c, spot_c, liq, fund = (np.full((n, k), np.nan) for _ in range(4))
    for j, c in enumerate(coins):
        hb, sb, lq, fr = frames[c]
        hyb_c[:, j], mh = _align(hb.set_index("ts_local")["close"], cal)
        spot_c[:, j], ms = _align(sb.set_index("ts_local")["close"], cal)
        liq[:, j] = lq["trailing_median"].reindex(cal).to_numpy()
        day = (fr.index - pd.Timedelta(minutes=1)).normalize()          # event in (D 00:00, D+1 00:00] -> day D
        fd = fr.groupby(day).sum().reindex(cal)
        fund[:, j] = fd.fillna(0.0).to_numpy()
        out["missing"][c] = {"hybrid_days": mh, "spot_days": ms}
    perp_ok = np.stack([cal >= pd.Timestamp(switch[c]) for c in coins], axis=1)
    vol = _vol(hyb_c, 365.0)
    liquid = np.nan_to_num(liq) >= ccfg["liquidity"]["min_median_usd"]
    elig = perp_ok & (_history(hyb_c) >= HIST_DAYS) & np.isfinite(vol) & liquid
    slip = slippage_for(np.nan_to_num(liq).ravel(), ccfg["liquidity"]["slippage_bands"]).reshape(n, k)
    slip = np.where(np.isfinite(slip), slip, max(b[1] for b in ccfg["liquidity"]["slippage_bands"]))
    out.update({"hyb_close": hyb_c, "spot_close": spot_c, "ret_perp": _returns(hyb_c), "ret_spot": _returns(spot_c),
                "funding": fund, "vol": vol, "eligible": elig, "slip": slip, "liq": liq})
    return out


def _schedule(cal: pd.DatetimeIndex, kind: str, start: str) -> np.ndarray:
    first = cal.get_loc(pd.Timestamp(start)) - 1                          # close of the day before the window
    if kind == "daily":
        m = np.ones(len(cal), bool)
    elif kind == "weekly":
        m = np.asarray(cal.dayofweek == 6)                               # Sunday bar closes Monday 00:00 UTC
    elif kind == "monthly":
        m = np.asarray((cal + pd.Timedelta(days=1)).day == 1)            # last day of the month
    else:
        raise ValueError(kind)
    m[:first] = False
    m[first] = True
    return m


def _xs_weights(score: np.ndarray, elig: np.ndarray, vol: np.ndarray, long_high: bool) -> np.ndarray:
    w = np.zeros(len(score))
    idx = np.flatnonzero(elig & np.isfinite(score))
    if len(idx) < 3:
        return w
    m = len(idx) // 3
    order = idx[np.argsort(score[idx], kind="stable")]
    low, high = order[:m], order[-m:]
    longs, shorts = (high, low) if long_high else (low, high)
    for side, sgn in ((longs, 1.0), (shorts, -1.0)):
        iv = 1.0 / vol[side]
        w[side] = sgn * 0.5 * iv / iv.sum()
    return w


def crypto_hypothesis(p: dict, name: str, fees: dict, start: str) -> dict:
    """Arrays for the simulator: ret, c_lin, c_abs, cost, targets, groups, asset names."""
    cal, coins, k = p["cal"], p["coins"], len(p["coins"])
    n = len(cal)
    elig, vol, close = p["eligible"], p["vol"], p["hyb_close"]
    perp_cost = fees["perp"] + p["slip"]
    if name == "H1_funding_carry":
        reb = _schedule(cal, "monthly", start)
        tg = np.full((n, 2 * k), np.nan)
        for d in np.flatnonzero(reb):
            e = elig[d]
            w = np.zeros(2 * k)
            if e.any():
                w[:k][e], w[k:][e] = 1.0 / e.sum(), -1.0 / e.sum()
            tg[d] = w
        return {"ret": np.c_[p["ret_spot"], p["ret_perp"]], "c_lin": np.c_[np.zeros((n, k)), -p["funding"]],
                "c_abs": np.zeros((n, 2 * k)), "cost": np.c_[fees["spot"] + p["slip"], perp_cost], "targets": tg,
                "groups": np.r_[np.arange(k), np.arange(k)],
                "assets": [f"{c}_spot" for c in coins] + [f"{c}_perp" for c in coins]}
    tg = np.full((n, k), np.nan)
    if name == "H2_funding_extreme_xs":
        reb = _schedule(cal, "weekly", start)
        f7 = pd.DataFrame(p["funding"]).rolling(7, min_periods=7).sum().to_numpy()
        for d in np.flatnonzero(reb):
            tg[d] = _xs_weights(f7[d], elig[d], vol[d], long_high=False)
    elif name == "H3_tsmom_crypto":
        reb = _schedule(cal, "daily", start)
        sig = tsmom_signal(close)
        for d in np.flatnonzero(reb):
            tg[d] = inverse_vol_gross1(sig[d], elig[d], vol[d])
    elif name == "H4_xsmom_crypto":
        reb = _schedule(cal, "weekly", start)
        score = np.full_like(close, np.nan)
        score[28:] = close[21:-7] / close[:-28] - 1.0                    # close(d-7) / close(d-28) - 1
        for d in np.flatnonzero(reb):
            tg[d] = _xs_weights(score[d], elig[d], vol[d], long_high=True)
    else:
        raise ValueError(name)
    return {"ret": p["ret_perp"], "c_lin": -p["funding"], "c_abs": np.zeros((n, k)), "cost": perp_cost, "targets": tg,
            "groups": np.arange(k), "assets": [f"{c}_perp" for c in coins]}


def tsmom_signal(close: np.ndarray) -> np.ndarray:
    s = np.zeros_like(close)
    for lb in LOOKBACKS:
        r = np.full_like(close, np.nan)
        r[lb:] = close[lb:] / close[:-lb] - 1.0
        s += np.sign(np.nan_to_num(r))
    return s / len(LOOKBACKS)


def inverse_vol_gross1(sig: np.ndarray, elig: np.ndarray, vol: np.ndarray) -> np.ndarray:
    w = np.zeros(len(sig))
    e = elig & np.isfinite(vol) & (vol > 0)
    if e.any():
        iv = 1.0 / vol[e]
        w[e] = sig[e] * iv / iv.sum()
    return w


# ------------------------------------------------------------------ forex
def forex_panel(c2: dict) -> dict:
    pairs = c2["data"]["forex_pairs"]
    costs = load_config("costs")
    swap = load_config("swap")
    bars = {}
    for pr in pairs:
        m15 = load_m15_period(pr, None, c2["data"]["forex_until"])
        d1 = build_local_bars(m15, "D1")
        bars[pr] = d1.set_index("bucket_start_local")["close"]
    cal = pd.DatetimeIndex(sorted(set().union(*[b.index for b in bars.values()])))
    n, k = len(cal), len(pairs)
    close = np.full((n, k), np.nan)
    missing = {}
    for j, pr in enumerate(pairs):
        close[:, j], missing[pr] = _align(bars[pr], cal)
    pip = np.array([costs["pairs"][pr]["pip"] for pr in pairs])
    side = np.array([costs["pairs"][pr]["spread_pips"] / 2 + costs["default_slippage_pips_per_side"] for pr in pairs])
    sw = np.array([max(swap["pairs"][pr]["long"], swap["pairs"][pr]["short"]) for pr in pairs])
    nights = np.array([SWAP_NIGHTS[d] for d in cal.dayofweek], float)
    prev = np.vstack([close[:1], close[:-1]])
    vol = _vol(close, 260.0)
    elig = (_history(close) >= HIST_DAYS) & np.isfinite(vol) & (vol > 0)
    return {"cal": cal, "pairs": pairs, "close": close, "ret": _returns(close), "vol": vol, "eligible": elig,
            "cost": np.nan_to_num(side * pip / close, nan=0.0), "c_abs": np.nan_to_num(nights[:, None] * sw * pip / prev),
            "missing": missing}


def forex_hypothesis(p: dict, start: str, vol_target: float = 0.10, cap: float = 5.0) -> dict:
    cal, k = p["cal"], len(p["pairs"])
    n = len(cal)
    first = int(np.searchsorted(cal, pd.Timestamp(start))) - 1
    sig = tsmom_signal(p["close"])
    tg = np.full((n, k), np.nan)
    for d in range(first, n):
        e = p["eligible"][d]
        w = np.zeros(k)
        if e.any():
            w[e] = np.clip(sig[d][e] * (vol_target / np.sqrt(e.sum())) / p["vol"][d][e], -cap, cap)
        tg[d] = w
    return {"ret": p["ret"], "c_lin": np.zeros((n, k)), "c_abs": p["c_abs"], "cost": p["cost"], "targets": tg,
            "groups": np.arange(k), "assets": list(p["pairs"])}
