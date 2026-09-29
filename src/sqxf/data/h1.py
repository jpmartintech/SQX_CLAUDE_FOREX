"""H1 bars derived from canonical M15, without look-ahead.

H1 bar labelled ``t`` (bar-open, clock hour) aggregates exactly the M15 bars with ``t <= ts < t + 1h``.
Hours without M15 bars do not exist (no forward fill, no synthetic bars). A bar is ``complete`` when it has 4 M15 bars;
its information is available at ``close_ts = t + 1h``. Local (EET) and UTC differ by whole hours, so the hour grid is the same.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from sqxf.data.m15 import utc_int_ns

HOUR_NS = 3_600_000_000_000


def build_h1(m15: pd.DataFrame) -> pd.DataFrame:
    """Aggregate canonical M15 (sorted, unique) into H1. Keeps the M15 index range of every hour."""
    utc_ns = utc_int_ns(m15["ts_utc"])
    if len(utc_ns) == 0:
        raise ValueError("empty M15 input")
    if (np.diff(utc_ns) <= 0).any():
        raise ValueError("M15 must be strictly increasing")
    key = utc_ns // HOUR_NS
    starts = np.flatnonzero(np.r_[True, key[1:] != key[:-1]])
    ends = np.r_[starts[1:], len(key)]
    o, h, l, c = (m15[k].to_numpy() for k in ("open", "high", "low", "close"))
    n = ends - starts
    ts_utc = pd.to_datetime(key[starts] * HOUR_NS, utc=True)
    ts_local = m15["ts_local"].to_numpy()[starts].astype("datetime64[h]").astype("datetime64[ns]")
    return pd.DataFrame({
        "ts_utc": ts_utc,
        "ts_local": ts_local,
        "close_ts_utc": ts_utc + pd.Timedelta(hours=1),
        "open": o[starts],
        "high": np.maximum.reduceat(h, starts),
        "low": np.minimum.reduceat(l, starts),
        "close": c[ends - 1],
        "volume": np.add.reduceat(m15["volume"].to_numpy(), starts),
        "n_m15": n.astype(np.int64),
        "m15_start": starts.astype(np.int64),
        "m15_end": ends.astype(np.int64),
        "complete": n == 4,
        "no_trade": np.logical_or.reduceat(m15["no_trade"].to_numpy(), starts),
        "day_id": m15["day_id"].to_numpy()[starts],
    })
