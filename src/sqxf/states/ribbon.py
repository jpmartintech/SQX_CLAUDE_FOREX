"""EMA ribbon market states (Phase S). All parameters are fixed a priori in configs/states_ribbon.yaml (never fitted).

Per timeframe, three descriptors, each discretised to 3 levels with hysteresis (state machines; causal):
* ORDER  (-1 bear, 0 mixed, +1 bull): score = sum over the 6 adjacent pairs of sign(EMA_fast - EMA_slow), in [-6, 6].
* WIDTH  (0 compressed, 1 normal, 2 expanded): (max EMA - min EMA) / ATR14, as a causal rolling percentile.
* SLOPE  (-1 down, 0 flat, +1 up): (EMA_mid[t] - EMA_mid[t-k]) / ATR14[t].
Per-timeframe state = 9 * (order + 1) + 3 * width + (slope + 1) in 0..26.
Combined multi-timeframe state on the base (H1) bars, at most 27: regime from D1 and H8 order (UP / RANGE / DOWN), H4 slope,
H1 order: 9 * (regime + 1) + 3 * (h4_slope + 1) + (h1_order + 1).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from numba import njit

from sqxf.features.bank import atr as atr_sma


def emas(close: np.ndarray, periods) -> np.ndarray:
    c = pd.Series(close)
    return np.stack([c.ewm(span=p, adjust=False, min_periods=p).mean().to_numpy() for p in periods])


@njit(cache=True)
def hysteresis3(x, enter_hi, stay_hi, enter_lo, stay_lo):
    """3-level state machine: +1 entered when x >= enter_hi and kept while x >= stay_hi; -1 entered when x <= enter_lo and
    kept while x <= stay_lo; else 0. NaN input -> NaN state and reset."""
    n = len(x)
    out = np.full(n, np.nan)
    s = 0.0
    valid = False
    for i in range(n):
        v = x[i]
        if np.isnan(v):
            out[i] = np.nan
            valid = False
            continue
        if not valid:
            s = 0.0
            valid = True
        if s == 1.0:
            if v < stay_hi:
                s = 0.0
        elif s == -1.0:
            if v > stay_lo:
                s = 0.0
        if s == 0.0:
            if v >= enter_hi:
                s = 1.0
            elif v <= enter_lo:
                s = -1.0
        out[i] = s
    return out


def descriptors(bars: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    """Raw descriptors and discretised levels for one timeframe (causal: value at bar t uses bars <= t only)."""
    close = bars["close"].to_numpy(float)
    e = emas(close, cfg["ema_periods"])
    a = atr_sma(bars["high"].to_numpy(float), bars["low"].to_numpy(float), close, cfg["atr_period"])
    with np.errstate(invalid="ignore"):
        score = np.sign(e[:-1] - e[1:]).sum(axis=0)
    score[np.isnan(e).any(axis=0)] = np.nan
    width = (e.max(axis=0) - e.min(axis=0)) / a  # NaN while any EMA is warming up
    w = cfg["width"]
    pct = pd.Series(width).rolling(w["percentile_window"] + 1, min_periods=w["percentile_window"] + 1).rank(pct=True).to_numpy()
    s = cfg["slope"]
    mid = e[list(cfg["ema_periods"]).index(s["ema"])]
    slope = (mid - np.r_[np.full(s["lag"], np.nan), mid[:-s["lag"]]]) / a
    o = cfg["order"]
    order_l = hysteresis3(score, o["enter_bull"], o["stay_bull"], -o["enter_bull"], -o["stay_bull"])
    # width: +1 = expanded, -1 = compressed (mapped to 2 / 0 below)
    width_l = hysteresis3(pct, w["enter_expanded"], w["stay_expanded"], w["enter_compressed"], w["stay_compressed"])
    slope_l = hysteresis3(slope, s["enter_up"], s["stay_up"], -s["enter_up"], -s["stay_up"])
    state = 9 * (order_l + 1) + 3 * (width_l + 1) + (slope_l + 1)
    return pd.DataFrame({"order_score": score, "width": width, "width_pct": pct, "slope": slope, "atr": a,
                         "order": order_l, "width_level": width_l + 1, "slope_dir": slope_l, "state": state})


def combined_state(base: pd.DataFrame, aligned: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Combined state on base (H1) bars from aligned per-timeframe descriptors (D1/H8 regime, H4 slope, H1 order)."""
    d1, h8 = aligned["D1"]["order"].to_numpy(), aligned["H8"]["order"].to_numpy()
    regime = np.where((d1 == 1) & (h8 == 1), 1.0, np.where((d1 == -1) & (h8 == -1), -1.0, 0.0))
    regime[np.isnan(d1) | np.isnan(h8)] = np.nan
    h4s = aligned["H4"]["slope_dir"].to_numpy()
    h1o = aligned["H1"]["order"].to_numpy()
    state = 9 * (regime + 1) + 3 * (h4s + 1) + (h1o + 1)
    return pd.DataFrame({"regime": regime, "h4_slope": h4s, "h1_order": h1o, "state": state}, index=base.index)
