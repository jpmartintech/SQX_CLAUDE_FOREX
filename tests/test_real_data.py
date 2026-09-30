"""Oracle == Numba and causality invariants on real EURUSD Development data (skipped without data/raw).

Engineering evaluations only: nothing is selected, metrics are not inspected. Tests do not write to the trial ledger.
"""
import numpy as np
import pytest

from conftest import needs_data
from sqxf.grammar import random_strategy

pytestmark = [needs_data, pytest.mark.data]
N_STRATEGIES = 40


@pytest.fixture(scope="module")
def real():
    from sqxf.backtest.evaluator import load_market
    market = load_market("EURUSD")
    rng = np.random.default_rng(20260929)
    strategies = [random_strategy(rng, "EURUSD", max_predicates=2) for _ in range(N_STRATEGIES)]
    return market, strategies


@pytest.mark.parametrize("exec_tf,delay", [("M15", 0), ("M15", 2), ("H1", 0), ("H1", 1)])
def test_real_oracle_equals_numba(real, exec_tf, delay):
    from sqxf.backtest.evaluator import evaluate_light, evaluate_oracle, evaluate_rich
    market, strategies = real
    light = evaluate_light(market, strategies, exec_tf=exec_tf, delay=delay)
    n_trades = 0
    for i, s in enumerate(strategies):
        trades, agg = evaluate_oracle(market, s, exec_tf=exec_tf, delay=delay)
        rich = evaluate_rich(market, s, exec_tf=exec_tf, delay=delay)
        df = rich.trades
        assert len(df) == len(trades)
        for col in ("signal_idx", "entry_idx", "exit_idx", "entry_exec", "exit_exec", "entry_price", "exit_price", "r"):
            np.testing.assert_array_equal(df[col].to_numpy(), np.array([t[col] for t in trades]), err_msg=col)
        np.testing.assert_allclose(rich.agg, agg, rtol=1e-9, atol=1e-15)
        np.testing.assert_array_equal(light[i], rich.agg)
        if len(df):
            assert (df["exit_idx"] >= df["entry_idx"]).all() and (df["bars_held"] >= 1).all()
            assert (df["entry_idx"] == df["signal_idx"] + 1 + delay).all()
        n_trades += len(df)
    assert n_trades > 1000
