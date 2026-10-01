"""Post-hoc, informative sensitivity of the funnel control (no threshold changes): price drift of the planted worlds, rank of
the planted strategy in the pool, and its DSR with the NULL-world Var[SR] vs the planted-world Var[SR] (N = 168,590).
Usage: python scripts/funnel_control_sensitivity.py --shard i --n-shards n ; then --merge
"""
from __future__ import annotations

import argparse
import json
import math

import numpy as np

from funnel_control import CAL_START, N_DAYS, OUT, calibration, null_world, planted_world, pool, setup, syn
from sqxf.backtest.evaluator import evaluate_light
from sqxf.control.factory import make_market, planted
from sqxf.control.synthetic import rebuild
from sqxf.funnel.pipeline import daily_returns, stats, window
from sqxf.stats.dsr import deflated_sharpe


def run(shard: int, n_shards: int) -> None:
    fc, f, dev, dcfg = setup()
    cal = calibration(fc)
    P = pool(fc)
    N = fc["part_A"]["dsr_n_trials"]
    nulls = {x["replica"]: x["null"]["var_sr"] for p in OUT.glob("A_shard*.jsonl") for x in map(json.loads, p.read_text().splitlines())}
    path = OUT / f"S_shard{shard}.jsonl"
    for i in range(shard, fc["part_A"]["replicas"], n_shards):
        w0 = null_world(fc, dev, fc["world"]["replica_seed_base"] + i)
        mk0 = make_market(w0, CAL_START, N_DAYS, dcfg)
        c0 = rebuild(w0["o0"], w0["shapes"])[3]
        for name, cc in cal.items():
            s = planted(fc["planted_strategies"][name])
            for t, c in cc["targets"].items():
                wp = planted_world(w0, mk0, s, c["delta_pips_per_h1"])
                cp = rebuild(wp["o0"], wp["shapes"])[3]
                mk = make_market(wp, CAL_START, N_DAYS, dcfg)
                dw = window(mk, *f["periods"]["dsr_window"])
                st = stats(evaluate_light(mk, [*P, s], exec_tf="M15", window=dw))
                act = st["n"] >= f["fitness"]["min_trades_per_block"]
                var_planted = float(np.var(st["sharpe"][act] / math.sqrt(mk.days_per_year)))
                d = daily_returns(mk, s, "M15", dw)
                rec = {"replica": i, "key": f"{name}|{t}", "price_ratio_end_start": float(cp[-1] / cp[0]),
                       "null_price_ratio": float(c0[-1] / c0[0]), "planted_sharpe": float(st["sharpe"][-1]),
                       "pool_share_sharpe_above_planted": float(np.mean(st["sharpe"][:-1][act[:-1]] > st["sharpe"][-1])),
                       "pool_share_positive_sharpe": float(np.mean(st["sharpe"][:-1][act[:-1]] > 0)),
                       "var_sr_planted_world": var_planted, "var_sr_null_world": nulls[i],
                       "dsr_planted_world_var": deflated_sharpe(d, N, var_planted)["dsr"],
                       "dsr_null_world_var": deflated_sharpe(d, N, nulls[i])["dsr"],
                       "sr_star_annual_null_var": deflated_sharpe(d, N, nulls[i])["sr_expected_max"] * math.sqrt(260)}
                with path.open("a") as fh:
                    fh.write(json.dumps(rec) + "\n")
                print(rec, flush=True)
        syn("funnel control sensitivity (pool re-evaluated in planted worlds)", (len(P) + 1) * 8, replica=i)


def merge() -> None:
    rows = [json.loads(x) for p in OUT.glob("S_shard*.jsonl") for x in p.read_text().splitlines()]
    out = {}
    for k in sorted({r["key"] for r in rows}):
        g = [r for r in rows if r["key"] == k]
        out[k] = {m: float(np.mean([r[m] for r in g])) for m in ("price_ratio_end_start", "null_price_ratio", "planted_sharpe",
                                                                  "pool_share_sharpe_above_planted", "pool_share_positive_sharpe",
                                                                  "var_sr_planted_world", "var_sr_null_world",
                                                                  "dsr_planted_world_var", "dsr_null_world_var",
                                                                  "sr_star_annual_null_var")}
        out[k]["replicas"] = len(g)
    (OUT / "S_summary.json").write_text(json.dumps(out, indent=1))
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--shard", type=int, default=0)
    ap.add_argument("--n-shards", type=int, default=1)
    ap.add_argument("--merge", action="store_true")
    a = ap.parse_args()
    merge() if a.merge else run(a.shard, a.n_shards)
