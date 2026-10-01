"""Phase S: local-anchored bars, closed-bar multi-timeframe alignment, ribbon descriptors with hysteresis, descriptive stats."""
import numpy as np
import pandas as pd
import pytest

from conftest import make_config, synthetic_raw_m15
from sqxf.data.m15 import canonicalize
from sqxf.states.bars import align_closed, build_local_bars
from sqxf.states.pipeline import compute_states, describe, spells
from sqxf.states.ribbon import descriptors, hysteresis3

CFG = {"ema_periods": [8, 13, 21, 34, 55, 89, 144], "atr_period": 14,
       "order": {"enter_bull": 6, "stay_bull": 2},
       "width": {"percentile_window": 200, "enter_expanded": 0.80, "stay_expanded": 0.65, "enter_compressed": 0.20,
                 "stay_compressed": 0.35},
       "slope": {"ema": 34, "lag": 5, "enter_up": 0.30, "stay_up": 0.10}}


@pytest.fixture(scope="module")
def m15():
    return canonicalize(synthetic_raw_m15(n_weeks=120, seed=3, start="2010-01-04", drop_frac=0.002), make_config())


@pytest.mark.parametrize("tf,hours", [("H1", 1), ("H4", 4), ("H8", 8)])
def test_intraday_buckets_anchor_on_local_midnight(m15, tf, hours):
    b = build_local_bars(m15, tf)
    assert (b["bucket_start_local"].dt.hour % hours == 0).all() and (b["bucket_start_local"].dt.minute == 0).all()
    g = m15.groupby(m15["ts_local"].dt.floor(f"{hours}h"))
    np.testing.assert_array_equal(b["high"].to_numpy(), g["high"].max().to_numpy())
    np.testing.assert_array_equal(b["close"].to_numpy(), g["close"].last().to_numpy())
    assert (b["complete"] == (b["n_m15"] == 4 * hours)).all() and (~b["complete"]).any()
    # available at the END of the bucket, converted from local (EET/EEST) to UTC
    end_local = b["bucket_start_local"] + pd.Timedelta(hours=hours)
    exp = end_local.dt.tz_localize("Europe/Athens").dt.tz_convert("UTC")
    assert (b["available_utc"] == exp).all()


def test_d1_is_the_fx_trading_day_and_sunday_bars_go_to_monday():
    ts = pd.to_datetime(["2019-03-10 23:00", "2019-03-10 23:15", "2019-03-10 23:30", "2019-03-10 23:45"]).append(
        pd.date_range("2019-03-11 00:00", periods=96, freq="15min"))
    raw = pd.DataFrame({"ts_local": ts, "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 1.0})
    m = canonicalize(raw, make_config())
    d1 = build_local_bars(m, "D1")
    assert len(d1) == 1 and d1["n_m15"].iat[0] == 100 and d1["complete"].iat[0]
    assert d1["available_utc"].iat[0] == pd.Timestamp("2019-03-11 22:00", tz="UTC")   # Tue 00:00 EET (winter, UTC+2)
    h4 = build_local_bars(m, "H4")
    assert h4["bucket_start_local"].iat[0] == pd.Timestamp("2019-03-10 20:00") and not h4["complete"].iat[0]


@pytest.mark.parametrize("tf", ["H4", "H8", "D1"])
def test_alignment_uses_only_closed_complete_bars(m15, tf):
    base, htf = build_local_bars(m15, "H1"), build_local_bars(m15, tf)
    idx_vals = np.arange(len(htf), dtype=float)
    al = align_closed(base, htf, idx_vals)
    has = ~np.isnan(al)
    used = al[has].astype(int)
    assert (htf["available_utc"].to_numpy()[used] <= base["available_utc"].to_numpy()[has]).all()
    assert htf["complete"].to_numpy()[used].all()
    # the most recent complete bar is used (no stale value when a newer closed one exists)
    nxt = np.minimum(used + 1, len(htf) - 1)
    newer_ok = htf["complete"].to_numpy()[nxt] & (htf["available_utc"].to_numpy()[nxt] <= base["available_utc"].to_numpy()[has])
    assert not (newer_ok & (nxt != used)).any()


def test_hysteresis_golden():
    x = np.array([np.nan, 0, 5, 6, 4, 2, 1.9, -6, -3, -1.9, 6, np.nan, 6])
    got = hysteresis3(x, 6, 2, -6, -2)
    exp = np.array([np.nan, 0, 0, 1, 1, 1, 0, -1, -1, 0, 1, np.nan, 1])
    np.testing.assert_array_equal(got, exp)


@pytest.mark.parametrize("tf", ["H1", "H4", "H8", "D1"])
def test_descriptors_are_prefix_invariant(m15, tf):
    full = build_local_bars(m15, tf)
    cut = int(len(m15) * 0.7)
    part = build_local_bars(m15.iloc[:cut].reset_index(drop=True), tf)
    closed = part["available_utc"] <= m15["ts_utc"].iat[cut]
    k = int(closed.sum())
    a, b = descriptors(full, CFG), descriptors(part, CFG)
    pd.testing.assert_frame_equal(a.iloc[:k].reset_index(drop=True), b.iloc[:k].reset_index(drop=True))


def test_combined_states_are_causal_and_bounded(m15):
    s = compute_states(m15, CFG)["combined"]["state"].to_numpy()
    v = s[~np.isnan(s)]
    assert len(v) > 1000 and v.min() >= 0 and v.max() <= 26 and len(np.unique(v)) > 3
    cut = int(len(m15) * 0.8)
    part = compute_states(m15.iloc[:cut].reset_index(drop=True), CFG)
    full = compute_states(m15, CFG)
    base_p = part["bars"]["H1"]
    closed = (base_p["available_utc"] <= m15["ts_utc"].iat[cut]).to_numpy()
    np.testing.assert_array_equal(part["combined"]["state"].to_numpy()[closed],
                                  full["combined"]["state"].to_numpy()[:closed.sum()])


def test_describe_counts_spells_and_transitions():
    s = np.array([np.nan, 1, 1, 1, 2, 2, 1, 1, np.nan, 2])
    sp = spells(s)
    assert sp["length"].tolist() == [3, 2, 2, 1] and sp["state"].tolist() == [1, 2, 1, 2]
    d = describe(s, n_states=3)
    assert d["mean_duration"][1] == 2.5 and d["mean_duration"][2] == 1.5
    assert d["transition_on_change"][1][2] == 1.0 and d["transition_on_change"][2][1] == 1.0
    assert d["changes_per_100_bars"] == pytest.approx(100 * 2 / 6)


def test_adx_prefix_invariant_and_range(m15):
    from sqxf.features.bank import adx
    b = build_local_bars(m15, "H4")
    full = adx(b["high"].to_numpy(), b["low"].to_numpy(), b["close"].to_numpy())
    k = len(b) // 2
    part = adx(b["high"].to_numpy()[:k], b["low"].to_numpy()[:k], b["close"].to_numpy()[:k])
    np.testing.assert_array_equal(part, full[:k])
    v = full[~np.isnan(full)]
    assert v.min() >= 0 and v.max() <= 100


def test_preregistered_ribbon_config_drives_the_descriptors(m15):
    from sqxf.provenance import load_config
    cfg = load_config("states_ribbon")["ribbon"]
    assert cfg["ema_periods"] == [8, 13, 21, 34, 55, 89, 144]
    d = descriptors(build_local_bars(m15, "H1"), cfg)
    assert set(np.unique(d["state"].dropna())) <= set(range(27))
