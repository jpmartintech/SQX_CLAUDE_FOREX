"""Funnel v2 calibration by simulation (configs/funnel_calibrated.yaml, pre-registered).

  calibrate --strategy NAME           delta per target Sharpe (localised, compensated edge) on the calibration world 79999
  worlds --shard i --n-shards n       all synthetic worlds (200 calibration nulls, 100 FP nulls, 320 planted), resumable
  report                              threshold, FP, survival, design choice, validity -> docs/reports/funnel_calibration_results.json
Synthetic evaluations -> trials/synthetic_ledger.jsonl only.
"""
from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime

import matplotlib
import numpy as np

from sqxf.backtest.evaluator import Costs, strategy_signal
from sqxf.control.factory import make_market, planted, run_funnel_pool, strategy_sharpe, world_shapes
from sqxf.control.funnel_v2 import DESIGNS, killer, plant_edge_compensated, price_ratio, survives, world_record
from sqxf.control.synthetic import load_dev_shapes, rebuild
from sqxf.data.m15 import DataConfig
from sqxf.funnel.pipeline import make_fitness, window
from sqxf.generators.genetic import GAConfig, run_genetic
from sqxf.provenance import PROJECT_ROOT, code_version, load_yaml_strict, require_committed

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

CONFIG = PROJECT_ROOT / "configs" / "funnel_calibrated.yaml"
OUT = PROJECT_ROOT / "runs" / "funnel_v2_k1"
SYN = PROJECT_ROOT / "trials" / "synthetic_ledger.jsonl"
CAL_START, N_DAYS, N_PHASE2 = "2004-01-05", 3911, 168590


def setup():
    require_committed(CONFIG)
    v2 = load_yaml_strict(CONFIG)
    ref = load_yaml_strict(PROJECT_ROOT / v2["reference_funnel"])
    dev = load_dev_shapes(["EURUSD"], "2004-01-01", "2019-01-01")
    return v2, ref, dev, DataConfig.load()


def syn(purpose, n, **kw):
    SYN.parent.mkdir(parents=True, exist_ok=True)
    with SYN.open("a") as fh:
        fh.write(json.dumps({"utc": datetime.now(UTC).isoformat(), "purpose": purpose, "n_evaluations": int(n),
                             "code_version": code_version(), **kw}) + "\n")


def null_shapes(dev, seed):
    return world_shapes(dev["pairs"]["EURUSD"], len(dev["days"]), seed, N_DAYS)


def plant(w0, mk0, s, delta):
    return plant_edge_compensated(w0, strategy_signal(mk0, s), s.sign, delta, Costs.for_pair("EURUSD").pip, s.max_bars)


def genetic_archive(mk, ref, seed):
    blocks = [window(mk, a, b) for a, b in ref["periods"]["fitness_blocks"]]
    ga = run_genetic("EURUSD", make_fitness(mk, blocks, ref["fitness"]["min_trades_per_block"], ref["exec_timeframe_fitness"]),
                     GAConfig.from_dict(ref["genetic"]), seed=seed)
    return [x for x, _ in ga.archive.values()], ga.n_evaluated


def run_calibrate(name):
    v2, ref, dev, dcfg = setup()
    s = planted(v2["planted"]["strategies"][name])
    w0 = null_shapes(dev, 79999)
    mk0 = make_market(w0, CAL_START, N_DAYS, dcfg)
    dw = window(mk0, *ref["periods"]["dsr_window"])
    c0 = rebuild(w0["o0"], w0["shapes"])[3]
    lo0, hi0 = float(c0.min()), float(c0.max())
    out = {"strategy": name, "null_ratio": price_ratio(w0), "null_sharpe": strategy_sharpe(mk0, s, dw)[0], "targets": {}}
    evals = 0
    for target in v2["planted"]["target_net_sharpe"]:
        lo, hi, best = 0.0, 20.0, None
        for _ in range(30):
            mid = (lo + hi) / 2
            wp = plant(w0, mk0, s, mid)
            c = rebuild(wp["o0"], wp["shapes"])[3]
            sh, mr, n = float("nan"), float("nan"), 0
            if np.isfinite(c).all() and c.min() >= 0.05 * lo0 and c.max() <= 20 * hi0:
                try:
                    sh, mr, n = strategy_sharpe(make_market(wp, CAL_START, N_DAYS, dcfg), s, dw)
                    evals += 1
                except (ZeroDivisionError, SystemError, FloatingPointError):
                    pass
            deg = not np.isfinite(sh) or not np.isfinite(mr) or abs(mr) > 10
            best = {"delta_pips_per_h1": mid, "sharpe": sh, "mean_r": mr, "trades": n, "ratio": price_ratio(wp),
                    "degenerate": bool(deg)}
            if not deg and abs(sh - target) <= 0.05:
                break
            lo, hi = (mid, hi) if (sh < target and not deg) else (lo, mid)
        out["targets"][str(target)] = best
        print(f"{name} {target}: delta {best['delta_pips_per_h1']:.4f} sharpe {best['sharpe']:.3f} R {best['mean_r']:+.3f} "
              f"n {best['trades']} ratio {best['ratio']:.3f} (null {out['null_ratio']:.3f})", flush=True)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"calibration_{name}.json").write_text(json.dumps(out, indent=1))
    syn("phase K calibration bisection", evals, strategy=name)


def jobs(v2):
    nw = v2["null_worlds"]
    out = [("cal", i, nw["calibration"]["seed_base"] + i, None, None) for i in range(nw["calibration"]["count"])]
    out += [("fp", i, nw["false_positive"]["seed_base"] + i, None, None) for i in range(nw["false_positive"]["count"])]
    p = v2["planted"]
    for r in range(p["replicas"]["count"]):
        for name in p["strategies"]:
            for t in p["target_net_sharpe"]:
                out.append(("planted", r, p["replicas"]["seed_base"] + r, name, str(t)))
    return out


def run_worlds(shard, n_shards):
    v2, ref, dev, dcfg = setup()
    cal = {n: json.loads((OUT / f"calibration_{n}.json").read_text()) for n in v2["planted"]["strategies"]}
    path = OUT / f"worlds_shard{shard}.jsonl"
    done = {tuple(json.loads(x)["job"]) for x in path.read_text().splitlines()} if path.exists() else set()
    cmp = v2["comparison_phase2"]
    for j, (kind, i, seed, name, t) in enumerate(jobs(v2)):
        key = (kind, i, seed, name, t)
        if j % n_shards != shard or tuple(key) in done:
            continue
        w0 = null_shapes(dev, seed)
        rec = {"job": list(key)}
        if kind in ("cal", "fp"):
            mk = make_market(w0, CAL_START, N_DAYS, dcfg)
            pool, n_ga = genetic_archive(mk, ref, seed)
            rec.update(world_record(mk, pool, ref, v2))
            rec["price_ratio"] = price_ratio(w0)
            if kind == "cal" and i < 30:
                p2 = run_funnel_pool(mk, pool, ref, N_PHASE2)
                rec["phase2"] = {"counts": p2["counts"], "survivors": len(p2["survivors"])}
        else:
            s = planted(v2["planted"]["strategies"][name])
            mk0 = make_market(w0, CAL_START, N_DAYS, dcfg)
            wp = plant(w0, mk0, s, cal[name]["targets"][t]["delta_pips_per_h1"])
            mk = make_market(wp, CAL_START, N_DAYS, dcfg)
            pool, n_ga = genetic_archive(mk, ref, seed)
            found = s.canonical_hash in {x.canonical_hash for x in pool}
            pool = [x for x in pool if x.canonical_hash != s.canonical_hash] + [s]
            dw = window(mk, *ref["periods"]["dsr_window"])
            sh, mr, n = strategy_sharpe(mk, s, dw)
            rec.update(world_record(mk, pool, ref, v2, planted_index=len(pool) - 1))
            rec.update({"realised_sharpe": sh, "realised_mean_r": mr, "trades": n, "price_ratio": price_ratio(wp),
                        "null_price_ratio": price_ratio(w0), "ga_found_hash": found})
            if i in cmp["planted_replicas"]:
                p2 = run_funnel_pool(mk, pool, ref, N_PHASE2, track=len(pool) - 1)
                rec["phase2"] = {"survived": p2["tracked"]["survived"], "killer": p2["tracked"]["killer"],
                                 "counts": p2["counts"]}
        rec["ga_evaluated"] = int(n_ga)
        with path.open("a") as fh:
            fh.write(json.dumps(rec, default=float) + "\n")
        syn(f"phase K world {kind}", n_ga + 1, job=list(key))
        print(f"{key}: counts {rec['counts']} max {rec['max']}" + (f" planted {rec.get('planted_stat')}" if name else ""),
              flush=True)


def load_worlds():
    rows = [json.loads(x) for p in OUT.glob("worlds_shard*.jsonl") for x in p.read_text().splitlines()]
    return {tuple(r["job"]): r for r in rows}


def report():
    v2 = load_yaml_strict(CONFIG)
    W = load_worlds()
    cal_rows = [r for k, r in W.items() if k[0] == "cal"]
    fp_rows = [r for k, r in W.items() if k[0] == "fp"]
    pl = [r for k, r in W.items() if k[0] == "planted"]
    out = {"n_cal": len(cal_rows), "n_fp": len(fp_rows), "n_planted": len(pl), "designs": {}}
    strategies = list(v2["planted"]["strategies"])
    targets = [str(t) for t in v2["planted"]["target_net_sharpe"]]
    for d in DESIGNS:
        mx = np.array([r["max"][d] for r in cal_rows], float)
        thr = float(np.percentile(np.where(np.isfinite(mx), mx, -1e9), 95))
        fp = float(np.mean([r["max"][d] > thr for r in fp_rows])) if fp_rows else float("nan")
        surv = {}
        for name in strategies:
            for t in targets:
                g = [r for r in pl if r["job"][3] == name and r["job"][4] == t]
                if not g:
                    continue
                kills = {}
                for r in g:
                    k = killer(r, d, thr) or "survived"
                    kills[k] = kills.get(k, 0) + 1
                surv[f"{name}|{t}"] = {
                    "replicas": len(g), "survival": float(np.mean([survives(r, d, thr) for r in g])), "killers": kills,
                    "realised_sharpe_mean": float(np.mean([r["realised_sharpe"] for r in g])),
                    "realised_sharpe_sd": float(np.std([r["realised_sharpe"] for r in g])),
                    "realised_mean_r": float(np.mean([r["realised_mean_r"] for r in g])),
                    "trades_mean": float(np.mean([r["trades"] for r in g])),
                    "price_ratio_mean": float(np.mean([r["price_ratio"] for r in g])),
                    "price_ratio_min": float(np.min([r["price_ratio"] for r in g])),
                    "price_ratio_max": float(np.max([r["price_ratio"] for r in g])),
                    "planted_reaches_gate": float(np.mean([r["planted_path"]["out_of_sample"] for r in g])),
                    "planted_stat_median": float(np.median([r["planted_stat"][d] for r in g if r["planted_stat"][d] is not None]))
                    if any(r["planted_stat"][d] is not None for r in g) else None,
                    "ga_found_hash": float(np.mean([r["ga_found_hash"] for r in g]))}
        min10 = min(surv[f"{n}|1.0"]["survival"] for n in strategies) if all(f"{n}|1.0" in surv for n in strategies) else 0.0
        out["designs"][d] = {"threshold": thr, "null_max_quantiles": {q: float(np.percentile(np.where(np.isfinite(mx), mx, -1e9), q))
                                                                      for q in (50, 90, 95, 99)},
                             "fp_rate": fp, "survival": surv, "min_survival_at_1_0": min10}
    elig = [d for d in DESIGNS if out["designs"][d]["fp_rate"] <= v2["validity"]["false_positive_rate_max"]]
    chosen = max(elig, key=lambda d: (out["designs"][d]["min_survival_at_1_0"], -DESIGNS.index(d))) if elig else None
    out["chosen_design"] = chosen
    val = v2["validity"]
    per_strategy = {}
    if chosen:
        for name in strategies:
            ok = [t for t in targets if f"{name}|{t}" in out["designs"][chosen]["survival"]
                  and out["designs"][chosen]["survival"][f"{name}|{t}"]["survival"] >= val["survival_min"]
                  and out["designs"][chosen]["survival"][f"{name}|{t}"]["realised_sharpe_mean"] <= val["realised_sharpe_max"]]
            per_strategy[name] = ok
    out["validity"] = {"fp_ok": bool(chosen is not None), "per_strategy_targets_meeting": per_strategy,
                       "valid": bool(chosen is not None and all(per_strategy.get(n) for n in strategies))}
    p2n = [r["phase2"]["survivors"] for r in cal_rows if "phase2" in r]
    p2p = [r for r in pl if "phase2" in r]
    out["phase2_comparison"] = {"null_worlds": len(p2n), "null_fp": float(np.mean([x > 0 for x in p2n])) if p2n else None,
                                "planted": {f"{n}|{t}": float(np.mean([r["phase2"]["survived"] for r in p2p
                                                                       if r["job"][3] == n and r["job"][4] == t]))
                                            for n in strategies for t in targets
                                            if any(r["job"][3] == n and r["job"][4] == t for r in p2p)}}
    out["null_counts_mean"] = {k: float(np.mean([r["counts"][k] for r in cal_rows])) for k in cal_rows[0]["counts"]}
    (PROJECT_ROOT / "docs/reports/funnel_calibration_results.json").write_text(json.dumps(out, indent=1, default=float))
    plt.style.use("dark_background")
    fig, ax = plt.subplots(1, 2, figsize=(12, 4.5))
    d = chosen or "D1_tstat_r"
    for name in strategies:
        xs = [out["designs"][d]["survival"][f"{name}|{t}"]["realised_sharpe_mean"] for t in targets]
        ys = [out["designs"][d]["survival"][f"{name}|{t}"]["survival"] for t in targets]
        ax[0].plot(xs, ys, "o-", label=name)
    ax[0].axhline(0.8, color="grey", ls=":")
    ax[0].axvline(1.0, color="grey", ls=":")
    ax[0].set_xlabel("Sharpe neto realizado (media de réplicas)")
    ax[0].set_ylabel("supervivencia embudo v2")
    ax[0].set_title(f"Embudo v2 ({d}); FP {out['designs'][d]['fp_rate']:.2f}")
    ax[0].legend(fontsize=8)
    mx = np.array([r["max"][d] for r in cal_rows], float)
    ax[1].hist(mx[np.isfinite(mx)], bins=30, color="tab:cyan")
    ax[1].axvline(out["designs"][d]["threshold"], color="tab:orange", label="umbral p95")
    ax[1].set_title("Máximo fuera de muestra en mundos nulos")
    ax[1].legend()
    fig.tight_layout()
    fig.savefig(PROJECT_ROOT / "docs/reports/figures/k_survival_threshold.png", dpi=120)
    print(json.dumps({k: v for k, v in out.items() if k != "designs"}, indent=1, default=float))
    for dd in DESIGNS:
        print(dd, "thr", out["designs"][dd]["threshold"], "fp", out["designs"][dd]["fp_rate"], "min surv 1.0",
              out["designs"][dd]["min_survival_at_1_0"])


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["calibrate", "worlds", "report"])
    ap.add_argument("--strategy")
    ap.add_argument("--shard", type=int, default=0)
    ap.add_argument("--n-shards", type=int, default=1)
    a = ap.parse_args()
    {"calibrate": lambda: run_calibrate(a.strategy), "worlds": lambda: run_worlds(a.shard, a.n_shards),
     "report": report}[a.mode]()
