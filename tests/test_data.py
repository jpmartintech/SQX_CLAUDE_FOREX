import numpy as np
import pandas as pd
import pytest

from conftest import make_config, needs_data, synthetic_raw_m15
from sqxf.data.h1 import build_h1
from sqxf.data.holdout import HoldoutSealedError, load_sealed_holdout
from sqxf.data.m15 import DataConfig, DataError, canonicalize, holiday_mask, load_m15, trading_date, validate_m15


# ---------------------------------------------------------------- validation (never repair silently)
def test_validate_rejects_duplicates_disorder_and_bad_ohlc():
    raw = synthetic_raw_m15(n_weeks=1, drop_frac=0)
    validate_m15(raw)
    dup = pd.concat([raw.iloc[:10], raw.iloc[9:10], raw.iloc[10:]], ignore_index=True)
    with pytest.raises(DataError, match="duplicated"):
        validate_m15(dup)
    swapped = raw.copy()
    swapped.loc[[5, 6]] = swapped.loc[[6, 5]].to_numpy()
    with pytest.raises(DataError, match="backward"):
        validate_m15(swapped)
    bad = raw.copy()
    bad.loc[3, "high"] = bad.loc[3, "low"] - 1e-4
    with pytest.raises(DataError, match="OHLC"):
        validate_m15(bad)
    nan = raw.copy()
    nan.loc[4, "close"] = np.nan
    with pytest.raises(DataError, match="non-finite"):
        validate_m15(nan)
    off = raw.copy()
    off.loc[len(off) - 1, "ts_local"] += pd.Timedelta(minutes=20)
    with pytest.raises(DataError, match="grid"):
        validate_m15(off)


# ---------------------------------------------------------------- timezone, holdout, flags
def test_canonicalize_converts_eet_to_utc_with_european_dst(cfg):
    raw = pd.DataFrame({"ts_local": pd.to_datetime(["2020-01-06 00:00", "2020-07-06 00:00"]),
                        "open": [1.0, 1.0], "high": [1.0, 1.0], "low": [1.0, 1.0], "close": [1.0, 1.0],
                        "volume": [1.0, 1.0]})
    out = canonicalize(raw, cfg)
    assert list(out["ts_utc"]) == [pd.Timestamp("2020-01-05 22:00", tz="UTC"), pd.Timestamp("2020-07-05 21:00", tz="UTC")]


def test_holdout_is_dropped_and_sealed(tmp_path, monkeypatch):
    cfg = make_config(tmp_path, holdout="2010-03-01 00:00:00")
    raw = synthetic_raw_m15(n_weeks=12, start="2010-01-04")
    out = canonicalize(raw, cfg)
    assert out["ts_local"].max() < pd.Timestamp("2010-03-01")
    assert len(out) == int((raw["ts_local"] < pd.Timestamp("2010-03-01")).sum())
    monkeypatch.delenv("SQXF_UNSEAL_HOLDOUT", raising=False)
    with pytest.raises(HoldoutSealedError):
        load_sealed_holdout("EURUSD", "peek", cfg)


def test_holiday_mask_windows_and_year_wrap():
    ts = pd.Series(pd.to_datetime(["2019-12-24 19:45", "2019-12-24 20:00", "2019-12-26 23:45", "2019-12-27 00:00",
                                   "2019-12-31 20:00", "2020-01-01 12:00", "2020-01-02 00:00", "2020-07-01 12:00"]))
    windows = (("12-24 20:00", "12-27 00:00"), ("12-31 20:00", "01-02 00:00"))
    assert holiday_mask(ts, windows).tolist() == [False, True, True, False, True, True, False, False]


def test_trading_date_moves_sunday_to_monday_and_saturday_to_friday():
    ts = pd.Series(pd.to_datetime(["2019-03-10 23:00", "2019-03-11 00:00", "2005-04-02 00:30", "2005-04-01 23:45"]))
    assert [d.date().isoformat() for d in trading_date(ts)] == ["2019-03-11", "2019-03-11", "2005-04-01", "2005-04-01"]


def test_volume_overflow_becomes_nan(cfg):
    raw = synthetic_raw_m15(n_weeks=1, drop_frac=0)
    raw.loc[7, "volume"] = 92233720368547.0
    out = canonicalize(raw, cfg)
    assert np.isnan(out.loc[7, "volume"]) and out["volume"].isna().sum() == 1


# ---------------------------------------------------------------- H1 derivation
def _naive_h1(m15: pd.DataFrame) -> pd.DataFrame:
    """Independent oracle: pandas groupby on the floored UTC hour."""
    g = m15.groupby(m15["ts_utc"].dt.floor("h"), sort=True)
    return pd.DataFrame({"open": g["open"].first(), "high": g["high"].max(), "low": g["low"].min(),
                         "close": g["close"].last(), "volume": g["volume"].sum(min_count=1), "n": g.size(),
                         "no_trade": g["no_trade"].any()})


def test_h1_matches_groupby_oracle(m15_synth):
    h1 = build_h1(m15_synth)
    ref = _naive_h1(m15_synth)
    assert len(h1) == len(ref)
    assert (h1["ts_utc"].to_numpy() == ref.index.to_numpy()).all()
    for col in ("open", "high", "low", "close", "volume"):
        np.testing.assert_array_equal(h1[col].to_numpy(), ref[col].to_numpy())
    np.testing.assert_array_equal(h1["n_m15"].to_numpy(), ref["n"].to_numpy())
    np.testing.assert_array_equal(h1["no_trade"].to_numpy(), ref["no_trade"].to_numpy())
    assert (h1["complete"] == (h1["n_m15"] == 4)).all()
    assert (~h1["complete"]).sum() > 0  # the synthetic market has missing bars


def test_h1_bar_only_contains_its_own_hour(m15_synth):
    h1 = build_h1(m15_synth)
    ts = m15_synth["ts_utc"].to_numpy()
    for i in range(len(h1)):
        a, b = h1["m15_start"].iat[i], h1["m15_end"].iat[i]
        assert (ts[a:b] >= h1["ts_utc"].to_numpy()[i]).all()
        assert (ts[a:b] < h1["close_ts_utc"].to_numpy()[i]).all()
    assert (h1["m15_start"].to_numpy()[1:] == h1["m15_end"].to_numpy()[:-1]).all()


@pytest.mark.parametrize("cut", [100, 1001, 2502, 5003])
def test_h1_prefix_invariance(m15_synth, cut):
    """Truncating M15 at T never changes any H1 bar that closed at or before T."""
    full = build_h1(m15_synth)
    part = build_h1(m15_synth.iloc[:cut].reset_index(drop=True))
    t_cut = m15_synth["ts_utc"].iat[cut]  # first bar NOT available
    closed = part["close_ts_utc"] <= t_cut
    # The last partial hour may be open at T: it is exactly the non-closed one (if any).
    assert (~closed).sum() <= 1
    cols = ["ts_utc", "open", "high", "low", "close", "n_m15", "m15_start", "m15_end", "no_trade"]
    pd.testing.assert_frame_equal(part.loc[closed, cols].reset_index(drop=True),
                                  full.loc[: closed.sum() - 1, cols].reset_index(drop=True))


# ---------------------------------------------------------------- real data (skipped if absent)
@needs_data
@pytest.mark.data
def test_real_eurusd_loader_is_pre_holdout_and_consistent():
    cfg = DataConfig.load()
    m15 = load_m15("EURUSD", cfg)
    assert m15["ts_local"].max() < cfg.holdout_start_local
    assert m15.attrs["source_sha256"].startswith("fec7a62567a2")
    h1 = build_h1(m15)
    assert h1["complete"].mean() > 0.999
    assert h1["ts_utc"].is_monotonic_increasing and h1["ts_utc"].is_unique
