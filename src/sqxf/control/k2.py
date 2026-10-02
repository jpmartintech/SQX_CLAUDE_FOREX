"""Phase K2 (configs/funnel_k2.yaml): combined 6-pair funnel with power by design.

* 6-pair synthetic worlds: complete development days common to the 6 pairs, ONE day order for all pairs (cross-pair
  correlation kept), on a synthetic 15-year calendar.
* Expanding walk-forward: at each boundary b the genetic runs on EURUSD training [2004, b) only; gates (sanity, costs x2,
  1-bar delay) inside the training window; top-K by training fitness.
* OOS statistic of a rule: daily series = mean over the 6 pairs of its daily returns (same rule, no per-pair re-selection);
  in an OOS segment the rule only trades if it was in that segment's top-K (zeros otherwise); t = mean / circular-block-
  bootstrap SE (closed form, exact expectation of the CBB variance of the mean).
"""
from __future__ import annotations

import dataclasses

import numpy as np

from sqxf.backtest.evaluator import Costs, Market, build_market, evaluate_light
from sqxf.control.synthetic import calendar, to_m15
from sqxf.data.m15 import DataConfig
from sqxf.funnel.pipeline import _gate, daily_returns, make_fitness, stats, window
from sqxf.funnel.wf_procedure import day_dates
from sqxf.generators.genetic import GAConfig, run_genetic
from sqxf.strategy.definition import StrategyDefinition

GATE_STAGES = ("sanity", "cost_stress", "execution_stress", "top_k")


# ------------------------------------------------------------------ worlds
def multi_world_shapes(dev: dict, pairs: list[str], seed: int, n_total: int) -> dict:
    """All common pool days permuted, then extra days drawn with replacement; the SAME order for every pair."""
    rng = np.random.default_rng(seed)
    n_pool = len(dev["days"])
    order = rng.permutation(n_pool)
    if n_total > n_pool:
        order = np.r_[order, rng.integers(0, n_pool, n_total - n_pool)]
    order = order[:n_total]
    out = {}
    for p in pairs:
        d = dev["pairs"][p]
        idx = (d["day_start"][order][:, None] + np.arange(96)[None, :]).ravel()
        out[p] = {"shapes": d["shapes"][idx].copy(), "volume": d["volume"][idx].copy(), "o0": d["o0"]}
    return out


def pair_market(shapes: dict, pair: str, cal_start: str, n_days: int, dcfg: DataConfig) -> Market:
    return build_market(pair, to_m15(shapes, calendar(cal_start, n_days), dcfg), Costs.for_pair(pair))


def on_pair(s: StrategyDefinition, pair: str) -> StrategyDefinition:
    return s if s.pair == pair else dataclasses.replace(s, pair=pair)


# ------------------------------------------------------------------ one walk-forward boundary
def train_blocks(market: Market, start_year: int, boundary: int, n_blocks: int) -> list[tuple[int, int]]:
    edges = np.linspace(start_year, boundary, n_blocks + 1).round().astype(int)
    return [window(market, f"{a}-01-01", f"{b}-01-01") for a, b in zip(edges[:-1], edges[1:], strict=True)]


def preselect(market: Market, strategies: list[StrategyDefinition], fit: np.ndarray, train: tuple[int, int],
              gates: dict, k_max: int, tf: str, track: int | None = None) -> dict:
    """Gates inside the training window, then the top ``k_max`` by fitness (ranked). ``track`` = index of a planted
    strategy: the stage that eliminates it (or its rank)."""
    idx = np.flatnonzero(np.isfinite(fit))
    path = {}
    s = stats(evaluate_light(market, [strategies[i] for i in idx], exec_tf=tf, window=train)) if len(idx) else None
    sg = gates["sanity"]
    if len(idx):
        ok = (s["n"] >= sg["min_trades"]) & (s["mean_r"] > sg["min_mean_r"]) & (s["pf"] > sg["min_profit_factor"])
        idx = idx[ok]
    path["sanity"] = idx.copy()
    for name, mult in (("cost_stress", "cost_multiplier"), ("execution_stress", "entry_delay")):
        if len(idx):
            c = gates[name]
            kw = {"cost_multiplier": c[mult]} if mult == "cost_multiplier" else {"delay": c[mult]}
            s2 = stats(evaluate_light(market, [strategies[i] for i in idx], exec_tf=tf, window=train, **kw))
            idx = idx[_gate(s2, np.arange(len(idx)), c)]
        path[name] = idx.copy()
    order = idx[np.argsort(-fit[idx], kind="stable")][:k_max]
    out = {"top": [int(i) for i in order], "counts": {k: int(len(v)) for k, v in path.items()},
           "finite": int(np.isfinite(fit).sum())}
    if track is not None:
        if not np.isfinite(fit[track]):
            out["planted"] = {"stage": "fitness", "rank": None}
        else:
            stage = next((k for k in ("sanity", "cost_stress", "execution_stress") if track not in set(path[k].tolist())), None)
            rank = int(np.flatnonzero(idx[np.argsort(-fit[idx], kind="stable")] == track)[0]) if stage is None else None
            out["planted"] = {"stage": stage, "rank": rank, "fitness": float(fit[track])}
    return out


def run_boundary(market: Market, boundary: int, cfg: dict, gates: dict, seed: int,
                 planted: StrategyDefinition | None = None) -> tuple[list[StrategyDefinition], dict, int]:
    g = cfg["generator"]
    blocks = train_blocks(market, g["train_start_year"], boundary, g["train_blocks"])
    fitness = make_fitness(market, blocks, g["min_trades_per_block"], g["exec_timeframe"])
    ga = run_genetic(market.pair, fitness, GAConfig.from_dict(g["genetic"]), seed=seed)
    strategies = [s for s, _ in ga.archive.values()]
    fit = np.array([f for _, f in ga.archive.values()])
    track = None
    if planted is not None:
        keep = [i for i, s in enumerate(strategies) if s.canonical_hash != planted.canonical_hash]
        found = len(keep) < len(strategies)
        strategies = [strategies[i] for i in keep] + [planted]
        fit = np.r_[fit[keep], fitness([planted])]
        track = len(strategies) - 1
    sel = preselect(market, strategies, fit, (blocks[0][0], blocks[-1][1]), gates, max(cfg["preselection"]["k_values"]),
                    g["exec_timeframe"], track)
    if planted is not None:
        sel["planted"]["ga_found_hash"] = bool(found)
    return strategies, sel, ga.n_evaluated


# ------------------------------------------------------------------ OOS series and statistic
def combined_daily(markets: dict[str, Market], rules: list[StrategyDefinition], start: str, end: str, tf: str
                   ) -> tuple[np.ndarray, np.ndarray]:
    """(rules, days) mean over pairs of daily returns on the union of the pairs' trading dates in [start, end)."""
    per = {}
    for p, mk in markets.items():
        w = window(mk, start, end)
        ex = mk.execs[tf]
        first = int(ex.day_id[ex.h1_start[w[0]]])
        rows = np.array([daily_returns(mk, on_pair(r, p), tf, w) for r in rules]) if rules else np.zeros((0, 0))
        dates = day_dates(mk)[first:first + (rows.shape[1] if rules else 0)]
        per[p] = (dates, rows)
    all_dates = np.unique(np.concatenate([d for d, _ in per.values()]))
    out = np.zeros((len(rules), len(all_dates)))
    for dates, rows in per.values():
        if len(rules):
            out[:, np.searchsorted(all_dates, dates)] += rows
    return out / len(markets), all_dates


def cbb_se(x: np.ndarray, block: int) -> np.ndarray:
    """Standard error of the mean under the circular block bootstrap (exact expectation): along the last axis,
    Var = (1/n) * sum_{|h|<b} (1 - |h|/b) * circular autocovariance(h)."""
    x = np.atleast_2d(np.asarray(x, float))
    n = x.shape[-1]
    xc = x - x.mean(axis=-1, keepdims=True)
    var = (xc * xc).mean(axis=-1)
    for h in range(1, block):
        g = (xc * np.roll(xc, -h, axis=-1)).mean(axis=-1)
        var = var + 2 * (1 - h / block) * g
    return np.sqrt(np.maximum(var, 0) / n)


def tstat(x: np.ndarray, block: int) -> np.ndarray:
    x = np.atleast_2d(x)
    se = cbb_se(x, block)
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(se > 0, x.mean(axis=-1) / se, 0.0)


def masked_series(daily: np.ndarray, dates: np.ndarray, member: np.ndarray, segments: list[tuple[str, str]]) -> np.ndarray:
    """``member[r, f]`` = rule r preselected for segment f; zeros outside its selected segments."""
    out = np.zeros_like(daily)
    for f, (a, b) in enumerate(segments):
        cols = (dates >= np.datetime64(a)) & (dates < np.datetime64(b))
        out[np.ix_(member[:, f], cols)] = daily[np.ix_(member[:, f], cols)]
    return out
