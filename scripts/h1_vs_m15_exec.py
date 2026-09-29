"""How much does H1 execution (stop wins every ambiguous bar) differ from walking the M15 path? Engineering check only.

Usage: python scripts/h1_vs_m15_exec.py --pair EURUSD --n 2000 --out docs/reports/phase1_h1_vs_m15.json
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from sqxf.backtest.evaluator import derive_metrics, evaluate_light, load_market
from sqxf.grammar import random_strategy
from sqxf.provenance import code_version
from sqxf.trials import record_evaluations


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pair", default="EURUSD")
    ap.add_argument("--n", type=int, default=2000)
    ap.add_argument("--seed", type=int, default=2)
    ap.add_argument("--out", default="docs/reports/phase1_h1_vs_m15.json")
    args = ap.parse_args()
    market = load_market(args.pair)
    rng = np.random.default_rng(args.seed)
    strategies = [random_strategy(rng, args.pair) for _ in range(args.n)]
    a = [derive_metrics(x) for x in evaluate_light(market, strategies, exec_tf="H1")]
    b = [derive_metrics(x) for x in evaluate_light(market, strategies, exec_tf="M15")]
    keep = [i for i in range(args.n) if a[i]["n_trades"] >= 30 and b[i]["n_trades"] >= 30]
    d_mean_r = np.array([b[i]["mean_r"] - a[i]["mean_r"] for i in keep])
    d_trades = np.array([b[i]["n_trades"] / a[i]["n_trades"] - 1 for i in keep])
    d_dd = np.array([b[i]["max_dd"] - a[i]["max_dd"] for i in keep])
    pf_flip = np.mean([(a[i]["profit_factor"] > 1) != (b[i]["profit_factor"] > 1) for i in keep])
    report = {"pair": args.pair, "n": args.n, "seed": args.seed, "compared": len(keep), "code_version": code_version(),
              "mean_r_m15_minus_h1": {"median": float(np.median(d_mean_r)), "p05": float(np.percentile(d_mean_r, 5)),
                                      "p95": float(np.percentile(d_mean_r, 95))},
              "trade_count_rel_diff": {"median": float(np.median(d_trades)), "p95_abs": float(np.percentile(np.abs(d_trades), 95))},
              "max_dd_m15_minus_h1": {"median": float(np.median(d_dd))},
              "share_pf_side_flips": float(pf_flip)}
    record_evaluations("phase1 H1 vs M15 execution check", args.pair, 2 * args.n, selection=False, seed=args.seed)
    Path(args.out).write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
