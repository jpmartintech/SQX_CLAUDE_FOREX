"""Positive control of the whole Phase 2 funnel (configs/funnel_control.yaml): synthetic EURUSD worlds, planted strategies
with a causal edge, and the Phase 2 funnel stages replicated on a given pool (same thresholds, same windows, same DSR).
"""
from __future__ import annotations

import math

import numpy as np

from sqxf.backtest.evaluator import Costs, Market, build_market, evaluate_light
from sqxf.control.synthetic import calendar, rebuild, to_m15
from sqxf.data.m15 import DataConfig
from sqxf.funnel.pipeline import _gate, daily_returns, stats, window
from sqxf.stats.dsr import deflated_sharpe
from sqxf.strategy.definition import Predicate, StrategyDefinition


def planted(spec: dict, pair: str = "EURUSD") -> StrategyDefinition:
    return StrategyDefinition(pair, spec["direction"], tuple(Predicate(f, o, v) for f, o, v in spec["predicates"]),
                              spec["sl_atr"], spec["tp_atr"], spec["max_bars"])


def world_shapes(dev_pair: dict, n_days_pool: int, seed: int, n_total: int) -> dict:
    """All pool days permuted, then (n_total - pool) extra days drawn with replacement; returns shapes for EURUSD."""
    rng = np.random.default_rng(seed)
    order = rng.permutation(n_days_pool)
    if n_total > n_days_pool:
        order = np.r_[order, rng.integers(0, n_days_pool, n_total - n_days_pool)]
    order = order[:n_total]
    idx = (dev_pair["day_start"][order][:, None] + np.arange(96)[None, :]).ravel()
    return {"shapes": dev_pair["shapes"][idx].copy(), "volume": dev_pair["volume"][idx].copy(), "o0": dev_pair["o0"]}


def plant_edge(shapes: dict, null_signal: np.ndarray, direction: int, delta_pips: float, pip: float, horizon: int) -> dict:
    """+delta pips per H1 bar (log at the bar open, over its 4 M15 closes) in the strategy direction on every bar u whose
    previous ``horizon`` H1 bars contain a NULL-world signal. Causal: bar u only depends on signals before u."""
    trig = np.asarray(null_signal, bool).astype(np.int64)
    n = len(trig)
    cum = np.r_[0, np.cumsum(trig)]
    u = np.arange(n)
    active = (cum[u] - cum[np.maximum(u - horizon, 0)]) > 0
    o, *_ = rebuild(shapes["o0"], shapes["shapes"])
    d = np.where(active, direction * np.log1p(delta_pips * pip / o[::4][:n]) / 4.0, 0.0)
    new = {**shapes, "shapes": shapes["shapes"].copy()}
    new["shapes"][: 4 * n, 3] += np.repeat(d, 4)
    return new


def make_market(shapes: dict, cal_start: str, n_days: int, dcfg: DataConfig) -> Market:
    m15 = to_m15(shapes, calendar(cal_start, n_days), dcfg)
    return build_market("EURUSD", m15, Costs.for_pair("EURUSD"))


def strategy_sharpe(market: Market, s: StrategyDefinition, w: tuple[int, int]) -> tuple[float, float, int]:
    a = evaluate_light(market, [s], exec_tf="M15", window=w)[0]
    st = stats(a[None, :])
    return float(a[8]), float(st["mean_r"][0]), int(st["n"][0])


def run_funnel_pool(market: Market, strategies: list[StrategyDefinition], fcfg: dict, n_trials: float,
                    track: int | None = None) -> dict:
    """Phase 2 funnel stages (basic .. Deflated Sharpe) on a fixed pool, exactly as sqxf.funnel.pipeline.run_funnel.
    ``track`` = index of the planted strategy in ``strategies`` (its stage path is reported)."""
    periods, st = fcfg["periods"], fcfg["stages"]
    tf = fcfg["exec_timeframe_funnel"]
    blocks = [window(market, a, b) for a, b in periods["fitness_blocks"]]
    fit_w = (blocks[0][0], blocks[-1][1])
    wf_ws = [window(market, f"{y}-01-01", f"{y + 1}-01-01") for y in periods["walk_forward_years"]]
    wf_all = (wf_ws[0][0], wf_ws[-1][1])
    dsr_w = window(market, *periods["dsr_window"])

    def sub(ix):
        return [strategies[i] for i in ix]

    idx = np.arange(len(strategies))
    alive = {"generated": idx}
    s = stats(evaluate_light(market, strategies, exec_tf=tf, window=fit_w))
    idx = _gate(s, idx, st["basic"])
    alive["basic"] = idx
    if len(idx):
        pos = np.zeros(len(idx), dtype=int)
        for w in blocks:
            pos += stats(evaluate_light(market, sub(idx), exec_tf=tf, window=w))["mean_r"] > 0
        idx = idx[pos >= st["stability"]["min_positive_blocks"]]
    alive["stability"] = idx
    if len(idx):
        c = st["cost_stress"]
        s2 = stats(evaluate_light(market, sub(idx), exec_tf=tf, window=fit_w, cost_multiplier=c["cost_multiplier"]))
        idx = idx[_gate(s2, np.arange(len(idx)), c)]
    alive["cost_stress"] = idx
    if len(idx):
        c = st["execution_stress"]
        s2 = stats(evaluate_light(market, sub(idx), exec_tf=tf, window=fit_w, delay=c["entry_delay"]))
        idx = idx[_gate(s2, np.arange(len(idx)), c)]
    alive["execution_stress"] = idx
    if len(idx):
        c = st["walk_forward"]
        years = np.array([stats(evaluate_light(market, sub(idx), exec_tf=tf, window=w))["mean_r"] for w in wf_ws])
        pooled = stats(evaluate_light(market, sub(idx), exec_tf=tf, window=wf_all))
        ok = (years > 0).sum(axis=0) >= c["min_positive_years"]
        ok &= np.isin(np.arange(len(idx)), _gate(pooled, np.arange(len(idx)),
                                                 {k: c[k] for k in c if k != "min_trades_total"}))
        ok &= pooled["n"] >= c["min_trades_total"]
        idx = idx[ok]
    alive["walk_forward"] = idx
    all_dsr = stats(evaluate_light(market, strategies, exec_tf=tf, window=dsr_w))
    active = all_dsr["n"] >= fcfg["fitness"]["min_trades_per_block"]
    var_sr = float(np.var(all_dsr["sharpe"][active] / math.sqrt(market.days_per_year)))
    dsr_vals = {}
    keep = []
    for i in idx:
        d = deflated_sharpe(daily_returns(market, strategies[i], tf, dsr_w), n_trials, var_sr)
        dsr_vals[int(i)] = d
        if d["dsr"] >= st["deflated_sharpe"]["min_dsr"]:
            keep.append(i)
    alive["deflated_sharpe"] = np.array(keep, dtype=int)
    stages = list(alive)
    out = {"counts": {k: int(len(v)) for k, v in alive.items()}, "var_sr": var_sr,
           "survivors": [int(i) for i in alive["deflated_sharpe"]], "dsr": {k: v["dsr"] for k, v in dsr_vals.items()},
           "dsr_window": dsr_w}
    if track is not None:
        path = {k: bool(track in set(v.tolist())) for k, v in alive.items()}
        out["tracked"] = {"path": path, "killer": next((k for k in stages if not path[k]), None),
                          "dsr": dsr_vals.get(track), "survived": path["deflated_sharpe"]}
        out["pool_survivors"] = [i for i in out["survivors"] if i != track]
    else:
        out["pool_survivors"] = out["survivors"]
    return out


def effective_trials_clusters(daily: np.ndarray, threshold: float, n_total: float) -> dict:
    """Average-linkage clustering of daily-return series (distance 1 - rho) cut at ``threshold``; N_eff scaled to n_total."""
    from scipy.cluster.hierarchy import fcluster, linkage
    from scipy.spatial.distance import squareform
    x = daily[daily.std(axis=1) > 0]
    corr = np.corrcoef(x)
    dist = np.clip(1.0 - corr, 0.0, 2.0)
    np.fill_diagonal(dist, 0.0)
    z = linkage(squareform(dist, checks=False), method="average")
    k = int(len(np.unique(fcluster(z, t=threshold, criterion="distance"))))
    return {"sample": int(len(x)), "clusters": k, "n_eff": n_total * k / len(x), "mean_abs_corr": float(np.abs(
        corr[np.triu_indices(len(corr), 1)]).mean())}
