"""Shared fixtures: synthetic M15 markets and a small DataConfig."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from sqxf.data.m15 import DataConfig, canonicalize
from sqxf.provenance import PROJECT_ROOT


def synthetic_raw_m15(n_weeks: int = 30, seed: int = 0, start: str = "2010-01-04", continuous: bool = False,
                      drop_frac: float = 0.01, vol: float = 4e-4) -> pd.DataFrame:
    """Raw-format M15 (ts_local + OHLCV) Monday 00:00 -> Friday 23:45 local, random walk, random missing bars.

    ``continuous=True`` makes every open equal the previous close (no intra-week gaps in price).
    """
    rng = np.random.default_rng(seed)
    days = pd.bdate_range(start, periods=n_weeks * 5)
    ts = (days.values[:, None] + (np.arange(96) * np.timedelta64(15, "m"))[None, :]).ravel()
    ts = pd.DatetimeIndex(ts)
    if drop_frac > 0:
        keep = rng.random(len(ts)) >= drop_frac
        keep[0] = True
        ts = ts[keep]
    n = len(ts)
    steps = rng.standard_t(4, size=(n, 4)) * vol
    close = 1.2 * np.exp(np.cumsum(steps[:, 0]))
    if continuous:
        open_ = np.r_[1.2, close[:-1]]
    else:
        open_ = np.r_[1.2, close[:-1]] * np.exp(rng.normal(0, vol / 8, n) * (rng.random(n) < 0.3))
    wick_hi = np.abs(steps[:, 1]) * 0.8
    wick_lo = np.abs(steps[:, 2]) * 0.8
    high = np.maximum(open_, close) * np.exp(wick_hi)
    low = np.minimum(open_, close) * np.exp(-wick_lo)
    return pd.DataFrame({"ts_local": ts.astype("datetime64[ns]"), "open": open_, "high": high, "low": low,
                         "close": close, "volume": rng.integers(1, 1000, n).astype(float)})


def make_config(tmp_path: Path | None = None, holdout: str = "2099-01-01 00:00:00") -> DataConfig:
    base = tmp_path or PROJECT_ROOT / "data"
    return DataConfig(raw_dir=base / "raw", derived_dir=base / "derived", source_tz="Europe/Athens",
                      holdout_start_local=pd.Timestamp(holdout), dev_start_local=pd.Timestamp("2000-01-01"),
                      holiday_no_trade=(("12-24 20:00", "12-27 00:00"), ("12-31 20:00", "01-02 00:00")),
                      volume_overflow_threshold=9e13)


@pytest.fixture
def cfg(tmp_path):
    return make_config(tmp_path)


@pytest.fixture
def m15_synth(cfg):
    return canonicalize(synthetic_raw_m15(seed=1), cfg)


def raw_available(pair: str = "EURUSD") -> bool:
    return (PROJECT_ROOT / "data" / "raw" / f"{pair}_15M.csv").exists()


needs_data = pytest.mark.skipif(not raw_available(), reason="data/raw not present")


@pytest.fixture(autouse=True)
def _isolate_ledgers(tmp_path, monkeypatch):
    """Tests never write to trials/ or runs/: every ledger/access log is redirected to a temporary directory."""
    import sqxf.data.holdout as holdout
    import sqxf.funnel.pipeline as pipeline
    import sqxf.trials as trials
    monkeypatch.setattr(trials, "LEDGER", tmp_path / "ledger.jsonl")
    monkeypatch.setattr(pipeline, "FINAL_ACCESS_LOG", tmp_path / "final_block_access.jsonl")
    monkeypatch.setattr(holdout, "ACCESS_LOG", tmp_path / "holdout_access.jsonl")
