"""Positive-control machinery on synthetic inputs (no real data)."""
import numpy as np
import pytest

from conftest import make_config, synthetic_raw_m15
from sqxf.control.funnel import calibration_run, predictive_test, state_nets
from sqxf.control.synthetic import calendar, inject_h4_ar, inject_state_edge, null_world_shapes, rebuild, to_m15
from sqxf.data.m15 import canonicalize
from sqxf.states.pipeline import compute_states
from test_states import CFG as RIBBON


def _shapes_from(m):
    o, h, l, c = (m[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    prev = np.r_[o[0], c[:-1]]
    return np.stack([np.log(o / prev), np.log(h / o), np.log(l / o), np.log(c / o)], axis=1), o, h, l, c


def _dev(n_days=400, pairs=("AAA", "BBB")):
    out = {"days": np.arange(n_days), "pairs": {}}
    for i, p in enumerate(pairs):
        m = canonicalize(synthetic_raw_m15(n_weeks=n_days // 5, seed=50 + i, drop_frac=0.0), make_config())
        s, o, *_ = _shapes_from(m)
        out["pairs"][p] = {"shapes": s, "day_start": np.arange(n_days) * 96, "volume": np.repeat(np.arange(n_days), 96) * 1.0,
                           "o0": o[0]}
    return out


def test_rebuild_round_trip():
    m = canonicalize(synthetic_raw_m15(n_weeks=4, seed=1, drop_frac=0.0), make_config())
    s, o, h, l, c = _shapes_from(m)
    for a, b in zip(rebuild(o[0], s), (o, h, l, c), strict=True):
        np.testing.assert_allclose(a, b, rtol=1e-12)


def test_null_world_uses_the_same_day_order_for_all_pairs():
    w = null_world_shapes(_dev(), seed=3, n_days=200)
    np.testing.assert_array_equal(w["AAA"]["volume"], w["BBB"]["volume"])   # volume encodes the source day
    assert not np.array_equal(w["AAA"]["volume"][::96], np.arange(200))      # shuffled


def test_state_edge_is_causal_and_has_the_intended_size():
    w = null_world_shapes(_dev(), seed=3, n_days=200)["AAA"]
    n = len(w["shapes"]) // 4
    st = np.full(n, 5.0)
    st[1000] = 26
    a = inject_state_edge(w, st, 26, +1, 24.0, 0.0001, 24)
    d = (a["shapes"][:, 3] - w["shapes"][:, 3]).reshape(-1, 4).sum(axis=1)
    assert (d[:1001] == 0).all() and (d[1001:1025] > 0).all() and (d[1025:] == 0).all()
    o, *_ = rebuild(w["o0"], w["shapes"])
    np.testing.assert_allclose(d[1001:1025].sum(), np.sum(np.log1p(1.0 * 0.0001 / o[::4][1001:1025])), rtol=1e-12)
    st2 = st.copy()
    st2[1500:] = 26                                   # future states never change the past drift
    b = inject_state_edge(w, st2, 26, +1, 24.0, 0.0001, 24)
    np.testing.assert_array_equal(b["shapes"][: 4 * 1501, 3], a["shapes"][: 4 * 1501, 3])


def test_h4_ar_injection_creates_the_autocorrelation():
    rng = np.random.default_rng(0)
    n = 16 * 20000
    base = {"shapes": np.c_[np.zeros(n), np.full(n, 1e-3), np.full(n, -1e-3), rng.normal(0, 1e-3, n)], "o0": 1.0}
    r = inject_h4_ar(base, 0.2)
    h4 = (r["shapes"][:, 0] + r["shapes"][:, 3]).reshape(-1, 16).sum(axis=1)
    rho = np.corrcoef(h4[1:], h4[:-1])[0, 1]
    assert rho == pytest.approx(0.2, abs=0.03)


def test_predictive_and_calibration_run_on_a_synthetic_world():
    dev = _dev(n_days=400, pairs=("EURUSD", "GBPUSD", "USDJPY", "USDCHF"))
    w = null_world_shapes(dev, seed=4, n_days=400)
    cal = calendar("2008-01-07", 400)
    m15 = {p: to_m15(s, cal, make_config()) for p, s in w.items()}
    nets = {p: state_nets(compute_states(m, RIBBON), 0.0001, [6, 24], ["2009-01-01", "2010-01-01"]) for p, m in m15.items()}
    pt = {"acceptance": {"holm_p_le": 0.05, "min_mean_net_pips": 1.0},
          "bootstrap": {"resamples": 200, "seed": 1}}
    rows = predictive_test(nets, "EURUSD", [0, 26], [6, 24], pt, [2009])
    assert len(rows) == 4 and all(0 <= r["p_holm"] <= 1 for r in rows)
    cal_cfg = {"initial_stop_atr": 3.0, "trailing_atr": 3.0, "max_bars_h4": 500}
    acc = {"pooled_mean_r_x1_gt": 0.0, "pooled_mean_r_x2_gt": 0.0, "pooled_profit_factor_ge": 1.1, "pairs_positive_min": 4,
           "pair_min_trades": 20, "years_positive_min": 3, "pooled_min_trades": 100, "dsr_ge": 0.95}
    swap = {"default": {"long": 1.0, "short": 1.0}, "pairs": {}}
    res = calibration_run(m15, swap, cal_cfg, acc, ("2008-06-01", "2009-07-01"), [2008, 2009], 13.9, 0.0015)
    assert res["trades"] > 0 and set(res["checks"]) and isinstance(res["accepted"], bool)
