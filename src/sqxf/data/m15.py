"""Canonical M15 loader.

Raw files are SQX exports (``Date,Time,Open,High,Low,Close,Volume``; bar-open timestamps in Europe/Athens time).
The loader never sorts, deduplicates or fills: any structural problem raises :class:`DataError`.
The sealed holdout (local time >= ``holdout_start_local``) is dropped before anything is returned or cached.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from sqxf.provenance import PROJECT_ROOT, code_version, file_sha256, load_config

# Bump when the canonical M15 schema or its derivation changes (invalidates data/derived caches).
SCHEMA_VERSION = 1
RAW_COLUMNS = ["Date", "Time", "Open", "High", "Low", "Close", "Volume"]


class DataError(ValueError):
    """Raised when raw data violates a structural rule (order, duplicates, NaN, OHLC consistency)."""


@dataclass(frozen=True)
class DataConfig:
    raw_dir: Path
    derived_dir: Path
    source_tz: str
    holdout_start_local: pd.Timestamp
    dev_start_local: pd.Timestamp
    holiday_no_trade: tuple[tuple[str, str], ...]
    volume_overflow_threshold: float

    @classmethod
    def load(cls) -> DataConfig:
        cfg = load_config("data")
        return cls(
            raw_dir=PROJECT_ROOT / cfg["raw_dir"],
            derived_dir=PROJECT_ROOT / cfg["derived_dir"],
            source_tz=cfg["source_tz"],
            holdout_start_local=pd.Timestamp(cfg["holdout_start_local"]),
            dev_start_local=pd.Timestamp(cfg["dev_start_local"]),
            holiday_no_trade=tuple((a, b) for a, b in cfg["holiday_no_trade"]),
            volume_overflow_threshold=float(cfg["volume_overflow_threshold"]),
        )


def raw_path(pair: str, cfg: DataConfig) -> Path:
    return cfg.raw_dir / f"{pair}_15M.csv"


def read_raw_csv(path: Path) -> pd.DataFrame:
    """Parse a raw SQX CSV into ``ts_local`` + float OHLCV. Validates columns and parsing only."""
    raw = pd.read_csv(path, dtype=str, keep_default_na=False)
    if list(raw.columns) != RAW_COLUMNS:
        raise DataError(f"{path.name}: unexpected columns {list(raw.columns)}")
    ts = pd.to_datetime(raw["Date"] + " " + raw["Time"], format="%Y%m%d %H:%M:%S", errors="coerce")
    if ts.isna().any():
        raise DataError(f"{path.name}: {int(ts.isna().sum())} unparseable timestamps")
    out = pd.DataFrame({"ts_local": ts.astype("datetime64[ns]")})
    for col in RAW_COLUMNS[2:]:
        values = pd.to_numeric(raw[col], errors="coerce").astype("float64")
        if values.isna().any():
            raise DataError(f"{path.name}: {int(values.isna().sum())} NaN/unparseable values in {col}")
        out[col.lower()] = values
    return out


def validate_m15(df: pd.DataFrame, name: str = "M15") -> None:
    """Structural checks. Raises instead of repairing."""
    ts = df["ts_local"].to_numpy()
    if len(ts) == 0:
        raise DataError(f"{name}: empty")
    steps = np.diff(ts.astype("datetime64[ns]").astype(np.int64))
    if (steps < 0).any():
        raise DataError(f"{name}: {int((steps < 0).sum())} backward timestamp steps")
    if (steps == 0).any():
        raise DataError(f"{name}: {int((steps == 0).sum())} duplicated timestamps")
    minutes = df["ts_local"].dt.minute.to_numpy()
    seconds = df["ts_local"].dt.second.to_numpy()
    if ((minutes % 15) != 0).any() or (seconds != 0).any():
        raise DataError(f"{name}: timestamps off the 15-minute grid")
    o, h, l, c = (df[k].to_numpy() for k in ("open", "high", "low", "close"))
    if not np.isfinite(np.stack([o, h, l, c])).all():
        raise DataError(f"{name}: non-finite prices")
    if (np.stack([o, h, l, c]) <= 0).any():
        raise DataError(f"{name}: non-positive prices")
    bad = (h < l) | (h < np.maximum(o, c)) | (l > np.minimum(o, c))
    if bad.any():
        raise DataError(f"{name}: {int(bad.sum())} inconsistent OHLC bars")


def holiday_mask(ts_local: pd.Series, windows: tuple[tuple[str, str], ...]) -> np.ndarray:
    """True inside any ``[MM-DD HH:MM, MM-DD HH:MM)`` local window (windows may wrap the year end)."""
    # Encode as minutes since Jan 1 00:00 on a fixed 366-day calendar (month/day only, year ignored).
    def code(month, day, hour, minute):
        return ((np.asarray(month) * 31 + np.asarray(day)) * 24 + np.asarray(hour)) * 60 + np.asarray(minute)

    t = code(ts_local.dt.month, ts_local.dt.day, ts_local.dt.hour, ts_local.dt.minute)
    mask = np.zeros(len(ts_local), dtype=bool)
    for start, end in windows:
        a = pd.Timestamp(f"2000-{start}")
        b = pd.Timestamp(f"2000-{end}")
        ca, cb = code(a.month, a.day, a.hour, a.minute), code(b.month, b.day, b.hour, b.minute)
        mask |= ((t >= ca) & (t < cb)) if ca <= cb else ((t >= ca) | (t < cb))
    return mask


def trading_date(ts_local: pd.Series) -> pd.Series:
    """FX trading day in local (EET) time: Sunday-evening bars belong to Monday, Saturday stubs to Friday."""
    date = ts_local.dt.normalize()
    dow = ts_local.dt.dayofweek
    date = date.where(dow != 6, date + pd.Timedelta(days=1))
    return date.where(dow != 5, date - pd.Timedelta(days=1))


def canonicalize(raw: pd.DataFrame, cfg: DataConfig, name: str = "M15") -> pd.DataFrame:
    """Validate, drop the sealed holdout, convert to UTC and add flags. Input rows are never reordered."""
    validate_m15(raw, name)
    keep = raw["ts_local"] < cfg.holdout_start_local
    df = raw.loc[keep].reset_index(drop=True)
    ts_utc = df["ts_local"].dt.tz_localize(cfg.source_tz, ambiguous="raise", nonexistent="raise").dt.tz_convert("UTC")
    utc_ns = utc_int_ns(ts_utc)
    if (np.diff(utc_ns) <= 0).any():
        raise DataError(f"{name}: UTC timestamps not strictly increasing after tz conversion")
    volume = df["volume"].to_numpy(copy=True)
    volume[volume >= cfg.volume_overflow_threshold] = np.nan
    tdate = trading_date(df["ts_local"])
    out = pd.DataFrame({
        "ts_utc": ts_utc.astype("datetime64[ns, UTC]"),
        "ts_local": df["ts_local"],
        "open": df["open"], "high": df["high"], "low": df["low"], "close": df["close"],
        "volume": volume,
        "no_trade": holiday_mask(df["ts_local"], cfg.holiday_no_trade),
        "day_id": pd.factorize(tdate, sort=True)[0].astype(np.int64),
    })
    return out


def utc_int_ns(ts: pd.Series) -> np.ndarray:
    """Tz-aware timestamps -> int64 nanoseconds since the epoch (UTC)."""
    return ts.dt.tz_convert("UTC").dt.tz_localize(None).to_numpy().astype("datetime64[ns]").astype(np.int64)


def _cache_path(pair: str, cfg: DataConfig) -> Path:
    return cfg.derived_dir / "m15" / f"{pair}.parquet"


def load_m15(pair: str, cfg: DataConfig | None = None, use_cache: bool = True) -> pd.DataFrame:
    """Canonical pre-holdout M15 bars for ``pair``. Rebuilds the parquet cache when the source hash or schema changes."""
    cfg = cfg or DataConfig.load()
    src = raw_path(pair, cfg)
    if not src.exists():
        raise FileNotFoundError(src)
    sha = file_sha256(src)
    cache = _cache_path(pair, cfg)
    expected = {"source_sha256": sha, "schema_version": str(SCHEMA_VERSION),
                "holdout_start_local": str(cfg.holdout_start_local), "tz": cfg.source_tz,
                "holiday_no_trade": json.dumps(cfg.holiday_no_trade)}
    if use_cache and cache.exists():
        meta = {k.decode(): v.decode() for k, v in (pq.read_schema(cache).metadata or {}).items()}
        if all(meta.get(k) == v for k, v in expected.items()):
            df = pd.read_parquet(cache)
            df.attrs.update(meta)
            return df
    df = canonicalize(read_raw_csv(src), cfg, name=pair)
    meta = {**expected, "pair": pair, "code_version": code_version(), "rows": str(len(df))}
    if use_cache:
        cache.parent.mkdir(parents=True, exist_ok=True)
        table = pa.Table.from_pandas(df, preserve_index=False)
        table = table.replace_schema_metadata({**(table.schema.metadata or {}), **{k: v for k, v in meta.items()}})
        tmp = cache.with_suffix(".tmp")
        pq.write_table(table, tmp)
        tmp.replace(cache)
    df.attrs.update(meta)
    return df
