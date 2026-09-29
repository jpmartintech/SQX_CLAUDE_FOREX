"""Phase 2 discovery funnel: genetic search on training windows -> staged stress tests -> Deflated Sharpe -> final block.

All thresholds come from a committed YAML (``configs/funnel.yaml``); nothing here has a default threshold.
Data exposure:
* the GA fitness only evaluates ``periods.fitness_blocks`` (H1 execution);
* funnel stages use M15 execution; walk-forward years and the final block are never seen by the GA;
* the final block is looked at once per run (logged in ``trials/final_block_access.jsonl``); the sealed holdout is not loaded.
"""
from __future__ import annotations

import json
import math
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from sqxf.backtest.evaluator import Market, evaluate_light, evaluate_rich
from sqxf.backtest.semantics import AGG
from sqxf.generators.genetic import GAConfig, run_genetic
from sqxf.provenance import PROJECT_ROOT, code_version
from sqxf.stats.dsr import deflated_sharpe
from sqxf.strategy.definition import StrategyDefinition
from sqxf.trials import record_evaluations, total_evaluations

FINAL_ACCESS_LOG = PROJECT_ROOT / "trials" / "final_block_access.jsonl"


# ------------------------------------------------------------------ helpers
def window(market: Market, start: str, end: str) -> tuple[int, int]:
    ts = market.h1["ts_local"].to_numpy()
    return int(np.searchsorted(ts, np.datetime64(start))), int(np.searchsorted(ts, np.datetime64(end)))


def stats(agg: np.ndarray) -> dict[str, np.ndarray]:
    """Vectorised per-strategy metrics from an aggregate matrix."""
    n = agg[:, AGG["n_trades"]]
    with np.errstate(divide="ignore", invalid="ignore"):
        mean_r = np.where(n > 0, agg[:, AGG["sum_r"]] / n, 0.0)
        var_r = np.where(n > 0, agg[:, AGG["sum_r2"]] / n - mean_r**2, 0.0)
        gl = agg[:, AGG["gross_loss_r"]]
        pf = np.where(gl > 0, agg[:, AGG["gross_win_r"]] / gl, np.where(agg[:, AGG["gross_win_r"]] > 0, np.inf, 0.0))
        tstat = np.where(var_r > 0, mean_r / np.sqrt(np.maximum(var_r, 1e-300)) * np.sqrt(n), 0.0)
    return {"n": n, "mean_r": mean_r, "pf": pf, "tstat": tstat, "sharpe": agg[:, AGG["sharpe"]],
            "max_dd_mtm": agg[:, AGG["max_dd_mtm"]], "max_dd": agg[:, AGG["max_dd"]]}


def make_fitness(market: Market, blocks: list[tuple[int, int]], min_trades: int, exec_tf: str
                 ) -> Callable[[list[StrategyDefinition]], np.ndarray]:
    """Fitness = worst per-block t-statistic of R (cost x1); -inf if any block has fewer than ``min_trades`` trades."""
    def fitness(strategies):
        out = np.full(len(strategies), np.inf)
        for w in blocks:
            s = stats(evaluate_light(market, strategies, exec_tf=exec_tf, window=w))
            f = np.where(s["n"] >= min_trades, s["tstat"], -np.inf)
            out = np.minimum(out, f)
        return out
    return fitness


def daily_returns(market: Market, strategy: StrategyDefinition, exec_tf: str, w: tuple[int, int]) -> np.ndarray:
    """Daily returns of closed-trade equity over every trading day in the window (zeros on days without exits)."""
    rich = evaluate_rich(market, strategy, exec_tf=exec_tf, window=w)
    ex = market.execs[exec_tf]
    first = int(ex.day_id[ex.h1_start[w[0]]])
    n_days = int(ex.day_id[ex.h1_end[w[1] - 1] - 1]) - first + 1
    daily = np.zeros(n_days)
    df = rich.trades
    if df.empty:
        return daily
    days = ex.day_id[df["exit_exec"].to_numpy()] - first
    eq = df["equity_after"].to_numpy()
    last_idx = np.r_[np.flatnonzero(np.diff(days) != 0), len(days) - 1]
    end_eq = eq[last_idx]
    prev = np.r_[1.0, end_eq[:-1]]
    daily[days[last_idx]] = end_eq / prev - 1.0
    return daily


def _gate(s: dict, idx: np.ndarray, cfg: dict) -> np.ndarray:
    ok = np.ones(len(idx), dtype=bool)
    if "min_trades" in cfg:
        ok &= s["n"] >= cfg["min_trades"]
    if "min_profit_factor" in cfg:
        ok &= s["pf"] >= cfg["min_profit_factor"]
    if "min_mean_r" in cfg:
        ok &= s["mean_r"] > cfg["min_mean_r"]
    if "max_dd_mtm" in cfg:
        ok &= s["max_dd_mtm"] <= cfg["max_dd_mtm"]
    return idx[ok]


def _row(s: dict, i: int) -> dict:
    return {k: (float(v[i]) if math.isfinite(float(v[i])) else str(float(v[i]))) for k, v in s.items()}


# ------------------------------------------------------------------ pipeline
def run_funnel(market: Market, cfg: dict, out_dir: Path | None = None, record: bool = True,
               log: Callable[[str], None] = print) -> dict:
    periods, st = cfg["periods"], cfg["stages"]
    fit_tf, fun_tf = cfg["exec_timeframe_fitness"], cfg["exec_timeframe_funnel"]
    blocks = [window(market, a, b) for a, b in periods["fitness_blocks"]]
    fit_w = (blocks[0][0], blocks[-1][1])
    wf_ws = [window(market, f"{y}-01-01", f"{y + 1}-01-01") for y in periods["walk_forward_years"]]
    wf_all = (wf_ws[0][0], wf_ws[-1][1])
    dsr_w = window(market, *periods["dsr_window"])
    final_w = window(market, *periods["final_block"])
    if record and FINAL_ACCESS_LOG.exists() and any(
            json.loads(x)["run_name"] == cfg["run_name"] for x in FINAL_ACCESS_LOG.read_text().splitlines()):
        raise RuntimeError(f"run {cfg['run_name']!r} already looked at the final block; a new run needs a new name and "
                           "a DECISIONS.md entry (no fishing)")
    report: dict = {"run_name": cfg["run_name"], "pair": market.pair, "seed": cfg["seed"], "config": cfg,
                    "code_version": code_version(), "source_sha256": market.meta.get("source_sha256"),
                    "started_utc": datetime.now(UTC).isoformat(),
                    "windows_h1_idx": {"fitness_blocks": blocks, "walk_forward": wf_ws, "dsr": dsr_w, "final": final_w}}

    # 1) genetic search, fitness on training blocks only
    ga_cfg = GAConfig.from_dict(cfg["genetic"])
    fitness = make_fitness(market, blocks, cfg["fitness"]["min_trades_per_block"], fit_tf)
    ga = run_genetic(market.pair, fitness, ga_cfg, seed=cfg["seed"], log=log)
    strategies = [s for s, _ in ga.archive.values()]
    fit_vals = np.array([f for _, f in ga.archive.values()])
    if record:
        record_evaluations("phase2 genetic discovery", market.pair, ga.n_evaluated, selection=True,
                           run=cfg["run_name"], seed=cfg["seed"])
    report["genetic"] = {"evaluated_unique": ga.n_evaluated, "history": ga.history,
                         "finite_fitness": int(np.isfinite(fit_vals).sum())}
    counts = {"generated": ga.n_evaluated}
    idx = np.arange(len(strategies))

    def sub(ix):
        return [strategies[i] for i in ix]

    # 2) basic (fitness period, M15, cost x1)
    s = stats(evaluate_light(market, strategies, exec_tf=fun_tf, window=fit_w))
    idx = _gate(s, idx, st["basic"])
    counts["basic"] = len(idx)
    # 3) stability: positive mean R in the fitness blocks
    if len(idx):
        pos = np.zeros(len(idx), dtype=int)
        for w in blocks:
            pos += stats(evaluate_light(market, sub(idx), exec_tf=fun_tf, window=w))["mean_r"] > 0
        idx = idx[pos >= st["stability"]["min_positive_blocks"]]
    counts["stability"] = len(idx)
    # 4) cost stress
    if len(idx):
        c = st["cost_stress"]
        s2 = stats(evaluate_light(market, sub(idx), exec_tf=fun_tf, window=fit_w, cost_multiplier=c["cost_multiplier"]))
        idx = idx[_gate(s2, np.arange(len(idx)), c)]
    counts["cost_stress"] = len(idx)
    # 5) execution stress (entry delay)
    if len(idx):
        c = st["execution_stress"]
        s2 = stats(evaluate_light(market, sub(idx), exec_tf=fun_tf, window=fit_w, delay=c["entry_delay"]))
        idx = idx[_gate(s2, np.arange(len(idx)), c)]
    counts["execution_stress"] = len(idx)
    # 6) walk-forward: fixed strategies on yearly windows never used by the fitness
    wf_profiles = {}
    if len(idx):
        c = st["walk_forward"]
        years = np.array([stats(evaluate_light(market, sub(idx), exec_tf=fun_tf, window=w))["mean_r"] for w in wf_ws])
        pooled = stats(evaluate_light(market, sub(idx), exec_tf=fun_tf, window=wf_all))
        ok = (years > 0).sum(axis=0) >= c["min_positive_years"]
        ok &= np.isin(np.arange(len(idx)), _gate(pooled, np.arange(len(idx)), {k: c[k] for k in c if k != "min_trades_total"}))
        ok &= pooled["n"] >= c["min_trades_total"]
        for j, i in enumerate(idx):
            wf_profiles[strategies[i].canonical_hash] = {"yearly_mean_r": years[:, j].tolist(), "pooled": _row(pooled, j)}
        idx = idx[ok]
    counts["walk_forward"] = len(idx)
    # 7) Deflated Sharpe on the whole period used for selection, N = ledger total
    n_trials = total_evaluations()
    all_dsr = stats(evaluate_light(market, strategies, exec_tf=fun_tf, window=dsr_w))
    dpy = market.days_per_year
    active = all_dsr["n"] >= cfg["fitness"]["min_trades_per_block"]
    var_sr = float(np.var(all_dsr["sharpe"][active] / math.sqrt(dpy))) if active.sum() > 1 else 0.0
    dsr_rows = {}
    keep = []
    for i in idx:
        d = deflated_sharpe(daily_returns(market, strategies[i], fun_tf, dsr_w), n_trials, var_sr)
        dsr_rows[strategies[i].canonical_hash] = d
        if d["dsr"] >= st["deflated_sharpe"]["min_dsr"]:
            keep.append(i)
    idx = np.array(keep, dtype=int)
    counts["deflated_sharpe"] = len(idx)
    report["dsr_inputs"] = {"n_trials": n_trials, "var_sr_daily": var_sr, "strategies_in_var": int(active.sum())}
    # 8) final block (never seen by the GA), looked at once
    final_rows = {}
    if len(idx):
        if record:
            FINAL_ACCESS_LOG.parent.mkdir(parents=True, exist_ok=True)
            with FINAL_ACCESS_LOG.open("a") as fh:
                fh.write(json.dumps({"utc": datetime.now(UTC).isoformat(), "run_name": cfg["run_name"],
                                     "n_strategies": len(idx), "code_version": code_version()}) + "\n")
        f1 = stats(evaluate_light(market, sub(idx), exec_tf=fun_tf, window=final_w))
        f2 = stats(evaluate_light(market, sub(idx), exec_tf=fun_tf, window=final_w, cost_multiplier=2.0))
        for j, i in enumerate(idx):
            final_rows[strategies[i].canonical_hash] = {"cost_x1": _row(f1, j), "cost_x2": _row(f2, j)}
        idx = idx[_gate(f1, np.arange(len(idx)), st["final_block"])]
    counts["final_block"] = len(idx)
    report["counts"] = counts

    # too-good check on everything measured outside the fitness windows
    tg = cfg["too_good"]
    flags = []
    for h, prof in {**{k: v["pooled"] for k, v in wf_profiles.items()},
                    **{k: v["cost_x1"] for k, v in final_rows.items()}}.items():
        pf = float(prof["pf"]) if not isinstance(prof["pf"], str) else math.inf
        if (prof["n"] >= tg["min_trades_for_pf_check"] and pf > tg["max_profit_factor"]) or prof["sharpe"] > tg["max_sharpe"]:
            flags.append(h)
    report["too_good_flags"] = sorted(set(flags))

    report["survivors"] = [{"hash": strategies[i].canonical_hash, "strategy": json.loads(strategies[i].canonical_json),
                            "fitness": float(fit_vals[i]), "walk_forward": wf_profiles.get(strategies[i].canonical_hash),
                            "dsr": dsr_rows.get(strategies[i].canonical_hash),
                            "final_block": final_rows.get(strategies[i].canonical_hash)} for i in idx]
    report["dsr_candidates"] = [{"hash": h, "strategy": json.loads(strategies[next(
        i for i in range(len(strategies)) if strategies[i].canonical_hash == h)].canonical_json), **d}
        for h, d in sorted(dsr_rows.items(), key=lambda kv: -kv[1]["dsr"])[:20]]
    report["finished_utc"] = datetime.now(UTC).isoformat()
    if out_dir is not None:
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "report.json").write_text(json.dumps(report, indent=2, default=str))
    return report
