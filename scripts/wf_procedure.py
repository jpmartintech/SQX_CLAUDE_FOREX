"""Phase 2b runner: walk-forward evaluation of the discovery procedure vs a random control and a permutation null.

Modes (config must be committed first):
  observed           GA procedure and random control on real EURUSD (data truncated at data_end_local). Runs once.
  null --shard i --n-shards n   permutation null runs j = i, i+n, ... (resumable: finished j are skipped)
  report             p-values, acceptance verdict and PSR of the OOS portfolio -> runs/<run>/report.json
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from sqxf.backtest.evaluator import Costs, build_market
from sqxf.data.m15 import DataConfig, load_m15
from sqxf.funnel.wf_procedure import effective_trials_rho, folds, generate, null_market, run_procedure, truncate_m15
from sqxf.provenance import PROJECT_ROOT, code_version, load_yaml_strict, require_committed
from sqxf.stats.dsr import expected_max_sharpe, moments, probabilistic_sharpe
from sqxf.trials import record_evaluations

PROCEDURE_LEDGER = PROJECT_ROOT / "trials" / "procedure_ledger.jsonl"


def jsonable(summary: dict) -> dict:
    return {k: v for k, v in summary.items() if not k.startswith("_")}


def setup(cfg: dict):
    m15 = truncate_m15(load_m15(cfg["pair"], DataConfig.load()), cfg["data_end_local"])
    market = build_market(cfg["pair"], m15, Costs.for_pair(cfg["pair"]))
    assert market.h1["ts_local"].max() < np.datetime64(cfg["data_end_local"])
    return m15, market


def observed(cfg: dict, out: Path) -> None:
    target = out / "observed.json"
    if target.exists():
        sys.exit(f"{target} exists: the observed procedure runs once per run_name (no relaunch)")
    m15, market = setup(cfg)
    res = {"code_version": code_version(), "source_sha256": market.meta.get("source_sha256"),
           "started_utc": datetime.now(UTC).isoformat()}
    for gen in ("genetic", "random"):
        s = run_procedure(market, cfg, gen, log=print)
        record_evaluations(f"phase2b procedure ({gen})", cfg["pair"], s["evaluated"], selection=True, run=cfg["run_name"])
        res[gen] = jsonable(s)
        res[gen]["daily_x1"] = s["_daily_x1"].tolist()
    # informational effective number of trials (strategy level) on each fold's genetic archive
    ns = cfg["effective_trials"]["strategy_level"]
    neff = []
    for i, fold in enumerate(folds(market, cfg)):
        strategies, _ = generate(market, fold, cfg, "genetic", cfg["seed"] + i)  # same seed -> same archive
        neff.append({"year": fold["year"], **effective_trials_rho(market, strategies, fold["train"],
                                                                   cfg["exec_timeframe_train"], ns["sample"], ns["seed"])})
    res["strategy_level_effective_trials"] = neff
    record_evaluations("phase2b N_eff archive regeneration (same seeds, no selection)", cfg["pair"],
                       sum(x["n"] for x in neff), selection=False, run=cfg["run_name"])
    PROCEDURE_LEDGER.parent.mkdir(parents=True, exist_ok=True)
    with PROCEDURE_LEDGER.open("a") as fh:
        fh.write(json.dumps({"utc": datetime.now(UTC).isoformat(), "run_name": cfg["run_name"],
                             "oos_years": cfg["folds"]["oos_years"], "procedures": ["genetic", "random"],
                             "code_version": code_version()}) + "\n")
    res["finished_utc"] = datetime.now(UTC).isoformat()
    out.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(res, indent=1))


def null(cfg: dict, out: Path, shard: int, n_shards: int) -> None:
    m15, market = setup(cfg)
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"null_shard{shard}.jsonl"
    done = {json.loads(x)["j"] for x in path.read_text().splitlines()} if path.exists() else set()
    nc = cfg["null"]
    for j in range(shard, nc["n_permutations"], n_shards):
        if j in done:
            continue
        mk = null_market(m15, market, nc["seed_base"] + j)
        row = {"j": j, "seed": nc["seed_base"] + j}
        for gen in ("genetic", "random"):
            s = run_procedure(mk, cfg, gen)
            row[gen] = jsonable(s)
            row[gen]["daily_sharpe"] = s["portfolio_sharpe"]
        with path.open("a") as fh:
            fh.write(json.dumps(row) + "\n")
        print(f"null {j} done: GA mean R {row['genetic']['mean_r_x1']:+.4f} random {row['random']['mean_r_x1']:+.4f}",
              flush=True)


def report(cfg: dict, out: Path) -> dict:
    obs = json.loads((out / "observed.json").read_text())
    rows = [json.loads(x) for p in sorted(out.glob("null_shard*.jsonl")) for x in p.read_text().splitlines()]
    rows = sorted({r["j"]: r for r in rows}.values(), key=lambda r: r["j"])
    acc = cfg["acceptance"]

    def val(x):
        return -math.inf if x is None or (isinstance(x, float) and math.isnan(x)) else x

    rep = {"run_name": cfg["run_name"], "n_null": len(rows), "code_version": code_version()}
    for gen in ("genetic", "random"):
        o = obs[gen]
        null_stats = np.array([val(r[gen]["mean_r_x1"]) for r in rows])
        p = (1 + int((null_stats >= val(o["mean_r_x1"])).sum())) / (1 + len(rows))
        null_sr = np.array([r[gen]["portfolio_sharpe"] for r in rows]) / math.sqrt(cfg["days_per_year"])
        daily = np.array(o["daily_x1"])
        sr, skew, kurt = moments(daily)
        n_proc = len(PROCEDURE_LEDGER.read_text().splitlines()) * 2  # every logged config evaluated 2 procedures
        sr0 = expected_max_sharpe(n_proc, float(np.var(null_sr))) if len(rows) > 1 else 0.0
        rep[gen] = {k: o[k] for k in o if k not in ("daily_x1",)}
        rep[gen].update({"p_value_permutation": p,
                         "null_mean_r_x1": {"mean": float(np.mean(null_stats)), "p95": float(np.percentile(null_stats, 95)),
                                            "max": float(np.max(null_stats))} if len(rows) else None,
                         "portfolio_psr_vs_0": probabilistic_sharpe(sr, 0.0, len(daily), skew, kurt),
                         "portfolio_dsr": probabilistic_sharpe(sr, sr0, len(daily), skew, kurt),
                         "dsr_n_procedures": n_proc, "dsr_sr_expected_max_annual": sr0 * math.sqrt(cfg["days_per_year"])})
    g, r = rep["genetic"], rep["random"]
    checks = {"oos_mean_r_x1_gt": g["mean_r_x1"] > acc["oos_mean_r_x1_gt"],
              "oos_mean_r_x2_gt": g["mean_r_x2"] > acc["oos_mean_r_x2_gt"],
              "permutation_p_value_le": g["p_value_permutation"] <= acc["permutation_p_value_le"],
              "beats_random_control": (g["mean_r_x1"] > r["mean_r_x1"]) if acc["must_beat_random_control"] else True}
    rep["acceptance_checks"] = checks
    rep["procedure_has_edge"] = bool(all(checks.values()))
    rep["strategy_level_effective_trials"] = obs.get("strategy_level_effective_trials")
    (out / "report.json").write_text(json.dumps(rep, indent=1))
    return rep


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["observed", "null", "report"])
    ap.add_argument("--config", default=str(PROJECT_ROOT / "configs" / "wf_procedure.yaml"))
    ap.add_argument("--shard", type=int, default=0)
    ap.add_argument("--n-shards", type=int, default=1)
    args = ap.parse_args()
    require_committed(Path(args.config))
    cfg = load_yaml_strict(Path(args.config))
    out = PROJECT_ROOT / "runs" / cfg["run_name"]
    if args.mode == "observed":
        observed(cfg, out)
    elif args.mode == "null":
        null(cfg, out, args.shard, args.n_shards)
    else:
        print(json.dumps(report(cfg, out), indent=1))


if __name__ == "__main__":
    main()
