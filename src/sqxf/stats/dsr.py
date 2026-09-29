"""Deflated Sharpe Ratio (Bailey & López de Prado, 2014).

All Sharpe ratios here are per observation (daily, not annualised). ``kurt`` is the non-excess kurtosis (normal = 3).

* ``expected_max_sharpe``: expected maximum Sharpe among ``n_trials`` unskilled trials with cross-trial variance ``var_sr``.
* ``probabilistic_sharpe``: P(true SR > sr_ref) given the estimate, sample length, skewness and kurtosis.
* ``deflated_sharpe``: PSR against the expected maximum under the null (the multiple-testing correction).
"""
from __future__ import annotations

import math
from statistics import NormalDist

import numpy as np

EULER_GAMMA = 0.5772156649015329
_N = NormalDist()


def expected_max_sharpe(n_trials: float, var_sr: float) -> float:
    if n_trials <= 1 or var_sr <= 0:
        return 0.0
    z1 = _N.inv_cdf(1.0 - 1.0 / n_trials)
    z2 = _N.inv_cdf(1.0 - 1.0 / (n_trials * math.e))
    return math.sqrt(var_sr) * ((1.0 - EULER_GAMMA) * z1 + EULER_GAMMA * z2)


def probabilistic_sharpe(sr: float, sr_ref: float, n_obs: int, skew: float, kurt: float) -> float:
    if n_obs < 2:
        return 0.0
    denom = 1.0 - skew * sr + (kurt - 1.0) / 4.0 * sr * sr
    if denom <= 0:
        return 0.0
    return _N.cdf((sr - sr_ref) * math.sqrt(n_obs - 1) / math.sqrt(denom))


def moments(returns: np.ndarray) -> tuple[float, float, float]:
    """Per-observation Sharpe, skewness and non-excess kurtosis (population moments)."""
    r = np.asarray(returns, dtype=float)
    sd = r.std()
    if len(r) < 2 or sd == 0:
        return 0.0, 0.0, 3.0
    z = (r - r.mean()) / sd
    return float(r.mean() / sd), float((z**3).mean()), float((z**4).mean())


def deflated_sharpe(returns: np.ndarray, n_trials: float, var_sr: float) -> dict:
    sr, skew, kurt = moments(returns)
    sr0 = expected_max_sharpe(n_trials, var_sr)
    return {"sr": sr, "skew": skew, "kurt": kurt, "n_obs": len(returns), "sr_expected_max": sr0,
            "n_trials": float(n_trials), "var_sr": float(var_sr),
            "dsr": probabilistic_sharpe(sr, sr0, len(returns), skew, kurt)}
