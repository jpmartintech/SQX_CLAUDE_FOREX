"""Crypto data: spot M15 loader (UTC), sealed selection block and holdout, derived-copy repairs, suspect-wick flags,
bars (H1/H4/D1) without look-ahead, causal liquidity filter and funding arrays.

Rules (CLAUDE.md "Cripto"): the raw CSVs are never modified; nothing is sorted, deduplicated or filled silently.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from sqxf.data.m15 import DataError
from sqxf.provenance import PROJECT_ROOT, code_version, file_sha256, load_config

ACCESS_LOG = PROJECT_ROOT / "trials" / "crypto_holdout_access.jsonl"
UNSEAL_ENV = "SQXF_UNSEAL_CRYPTO"
FREQ_BARS = {"1h": 4, "4h": 16, "1D": 96}


class SealedError(PermissionError):
    pass


@dataclass(frozen=True)
class CryptoConfig:
    raw: dict

    @classmethod
    def load(cls) -> CryptoConfig:
        return cls(load_config("crypto_data"))

    def __getitem__(self, k):
        return self.raw[k]

    @property
    def holdout_start(self) -> pd.Timestamp:
        return pd.Timestamp(self.raw["holdout_start_utc"])

    @property
    def selection_start(self) -> pd.Timestamp:
        return pd.Timestamp(self.raw["selection_block_start_utc"])


# ------------------------------------------------------------------ raw spot
def read_spot_csv(path: Path) -> pd.DataFrame:
    raw = pd.read_csv(path, dtype=str, keep_default_na=False)
    if list(raw.columns) != ["datetime", "open", "high", "low", "close", "volume"]:
        raise DataError(f"{path.name}: unexpected columns {list(raw.columns)}")
    ts = pd.to_datetime(raw["datetime"], format="%Y-%m-%d %H:%M:%S", errors="coerce")
    if ts.isna().any():
        raise DataError(f"{path.name}: unparseable timestamps")
    df = pd.DataFrame({"ts_local": ts.astype("datetime64[ns]")})
    for c in ("open", "high", "low", "close", "volume"):
        v = pd.to_numeric(raw[c], errors="coerce").astype(float)
        if v.isna().any():
            raise DataError(f"{path.name}: NaN in {c}")
        df[c] = v
    return df


def validate_utc_m15(df: pd.DataFrame, name: str) -> None:
    ns = df["ts_local"].to_numpy().astype("datetime64[ns]").astype(np.int64)
    if (np.diff(ns) <= 0).any():
        raise DataError(f"{name}: timestamps not strictly increasing")
    if (df["ts_local"].dt.minute % 15 != 0).any() or (df["ts_local"].dt.second != 0).any():
        raise DataError(f"{name}: off the 15-minute grid")
    o, h, l, c = (df[k].to_numpy() for k in ("open", "high", "low", "close"))
    if (np.stack([o, h, l, c]) <= 0).any() or ((h < l) | (h < np.maximum(o, c)) | (l > np.minimum(o, c))).any():
        raise DataError(f"{name}: invalid OHLC")


def suspect_wicks(df: pd.DataFrame, body_excess: float, neighbour_excess: float) -> np.ndarray:
    o, h, l, c = (df[k] for k in ("open", "high", "low", "close"))
    nb_hi = pd.concat([h.shift(), h.shift(-1)], axis=1).max(axis=1)
    nb_lo = pd.concat([l.shift(), l.shift(-1)], axis=1).min(axis=1)
    up = (h / np.maximum(o, c) - 1 > body_excess) & (h / nb_hi - 1 > neighbour_excess)
    dn = (1 - l / np.minimum(o, c) > body_excess) & (1 - l / nb_lo > neighbour_excess)
    return (up | dn).to_numpy()


def _log_access(kind: str, coin: str, reason: str) -> None:
    ACCESS_LOG.parent.mkdir(parents=True, exist_ok=True)
    with ACCESS_LOG.open("a") as fh:
        fh.write(json.dumps({"utc": datetime.now(UTC).isoformat(), "kind": kind, "coin": coin, "reason": reason,
                             "code_version": code_version()}) + "\n")


def load_spot_m15(coin: str, cfg: CryptoConfig | None = None, repair: bool = True, until: str = "development",
                  reason: str = "") -> pd.DataFrame:
    """Canonical spot M15 (UTC). ``until``: 'development' (< selection block, default), 'selection' (< holdout; logged,
    needs a reason) or 'holdout' (everything; needs SQXF_UNSEAL_CRYPTO=I_UNDERSTAND and a reason; logged).
    ``repair=True`` applies the documented derived-copy repairs; ``repair=False`` is the raw (stress) variant."""
    cfg = cfg or CryptoConfig.load()
    path = PROJECT_ROOT / cfg["spot_dir"] / f"{coin}_15M.csv"
    raw = read_spot_csv(path)
    validate_utc_m15(raw, coin)
    if until == "development":
        end = cfg.selection_start
    elif until == "selection":
        if not reason.strip():
            raise SealedError("the selection block needs an explicit reason (it is logged)")
        _log_access("selection_block", coin, reason)
        end = cfg.holdout_start
    elif until == "holdout":
        if os.environ.get(UNSEAL_ENV) != "I_UNDERSTAND" or not reason.strip():
            raise SealedError("crypto holdout is sealed: set SQXF_UNSEAL_CRYPTO=I_UNDERSTAND and give a reason")
        _log_access("holdout", coin, reason)
        end = pd.Timestamp.max
    else:
        raise ValueError(until)
    df = raw.loc[raw["ts_local"] < end].reset_index(drop=True)
    df["repaired"] = False
    if repair:
        for rp in cfg["repairs"]:
            if rp["coin"] != coin:
                continue
            m = df["ts_local"] == pd.Timestamp(rp["bar_utc"])
            if m.sum() == 1:
                df.loc[m, "low"] = np.minimum(df.loc[m, "open"], df.loc[m, "close"])
                df.loc[m, "repaired"] = True
    sw = cfg["suspect_wick"]
    df["suspect_wick"] = suspect_wicks(df, sw["body_excess"], sw["neighbour_excess"])
    df["ts_utc"] = df["ts_local"].dt.tz_localize("UTC")
    df["no_trade"] = False
    df["day_id"] = pd.factorize(df["ts_local"].dt.normalize(), sort=True)[0].astype(np.int64)
    df.attrs.update({"coin": coin, "source_sha256": file_sha256(path), "until": until, "repair": repair,
                     "calendar": "utc"})
    return df


# ------------------------------------------------------------------ bars
def build_bars(m15: pd.DataFrame, freq: str) -> pd.DataFrame:
    """Aggregate UTC M15 into ``freq`` bars (1h, 4h, 1D) with the same columns as forex H1 (``build_h1``).

    Bar ``t`` = M15 with ``t <= ts < t + len``; 4h bars start at 00/04/08/12/16/20 UTC; D1 closes at 00:00 UTC. Empty periods do
    not exist; ``complete`` needs every M15 bar. Available at ``close_ts_utc``.
    """
    if freq not in FREQ_BARS:
        raise ValueError(freq)
    ns = m15["ts_local"].to_numpy().astype("datetime64[ns]").astype(np.int64)
    step = pd.Timedelta(freq).value
    key = ns // step
    starts = np.flatnonzero(np.r_[True, key[1:] != key[:-1]])
    ends = np.r_[starts[1:], len(key)]
    o, h, l, c = (m15[k].to_numpy() for k in ("open", "high", "low", "close"))
    ts = pd.to_datetime(key[starts] * step)
    n = ends - starts
    return pd.DataFrame({
        "ts_utc": ts.tz_localize("UTC"), "ts_local": ts, "close_ts_utc": (ts + pd.Timedelta(freq)).tz_localize("UTC"),
        "open": o[starts], "high": np.maximum.reduceat(h, starts), "low": np.minimum.reduceat(l, starts),
        "close": c[ends - 1], "volume": np.add.reduceat(m15["volume"].to_numpy(), starts),
        "n_m15": n.astype(np.int64), "m15_start": starts.astype(np.int64), "m15_end": ends.astype(np.int64),
        "complete": n == FREQ_BARS[freq], "no_trade": np.zeros(len(starts), dtype=bool),
        "day_id": m15["day_id"].to_numpy()[starts],
    })


# ------------------------------------------------------------------ liquidity (causal)
def daily_liquidity(m15: pd.DataFrame, window_days: int) -> pd.DataFrame:
    """Per UTC day: USD volume and the trailing median over the previous ``window_days`` days (excluding the day itself)."""
    usd = m15["volume"] * (m15["open"] + m15["high"] + m15["low"] + m15["close"]) / 4
    day = usd.groupby(m15["day_id"]).sum()
    med = day.rolling(window_days, min_periods=window_days).median().shift(1)
    return pd.DataFrame({"usd": day, "trailing_median": med})


def slippage_for(median_usd: np.ndarray, bands: list) -> np.ndarray:
    """Slippage fraction per side by liquidity band; NaN when below the lowest band (not tradable)."""
    out = np.full(len(median_usd), np.nan)
    for lower, slip in sorted(bands, key=lambda b: b[0]):
        out = np.where(median_usd >= lower, slip, out)
    return out


# ------------------------------------------------------------------ funding
def read_funding(coin: str, cfg: CryptoConfig, end: pd.Timestamp) -> pd.Series:
    """Funding rates indexed by the event time floored to the minute (UTC), strictly before ``end``."""
    path = PROJECT_ROOT / cfg["perp_dir"] / f"{coin}_funding.csv"
    f = pd.read_csv(path)
    t = pd.to_datetime(f["fundingTime"], unit="ms").dt.floor("min")
    s = pd.Series(f["fundingRate"].astype(float).to_numpy(), index=t)
    s = s[~s.index.duplicated()]
    return s[s.index < end]


def funding_arrays(bar_open: pd.DatetimeIndex, rates: pd.Series, mean_abs: float, event_hours: list[int]
                   ) -> tuple[np.ndarray, np.ndarray, int]:
    """Per execution bar: the signed rate of any funding event at its open, and, before the first real event of the
    perpetual, ``mean_abs`` at every scheduled event hour (charged to both sides). Returns ``(fr, fr_abs, n_unplaced)``:
    events that fall on no bar open (exchange outages, or times inside a bar) are not applied and are counted."""
    idx = pd.DatetimeIndex(bar_open)
    fr = rates.reindex(idx).fillna(0.0).to_numpy()
    scheduled = (idx.minute == 0) & np.isin(idx.hour, event_hours)
    first = rates.index.min() if len(rates) else pd.Timestamp.max
    fr_abs = np.where(scheduled & (idx < first), mean_abs, 0.0)
    inside = rates.index[(rates.index >= idx.min()) & (rates.index <= idx.max())]
    return fr, fr_abs, int(len(inside.difference(idx)))
