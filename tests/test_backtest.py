"""Evaluator correctness: golden cases, entry_delay causality, drawdown units, oracle == Numba (light and rich),
future-perturbation leak test and H1-vs-M15 execution consistency."""
import numpy as np
import pandas as pd
import pytest

from conftest import make_config, synthetic_raw_m15
from sqxf.backtest.evaluator import (
    Costs,
    build_market,
    derive_metrics,
    evaluate_light,
    evaluate_oracle,
    evaluate_rich,
)
from sqxf.backtest.kernels import simulate_rich
from sqxf.backtest.oracle import simulate_oracle
from sqxf.backtest.semantics import AGG, END, N_AGG, STOP, STOP_GAP, TARGET, TIME, TRADE
from sqxf.data.m15 import canonicalize
from sqxf.features.predicates import pack_bits
from sqxf.grammar import random_strategy

RISK = 0.005
DPY = 260.0


# ------------------------------------------------------------------ helpers for hand-built H1-only markets
def run_both(signal, o, h, l, c, atr, direction=1, sl=1.0, tp=2.0, max_bars=10, delay=0, cost=0.0, t0=0, t1=None,
             day_id=None):
    """Run the oracle and the rich kernel on identity-mapped bars; assert identical trades; return oracle output."""
    n = len(o)
    t1 = n if t1 is None else t1
    idx = np.arange(n, dtype=np.int64)
    day_id = np.arange(n, dtype=np.int64) if day_id is None else day_id
    arrs = [np.asarray(x, dtype=np.float64) for x in (o, h, l, c)]
    atr = np.asarray(atr, dtype=np.float64)
    trades, agg = simulate_oracle(np.asarray(signal, bool), atr, idx, idx + 1, idx, *arrs, day_id, direction, sl, tp,
                                  max_bars, delay, cost, RISK, DPY, t0, t1)
    rec, kagg = simulate_rich(pack_bits(np.asarray(signal, bool)[None, :]), np.array([0, -1, -1, -1]), 1,
                              pack_bits(np.ones(n, bool)), atr, idx, idx + 1, idx, *arrs, day_id, direction, sl, tp,
                              max_bars, delay, cost, RISK, DPY, t0, t1, np.zeros(n), np.zeros(n), np.zeros(n), 1.0,
                              np.inf, 0.0, np.zeros(n, dtype=np.bool_))
    assert len(rec) == len(trades)
    for row, tr in zip(rec, trades, strict=True):
        for name, j in TRADE.items():
            assert row[j] == tr[name], name
    np.testing.assert_allclose(kagg, agg, rtol=1e-12, atol=1e-15)
    return trades, agg


def flat_bars(n, price=1.0, rng=0.0):
    o = np.full(n, price)
    return o, o + rng, o - rng, o.copy()


# ------------------------------------------------------------------ golden cases
def test_sl_and_tp_in_same_bar_stop_wins():
    o, h, l, c = flat_bars(6)
    h[2], l[2] = 1.05, 0.95  # entry bar 2 touches both stop (0.99) and target (1.02)
    sig = np.zeros(6, bool)
    sig[1] = True
    trades, _ = run_both(sig, o, h, l, c, atr=np.full(6, 0.01), sl=1.0, tp=2.0)
    (tr,) = trades
    assert tr["entry_idx"] == 2 and tr["exit_idx"] == 2 and tr["reason"] == STOP
    assert tr["exit_price"] == pytest.approx(0.99) and tr["r"] == pytest.approx(-1.0)


def test_short_same_bar_stop_wins_and_target():
    o, h, l, c = flat_bars(8)
    h[2], l[2] = 1.05, 0.95
    l[5] = 0.97
    sig = np.zeros(8, bool)
    sig[[1, 3]] = True
    trades, _ = run_both(sig, o, h, l, c, atr=np.full(8, 0.01), direction=-1, sl=1.0, tp=2.0)
    assert [t["reason"] for t in trades] == [STOP, TARGET]
    assert trades[0]["exit_price"] == pytest.approx(1.01)
    assert trades[1]["entry_idx"] == 4 and trades[1]["exit_price"] == pytest.approx(0.98)
    assert trades[1]["r"] == pytest.approx(2.0)


def test_gap_through_stop_exits_at_open():
    o, h, l, c = flat_bars(6)
    o[3], h[3], l[3], c[3] = 0.97, 0.975, 0.96, 0.97
    sig = np.zeros(6, bool)
    sig[1] = True
    trades, _ = run_both(sig, o, h, l, c, atr=np.full(6, 0.01))
    (tr,) = trades
    assert tr["reason"] == STOP_GAP and tr["exit_price"] == 0.97 and tr["r"] == pytest.approx(-3.0)


@pytest.mark.parametrize("delay", [1, 2, 3])
def test_entry_delay_position_does_not_exist_before_entry(delay):
    """Reference bug 1: with delay >= 1 the old engine evaluated SL/TP between the signal and the real entry."""
    n = 12
    o, h, l, c = flat_bars(n)
    # Crash right after the signal: bars 2..(1+delay) trade far below any stop, then price recovers at the entry bar.
    for i in range(2, 2 + delay):
        o[i] = h[i] = l[i] = c[i] = 0.90
    sig = np.zeros(n, bool)
    sig[1] = True
    trades, _ = run_both(sig, o, h, l, c, atr=np.full(n, 0.01), delay=delay, max_bars=3)
    (tr,) = trades
    assert tr["entry_idx"] == 1 + 1 + delay
    assert tr["entry_price"] == 1.0
    assert tr["exit_idx"] >= tr["entry_idx"]
    assert tr["reason"] == TIME and tr["exit_idx"] == tr["entry_idx"] + 2
    assert tr["r"] == 0.0


def test_time_exit_counts_bars_from_entry_and_end_clipping():
    o, h, l, c = flat_bars(10)
    sig = np.zeros(10, bool)
    sig[0] = True
    sig[6] = True
    trades, _ = run_both(sig, o, h, l, c, atr=np.full(10, 0.01), max_bars=4)
    assert trades[0]["reason"] == TIME and trades[0]["exit_idx"] - trades[0]["entry_idx"] + 1 == 4
    assert trades[1]["entry_idx"] == 7 and trades[1]["reason"] == END and trades[1]["exit_idx"] == 9


def test_next_signal_may_be_the_exit_bar():
    o, h, l, c = flat_bars(8)
    l[2] = 0.95
    sig = np.zeros(8, bool)
    sig[[1, 2]] = True
    trades, _ = run_both(sig, o, h, l, c, atr=np.full(8, 0.01), max_bars=2)
    assert [(t["signal_idx"], t["entry_idx"], t["exit_idx"]) for t in trades] == [(1, 2, 2), (2, 3, 4)]


def test_costs_are_charged_in_r():
    o, h, l, c = flat_bars(6)
    h[3] = 1.05
    sig = np.zeros(6, bool)
    sig[1] = True
    trades, _ = run_both(sig, o, h, l, c, atr=np.full(6, 0.01), cost=0.0002)
    assert trades[0]["reason"] == TARGET and trades[0]["r"] == pytest.approx(2.0 - 0.02)


# ------------------------------------------------------------------ units (reference bug 2)
def test_drawdown_is_percent_of_equity_with_fractional_risk():
    n = 60
    o, h, l, c = flat_bars(n)
    sig = np.zeros(n, bool)
    for k in range(10):  # 10 consecutive -1R trades (stop hit in the entry bar)
        sig[3 * k] = True
        l[3 * k + 1] = 0.98
    trades, agg = run_both(sig, o, h, l, c, atr=np.full(n, 0.01))
    assert len(trades) == 10 and all(t["r"] == pytest.approx(-1.0) for t in trades)
    expected = 1 - (1 - RISK) ** 10
    assert agg[AGG["max_dd"]] == pytest.approx(expected, rel=1e-12)
    assert 0.048 < agg[AGG["max_dd"]] < 0.049  # ~4.9 %, not ~1e-5
    m = derive_metrics(agg)
    assert m["max_consec_losses"] == 10 and m["total_r"] == pytest.approx(-10.0)


def test_sharpe_is_daily_and_counts_flat_days():
    n = 40
    o, h, l, c = flat_bars(n)
    sig = np.zeros(n, bool)
    sig[[0, 10, 20]] = True
    for i in (1, 11, 21):
        h[i] = 1.05
    trades, agg = run_both(sig, o, h, l, c, atr=np.full(n, 0.01))
    daily = np.zeros(n)
    daily[[1, 11, 21]] = RISK * 2.0 / np.array([1, 1 + RISK * 2, (1 + RISK * 2) ** 2]) * np.array(
        [1, 1 + RISK * 2, (1 + RISK * 2) ** 2])
    expected = daily.mean() / daily.std() * np.sqrt(DPY)
    assert agg[AGG["sharpe"]] == pytest.approx(expected, rel=1e-9)


# ------------------------------------------------------------------ synthetic markets
@pytest.fixture(scope="module")
def market():
    m15 = canonicalize(synthetic_raw_m15(n_weeks=60, seed=11), make_config())
    return build_market("EURUSD", m15, Costs(0.0001, 1.0, 0.25))


@pytest.fixture(scope="module")
def strategies():
    rng = np.random.default_rng(2024)
    return [random_strategy(rng, "EURUSD", max_predicates=2) for _ in range(120)]


def _assert_same(trades, rich, agg_oracle):
    df = rich.trades
    assert len(df) == len(trades)
    for name in ("signal_idx", "entry_idx", "exit_idx", "entry_exec", "exit_exec", "entry_price", "exit_price",
                 "stop", "target", "risk", "r", "equity_after"):
        np.testing.assert_array_equal(df[name].to_numpy(), np.array([t[name] for t in trades], dtype=df[name].dtype),
                                      err_msg=name)
    np.testing.assert_allclose(rich.agg, agg_oracle, rtol=1e-9, atol=1e-15)


@pytest.mark.parametrize("exec_tf", ["H1", "M15"])
@pytest.mark.parametrize("delay", [0, 1, 3])
def test_numba_rich_and_light_equal_python_oracle(market, strategies, exec_tf, delay):
    light = evaluate_light(market, strategies, exec_tf=exec_tf, delay=delay)
    assert light.shape == (len(strategies), N_AGG)
    total = 0
    for i, s in enumerate(strategies):
        trades, agg = evaluate_oracle(market, s, exec_tf=exec_tf, delay=delay)
        rich = evaluate_rich(market, s, exec_tf=exec_tf, delay=delay)
        _assert_same(trades, rich, agg)
        np.testing.assert_array_equal(light[i], rich.agg)  # light and rich share the core: bit-identical
        total += len(trades)
    assert total > 500  # the comparison actually exercised trades


@pytest.mark.parametrize("delay", [0, 2])
def test_causality_invariants(market, strategies, delay):
    ex = market.execs["M15"]
    for s in strategies[:60]:
        df = evaluate_rich(market, s, exec_tf="M15", delay=delay).trades
        if df.empty:
            continue
        assert (df["exit_idx"] >= df["entry_idx"]).all()
        assert (df["bars_held"] >= 1).all()
        assert (df["entry_idx"] == df["signal_idx"] + 1 + delay).all()
        assert (df["entry_exec"] == ex.h1_start[df["entry_idx"]]).all()
        assert (df["exit_exec"] >= df["entry_exec"]).all()
        assert (df["signal_idx"].to_numpy()[1:] >= df["exit_idx"].to_numpy()[:-1]).all()
        assert market.tradable[df["signal_idx"]].all()
        stops = df["reason"].isin(["STOP", "STOP_GAP"])
        sgn = s.sign
        assert ((sgn * (df.loc[stops, "exit_price"] - df.loc[stops, "entry_price"])) < 0).all()
        assert (df.loc[stops, "r"] <= -1.0 + 1e-12).all()


def test_future_perturbation_does_not_change_past_trades(strategies):
    """Leak test on the full pipeline (H1 build, features, predicates, kernels): scrambling prices after T leaves every
    trade that exits before T unchanged."""
    raw = synthetic_raw_m15(n_weeks=40, seed=5)
    cut = int(len(raw) * 0.6)
    scrambled = raw.copy()
    rng = np.random.default_rng(99)
    k = np.arange(cut, len(raw))
    factor = np.exp(np.cumsum(rng.normal(0, 2e-3, len(k))))
    for col in ("open", "high", "low", "close"):
        scrambled.loc[k, col] = raw.loc[k, col].to_numpy() * factor
    cfgd = make_config()
    ma = build_market("EURUSD", canonicalize(raw, cfgd), Costs(0.0001, 1.0, 0.25))
    mb = build_market("EURUSD", canonicalize(scrambled, cfgd), Costs(0.0001, 1.0, 0.25))
    t_cut = ma.execs["M15"].h1_of[cut]  # H1 bar containing the first scrambled M15 bar
    compared = 0
    for s in strategies[:80]:
        a = evaluate_rich(ma, s, exec_tf="M15", delay=1).trades
        b = evaluate_rich(mb, s, exec_tf="M15", delay=1).trades
        a_past, b_past = a[a["exit_idx"] < t_cut], b[b["exit_idx"] < t_cut]
        pd.testing.assert_frame_equal(a_past.reset_index(drop=True), b_past.reset_index(drop=True))
        compared += len(a_past)
    assert compared > 100


def test_h1_and_m15_execution_agree_until_an_ambiguous_bar():
    """With continuous M15 (open = previous close) the only way H1 and M15 execution can diverge is an H1 bar where
    both stop and target are touched (H1 must assume the stop; M15 knows the order)."""
    m15 = canonicalize(synthetic_raw_m15(n_weeks=40, seed=21, continuous=True, drop_frac=0.0), make_config())
    mk = build_market("EURUSD", m15, Costs(0.0001, 1.0, 0.25))
    ex = mk.execs["H1"]
    rng = np.random.default_rng(8)
    diverged = identical = 0
    for _ in range(100):
        s = random_strategy(rng, "EURUSD", max_predicates=2)
        a = evaluate_rich(mk, s, exec_tf="H1").trades
        b = evaluate_rich(mk, s, exec_tf="M15").trades
        cols = ["signal_idx", "entry_idx", "exit_idx", "entry_price", "exit_price", "r"]
        n = min(len(a), len(b))
        eq = (a[cols].iloc[:n].to_numpy() == b[cols].iloc[:n].to_numpy()).all(axis=1)
        if eq.all() and len(a) == len(b):
            identical += 1
            continue
        diverged += 1
        j = int(np.argmin(eq)) if not eq.all() else n
        tr = a.iloc[j]
        x = int(tr["exit_idx"])
        both = (ex.l[x] <= tr["stop"] and ex.h[x] >= tr["target"]) if s.sign == 1 else \
               (ex.h[x] >= tr["stop"] and ex.l[x] <= tr["target"])
        assert tr["reason"] == "STOP" and both, (s, j)
    assert identical > 0 and diverged > 0


def test_mark_to_market_drawdown_sees_intratrade_losses():
    """A trade that dips to -0.9R and then hits the target has 0 closed-trade drawdown but ~0.45 % MTM drawdown."""
    o, h, l, c = flat_bars(8)
    l[2], c[2] = 0.991, 0.995   # bar 2: adverse extreme -0.9R (risk 0.01), closes at -0.5R
    h[4] = 1.03                 # bar 4: target (+2R)
    sig = np.zeros(8, bool)
    sig[1] = True
    trades, agg = run_both(sig, o, h, l, c, atr=np.full(8, 0.01), sl=1.0, tp=2.0)
    assert trades[0]["reason"] == TARGET
    assert agg[AGG["max_dd"]] == 0.0
    assert agg[AGG["max_dd_mtm"]] == pytest.approx(1 - (1 - RISK * 0.9), rel=1e-12)


def test_mtm_drawdown_is_at_least_closed_trade_drawdown(market, strategies):
    agg = evaluate_light(market, strategies, exec_tf="M15")
    assert (agg[:, AGG["max_dd_mtm"]] >= agg[:, AGG["max_dd"]] - 1e-15).all()
