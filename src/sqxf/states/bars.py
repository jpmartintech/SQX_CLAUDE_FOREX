"""Forex multi-timeframe bars from canonical M15 (EET/EEST local clock), without look-ahead.

Anchoring (docs/DECISIONS.md, Phase S):
* H1, H4, H8: local clock buckets aligned to 00:00 local (Europe/Athens): H4 starts at 00/04/08/12/16/20, H8 at 00/08/16.
  Because the local day closes at 17:00 New York, H4/H8 boundaries are the FX broker ("NY close") boundaries.
* D1: the FX trading day (``trading_date``: Sunday-evening bars belong to Monday), i.e. 00:00 -> 24:00 local.
* A bar is available at the END of its bucket (``available_utc``), even if its last M15 bars are missing; ``complete`` needs every
  M15 bar of the bucket (D1: at least 96). Multi-timeframe context only uses COMPLETE higher-timeframe bars whose
  ``available_utc`` is <= the close of the base bar (``align_closed``).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from sqxf.data.m15 import trading_date, utc_int_ns

TZ = "Europe/Athens"
HOUR_NS = 3_600_000_000_000
TIMEFRAMES = {"H1": 1, "H4": 4, "H8": 8, "D1": 24}


def build_local_bars(m15: pd.DataFrame, tf: str) -> pd.DataFrame:
    hours = TIMEFRAMES[tf]
    local = m15["ts_local"]
    if tf == "D1":
        start_local = trading_date(local)
        key = start_local.to_numpy().astype("datetime64[ns]").astype(np.int64)
        expected = 96
    else:
        lns = local.to_numpy().astype("datetime64[ns]").astype(np.int64)
        key = (lns // (hours * HOUR_NS)) * (hours * HOUR_NS)
        expected = hours * 4
    if (np.diff(key) < 0).any():
        raise ValueError("bucket keys must be non-decreasing")
    starts = np.flatnonzero(np.r_[True, key[1:] != key[:-1]])
    ends = np.r_[starts[1:], len(key)]
    o, h, l, c = (m15[k].to_numpy() for k in ("open", "high", "low", "close"))
    bucket_start = pd.to_datetime(key[starts])
    bucket_end = bucket_start + pd.Timedelta(hours=hours)
    available = bucket_end.tz_localize(TZ, ambiguous="raise", nonexistent="raise").tz_convert("UTC")
    n = ends - starts
    out = pd.DataFrame({
        "ts_local": m15["ts_local"].to_numpy()[starts],          # first M15 of the bar (bar open)
        "bucket_start_local": bucket_start, "available_utc": available,
        "open": o[starts], "high": np.maximum.reduceat(h, starts), "low": np.minimum.reduceat(l, starts),
        "close": c[ends - 1], "volume": np.add.reduceat(m15["volume"].to_numpy(), starts),
        "n_m15": n.astype(np.int64), "m15_start": starts.astype(np.int64), "m15_end": ends.astype(np.int64),
        "complete": (n >= expected) if tf == "D1" else (n == expected),
        "no_trade": np.logical_or.reduceat(m15["no_trade"].to_numpy(), starts),
        "day_id": m15["day_id"].to_numpy()[starts],
    })
    out["ts_utc"] = m15["ts_utc"].to_numpy()[starts]
    out["close_ts_utc"] = out["available_utc"]
    return out


def align_closed(base: pd.DataFrame, htf: pd.DataFrame, values: np.ndarray) -> np.ndarray:
    """For every base bar, the value of the last COMPLETE higher-timeframe bar available at or before the base bar's close.

    NaN where none exists. ``values`` has one entry per htf bar."""
    ok = htf["complete"].to_numpy()
    avail = utc_int_ns(htf["available_utc"])[ok]
    vals = np.asarray(values, dtype=float)[ok]
    base_close = utc_int_ns(base["available_utc"])
    idx = np.searchsorted(avail, base_close, side="right") - 1
    out = np.full(len(base), np.nan)
    has = idx >= 0
    out[has] = vals[idx[has]]
    return out
