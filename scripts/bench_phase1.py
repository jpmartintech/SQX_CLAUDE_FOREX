"""Phase 1 benchmark: strategies/second of the sqxf kernels vs the reference SQX_ENGINE evaluator.

Same machine, same data (pair H1 bars up to the sealed holdout; evaluation window from dev_start), random strategies with
1-4 AND predicates from each engine's own grammar. Nothing is selected: the evaluations are only counted in the ledger.

Usage:
    python scripts/bench_phase1.py --pair EURUSD --n 20000 --ref-n 1000 --out docs/reports/phase1_bench.json
Run the reference import with NUMBA_CACHE_DIR outside reference/ (the script sets it) so reference/ stays untouched.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("NUMBA_CACHE_DIR", str(ROOT / "runs" / "numba_cache_reference"))
sys.dont_write_bytecode = True

import numba  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from sqxf.backtest.evaluator import derive_metrics, evaluate_light, evaluate_rich, load_market  # noqa: E402
from sqxf.grammar import random_strategy  # noqa: E402
from sqxf.provenance import code_version  # noqa: E402
from sqxf.trials import record_evaluations  # noqa: E402


def timed(fn, *args, repeat=1, **kwargs):
    best, out = float("inf"), None
    for _ in range(repeat):
        t = time.perf_counter()
        out = fn(*args, **kwargs)
        best = min(best, time.perf_counter() - t)
    return best, out


def bench_ours(market, strategies, n_rich):
    res = {}
    evaluate_light(market, strategies[:16], exec_tf="H1")  # compile / load cache
    evaluate_light(market, strategies[:16], exec_tf="M15")
    evaluate_rich(market, strategies[0], exec_tf="M15")
    threads = numba.get_num_threads()
    for tf in ("H1", "M15"):
        sec, agg = timed(evaluate_light, market, strategies, exec_tf=tf, repeat=2)
        res[f"light_{tf}_{threads}threads"] = {"seconds": sec, "strategies_per_sec": len(strategies) / sec}
        if tf == "H1":
            agg_h1 = agg
    numba.set_num_threads(1)
    sub = strategies[: max(len(strategies) // 4, 1)]
    for tf in ("H1", "M15"):
        sec, _ = timed(evaluate_light, market, sub, exec_tf=tf, repeat=2)
        res[f"light_{tf}_1thread"] = {"seconds": sec, "strategies_per_sec": len(sub) / sec}
    numba.set_num_threads(threads)
    sec, _ = timed(lambda: [evaluate_rich(market, s, exec_tf="M15") for s in strategies[:n_rich]])
    res["rich_M15_1thread"] = {"seconds": sec, "strategies_per_sec": n_rich / sec}
    return res, agg_h1, threads


def reference_strategies(rng, n, pair):
    from sqx_engine.grammar import ALL_PREDICATES
    from sqx_engine.strategy import StrategyDefinition as RefDef
    out, seen = [], set()
    while len(out) < n:
        k = int(rng.integers(1, 5))
        preds = tuple(ALL_PREDICATES[i] for i in rng.choice(len(ALL_PREDICATES), size=k, replace=False))
        try:
            s = RefDef(pair, "H1", ("LONG", "SHORT")[int(rng.integers(2))], preds, "AND", 14,
                       float(rng.choice([1.0, 1.5, 2.0, 3.0])), float(rng.choice([1.0, 1.5, 2.0, 3.0, 4.0])),
                       int(rng.choice([12, 24, 48, 96])), grammar_version="v1.7")
        except ValueError:
            continue
        if s.canonical_hash not in seen:
            seen.add(s.canonical_hash)
            out.append(s)
    return out


def bench_reference(market, n, seed, workers):
    sys.path.insert(0, str(ROOT / "reference" / "SQX_ENGINE" / "src"))
    from sqx_engine.backtest import FastEvaluator
    from sqx_engine.backtest.parallel import ParallelEvaluator
    from sqx_engine.features import prepare_features

    h1 = market.h1
    frame = pd.DataFrame({"timestamp": h1["ts_utc"], "open": h1["open"], "high": h1["high"], "low": h1["low"],
                          "close": h1["close"]})
    t = time.perf_counter()
    feats = prepare_features(frame, grammar_version="v1.7")
    feat_sec = time.perf_counter() - t
    cost = market.costs.round_trip
    strategies = reference_strategies(np.random.default_rng(seed), n, market.pair)
    ev = FastEvaluator(frame, feats, 10000, spread=cost, slippage=0.0, cache_size=4096, engine="numba")
    for s in strategies[:5]:
        ev.evaluate(s, start=market.t0, rich=False)
    ev = FastEvaluator(frame, feats, 10000, spread=cost, slippage=0.0, cache_size=4096, engine="numba")
    sec, _ = timed(lambda: [ev.evaluate(s, start=market.t0, rich=False) for s in strategies])
    res = {"features_seconds": feat_sec,
           "fast_evaluator_1process": {"seconds": sec, "strategies_per_sec": n / sec}}
    with ParallelEvaluator(frame, feats, 10000, cost, 0.0, workers, cache_size=4096, engine="numba") as pe:
        pe.evaluate_batch(strategies[: workers * 2], start=market.t0, rich=False)  # warm workers
        sec, _ = timed(pe.evaluate_batch, strategies, start=market.t0, rich=False)
    res[f"parallel_evaluator_{workers}workers"] = {"seconds": sec, "strategies_per_sec": n / sec}
    return res


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pair", default="EURUSD")
    ap.add_argument("--n", type=int, default=20000)
    ap.add_argument("--ref-n", type=int, default=1000)
    ap.add_argument("--n-rich", type=int, default=200)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--no-reference", action="store_true")
    ap.add_argument("--out", default=str(ROOT / "docs" / "reports" / "phase1_bench.json"))
    args = ap.parse_args()

    t = time.perf_counter()
    market = load_market(args.pair)
    load_sec = time.perf_counter() - t
    rng = np.random.default_rng(args.seed)
    strategies = [random_strategy(rng, args.pair) for _ in range(args.n)]
    ours, agg, threads = bench_ours(market, strategies, args.n_rich)

    # Sanity (not selection): random strategies after costs should not look profitable on average.
    m = [derive_metrics(a) for a in agg]
    active = [x for x in m if x["n_trades"] >= 30]
    sanity = {"strategies_with_30plus_trades": len(active),
              "median_mean_r": float(np.median([x["mean_r"] for x in active])) if active else None,
              "share_profit_factor_gt_1": float(np.mean([x["profit_factor"] > 1 for x in active])) if active else None,
              "median_trades": float(np.median([x["n_trades"] for x in m]))}

    report = {"pair": args.pair, "h1_bars_total": market.n_h1, "window_bars": market.t1 - market.t0,
              "m15_bars_total": int(len(market.execs["M15"].o)),
              "window": [str(market.h1["ts_local"].iat[market.t0]), str(market.h1["ts_local"].iat[market.t1 - 1])],
              "round_trip_cost": market.costs.round_trip, "n_strategies": args.n, "seed": args.seed,
              "market_build_seconds": load_sec, "numba_threads": threads, "sqxf": ours, "sanity_random_h1": sanity,
              "code_version": code_version(), "source_sha256": market.meta.get("source_sha256"),
              "machine": {"cpu_count": os.cpu_count(), "python": platform.python_version(),
                          "numba": numba.__version__, "numpy": np.__version__, "platform": platform.platform()}}
    n_evals = args.n * 2 + (args.n // 4) * 2 + args.n_rich
    if not args.no_reference:
        report["reference"] = bench_reference(market, args.ref_n, args.seed, workers=max(1, (os.cpu_count() or 2) - 1))
        n_evals += args.ref_n * 2
        ref_best = max(v["strategies_per_sec"] for k, v in report["reference"].items() if isinstance(v, dict))
        report["speedup_light_H1_vs_best_reference"] = ours[f"light_H1_{threads}threads"]["strategies_per_sec"] / ref_best
        report["speedup_light_M15_vs_best_reference"] = ours[f"light_M15_{threads}threads"]["strategies_per_sec"] / ref_best
    record_evaluations("phase1 benchmark", args.pair, n_evals, selection=False, seed=args.seed)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(report, indent=2, default=float))
    print(json.dumps(report, indent=2, default=float))


if __name__ == "__main__":
    main()
