"""Causal feature bank on H1 bars.

Every feature value at bar ``t`` uses only bars ``<= t`` (information closed at ``t``). Warm-up values are NaN, and any
predicate on NaN is False. Price-scale-free where thresholds are non-zero (ATR units, ratios), so grids work on JPY pairs too.
Adapted from the reference V1.7 bank (confirmed fractals, breakouts against prior swings) and rewritten.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

EMA_PERIODS = (10, 20, 50, 100, 200)
SLOPE_HORIZONS = (1, 3, 6, 12)
BREAKOUT_PERIODS = (10, 20, 50, 100)
ROC_PERIODS = (4, 8, 16, 32)
RSI_PERIODS = (14,)
WILLR_PERIODS = (7, 14, 28)
ATR_REGIME_PERIODS = (14, 28)
BB_PERIODS = (20, 50)
FRACTAL_DEPTHS = (2, 3, 5)
ATR_PERIOD = 14


def true_range(high: np.ndarray, low: np.ndarray, close: np.ndarray) -> np.ndarray:
    prev = np.r_[np.nan, close[:-1]]
    tr = np.fmax(high - low, np.fmax(np.abs(high - prev), np.abs(low - prev)))
    tr[0] = high[0] - low[0]
    return tr


def atr(high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int = ATR_PERIOD) -> np.ndarray:
    """Simple moving average of the true range (NaN during warm-up)."""
    return pd.Series(true_range(high, low, close)).rolling(period, min_periods=period).mean().to_numpy()


def wilder_rsi(close: np.ndarray, period: int) -> np.ndarray:
    d = pd.Series(close).diff()
    gain = d.clip(lower=0).ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    loss = (-d.clip(upper=0)).ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    with np.errstate(divide="ignore", invalid="ignore"):
        rsi = 100 - 100 / (1 + gain.to_numpy() / loss.to_numpy())
    rsi[(loss.to_numpy() == 0) & np.isfinite(gain.to_numpy())] = 100.0
    return rsi


def confirmed_structure(high: np.ndarray, low: np.ndarray, close: np.ndarray, depth: int) -> dict[str, np.ndarray]:
    """Fractal pivots confirmed at ``p + depth`` (never back-filled) and swing-structure features.

    Pivot high at ``p``: ``high[p]`` strictly above the ``depth`` highs on each side; published at ``t = p + depth``.
    ``swing_high[t]`` is the last pivot high confirmed strictly before ``t`` (so breakouts compare against prior swings).
    ``last`` encodes the latest swing comparison: 1 HH, 2 HL, 3 LH, 4 LL (0 before any, or on a simultaneous high+low event).
    """
    n, d = len(close), int(depth)
    if d < 1:
        raise ValueError("depth must be >= 1")
    hs, ls = pd.Series(high), pd.Series(low)
    pivot_h, pivot_l = hs.shift(d), ls.shift(d)
    left_h, left_l = hs.rolling(d).max().shift(d + 1), ls.rolling(d).min().shift(d + 1)
    right_h, right_l = hs.rolling(d).max(), ls.rolling(d).min()
    valid = np.arange(n) >= 2 * d
    fh = np.where(valid, ((pivot_h > left_h) & (pivot_h > right_h)).to_numpy(), np.nan)
    fl = np.where(valid, ((pivot_l < left_l) & (pivot_l < right_l)).to_numpy(), np.nan)
    state = np.full(n, np.nan)
    swing_high = np.full(n, np.nan)
    swing_low = np.full(n, np.nan)
    last_h = last_l = np.nan
    last_state = 0.0
    for t in range(n):
        swing_high[t], swing_low[t] = last_h, last_l
        if not valid[t]:
            continue
        h_ev, l_ev = fh[t] == 1, fl[t] == 1
        if h_ev and l_ev:
            last_state = 0.0
        elif h_ev and np.isfinite(last_h):
            if high[t - d] > last_h:
                last_state = 1.0
            elif high[t - d] < last_h:
                last_state = 3.0
        elif l_ev and np.isfinite(last_l):
            if low[t - d] > last_l:
                last_state = 2.0
            elif low[t - d] < last_l:
                last_state = 4.0
        if h_ev:
            last_h = high[t - d]
        if l_ev:
            last_l = low[t - d]
        state[t] = last_state
    return {"last": state, "fractal_high": fh, "fractal_low": fl,
            "break_high": close - swing_high, "break_low": close - swing_low}


def compute_features(h1: pd.DataFrame) -> dict[str, np.ndarray]:
    """All grammar features for an H1 frame (columns ``high``, ``low``, ``close``). Returns float64 arrays."""
    high = h1["high"].to_numpy(np.float64)
    low = h1["low"].to_numpy(np.float64)
    close = h1["close"].to_numpy(np.float64)
    c, hs, ls = pd.Series(close), pd.Series(high), pd.Series(low)
    tr = pd.Series(true_range(high, low, close))
    out: dict[str, np.ndarray] = {f"atr.{ATR_PERIOD}": atr(high, low, close, ATR_PERIOD)}
    atr14 = out[f"atr.{ATR_PERIOD}"]

    emas = {n: c.ewm(span=n, adjust=False, min_periods=n).mean() for n in EMA_PERIODS}
    for n, ema in emas.items():
        out[f"trend.close_ema.{n}"] = (c - ema).to_numpy()
        for k in SLOPE_HORIZONS:
            out[f"trend.ema_slope.{n}.{k}"] = (ema - ema.shift(k)).to_numpy()
        for slow in EMA_PERIODS:
            if n < slow:
                out[f"trend.ema_pair.{n}.{slow}"] = (ema - emas[slow]).to_numpy()
    for n in BREAKOUT_PERIODS:
        out[f"trend.breakout_high.{n}"] = (c - hs.rolling(n).max().shift(1)).to_numpy()
        out[f"trend.breakout_low.{n}"] = (c - ls.rolling(n).min().shift(1)).to_numpy()

    with np.errstate(divide="ignore", invalid="ignore"):
        for n in ROC_PERIODS:
            out[f"momentum.roc_atr.{n}"] = (c - c.shift(n)).to_numpy() / atr14
    for n in RSI_PERIODS:
        out[f"momentum.rsi.{n}"] = wilder_rsi(close, n)
    for n in WILLR_PERIODS:
        hi, lo = hs.rolling(n).max(), ls.rolling(n).min()
        out[f"momentum.willr.{n}"] = (-100 * (hi - c) / (hi - lo).replace(0, np.nan)).to_numpy()

    for n in ATR_REGIME_PERIODS:
        norm = tr.rolling(n).mean() / c
        out[f"volatility.atr_regime.{n}.50"] = (norm / norm.rolling(50).mean().shift(1) - 1).to_numpy()
    for n in BB_PERIODS:
        mid, std = c.rolling(n).mean(), c.rolling(n).std(ddof=0)
        upper, lower = mid + 2 * std, mid - 2 * std
        kc_mid = c.ewm(span=n, adjust=False, min_periods=n).mean()
        atr_n = tr.rolling(n).mean()
        kc_upper, kc_lower = kc_mid + 1.5 * atr_n, kc_mid - 1.5 * atr_n
        out[f"volatility.bb_upper.{n}.2"] = (c - upper).to_numpy()
        out[f"volatility.bb_lower.{n}.2"] = (c - lower).to_numpy()
        out[f"volatility.bb_middle.{n}.2"] = (c - mid).to_numpy()
        comp = np.full(len(c), np.nan)
        valid = (std.notna() & atr_n.notna() & kc_mid.notna()).to_numpy()
        inside = ((upper < kc_upper) & (lower > kc_lower)).to_numpy()
        outside = ((upper > kc_upper) & (lower < kc_lower)).to_numpy()
        comp[valid] = np.where(inside[valid], 1.0, np.where(outside[valid], -1.0, 0.0))
        out[f"volatility.compression.{n}.2.1.5"] = comp

    for d in FRACTAL_DEPTHS:
        for name, values in confirmed_structure(high, low, close, d).items():
            out[f"structure.{name}.{d}"] = values
    return {k: np.asarray(v, dtype=np.float64) for k, v in out.items()}
