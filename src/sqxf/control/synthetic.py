"""Synthetic worlds for the positive control of the Phase S funnel (configs/positive_control.yaml).

* Null world: complete development days (96 M15 bars in all pairs) shuffled without replacement, the SAME day order for every
  pair, laid on a synthetic weekday calendar; bar shapes (open gap, high/low/close vs open, in logs) are kept, prices rebuilt.
* Causal state edge: drift added to H1 bar u iff the NULL-world combined state was the target in [u-24, u-1].
* Causal H4 momentum: AR(1) of H4 log returns, inj_k = phi * R_{k-1}.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from sqxf.data.m15 import DataConfig, canonicalize, load_m15_period, trading_date


# ------------------------------------------------------------------ development shapes
def load_dev_shapes(pairs: list[str], start: str, end: str) -> dict:
    frames = {p: load_m15_period(p, start, end) for p in pairs}
    complete = None
    for df in frames.values():
        cnt = trading_date(df["ts_local"]).value_counts()
        days = set(cnt.index[cnt == 96])
        complete = days if complete is None else complete & days
    days = np.array(sorted(complete), dtype="datetime64[ns]")
    out = {"days": days, "pairs": {}}
    for p, df in frames.items():
        o, h, l, c = (df[k].to_numpy(float) for k in ("open", "high", "low", "close"))
        prev = np.r_[o[0], c[:-1]]
        shapes = np.stack([np.log(o / prev), np.log(h / o), np.log(l / o), np.log(c / o)], axis=1)
        td = trading_date(df["ts_local"]).to_numpy().astype("datetime64[ns]")
        first = pd.Series(np.arange(len(td))).groupby(td).first()
        starts = first.reindex(pd.DatetimeIndex(days)).to_numpy().astype(np.int64)
        out["pairs"][p] = {"shapes": shapes, "day_start": starts, "volume": df["volume"].to_numpy(float), "o0": o[0]}
    return out


def calendar(start: str, n_days: int) -> pd.DatetimeIndex:
    days = pd.bdate_range(start, periods=n_days)
    return pd.DatetimeIndex((days.values[:, None] + (np.arange(96) * np.timedelta64(15, "m"))[None, :]).ravel())


def rebuild(o0: float, shapes: np.ndarray) -> tuple[np.ndarray, ...]:
    g, hh, ll, cc = (shapes[:, i].copy() for i in range(4))
    g[0] = 0.0
    opn = np.exp(np.log(o0) + np.r_[0.0, np.cumsum(cc)[:-1]] + np.cumsum(g))
    close = opn * np.exp(cc)
    high = np.maximum(opn * np.exp(hh), np.maximum(opn, close))
    low = np.minimum(opn * np.exp(ll), np.minimum(opn, close))
    return opn, high, low, close


def null_world_shapes(dev: dict, seed: int, n_days: int) -> dict:
    """Per pair: (shapes[n_days*96, 4], volume, o0) for a random day order shared by all pairs."""
    rng = np.random.default_rng(seed)
    order = rng.permutation(len(dev["days"]))[:n_days]
    out = {}
    for p, d in dev["pairs"].items():
        idx = (d["day_start"][order][:, None] + np.arange(96)[None, :]).ravel()
        out[p] = {"shapes": d["shapes"][idx].copy(), "volume": d["volume"][idx].copy(), "o0": d["o0"]}
    return out


def to_m15(shapes: dict, cal: pd.DatetimeIndex, cfg: DataConfig) -> pd.DataFrame:
    o, h, l, c = rebuild(shapes["o0"], shapes["shapes"])
    raw = pd.DataFrame({"ts_local": cal.astype("datetime64[ns]"), "open": o, "high": h, "low": l, "close": c,
                        "volume": shapes["volume"]})
    return canonicalize(raw, cfg)


# ------------------------------------------------------------------ injections (causal)
def inject_state_edge(shapes: dict, null_state_h1: np.ndarray, target: int, sign: int, gross_pips: float, pip: float,
                      horizon: int) -> dict:
    """Add sign * gross_pips / horizon pips (log, at the H1 bar's open) to every H1 bar u whose previous ``horizon`` bars
    contain the target NULL state; spread over its 4 M15 closes. Bars are contiguous (complete synthetic days)."""
    trig = (null_state_h1 == target).astype(np.int64)
    n = len(trig)
    cum = np.r_[0, np.cumsum(trig)]
    u = np.arange(n)
    lo = np.maximum(u - horizon, 0)
    active = (cum[u] - cum[lo]) > 0               # any trigger in [u - horizon, u - 1]
    o, _, _, _ = rebuild(shapes["o0"], shapes["shapes"])
    open_h1 = o[::4][:n]
    delta = np.where(active, sign * np.log1p(gross_pips / horizon * pip / open_h1) / 4.0, 0.0)
    new = {**shapes, "shapes": shapes["shapes"].copy()}
    new["shapes"][: 4 * n, 3] += np.repeat(delta, 4)
    return new


def inject_h4_ar(shapes: dict, phi: float) -> dict:
    """AR(1) on H4 log returns (16 M15 bars per bucket, contiguous days): inj_k = phi * R_{k-1}, spread over 16 closes."""
    s = shapes["shapes"].copy()
    n4 = len(s) // 16
    base = (s[: n4 * 16, 0] + s[: n4 * 16, 3]).reshape(n4, 16).sum(axis=1)
    inj = np.zeros(n4)
    prev_r = 0.0
    for k in range(n4):
        inj[k] = phi * prev_r
        prev_r = base[k] + inj[k]
    s[: n4 * 16, 3] += np.repeat(inj / 16.0, 16)
    return {**shapes, "shapes": s}
