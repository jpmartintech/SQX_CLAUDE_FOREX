"""Phase 2c runner: the Phase 2b procedure on six pairs, two pre-registered selection variants, random control and a
day-block permutation null that keeps volatility clustering and cross-pair correlation.

Modes (the config must be committed first):
  observed                      real data (M15 truncated at data_end_local), once per run_name
  null --shard i --n-shards n   null permutations j = i, i+n, ... (resumable)
  report                        p-values, DSR and the pre-registered acceptance verdict -> runs/<run>/report.json
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
from sqxf.funnel.wf_procedure import block_permute_m15, day_block_mapping, run_multi, truncate_m15
from sqxf.provenance import PROJECT_ROOT, code_version, load_yaml_strict, require_committed
from sqxf.stats.dsr import expected_max_sharpe, moments, probabilistic_sharpe
from sqxf.trials import record_evaluations

PROCEDURE_LEDGER = PROJECT_ROOT / "trials" / "procedure_ledger.jsonl"


def offsets(cfg: dict) -> dict[str, int]:
    return {p: int(o) for p, o in cfg["pair_seed_offsets"].items()}


def setup(cfg: dict):
    dcfg = DataConfig.load()
    m15s = {p: truncate_m15(load_m15(p, dcfg), cfg["data_end_local"]) for p in cfg["pairs"]}
    markets = {p: build_market(p, m, Costs.for_pair(p)) for p, m in m15s.items()}
    for mk in markets.values():
        assert mk.h1["ts_local"].max() < np.datetime64(cfg["data_end_local"])
    return m15s, markets


def compact(res: dict, keep_daily: bool) -> dict:
    out = {}
    for gen, by_v in res.items():
        out[gen] = {}
        for v, s in by_v.items():
            d = {k: val for k, val in s.items() if not k.startswith("_")}
            if keep_daily:
                d["daily_portfolio"] = s["_daily_portfolio"].tolist()
            else:
                d.pop("per_pair", None)
                d["per_pair_mean_r_x1"] = {p: x["mean_r_x1"] for p, x in s["per_pair"].items()}
            out[gen][v] = d
    return out


def observed(cfg: dict, out: Path) -> None:
    target = out / "observed.json"
    if target.exists():
        sys.exit(f"{target} exists: the observed procedure runs once per run_name (no relaunch)")
    _, markets = setup(cfg)
    started = datetime.now(UTC).isoformat()
    res = run_multi(markets, cfg, cfg["selection_variants"], pair_seed_offsets=offsets(cfg), log=print)
    for gen in res:
        record_evaluations(f"phase2c procedure ({gen}, 6 pairs)", "+".join(cfg["pairs"]),
                           res[gen][next(iter(res[gen]))]["evaluated"], selection=True, run=cfg["run_name"])
    procs = [f"{g}/{v}" for g in res for v in res[g]]
    PROCEDURE_LEDGER.parent.mkdir(parents=True, exist_ok=True)
    with PROCEDURE_LEDGER.open("a") as fh:
        fh.write(json.dumps({"utc": datetime.now(UTC).isoformat(), "run_name": cfg["run_name"], "pairs": cfg["pairs"],
                             "oos_years": cfg["folds"]["oos_years"], "procedures": procs,
                             "code_version": code_version()}) + "\n")
    out.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({"code_version": code_version(), "started_utc": started,
                                  "finished_utc": datetime.now(UTC).isoformat(),
                                  "source_sha256": {p: m.meta.get("source_sha256") for p, m in markets.items()},
                                  "results": compact(res, keep_daily=True)}, indent=1))


def null(cfg: dict, out: Path, shard: int, n_shards: int) -> None:
    m15s, markets = setup(cfg)
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"null_shard{shard}.jsonl"
    done = {json.loads(x)["j"] for x in path.read_text().splitlines()} if path.exists() else set()
    nc = cfg["null"]
    for j in range(shard, nc["n_permutations"], n_shards):
        if j in done:
            continue
        mapping = day_block_mapping(m15s, nc["seed_base"] + j)
        nm = {p: build_market(p, block_permute_m15(m15s[p], mapping), markets[p].costs) for p in cfg["pairs"]}
        res = run_multi(nm, cfg, cfg["selection_variants"], pair_seed_offsets=offsets(cfg))
        with path.open("a") as fh:
            fh.write(json.dumps({"j": j, "seed": nc["seed_base"] + j, "results": compact(res, keep_daily=False)}) + "\n")
        print(f"null {j} done: " + ", ".join(f"{g}/{v} {res[g][v]['mean_r_x1']:+.4f}" for g in res for v in res[g]),
              flush=True)


def report(cfg: dict, out: Path) -> dict:
    obs = json.loads((out / "observed.json").read_text())["results"]
    rows = [json.loads(x) for p in sorted(out.glob("null_shard*.jsonl")) for x in p.read_text().splitlines()]
    rows = sorted({r["j"]: r for r in rows}.values(), key=lambda r: r["j"])
    acc = cfg["acceptance"]
    dpy = cfg["days_per_year"]
    n_proc = sum(len(json.loads(x)["procedures"]) for x in PROCEDURE_LEDGER.read_text().splitlines())

    def fin(x):
        return -math.inf if x is None or (isinstance(x, float) and math.isnan(x)) else x

    rep = {"run_name": cfg["run_name"], "n_null": len(rows), "dsr_n_procedures": n_proc, "code_version": code_version(),
           "results": {}}
    for gen, by_v in obs.items():
        rep["results"][gen] = {}
        for v, o in by_v.items():
            nul = np.array([fin(r["results"][gen][v]["mean_r_x1"]) for r in rows])
            nul2 = np.array([fin(r["results"][gen][v]["mean_r_x2"]) for r in rows])
            nsr = np.array([r["results"][gen][v]["portfolio_sharpe"] for r in rows]) / math.sqrt(dpy)
            daily = np.array(o["daily_portfolio"])
            sr, skew, kurt = moments(daily)
            sr0 = expected_max_sharpe(n_proc, float(np.var(nsr))) if len(rows) > 1 else 0.0
            per_pair_p = {}
            for pair, pp in o["per_pair"].items():
                pn = np.array([fin(r["results"][gen][v]["per_pair_mean_r_x1"][pair]) for r in rows])
                per_pair_p[pair] = (1 + int((pn >= fin(pp["mean_r_x1"])).sum())) / (1 + len(rows))
            d = {k: val for k, val in o.items() if k != "daily_portfolio"}
            d.update({"p_value": (1 + int((nul >= fin(o["mean_r_x1"])).sum())) / (1 + len(rows)),
                      "p_value_x2": (1 + int((nul2 >= fin(o["mean_r_x2"])).sum())) / (1 + len(rows)),
                      "null_mean_r_x1": {"mean": float(np.mean(nul)), "p95": float(np.percentile(nul, 95)),
                                         "max": float(np.max(nul))},
                      "per_pair_p_value_informative": per_pair_p,
                      "portfolio_psr_vs_0": probabilistic_sharpe(sr, 0.0, len(daily), skew, kurt),
                      "portfolio_dsr": probabilistic_sharpe(sr, sr0, len(daily), skew, kurt),
                      "dsr_sr_expected_max_annual": sr0 * math.sqrt(dpy)})
            rep["results"][gen][v] = d
    verdicts = {}
    for v in obs["genetic"]:
        g, r = rep["results"]["genetic"][v], rep["results"]["random"][v]
        checks = {"pooled_mean_r_x1_gt": g["mean_r_x1"] > acc["pooled_mean_r_x1_gt"],
                  "pooled_mean_r_x2_gt": g["mean_r_x2"] > acc["pooled_mean_r_x2_gt"],
                  "p_value_le": g["p_value"] <= acc["p_value_le"],
                  "beats_random_control": g["mean_r_x1"] > r["mean_r_x1"],
                  "portfolio_dsr_ge": g["portfolio_dsr"] >= acc["portfolio_dsr_ge"]}
        verdicts[v] = {"checks": checks, "has_edge": bool(all(checks.values()))}
    rep["verdicts"] = verdicts
    rep["any_variant_has_edge"] = any(x["has_edge"] for x in verdicts.values())
    (out / "report.json").write_text(json.dumps(rep, indent=1))
    return rep


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["observed", "null", "report"])
    ap.add_argument("--config", default=str(PROJECT_ROOT / "configs" / "wf_6pairs.yaml"))
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
