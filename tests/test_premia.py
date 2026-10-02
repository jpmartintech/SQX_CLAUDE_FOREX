"""C2 premia engine and signals: accounting, causality, stress, matched control, bootstrap."""
import numpy as np
import pandas as pd

from sqxf.premia.build import _schedule, _xs_weights, inverse_vol_gross1, tsmom_signal
from sqxf.premia.engine import bootstrap_stats, max_drawdown, participation_ratio, simulate, spell_flips


def _z(n, k):
    return np.zeros((n, k))


def test_buy_and_hold_compounds_and_pays_cost_once():
    rng = np.random.default_rng(0)
    r = rng.normal(0, 0.01, (50, 1))
    tg = np.full((50, 1), np.nan)
    tg[0] = 1.0
    out = simulate(r, _z(50, 1), _z(50, 1), np.full((50, 1), 0.001), tg)
    assert np.isclose(out["equity"][-1], (1 - 0.001) * np.prod(1 + r[1:, 0]))
    assert out["turnover"][0] == 1.0 and out["turnover"][1:].sum() == 0


def test_targets_earn_only_from_the_next_day():
    r = np.zeros((5, 1))
    r[2, 0] = 0.10                       # move on day 2
    tg = np.full((5, 1), np.nan)
    tg[2] = 1.0                          # set at the close of day 2 -> must NOT earn day 2's move
    out = simulate(r, _z(5, 1), _z(5, 1), _z(5, 1), tg)
    assert np.allclose(out["ret"], 0.0)
    tg = np.full((5, 1), np.nan)
    tg[1] = 1.0
    assert np.isclose(simulate(r, _z(5, 1), _z(5, 1), _z(5, 1), tg)["ret"][2], 0.10)


def test_funding_sign_and_payment_stress():
    n = 4
    f = np.full((n, 1), 0.001)           # positive funding: longs pay, shorts receive
    for w, expect in ((1.0, -0.001), (-1.0, 0.001)):
        tg = np.full((n, 1), np.nan)
        tg[0] = w
        assert np.isclose(simulate(_z(n, 1), -f, _z(n, 1), _z(n, 1), tg)["ret"][1], expect)
        x2 = simulate(_z(n, 1), -f, _z(n, 1), _z(n, 1), tg, pay_mult=2.0)["ret"][1]
        assert np.isclose(x2, 2 * expect if expect < 0 else expect)      # only payments are doubled
    tg = np.full((n, 1), np.nan)
    tg[0] = -1.0
    assert np.isclose(simulate(_z(n, 1), _z(n, 1), np.full((n, 1), 0.0002), _z(n, 1), tg)["ret"][1], -0.0002)


def test_hedged_pair_has_no_price_risk():
    rng = np.random.default_rng(1)
    r = rng.normal(0, 0.03, (30, 1))
    tg = np.full((30, 2), np.nan)
    tg[0] = [1.0, -1.0]
    out = simulate(np.c_[r, r], _z(30, 2), _z(30, 2), _z(30, 2), tg)
    assert abs(out["ret"][1]) < 1e-12           # first day exactly hedged; drift afterwards is the basis of equal moves


def test_signals_are_causal_prefix_invariant():
    rng = np.random.default_rng(2)
    close = np.exp(np.cumsum(rng.normal(0, 0.02, (400, 3)), axis=0))
    s_full = tsmom_signal(close)
    s_cut = tsmom_signal(close[:250])
    assert np.array_equal(s_full[:250], s_cut)
    assert set(np.unique(s_full[130:])) <= {-1, -1 / 3, 1 / 3, 1}


def test_weight_rules():
    vol = np.array([0.5, 1.0, 0.8, 0.6, 0.9, 0.7])
    w = inverse_vol_gross1(np.array([1, -1, 1 / 3, 0, 1, -1 / 3]), np.ones(6, bool), vol)
    assert np.abs(w).sum() <= 1 + 1e-12
    x = _xs_weights(np.array([5.0, 1, 3, 2, 4, 0]), np.ones(6, bool), vol, long_high=True)
    assert np.isclose(x[x > 0].sum(), 0.5) and np.isclose(x[x < 0].sum(), -0.5)
    assert x[0] > 0 and x[4] > 0 and x[5] < 0 and x[1] < 0 and x[2] == 0 and x[3] == 0
    assert not _xs_weights(np.array([1.0, 2]), np.ones(2, bool), vol[:2], True).any()


def test_schedule_starts_the_day_before_the_window():
    cal = pd.date_range("2020-01-01", "2020-03-31", freq="D")
    m = _schedule(cal, "monthly", "2020-01-15")
    assert cal[m][0] == pd.Timestamp("2020-01-14") and pd.Timestamp("2020-01-31") in cal[m]
    assert not m[:13].any()
    w = _schedule(cal, "weekly", "2020-01-15")
    assert all(d.dayofweek == 6 for d in cal[w][1:])


def test_spell_flips_keep_magnitude_and_schedule():
    rng = np.random.default_rng(3)
    tg = np.full((20, 2), np.nan)
    tg[::2] = rng.choice([-1.0, 0.0, 1.0], (10, 2)) * 0.4
    f = spell_flips(tg, np.array([0, 1]), np.random.default_rng(4))
    assert np.array_equal(np.isnan(f), np.isnan(tg))
    assert np.allclose(np.abs(np.nan_to_num(f)), np.abs(np.nan_to_num(tg)))
    tg2 = np.full((6, 2), np.nan)
    tg2[[0, 2, 4]] = [[0.5, -0.5], [0.5, -0.5], [0.5, -0.5]]
    f2 = spell_flips(tg2, np.array([0, 0]), np.random.default_rng(5))
    assert np.allclose(f2[[0, 2, 4], 0], -f2[[0, 2, 4], 1])        # a group flips together
    assert len(set(f2[[0, 2, 4], 0])) == 1                          # one spell -> one direction


def test_bootstrap_p_values():
    rng = np.random.default_rng(6)
    pos = bootstrap_stats(rng.normal(0.002, 0.01, 1500), 20, 2000, 1, 365.0)
    assert pos["p_one_sided"] < 0.01 and pos["t"] > 3
    null = [bootstrap_stats(rng.normal(0, 0.01, 500), 20, 400, s, 365.0)["p_one_sided"] for s in range(40)]
    assert 0.2 < np.mean(null) < 0.8


def test_drawdown_and_participation():
    assert np.isclose(max_drawdown(np.array([0.1, -0.5, 0.2])), -0.5)
    rng = np.random.default_rng(7)
    assert participation_ratio(rng.normal(size=(5000, 4))) > 3.8
    x = rng.normal(size=(5000, 1))
    assert participation_ratio(np.c_[x, x + 1e-3 * rng.normal(size=(5000, 1))]) < 1.01
