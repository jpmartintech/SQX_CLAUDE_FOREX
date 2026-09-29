import math

import numpy as np
import pytest

from sqxf.stats.dsr import deflated_sharpe, expected_max_sharpe, moments, probabilistic_sharpe


def test_expected_max_sharpe_grows_with_trials_and_matches_simulation():
    assert expected_max_sharpe(1, 0.01) == 0.0
    vals = [expected_max_sharpe(n, 0.01) for n in (10, 100, 1000, 100000)]
    assert all(a < b for a, b in zip(vals, vals[1:], strict=False))
    # Monte Carlo: max of N standard normals * sd ~ formula (within a few %).
    rng = np.random.default_rng(0)
    n, sd = 1000, 0.1
    sim = (rng.standard_normal((4000, n)) * sd).max(axis=1).mean()
    assert expected_max_sharpe(n, sd**2) == pytest.approx(sim, rel=0.03)


def test_psr_basics():
    assert probabilistic_sharpe(0.1, 0.1, 500, 0.0, 3.0) == pytest.approx(0.5)
    assert probabilistic_sharpe(0.1, 0.0, 1000, 0.0, 3.0) > 0.99
    # Negative skew and fat tails reduce confidence.
    assert probabilistic_sharpe(0.1, 0.0, 200, -2.0, 10.0) < probabilistic_sharpe(0.1, 0.0, 200, 0.0, 3.0)


def test_moments_of_normal_sample():
    r = np.random.default_rng(1).normal(0.001, 0.01, 200000)
    sr, skew, kurt = moments(r)
    assert sr == pytest.approx(0.1, abs=0.01) and abs(skew) < 0.03 and kurt == pytest.approx(3.0, abs=0.05)


def test_best_of_many_noise_strategies_is_deflated():
    """Select the best of 2000 zero-edge strategies: its raw PSR vs 0 looks significant, its DSR does not."""
    rng = np.random.default_rng(2)
    n_trials, n_obs = 2000, 1000
    rets = rng.normal(0.0, 0.01, (n_trials, n_obs))
    srs = rets.mean(axis=1) / rets.std(axis=1)
    best = int(np.argmax(srs))
    raw = probabilistic_sharpe(srs[best], 0.0, n_obs, 0.0, 3.0)
    d = deflated_sharpe(rets[best], n_trials, float(srs.var()))
    assert raw > 0.99
    assert d["dsr"] < 0.9
    assert not math.isnan(d["sr_expected_max"])
