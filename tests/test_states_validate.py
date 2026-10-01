"""Phase S Part 2 machinery on synthetic data (no real returns)."""
import math

import numpy as np
import pandas as pd
import pytest

from conftest import make_config, synthetic_raw_m15
from sqxf.backtest.evaluator import Costs
from sqxf.backtest.oracle import simulate_oracle
from sqxf.data.m15 import canonicalize
from sqxf.states.pipeline import compute_states
from sqxf.states.validate import (
    bars_market,
    block_bootstrap_means,
    calibration_signals,
    daily_series,
    forward_net,
    holm,
    matched_control,
    rule_signals,
    run_signal,
    window_of,
)
from test_states import CFG


@pytest.fixture(scope="module")
def m15():
    return canonicalize(synthetic_raw_m15(n_weeks=80, seed=17, start="2014-01-06"), make_config())


@pytest.fixture(scope="module")
def mk(m15):
    return bars_market("EURUSD", m15, "H1", Costs(0.0001, 1.0, 0.25), 1.0, 1.0)


@pytest.mark.parametrize("direction,trail", [(1, 0.0), (-1, 3.0), (1, 2.0)])
def test_run_signal_equals_oracle_with_swap_trailing_and_exits(mk, direction, trail):
    rng = np.random.default_rng(1)
    sig = rng.random(mk.n_h1) < 0.02
    xs = rng.random(mk.n_h1) < 0.01
    w = window_of(mk, "2014-06-01", "2015-06-01")
    df, agg = run_signal(mk, sig, direction, 2.0, 120, trail, xs, w, cost_mult=2.0, swap_mult=2.0)
    ex = mk.execs["M15"]
    fr, fr_abs = ex.funding_arrays()
    trades, oagg = simulate_oracle(sig & mk.tradable, mk.atr, ex.h1_start, ex.h1_end, ex.h1_of, ex.o, ex.h, ex.l, ex.c,
                                   ex.day_id, direction, 2.0, math.inf, 120, 0, mk.costs.round_trip * 2.0, 0.005, 260.0,
                                   w[0], w[1], np.zeros(mk.n_h1), fr, fr_abs, 2.0, math.inf, trail, xs)
    assert len(df) == len(trades) > 20
    np.testing.assert_array_equal(df["r"].to_numpy(), np.array([t["r"] for t in trades]))
    np.testing.assert_allclose(agg, oagg, rtol=1e-9, atol=1e-15)
    assert (df["funding"] < 0).any()  # the conservative swap is charged
    s = daily_series(mk, df, w)
    assert np.prod(1 + s.to_numpy()) == pytest.approx(df["equity_after"].iat[-1], rel=1e-12)


def test_forward_net_uses_next_open_and_horizon_close():
    bars = pd.DataFrame({"open": [1.0, 1.1, 1.2, 1.3, 1.4], "close": [1.05, 1.15, 1.25, 1.35, 1.45]})
    d = np.array([1, -1, 0, 1, 1], float)
    net = forward_net(bars, d, horizon=2, pip=0.01, cost_pips=1.5)
    assert net[0] == pytest.approx((1.25 - 1.1) / 0.01 - 1.5)
    assert net[1] == pytest.approx(-(1.35 - 1.2) / 0.01 - 1.5)
    assert np.isnan(net[2]) and np.isnan(net[3]) and np.isnan(net[4])


def test_block_bootstrap_is_deterministic_and_calibrated():
    rng = np.random.default_rng(0)
    n = 6000
    state = rng.integers(0, 3, n).astype(float)
    net = rng.normal(0, 10, n)
    net[state == 2] += 5.0
    a = block_bootstrap_means(state, net, 3, 120, 300, seed=1)
    b = block_bootstrap_means(state, net, 3, 120, 300, seed=1)
    np.testing.assert_array_equal(a, b)
    p = (a <= 0).mean(axis=0)
    assert 0.1 < p[0] < 0.9 and p[2] < 0.01


def test_holm_known_example():
    np.testing.assert_allclose(holm(np.array([0.01, 0.04, 0.03, 0.005])), [0.03, 0.06, 0.06, 0.02])


def test_signals_are_transitions_and_control_runs(m15, mk):
    st = compute_states(m15, CFG)
    for rule in ("R1_trend_continuation", "R2_pullback_end", "R3_compression_release", "R4_regime_change"):
        s = rule_signals(st["combined"], st["aligned"]["H4"], rule)
        for d in (1, -1):
            assert s[d].dtype == bool and s[d].sum() < 0.2 * len(s[d])
    r4 = rule_signals(st["combined"], st["aligned"]["H4"], "R4_regime_change")
    reg = st["combined"]["regime"].to_numpy()
    assert (reg[r4[1]] == 1).all() and (np.r_[np.nan, reg[:-1]][r4[1]] != 1).all()
    h4 = bars_market("EURUSD", m15, "H4", Costs(0.0001, 1.0, 0.25), 1.0, 1.0)
    cs = calibration_signals(h4)
    assert not (cs[1] & cs[-1]).any()
    w = window_of(mk, "2014-06-01", "2015-06-01")
    df, _ = run_signal(mk, r4[1] | r4[-1], 1, 8.0, 480, 0.0, r4["exit_1"], w)
    ctl = matched_control(mk, df, w, replicas=3, seed=2)
    assert len(ctl) == 3
