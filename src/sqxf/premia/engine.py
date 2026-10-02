"""Daily portfolio engine for the C2 structural premia (configs/premia_c2.yaml).

Arrays are (days, assets), aligned on one calendar:
* ``ret[d, a]``   price return of asset a from close d-1 to close d (0 when the asset has no bar);
* ``c_lin[d, a]`` carry earned on day d per unit of LONG notional (funding: minus the day's rates; a short earns the opposite);
* ``c_abs[d, a]`` carry PAID on day d per unit of |notional| whatever the side (conservative forex swap);
* ``cost[d, a]``  cost rate per unit of notional traded at the close of day d;
* ``targets[d]``  signed target notionals / equity set at the close of day d (rows of NaN = no rebalance).

Day d: holdings earn ``ret[d]`` and the carry, drift with prices, then (if d is a rebalance) move to the targets paying
``|target - holding| * cost``. Targets set at the close of d only earn from d+1 (causal by construction).
"""
from __future__ import annotations

import math

import numpy as np


def simulate(ret: np.ndarray, c_lin: np.ndarray, c_abs: np.ndarray, cost: np.ndarray, targets: np.ndarray,
             cost_mult: float = 1.0, pay_mult: float = 1.0) -> dict:
    """Returns daily net returns, equity, gross exposure, turnover, and the cost / carry / price components."""
    n_days, n_assets = ret.shape
    h = np.zeros(n_assets)
    eq = 1.0
    out = {k: np.zeros(n_days) for k in ("ret", "equity", "gross", "turnover", "cost", "carry", "price")}
    for d in range(n_days):
        prev = eq
        if d > 0 and h.any():
            price = float(h @ ret[d])
            car = h * c_lin[d] - np.abs(h) * c_abs[d]
            car = np.where(car < 0, pay_mult * car, car)
            carry = float(car.sum())
            pnl = price + carry
            eq *= 1.0 + pnl
            h = h * (1.0 + ret[d]) / (1.0 + pnl)
            out["price"][d], out["carry"][d] = price, carry
        t = targets[d]
        if not np.isnan(t).all():
            t = np.nan_to_num(t)
            trade = np.abs(t - h)
            c = float((trade * cost[d]).sum()) * cost_mult
            eq *= 1.0 - c
            out["cost"][d], out["turnover"][d] = c, float(trade.sum())
            h = t.copy()
        out["ret"][d] = eq / prev - 1.0
        out["equity"][d] = eq
        out["gross"][d] = float(np.abs(h).sum())
    return out


def spell_flips(targets: np.ndarray, groups: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    """Matched random control: each position spell (maximal run of rebalance rows in which the group's lead asset keeps the
    same non-zero target sign) gets a random direction; |targets| and the rebalance schedule are unchanged."""
    out = targets.copy()
    reb = np.flatnonzero(~np.isnan(targets).all(axis=1))
    for g in np.unique(groups):
        cols = np.flatnonzero(groups == g)
        lead = np.sign(np.nan_to_num(targets[reb, cols[0]]))
        flip = np.ones(len(reb))
        cur, sgn = 0.0, 1.0
        for k, s in enumerate(lead):
            if s != 0 and s != cur:
                sgn = rng.choice([-1.0, 1.0])
            cur = s
            flip[k] = sgn if s != 0 else 1.0
        out[np.ix_(reb, cols)] = targets[np.ix_(reb, cols)] * flip[:, None]
    return out


def _block_indices(n: int, block: int, size: int, rng: np.random.Generator) -> np.ndarray:
    n_blocks = int(math.ceil(n / block))
    starts = rng.integers(0, n, (size, n_blocks))
    return ((starts[:, :, None] + np.arange(block)[None, None, :]) % n).reshape(size, -1)[:, :n]


def bootstrap_stats(x: np.ndarray, block: int, resamples: int, seed: int, per_year: float, chunk: int = 500) -> dict:
    """Circular block bootstrap of a daily return series: one-sided p of mean > 0 (demeaned resamples), t = mean / bootstrap
    SE, annualised Sharpe with a 95 % percentile interval."""
    x = np.asarray(x, float)
    n = len(x)
    rng = np.random.default_rng(seed)
    mean, sd = float(x.mean()), float(x.std(ddof=1))
    xc = x - mean
    means, cmeans, sharpes = [], [], []
    for start in range(0, resamples, chunk):
        idx = _block_indices(n, block, min(chunk, resamples - start), rng)
        s = x[idx]
        means.append(s.mean(axis=1))
        cmeans.append(xc[idx].mean(axis=1))
        sharpes.append(s.mean(axis=1) / s.std(axis=1, ddof=1) * math.sqrt(per_year))
    means, cmeans, sharpes = (np.concatenate(v) for v in (means, cmeans, sharpes))
    se = float(means.std(ddof=1))
    return {"n": n, "mean": mean, "sd": sd, "sharpe": mean / sd * math.sqrt(per_year) if sd > 0 else float("nan"),
            "se_mean": se, "t": mean / se if se > 0 else float("nan"),
            "p_one_sided": float((1 + int((cmeans >= mean).sum())) / (1 + resamples)),
            "sharpe_ci95": [float(np.percentile(sharpes, 2.5)), float(np.percentile(sharpes, 97.5))]}


def max_drawdown(ret: np.ndarray) -> float:
    eq = np.cumprod(1.0 + np.asarray(ret, float))
    peak = np.maximum.accumulate(np.r_[1.0, eq])[1:]
    return float((eq / peak - 1.0).min())


def participation_ratio(returns: np.ndarray) -> float:
    """PCA effective number of series: (sum lambda)^2 / sum lambda^2 of the correlation matrix (columns = series)."""
    c = np.corrcoef(returns, rowvar=False)
    lam = np.clip(np.linalg.eigvalsh(c), 0, None)
    return float(lam.sum() ** 2 / (lam ** 2).sum())
