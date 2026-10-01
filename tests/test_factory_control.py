"""Funnel control machinery: planted edge causality/magnitude and the pool funnel == Phase 2 run_funnel."""
import numpy as np
import pytest

from conftest import make_config, synthetic_raw_m15
from sqxf.backtest.evaluator import Costs, build_market, strategy_signal
from sqxf.control.factory import plant_edge, planted, run_funnel_pool, world_shapes
from sqxf.control.synthetic import rebuild
from sqxf.data.m15 import canonicalize
from sqxf.funnel.pipeline import run_funnel

SPEC = {"direction": "LONG", "predicates": [["trend.ema_pair.20.100", ">", 0.0], ["trend.breakout_high.20", ">", 0.0]],
        "sl_atr": 2.0, "tp_atr": 3.0, "max_bars": 48}


def _dev(n_days=300):
    m = canonicalize(synthetic_raw_m15(n_weeks=n_days // 5, seed=70, drop_frac=0.0), make_config())
    o, h, l, c = (m[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    prev = np.r_[o[0], c[:-1]]
    sh = np.stack([np.log(o / prev), np.log(h / o), np.log(l / o), np.log(c / o)], axis=1)
    return {"shapes": sh, "day_start": np.arange(n_days) * 96, "volume": np.ones(len(o)), "o0": o[0]}


def test_world_uses_all_days_then_resamples():
    d = _dev(100)
    w = world_shapes(d, 100, seed=1, n_total=130)
    assert len(w["shapes"]) == 130 * 96
    firsts = w["shapes"][::96][:100, 3]
    assert len(np.unique(firsts)) == 100          # the first 100 days are a permutation of the pool


def test_planted_edge_is_causal_and_sized():
    d = _dev(100)
    w = world_shapes(d, 100, seed=2, n_total=100)
    n = len(w["shapes"]) // 4
    sig = np.zeros(n, bool)
    sig[500] = True
    a = plant_edge(w, sig, -1, 0.5, 0.0001, 10)
    dd = (a["shapes"][:, 3] - w["shapes"][:, 3]).reshape(-1, 4).sum(axis=1)
    assert (dd[:501] == 0).all() and (dd[501:511] < 0).all() and (dd[511:] == 0).all()
    o, *_ = rebuild(w["o0"], w["shapes"])
    np.testing.assert_allclose(dd[501:511], -np.log1p(0.5 * 0.0001 / o[::4][501:511]), rtol=1e-12)
    sig2 = sig.copy()
    sig2[800] = True
    b = plant_edge(w, sig2, -1, 0.5, 0.0001, 10)
    np.testing.assert_array_equal(b["shapes"][: 4 * 801, 3], a["shapes"][: 4 * 801, 3])


def test_pool_funnel_reproduces_phase2_run_funnel_counts(tmp_path):
    m15 = canonicalize(synthetic_raw_m15(n_weeks=160, seed=31, start="2010-01-04"), make_config())
    mk = build_market("EURUSD", m15, Costs(0.0001, 1.0, 0.25))
    blocks = [("2010-01-01", "2010-05-01"), ("2010-05-01", "2010-09-01"), ("2010-09-01", "2011-01-01")]
    cfg = {"run_name": "x", "seed": 1, "exec_timeframe_fitness": "H1", "exec_timeframe_funnel": "M15",
           "periods": {"fitness_blocks": blocks, "walk_forward_years": [2011], "dsr_window": ["2010-01-01", "2012-01-01"],
                       "final_block": ["2012-01-01", "2013-01-01"]},
           "genetic": {"population": 60, "generations": 4, "max_unique_evaluations": 250, "elite": 5, "tournament": 3},
           "fitness": {"min_trades_per_block": 5},
           "stages": {"basic": {"min_trades": 10, "min_profit_factor": 0.0, "min_mean_r": -99, "max_dd_mtm": 1.0},
                      "stability": {"min_positive_blocks": 1},
                      "cost_stress": {"cost_multiplier": 2.0, "min_profit_factor": 0.0, "min_mean_r": -99},
                      "execution_stress": {"entry_delay": 1, "min_profit_factor": 0.0, "min_mean_r": -99},
                      "walk_forward": {"min_positive_years": 0, "min_trades_total": 1, "min_profit_factor": 0.0,
                                       "min_mean_r": -99},
                      "deflated_sharpe": {"min_dsr": 0.3},
                      "final_block": {"min_trades": 1, "min_profit_factor": 0.0, "min_mean_r": -99}},
           "too_good": {"max_profit_factor": 2.0, "min_trades_for_pf_check": 50, "max_sharpe": 3.0}}
    rep = run_funnel(mk, cfg, out_dir=tmp_path, record=False, log=lambda m: None)
    from sqxf.funnel.pipeline import make_fitness, window
    from sqxf.generators.genetic import GAConfig, run_genetic
    ga = run_genetic("EURUSD", make_fitness(mk, [window(mk, a, b) for a, b in blocks], 5, "H1"),
                     GAConfig.from_dict(cfg["genetic"]), seed=1)
    pool = [s for s, _ in ga.archive.values()]
    mine = run_funnel_pool(mk, pool, cfg, n_trials=rep["dsr_inputs"]["n_trials"])
    for stage in ("generated", "basic", "stability", "cost_stress", "execution_stress", "walk_forward", "deflated_sharpe"):
        assert mine["counts"][stage] == rep["counts"][stage], stage
    assert mine["var_sr"] == pytest.approx(rep["dsr_inputs"]["var_sr_daily"], rel=1e-12)


def test_tracking_reports_the_killer_stage():
    m15 = canonicalize(synthetic_raw_m15(n_weeks=160, seed=32, start="2010-01-04"), make_config())
    mk = build_market("EURUSD", m15, Costs(0.0001, 1.0, 0.25))
    s = planted(SPEC)
    assert strategy_signal(mk, s).any()
    cfg = {"exec_timeframe_funnel": "M15", "fitness": {"min_trades_per_block": 5},
           "periods": {"fitness_blocks": [("2010-01-01", "2011-01-01")], "walk_forward_years": [2011],
                       "dsr_window": ["2010-01-01", "2012-01-01"]},
           "stages": {"basic": {"min_trades": 10 ** 6}, "stability": {"min_positive_blocks": 0},
                      "cost_stress": {"cost_multiplier": 2.0}, "execution_stress": {"entry_delay": 1},
                      "walk_forward": {"min_positive_years": 0, "min_trades_total": 0}, "deflated_sharpe": {"min_dsr": 0.0}}}
    out = run_funnel_pool(mk, [s], cfg, n_trials=10, track=0)
    assert out["tracked"]["killer"] == "basic" and not out["tracked"]["survived"]
