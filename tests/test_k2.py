"""Phase K2 machinery: shared day order, CBB standard error, segment membership, combined daily series, preselection."""
import numpy as np

from conftest import make_config, synthetic_raw_m15
from sqxf.backtest.evaluator import Costs, build_market
from sqxf.control.k2 import cbb_se, combined_daily, masked_series, multi_world_shapes, on_pair, preselect, tstat
from sqxf.data.m15 import canonicalize
from sqxf.funnel.pipeline import daily_returns, window
from sqxf.grammar import random_strategy


def _dev(n_days, pairs, seed=0):
    rng = np.random.default_rng(seed)
    out = {"days": np.arange(n_days), "pairs": {}}
    for k, p in enumerate(pairs):
        sh = rng.normal(0, 1e-4, (n_days * 96, 4))
        sh[:, 3] += k                                   # tag each pair
        out["pairs"][p] = {"shapes": sh, "day_start": np.arange(n_days) * 96, "volume": np.ones(n_days * 96), "o0": 1.0}
    return out


def test_same_day_order_for_all_pairs():
    dev = _dev(50, ["A", "B"])
    w = multi_world_shapes(dev, ["A", "B"], seed=4, n_total=60)
    assert len(w["A"]["shapes"]) == 60 * 96
    a = w["A"]["shapes"][:, 0]
    b = w["B"]["shapes"][:, 0]
    src = dev["pairs"]["A"]["shapes"][:, 0]
    idx_a = [int(np.flatnonzero(src == v)[0]) for v in a[::96][:50]]
    idx_b = [int(np.flatnonzero(dev["pairs"]["B"]["shapes"][:, 0] == v)[0]) for v in b[::96][:50]]
    assert idx_a == idx_b and sorted(i // 96 for i in idx_a) == list(range(50))   # permutation of the pool, shared


def test_cbb_closed_form_matches_monte_carlo():
    rng = np.random.default_rng(1)
    e = rng.normal(size=3000)
    x = np.convolve(e, np.ones(5) / 5, mode="same")             # autocorrelated
    se = cbb_se(x, 20)[0]
    n, b = len(x), 20
    means = []
    for _ in range(4000):
        st = rng.integers(0, n, n // b)
        means.append(x[((st[:, None] + np.arange(b)) % n).ravel()].mean())
    assert abs(se / np.std(means) - 1) < 0.05
    assert se > x.std() / np.sqrt(n) * 1.5                        # wider than iid under positive autocorrelation
    assert tstat(np.zeros((2, 10)), 3).tolist() == [0.0, 0.0]


def test_masked_series_only_trades_selected_segments():
    dates = np.arange(np.datetime64("2009-01-01"), np.datetime64("2011-01-01"))
    daily = np.ones((2, len(dates)))
    member = np.array([[True, False], [False, True]])
    m = masked_series(daily, dates, member, [("2009-01-01", "2010-01-01"), ("2010-01-01", "2011-01-01")])
    y2009 = dates < np.datetime64("2010-01-01")
    assert m[0, y2009].all() and not m[0, ~y2009].any() and m[1, ~y2009].all() and not m[1, y2009].any()


def _markets():
    out = {}
    for k, p in enumerate(["EURUSD", "GBPUSD"]):
        m15 = canonicalize(synthetic_raw_m15(n_weeks=120, seed=40 + k, start="2010-01-04"), make_config())
        out[p] = build_market(p, m15, Costs(0.0001, 1.0, 0.25))
    return out


def test_combined_daily_is_the_pair_mean_of_the_same_rule():
    mk = _markets()
    rng = np.random.default_rng(2)
    rules = [random_strategy(rng, "EURUSD", 2) for _ in range(4)]
    comb, dates = combined_daily(mk, rules, "2010-06-01", "2012-01-01", "M15")
    assert comb.shape == (4, len(dates))
    e = daily_returns(mk["EURUSD"], rules[0], "M15", window(mk["EURUSD"], "2010-06-01", "2012-01-01"))
    g = daily_returns(mk["GBPUSD"], on_pair(rules[0], "GBPUSD"), "M15", window(mk["GBPUSD"], "2010-06-01", "2012-01-01"))
    assert len(e) == len(g) == len(dates)
    assert np.allclose(comb[0], (e + g) / 2)


def test_preselect_gates_rank_and_planted_tracking():
    mk = _markets()["EURUSD"]
    rng = np.random.default_rng(3)
    strategies = [random_strategy(rng, "EURUSD", 2) for _ in range(200)]
    fit = rng.normal(size=200)
    fit[5] = -np.inf
    gates = {"sanity": {"min_trades": 10, "min_mean_r": -99, "min_profit_factor": 0.0},
             "cost_stress": {"cost_multiplier": 2.0, "min_profit_factor": 0.0, "min_mean_r": -99},
             "execution_stress": {"entry_delay": 1, "min_profit_factor": 0.0, "min_mean_r": -99}}
    w = window(mk, "2010-01-01", "2012-01-01")
    sel = preselect(mk, strategies, fit, w, gates, 20, "H1", track=5)
    assert sel["planted"]["stage"] == "fitness" and len(sel["top"]) <= 20
    f = fit[sel["top"]]
    assert (np.diff(f) <= 0).all() and 5 not in sel["top"]
    best = int(np.argmax(np.where(np.isfinite(fit), fit, -9)))
    sel2 = preselect(mk, strategies, fit, w, gates, 20, "H1", track=best)
    if sel2["planted"]["stage"] is None:
        assert sel2["planted"]["rank"] == 0 and sel2["top"][0] == best
