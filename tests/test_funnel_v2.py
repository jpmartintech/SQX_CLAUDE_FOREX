"""Funnel v2 machinery: localised compensated edge, stages, survival logic (synthetic only)."""
import numpy as np

from conftest import make_config, synthetic_raw_m15
from sqxf.backtest.evaluator import Costs, build_market
from sqxf.control.factory import world_shapes
from sqxf.control.funnel_v2 import killer, plant_edge_compensated, price_ratio, survives, v2_stages
from sqxf.data.m15 import canonicalize
from sqxf.grammar import random_strategy
from test_factory_control import _dev


def test_compensated_edge_keeps_the_price_ratio_and_is_localised():
    w = world_shapes(_dev(100), 100, seed=3, n_total=100)
    n = len(w["shapes"]) // 4
    sig = np.zeros(n, bool)
    sig[::50] = True
    a = plant_edge_compensated(w, sig, +1, 2.0, 0.0001, 10)
    assert abs(price_ratio(a) / price_ratio(w) - 1) < 1e-9          # total log drift unchanged
    d = (a["shapes"][:, 3] - w["shapes"][:, 3]).reshape(-1, 4).sum(axis=1)
    active = np.zeros(n, bool)
    for t in np.flatnonzero(sig):
        active[t + 1:t + 11] = True
    assert (d[active] > 0).all() and (d[~active] < 0).all()
    assert np.allclose(d[~active], d[~active][0])                   # compensation is uniform
    sig2 = sig.copy()
    sig2[-5] = True
    b = plant_edge_compensated(w, sig2, +1, 2.0, 0.0001, 10)
    d2 = (b["shapes"][:, 3] - w["shapes"][:, 3]).reshape(-1, 4).sum(axis=1)
    assert np.allclose(d2[active], d[active])                       # bars after a signal get exactly +delta


def test_v2_stages_and_survival_logic():
    m15 = canonicalize(synthetic_raw_m15(n_weeks=160, seed=31, start="2010-01-04"), make_config())
    mk = build_market("EURUSD", m15, Costs(0.0001, 1.0, 0.25))
    rng = np.random.default_rng(1)
    pool = [random_strategy(rng, "EURUSD", 2) for _ in range(300)]
    ref = {"exec_timeframe_funnel": "M15",
           "periods": {"fitness_blocks": [("2010-01-01", "2010-07-01"), ("2010-07-01", "2011-01-01"),
                                          ("2011-01-01", "2011-07-01")], "dsr_window": ["2010-01-01", "2013-01-01"]},
           "stages": {"stability": {"min_positive_blocks": 2}, "cost_stress": {"cost_multiplier": 2.0, "min_mean_r": -99},
                      "execution_stress": {"entry_delay": 1, "min_mean_r": -99}}}
    v2 = {"stages": {"sanity": {"min_trades": 10, "min_mean_r": -99, "min_profit_factor": 0.0},
                     "out_of_sample": {"window": ["2012-01-01", "2013-01-01"], "min_trades": 5}}}
    r = v2_stages(mk, pool, ref, v2)
    sizes = [len(r["alive"][k]) for k in ("pool", "sanity", "stability", "cost_stress", "execution_stress", "out_of_sample")]
    assert all(a >= b for a, b in zip(sizes, sizes[1:], strict=False)) and sizes[-1] > 0
    assert all(len(v) == sizes[-1] for v in r["oos"].values())
    rec = {"planted_stat": {"D1": 2.0}, "top_candidates": {"D1": [{"stat": 5.0, "corr": 0.9}, {"stat": 6.0, "corr": 0.1}]},
           "planted_killer_before_gate": None}
    assert survives(rec, "D1", 1.5) and survives(rec, "D1", 4.0) and not survives(rec, "D1", 5.5)
    assert killer(rec, "D1", 5.5) == "decision_gate"
