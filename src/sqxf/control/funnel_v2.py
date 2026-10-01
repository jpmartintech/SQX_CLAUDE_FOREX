"""Funnel v2 (configs/funnel_calibrated.yaml): sanity gate, stability / costs x2 / delay as in Phase 2, out-of-sample statistics
and a decision threshold calibrated on null worlds (95th percentile of the per-world maximum). Plus the localised, compensated
planted edge.
"""
from __future__ import annotations

import numpy as np

from sqxf.backtest.evaluator import Market, evaluate_light
from sqxf.control.synthetic import rebuild
from sqxf.funnel.pipeline import _gate, daily_returns, stats, window
from sqxf.strategy.definition import StrategyDefinition

DESIGNS = ("D1_tstat_r", "D2_sharpe", "D3_tstat_r_x2")
STAGES = ("pool", "sanity", "stability", "cost_stress", "execution_stress", "out_of_sample")


def plant_edge_compensated(shapes: dict, null_signal: np.ndarray, direction: int, delta_pips: float, pip: float,
                           horizon: int) -> dict:
    """+delta pips per H1 bar (direction-signed) on bars whose previous ``horizon`` H1 bars contain a NULL-world signal; the
    total injected log drift is subtracted uniformly over the bars without an active window (end/start price ratio kept)."""
    trig = np.asarray(null_signal, bool).astype(np.int64)
    n = len(trig)
    cum = np.r_[0, np.cumsum(trig)]
    u = np.arange(n)
    active = (cum[u] - cum[np.maximum(u - horizon, 0)]) > 0
    o, *_ = rebuild(shapes["o0"], shapes["shapes"])
    d = np.where(active, direction * np.log1p(delta_pips * pip / o[::4][:n]), 0.0)
    if (~active).any():
        d[~active] -= d.sum() / (~active).sum()
    new = {**shapes, "shapes": shapes["shapes"].copy()}
    new["shapes"][: 4 * n, 3] += np.repeat(d / 4.0, 4)
    return new


def price_ratio(shapes: dict) -> float:
    """Last close / first open (the first open is o0, untouched by any injection)."""
    o, _, _, c = rebuild(shapes["o0"], shapes["shapes"])
    return float(c[-1] / o[0])


def v2_stages(market: Market, strategies: list[StrategyDefinition], ref: dict, v2: dict) -> dict:
    """Run sanity .. out_of_sample on ``strategies``; return stage index sets and the 3 OOS statistics of the eligible ones."""
    per, st, tf = ref["periods"], ref["stages"], ref["exec_timeframe_funnel"]
    blocks = [window(market, a, b) for a, b in per["fitness_blocks"]]
    fit_w = (blocks[0][0], blocks[-1][1])
    oos_w = window(market, *v2["stages"]["out_of_sample"]["window"])

    def sub(ix):
        return [strategies[i] for i in ix]

    alive = {"pool": np.arange(len(strategies))}
    s = stats(evaluate_light(market, strategies, exec_tf=tf, window=fit_w))
    sg = v2["stages"]["sanity"]
    idx = np.flatnonzero((s["n"] >= sg["min_trades"]) & (s["mean_r"] > sg["min_mean_r"]) & (s["pf"] > sg["min_profit_factor"]))
    alive["sanity"] = idx
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
    out_stats = {d: np.zeros(0) for d in DESIGNS}
    if len(idx):
        o1 = stats(evaluate_light(market, sub(idx), exec_tf=tf, window=oos_w))
        o2 = stats(evaluate_light(market, sub(idx), exec_tf=tf, window=oos_w, cost_multiplier=2.0))
        ok = o1["n"] >= v2["stages"]["out_of_sample"]["min_trades"]
        idx = idx[ok]
        out_stats = {"D1_tstat_r": o1["tstat"][ok], "D2_sharpe": o1["sharpe"][ok], "D3_tstat_r_x2": o2["tstat"][ok]}
    alive["out_of_sample"] = idx
    return {"alive": alive, "oos": out_stats, "oos_window": oos_w}


def world_record(market: Market, strategies: list[StrategyDefinition], ref: dict, v2: dict, planted_index: int | None = None,
                 top_k: int = 50) -> dict:
    """Everything needed to apply any threshold later: per design the maximum OOS statistic, the planted strategy's stage path
    and statistic, and the daily-return correlation with the planted strategy of the top-k eligible strategies per design."""
    r = v2_stages(market, strategies, ref, v2)
    elig = r["alive"]["out_of_sample"]
    rec = {"counts": {k: int(len(v)) for k, v in r["alive"].items()},
           "max": {d: (float(np.max(r["oos"][d])) if len(elig) else float("-inf")) for d in DESIGNS}}
    if planted_index is None:
        return rec
    path = {k: bool(planted_index in set(v.tolist())) for k, v in r["alive"].items()}
    rec["planted_path"] = path
    rec["planted_killer_before_gate"] = next((k for k in STAGES if not path[k]), None)
    pos = np.flatnonzero(elig == planted_index)
    rec["planted_stat"] = {d: (float(r["oos"][d][pos[0]]) if len(pos) else None) for d in DESIGNS}
    dw = window(market, *ref["periods"]["dsr_window"])
    ref_daily = daily_returns(market, strategies[planted_index], ref["exec_timeframe_funnel"], dw)
    cand = {}
    for d in DESIGNS:
        if not len(elig):
            continue
        order = np.argsort(-r["oos"][d])[:top_k]
        for j in order:
            i = int(elig[j])
            if i == planted_index:
                continue
            if i not in cand:
                x = daily_returns(market, strategies[i], ref["exec_timeframe_funnel"], dw)
                cand[i] = float(np.corrcoef(ref_daily, x)[0, 1]) if x.std() > 0 and ref_daily.std() > 0 else 0.0
    tops = {d: (np.argsort(-r["oos"][d])[:top_k] if len(elig) else []) for d in DESIGNS}
    rec["top_candidates"] = {d: [{"stat": float(r["oos"][d][j]), "corr": cand.get(int(elig[j]))}
                                 for j in tops[d] if int(elig[j]) != planted_index] for d in DESIGNS}
    return rec


def survives(rec: dict, design: str, threshold: float) -> bool:
    ps = rec.get("planted_stat", {}).get(design)
    if ps is not None and ps > threshold:
        return True
    return any(c["stat"] > threshold and (c["corr"] or 0) > 0.8 for c in rec.get("top_candidates", {}).get(design, []))


def killer(rec: dict, design: str, threshold: float) -> str | None:
    if survives(rec, design, threshold):
        return None
    k = rec.get("planted_killer_before_gate")
    return k if k is not None else "decision_gate"
