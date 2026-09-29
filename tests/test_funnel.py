"""Genetic search and funnel on synthetic markets: determinism, training-window isolation, stage accounting."""
import numpy as np
import pytest

from conftest import make_config, synthetic_raw_m15
from sqxf.backtest.evaluator import Costs, build_market
from sqxf.data.m15 import canonicalize
from sqxf.funnel.pipeline import daily_returns, make_fitness, run_funnel, window
from sqxf.generators.genetic import GAConfig, run_genetic

SMALL = GAConfig(population=60, generations=6, max_unique_evaluations=300, elite=5, tournament=3)
BLOCKS = [("2010-01-01", "2010-05-01"), ("2010-05-01", "2010-09-01"), ("2010-09-01", "2011-01-01")]


def _market(raw):
    return build_market("EURUSD", canonicalize(raw, make_config()), Costs(0.0001, 1.0, 0.25))


@pytest.fixture(scope="module")
def raw():
    return synthetic_raw_m15(n_weeks=160, seed=31, start="2010-01-04")


@pytest.fixture(scope="module")
def market(raw):
    return _market(raw)


def _ga(market, seed=7):
    blocks = [window(market, a, b) for a, b in BLOCKS]
    return run_genetic("EURUSD", make_fitness(market, blocks, 5, "H1"), SMALL, seed=seed)


def test_genetic_is_deterministic_and_counts_unique(market):
    a, b = _ga(market), _ga(market)
    assert list(a.archive) == list(b.archive)
    assert [f for _, f in a.archive.values()] == [f for _, f in b.archive.values()]
    assert a.n_evaluated == len(set(a.archive)) <= SMALL.max_unique_evaluations
    assert a.n_evaluated > SMALL.population  # it evolved beyond the first generation
    assert list(_ga(market, seed=8).archive) != list(a.archive)


def test_genetic_never_sees_data_after_the_training_windows(raw, market):
    """Scrambling every price after the last training block leaves the whole GA trajectory unchanged."""
    cut = int(np.searchsorted(raw["ts_local"].to_numpy(), np.datetime64("2011-01-01")))
    scr = raw.copy()
    rng = np.random.default_rng(3)
    f = np.exp(np.cumsum(rng.normal(0, 3e-3, len(raw) - cut)))
    for col in ("open", "high", "low", "close"):
        scr.loc[cut:, col] = raw.loc[cut:, col].to_numpy() * f
    a, b = _ga(market), _ga(_market(scr))
    assert list(a.archive) == list(b.archive)
    assert [f for _, f in a.archive.values()] == [f for _, f in b.archive.values()]


def test_daily_returns_compound_to_final_equity(market):
    from sqxf.backtest.evaluator import evaluate_rich
    from sqxf.grammar import random_strategy
    rng = np.random.default_rng(1)
    w = window(market, "2010-01-01", "2011-01-01")
    for _ in range(10):
        s = random_strategy(rng, "EURUSD", max_predicates=1)
        d = daily_returns(market, s, "M15", w)
        eq = evaluate_rich(market, s, exec_tf="M15", window=w).agg[6]
        assert np.prod(1 + d) == pytest.approx(eq, rel=1e-12)


def test_funnel_stage_counts_are_monotone(market, tmp_path):
    cfg = {"run_name": "synthetic", "seed": 1, "exec_timeframe_fitness": "H1", "exec_timeframe_funnel": "M15",
           "periods": {"fitness_blocks": BLOCKS, "walk_forward_years": [2011], "dsr_window": ["2010-01-01", "2012-01-01"],
                       "final_block": ["2012-01-01", "2013-01-01"]},
           "genetic": SMALL.__dict__, "fitness": {"min_trades_per_block": 5},
           "stages": {"basic": {"min_trades": 10, "min_profit_factor": 0.0, "min_mean_r": -99, "max_dd_mtm": 1.0},
                      "stability": {"min_positive_blocks": 0},
                      "cost_stress": {"cost_multiplier": 2.0, "min_profit_factor": 0.0, "min_mean_r": -99},
                      "execution_stress": {"entry_delay": 1, "min_profit_factor": 0.0, "min_mean_r": -99},
                      "walk_forward": {"min_positive_years": 0, "min_trades_total": 1, "min_profit_factor": 0.0,
                                       "min_mean_r": -99},
                      "deflated_sharpe": {"min_dsr": 0.0},
                      "final_block": {"min_trades": 1, "min_profit_factor": 0.0, "min_mean_r": -99}},
           "too_good": {"max_profit_factor": 2.0, "min_trades_for_pf_check": 50, "max_sharpe": 3.0}}
    rep = run_funnel(market, cfg, out_dir=tmp_path, record=False, log=lambda m: None)
    counts = list(rep["counts"].values())
    assert counts[0] == SMALL.max_unique_evaluations
    assert all(a >= b for a, b in zip(counts, counts[1:], strict=False))
    assert counts[-1] > 0 and len(rep["survivors"]) == counts[-1]
    assert (tmp_path / "report.json").exists()
