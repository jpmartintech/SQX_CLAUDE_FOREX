"""Trailing stop, exit-on-signal and forex swap: golden cases, causality and oracle == Numba."""
import math

import numpy as np
import pandas as pd
import pytest

from conftest import make_config, synthetic_raw_m15
from sqxf.backtest.evaluator import Costs, build_market, evaluate_light, evaluate_oracle, evaluate_rich
from sqxf.backtest.kernels import simulate_rich
from sqxf.backtest.oracle import simulate_oracle
from sqxf.backtest.semantics import SIGNAL, TIME, TRADE, TRAIL
from sqxf.backtest.swap import forex_swap_arrays
from sqxf.data.m15 import canonicalize
from sqxf.features.predicates import pack_bits
from sqxf.grammar import random_strategy


def _run(sig, o, h, l, c, direction=1, sl=1.0, tp=math.inf, max_bars=20, trail=0.0, exit_sig=None, fr=None, fr_abs=None,
         fmult=1.0):
    n = len(o)
    idx = np.arange(n, dtype=np.int64)
    arrs = [np.asarray(x, float) for x in (o, h, l, c)]
    atr = np.full(n, 0.01)
    xs = np.zeros(n, np.bool_) if exit_sig is None else np.asarray(exit_sig, np.bool_)
    fr = np.zeros(n) if fr is None else fr
    fr_abs = np.zeros(n) if fr_abs is None else fr_abs
    trades, agg = simulate_oracle(sig, atr, idx, idx + 1, idx, *arrs, idx, direction, sl, tp, max_bars, 0, 0.0, 0.005, 260.0,
                                  0, n, np.zeros(n), fr, fr_abs, fmult, math.inf, trail, xs)
    rec, kagg = simulate_rich(pack_bits(sig[None, :]), np.array([0, -1, -1, -1]), 1, pack_bits(np.ones(n, bool)), atr, idx,
                              idx + 1, idx, *arrs, idx, direction, sl, tp, max_bars, 0, 0.0, 0.005, 260.0, 0, n,
                              np.zeros(n), fr, fr_abs, fmult, math.inf, trail, xs)
    assert len(rec) == len(trades)
    for row, tr in zip(rec, trades, strict=True):
        for name, j in TRADE.items():
            assert row[j] == tr[name], name
    np.testing.assert_allclose(kagg, agg, rtol=1e-12, atol=1e-15)
    return trades


def _flat(n=12, p=1.0):
    o = np.full(n, p)
    return o.copy(), o + 0.001, o - 0.001, o.copy()


def test_trailing_moves_from_the_next_bar_only_and_exits_as_trail():
    o, h, l, c = _flat()
    sig = np.zeros(12, bool)
    sig[1] = True
    h[2], l[2], c[2] = 1.05, 1.035, 1.045   # same bar: high moves the stop to 1.04, but the low 1.035 cannot use it yet
    o[3], h[3], l[3], c[3] = 1.045, 1.046, 1.035, 1.036
    (tr,) = _run(sig, o, h, l, c, trail=1.0)
    assert tr["exit_idx"] == 3 and tr["reason"] == TRAIL and tr["exit_price"] == pytest.approx(1.04)
    assert tr["stop"] == pytest.approx(0.99)   # the recorded stop is the initial one


def test_short_trailing_mirror():
    o, h, l, c = _flat()
    sig = np.zeros(12, bool)
    sig[1] = True
    l[3], c[3] = 0.95, 0.955
    o[4], h[4], l[4], c[4] = 0.955, 0.956, 0.954, 0.955   # stop now 0.96 (from bar 3's low); bar 4 stays below it
    o[5], h[5], l[5] = 0.955, 0.965, 0.954
    (tr,) = _run(sig, o, h, l, c, direction=-1, trail=1.0)
    assert tr["reason"] == TRAIL and tr["exit_price"] == pytest.approx(0.96)


def test_exit_signal_exits_at_next_open_and_ignores_signals_before_entry():
    o, h, l, c = _flat()
    o[5] = 1.003
    sig = np.zeros(12, bool)
    sig[1] = True
    xs = np.zeros(12, bool)
    xs[1] = True          # at the signal bar itself (before the entry bar 2): ignored
    xs[4] = True          # at the close of bar 4 -> exit at the open of bar 5
    (tr,) = _run(sig, o, h, l, c, exit_sig=xs)
    assert tr["entry_idx"] == 2 and tr["exit_idx"] == 5 and tr["reason"] == SIGNAL and tr["exit_price"] == 1.003
    (tr2,) = _run(sig, o, h, l, c, exit_sig=np.zeros(12, bool), max_bars=4)
    assert tr2["reason"] == TIME


@pytest.fixture(scope="module")
def market():
    m15 = canonicalize(synthetic_raw_m15(n_weeks=50, seed=13), make_config())
    return build_market("EURUSD", m15, Costs(0.0001, 1.0, 0.25))


@pytest.mark.parametrize("exec_tf", ["H1", "M15"])
@pytest.mark.parametrize("trail", [0.0, 2.0])
def test_oracle_equals_numba_with_trailing_and_exit_signals(market, exec_tf, trail):
    rng = np.random.default_rng(4)
    xs = rng.random(market.n_h1) < 0.03
    strategies = [random_strategy(rng, "EURUSD", max_predicates=2) for _ in range(60)]
    strategies = [type(s)(s.pair, s.direction, s.predicates, s.sl_atr, s.tp_atr, 96) for s in strategies]
    light = evaluate_light(market, strategies, exec_tf=exec_tf, trail_atr=trail, exit_signal=xs)
    reasons = set()
    for i, s in enumerate(strategies):
        trades, agg = evaluate_oracle(market, s, exec_tf=exec_tf, trail_atr=trail, exit_signal=xs)
        rich = evaluate_rich(market, s, exec_tf=exec_tf, trail_atr=trail, exit_signal=xs)
        df = rich.trades
        for col in ("entry_idx", "exit_idx", "exit_price", "r", "equity_after"):
            np.testing.assert_array_equal(df[col].to_numpy(), np.array([t[col] for t in trades]), err_msg=col)
        np.testing.assert_allclose(rich.agg, agg, rtol=1e-9, atol=1e-15)
        np.testing.assert_array_equal(light[i], rich.agg)
        reasons |= set(df["reason"])
    assert "SIGNAL" in reasons and (trail == 0 or "TRAIL" in reasons)


def test_forex_swap_rollover_schedule_and_direction():
    ts = pd.Series(pd.to_datetime(["2020-01-06 00:00", "2020-01-07 00:00", "2020-01-08 00:00", "2020-01-09 00:00",
                                   "2020-01-10 00:00", "2020-01-10 00:15"]))  # Mon..Fri 00:00, Fri 00:15
    o = np.full(6, 1.1)
    fr, fr_abs = forex_swap_arrays(ts, o, swap_long_pips=0.8, swap_short_pips=0.3, pip=0.0001)
    long_pay = -(fr * o) - fr_abs * o
    short_pay = fr * o - fr_abs * o
    np.testing.assert_allclose(long_pay, -0.8e-4 * np.array([0, 1, 1, 3, 1, 0]), atol=1e-15)
    np.testing.assert_allclose(short_pay, -0.3e-4 * np.array([0, 1, 1, 3, 1, 0]), atol=1e-15)
