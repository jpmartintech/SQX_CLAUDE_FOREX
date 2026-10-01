"""Positive control of the whole Phase 2 funnel (configs/funnel_control.yaml, pre-registered).

  calibrate --strategy T_trend      delta (pips per H1 bar) per target Sharpe, on the calibration world (seed 69999)
  A --shard i --n-shards n          pool (20,000 random g1) + planted strategy through the funnel; null FPR (resumable)
  B --shard i --n-shards n          genetic search on planted worlds (sizes 1.0/1.5, replicas 0-2) + funnel + equivalence
  C                                 informative N_eff by clustering pool trade series; DSR recomputed
  report                            aggregate -> docs/reports/funnel_control_results.json + figures
Synthetic evaluations go ONLY to trials/synthetic_ledger.jsonl.
"""
from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime

import matplotlib
import numpy as np

from sqxf.backtest.evaluator import Costs, evaluate_light, strategy_signal
from sqxf.control.factory import (
    effective_trials_clusters,
    make_market,
    plant_edge,
    planted,
    run_funnel_pool,
    strategy_sharpe,
    world_shapes,
)
from sqxf.control.synthetic import load_dev_shapes, rebuild
from sqxf.data.m15 import DataConfig
from sqxf.funnel.pipeline import daily_returns, make_fitness, stats, window
from sqxf.generators.genetic import GAConfig, run_genetic
from sqxf.grammar import random_strategy
from sqxf.provenance import PROJECT_ROOT, code_version, load_yaml_strict, require_committed
from sqxf.stats.dsr import deflated_sharpe

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

CONFIG = PROJECT_ROOT / "configs" / "funnel_control.yaml"
OUT = PROJECT_ROOT / "runs" / "funnel_control_s1"
SYN = PROJECT_ROOT / "trials" / "synthetic_ledger.jsonl"
CAL_START, N_DAYS = "2004-01-05", 3911


def setup():
    require_committed(CONFIG)
    fc = load_yaml_strict(CONFIG)
    f = load_yaml_strict(PROJECT_ROOT / fc["funnel_config"])
    dev = load_dev_shapes(["EURUSD"], "2004-01-01", "2019-01-01")
    return fc, f, dev, DataConfig.load()


def syn(purpose: str, n: int, **kw) -> None:
    SYN.parent.mkdir(parents=True, exist_ok=True)
    with SYN.open("a") as fh:
        fh.write(json.dumps({"utc": datetime.now(UTC).isoformat(), "purpose": purpose, "n_evaluations": n,
                             "code_version": code_version(), **kw}) + "\n")


def null_world(fc, dev, seed):
    return world_shapes(dev["pairs"]["EURUSD"], len(dev["days"]), seed, N_DAYS)


def planted_world(w0, mk0, s, delta):
    sig = strategy_signal(mk0, s)
    return plant_edge(w0, sig, s.sign, delta, Costs.for_pair("EURUSD").pip, s.max_bars)


def run_calibrate(name: str) -> None:
    fc, f, dev, dcfg = setup()
    s = planted(fc["planted_strategies"][name])
    w0 = null_world(fc, dev, 69999)
    mk0 = make_market(w0, CAL_START, N_DAYS, dcfg)
    dsr_w = window(mk0, *f["periods"]["dsr_window"])
    out = {"strategy": name, "null_sharpe": strategy_sharpe(mk0, s, dsr_w)[0], "targets": {}}
    null_close = rebuild(w0["o0"], w0["shapes"])[3]
    null_lo, null_hi = float(null_close.min()), float(null_close.max())
    evals = 0
    for target in fc["edge"]["target_net_sharpe"]:
        lo, hi, best = 0.0, 20.0, None
        for _ in range(30):
            mid = (lo + hi) / 2
            wp = planted_world(w0, mk0, s, mid)
            close = rebuild(wp["o0"], wp["shapes"])[3]
            sh, mr, n = float("nan"), float("nan"), 0
            if np.isfinite(close).all() and close.min() >= 0.05 * null_lo and close.max() <= 20.0 * null_hi:
                try:   # outside these bounds the price path has collapsed / exploded (degenerate world)
                    sh, mr, n = strategy_sharpe(make_market(wp, CAL_START, N_DAYS, dcfg), s, dsr_w)
                    evals += 1
                except (ZeroDivisionError, SystemError, FloatingPointError):
                    pass
            best = {"delta_pips_per_h1": mid, "sharpe": sh, "mean_r": mr, "trades": n}
            degenerate = not np.isfinite(mr) or not np.isfinite(sh) or abs(mr) > 10.0
            best["degenerate"] = bool(degenerate)
            if not degenerate and abs(sh - target) <= 0.05:
                break
            lo, hi = (mid, hi) if (sh < target and not degenerate) else (lo, mid)
        out["targets"][str(target)] = best
        print(f"{name} target {target}: delta {best['delta_pips_per_h1']:.4f} -> sharpe {best['sharpe']:.3f} "
              f"meanR {best['mean_r']:+.3f} n {best['trades']}", flush=True)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"calibration_{name}.json").write_text(json.dumps(out, indent=1))
    syn("funnel control calibration (bisection evaluations of one planted strategy)", evals, strategy=name)


def calibration(fc) -> dict:
    """Only (strategy, target) pairs whose calibration reached the target within +-0.05 (non-degenerate) are used."""
    out = {}
    for n in fc["planted_strategies"]:
        c = json.loads((OUT / f"calibration_{n}.json").read_text())
        ok = {t: v for t, v in c["targets"].items()
              if np.isfinite(v["sharpe"]) and not v.get("degenerate") and abs(v["sharpe"] - float(t)) <= 0.05}
        if ok:
            out[n] = {**c, "targets": ok}
    return out


def pool(fc):
    rng = np.random.default_rng(fc["part_A"]["pool_seed"])
    return [random_strategy(rng, "EURUSD") for _ in range(fc["part_A"]["pool_size"])]


def run_a(shard: int, n_shards: int) -> None:
    fc, f, dev, dcfg = setup()
    cal = calibration(fc)
    P = pool(fc)
    N = fc["part_A"]["dsr_n_trials"]
    path = OUT / f"A_shard{shard}.jsonl"
    done = {json.loads(x)["replica"] for x in path.read_text().splitlines()} if path.exists() else set()
    for i in range(shard, fc["part_A"]["replicas"], n_shards):
        if i in done:
            continue
        w0 = null_world(fc, dev, fc["world"]["replica_seed_base"] + i)
        mk0 = make_market(w0, CAL_START, N_DAYS, dcfg)
        res0 = run_funnel_pool(mk0, P, f, N)
        rec = {"replica": i, "null": {"counts": res0["counts"], "survivors": len(res0["pool_survivors"]),
                                      "var_sr": res0["var_sr"]}, "planted": {}}
        dsr_w = window(mk0, *f["periods"]["dsr_window"])
        for name, cc in cal.items():
            s = planted(fc["planted_strategies"][name])
            for target, c in cc["targets"].items():
                mk = make_market(planted_world(w0, mk0, s, c["delta_pips_per_h1"]), CAL_START, N_DAYS, dcfg)
                sh, mr, n = strategy_sharpe(mk, s, dsr_w)
                res = run_funnel_pool(mk, [*P, s], f, N, track=len(P))
                rec["planted"][f"{name}|{target}"] = {"realised_sharpe": sh, "realised_mean_r": mr, "trades": n,
                                                      "path": res["tracked"]["path"], "killer": res["tracked"]["killer"],
                                                      "survived": res["tracked"]["survived"],
                                                      "dsr": None if res["tracked"]["dsr"] is None else res["tracked"]["dsr"]["dsr"],
                                                      "pool_survivors": len(res["pool_survivors"]), "counts": res["counts"]}
                print(f"A rep {i} {name} {target}: sharpe {sh:.2f} R {mr:+.3f} -> "
                      f"{'SURVIVES' if res['tracked']['survived'] else 'killed at ' + str(res['tracked']['killer'])}", flush=True)
        with path.open("a") as fh:
            fh.write(json.dumps(rec, default=float) + "\n")
        syn("funnel control A (pool + planted through the funnel)",
            (1 + sum(len(c["targets"]) for c in cal.values())) * (len(P) + 1), replica=i)


def run_b(shard: int, n_shards: int) -> None:
    fc, f, dev, dcfg = setup()
    cal = calibration(fc)
    b = fc["part_B"]
    jobs = [(name, str(sz), r) for name in cal for sz in b["sizes"] for r in b["replicas"] if str(sz) in cal[name]["targets"]]
    path = OUT / f"B_shard{shard}.jsonl"
    done = {(x["strategy"], x["size"], x["replica"]) for x in map(json.loads, path.read_text().splitlines())} \
        if path.exists() else set()
    for j, (name, sz, r) in enumerate(jobs):
        if j % n_shards != shard or (name, sz, r) in done:
            continue
        s = planted(fc["planted_strategies"][name])
        w0 = null_world(fc, dev, fc["world"]["replica_seed_base"] + r)
        mk0 = make_market(w0, CAL_START, N_DAYS, dcfg)
        mk = make_market(planted_world(w0, mk0, s, cal[name]["targets"][sz]["delta_pips_per_h1"]), CAL_START, N_DAYS, dcfg)
        blocks = [window(mk, a, c) for a, c in f["periods"]["fitness_blocks"]]
        ga = run_genetic("EURUSD", make_fitness(mk, blocks, f["fitness"]["min_trades_per_block"], f["exec_timeframe_fitness"]),
                         GAConfig.from_dict(f["genetic"]), seed=f["seed"] + r)
        arch = [x for x, _ in ga.archive.values()]
        fit = np.array([v for _, v in ga.archive.values()])
        found_hash = s.canonical_hash in ga.archive
        res = run_funnel_pool(mk, arch, f, fc["part_A"]["dsr_n_trials"],
                              track=[x.canonical_hash for x in arch].index(s.canonical_hash) if found_hash else None)
        dsr_w = res["dsr_window"]
        ref = daily_returns(mk, s, "M15", dsr_w)
        top = list(np.argsort(-np.nan_to_num(fit, neginf=-1e9))[:500])
        cands = sorted(set(top) | set(res["survivors"]))
        corr = {int(i): float(np.corrcoef(ref, daily_returns(mk, arch[i], "M15", dsr_w))[0, 1]) for i in cands}
        eq = [i for i, c in corr.items() if c > 0.8]
        rec = {"strategy": name, "size": sz, "replica": r, "evaluated": ga.n_evaluated, "planted_hash_in_archive": found_hash,
               "equivalent_in_top500_or_survivors": len(eq), "max_corr_top500": max(corr[i] for i in top) if top else None,
               "equivalent_survivors": len([i for i in eq if i in set(res["survivors"])]),
               "funnel_counts": res["counts"], "survivors": len(res["survivors"]),
               "planted_tracked": res.get("tracked")}
        with path.open("a") as fh:
            fh.write(json.dumps(rec, default=float) + "\n")
        syn("funnel control B (genetic on planted world + funnel)", ga.n_evaluated, strategy=name, size=sz, replica=r)
        print(f"B {name} {sz} rep {r}: hash found {found_hash}, equivalents {len(eq)}, eq survivors "
              f"{rec['equivalent_survivors']}, survivors {rec['survivors']}", flush=True)


def run_c() -> None:
    fc, f, dev, dcfg = setup()
    cal = calibration(fc)
    c = fc["part_C"]
    P = pool(fc)
    N = fc["part_A"]["dsr_n_trials"]
    r = c["replicas"][0]
    w0 = null_world(fc, dev, fc["world"]["replica_seed_base"] + r)
    mk0 = make_market(w0, CAL_START, N_DAYS, dcfg)
    dsr_w = window(mk0, *f["periods"]["dsr_window"])
    st = stats(evaluate_light(mk0, P, exec_tf="M15", window=dsr_w))
    eligible = np.flatnonzero(st["n"] >= 30)
    rng = np.random.default_rng(52000)
    pick = rng.choice(eligible, size=min(2000, len(eligible)), replace=False)
    daily = np.array([daily_returns(mk0, P[i], "M15", dsr_w) for i in pick])
    ne = effective_trials_clusters(daily, 0.5, N)
    var_sr = float(np.var(st["sharpe"][eligible] / np.sqrt(mk0.days_per_year)))
    best = np.argsort(-st["sharpe"][eligible])[:5]
    nulls = []
    for j in best:
        d = daily_returns(mk0, P[eligible[j]], "M15", dsr_w)
        nulls.append({"sharpe": float(st["sharpe"][eligible[j]]), "dsr_raw": deflated_sharpe(d, N, var_sr)["dsr"],
                      "dsr_neff": deflated_sharpe(d, ne["n_eff"], var_sr)["dsr"]})
    plants = {}
    for name in cal:
        s = planted(fc["planted_strategies"][name])
        for sz in [z for z in c["sizes"] if str(z) in cal[name]["targets"]]:
            mk = make_market(planted_world(w0, mk0, s, cal[name]["targets"][str(sz)]["delta_pips_per_h1"]), CAL_START, N_DAYS,
                             dcfg)
            d = daily_returns(mk, s, "M15", dsr_w)
            plants[f"{name}|{sz}"] = {"dsr_raw": deflated_sharpe(d, N, var_sr)["dsr"],
                                      "dsr_neff": deflated_sharpe(d, ne["n_eff"], var_sr)["dsr"],
                                      "sharpe": strategy_sharpe(mk, s, dsr_w)[0]}
    out = {"replica": r, "clusters": ne, "var_sr": var_sr, "best_null_pool": nulls, "planted": plants}
    (OUT / "C.json").write_text(json.dumps(out, indent=1, default=float))
    syn("funnel control C (clustering + DSR sensitivity)", len(P) + len(pick), replica=r)
    print(json.dumps(out, indent=1, default=float))


def report() -> None:
    fc = load_yaml_strict(CONFIG)
    stages = ["generated", "basic", "stability", "cost_stress", "execution_stress", "walk_forward", "deflated_sharpe"]
    rows = sorted({x["replica"]: x for p in OUT.glob("A_shard*.jsonl") for x in map(json.loads, p.read_text().splitlines())}
                  .values(), key=lambda x: x["replica"])
    cal = calibration(fc)
    out = {"replicas": len(rows), "calibration": cal, "null": {
        "fpr": float(np.mean([r["null"]["survivors"] > 0 for r in rows])),
        "mean_survivors": float(np.mean([r["null"]["survivors"] for r in rows])),
        "mean_counts": {k: float(np.mean([r["null"]["counts"][k] for r in rows])) for k in stages}}, "planted": {}}
    for name in cal:
        for t in fc["edge"]["target_net_sharpe"]:
            key = f"{name}|{t}"
            if str(t) not in cal[name]["targets"]:
                continue
            g = [r["planted"][key] for r in rows]
            killers = {}
            for x in g:
                killers[x["killer"] or "none"] = killers.get(x["killer"] or "none", 0) + 1
            out["planted"][key] = {
                "survival": float(np.mean([x["survived"] for x in g])),
                "stage_survival": {k: float(np.mean([x["path"][k] for x in g])) for k in stages},
                "killers": killers, "realised_sharpe_mean": float(np.mean([x["realised_sharpe"] for x in g])),
                "realised_sharpe_sd": float(np.std([x["realised_sharpe"] for x in g])),
                "realised_mean_r": float(np.mean([x["realised_mean_r"] for x in g])),
                "trades_mean": float(np.mean([x["trades"] for x in g])),
                "dsr_median": float(np.median([x["dsr"] for x in g if x["dsr"] is not None])) if any(
                    x["dsr"] is not None for x in g) else None,
                "pool_survivors_mean": float(np.mean([x["pool_survivors"] for x in g]))}
    bpath = sorted(OUT.glob("B_shard*.jsonl"))
    out["B"] = [json.loads(x) for p in bpath for x in p.read_text().splitlines()]
    if (OUT / "C.json").exists():
        out["C"] = json.loads((OUT / "C.json").read_text())
    (PROJECT_ROOT / "docs/reports/funnel_control_results.json").write_text(json.dumps(out, indent=1, default=float))
    plt.style.use("dark_background")
    fig, ax = plt.subplots(1, 2, figsize=(12, 4.5))
    ts = fc["edge"]["target_net_sharpe"]
    for name in cal:
        ax[0].plot(ts, [out["planted"][f"{name}|{t}"]["survival"] for t in ts], "o-", label=f"{name} (embudo completo)")
        ax[0].plot(ts, [out["planted"][f"{name}|{t}"]["stage_survival"]["walk_forward"] for t in ts], ":", alpha=0.7,
                   label=f"{name} (hasta walk-forward)")
    ax[0].axhline(0.8, color="grey", lw=0.8, ls=":")
    ax[0].set_xlabel("Sharpe neto objetivo de la estrategia plantada")
    ax[0].set_ylabel("tasa de supervivencia")
    ax[0].set_title(f"Embudo Fase 2 (N=168.590, {len(rows)} réplicas; FPR nulo {out['null']['fpr']:.2f})")
    ax[0].legend(fontsize=7)
    kill = {}
    for v in out["planted"].values():
        for k, n in v["killers"].items():
            kill[k] = kill.get(k, 0) + n
    ax[1].bar(list(kill), list(kill.values()), color="tab:orange")
    ax[1].set_title("Etapa que elimina a la estrategia plantada (todas las combinaciones)")
    ax[1].tick_params(axis="x", rotation=30)
    fig.tight_layout()
    fig.savefig(PROJECT_ROOT / "docs/reports/figures/fc_survival_and_killers.png", dpi=120)
    print(json.dumps({k: v for k, v in out.items() if k not in ("calibration", "B")}, indent=1, default=float))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["calibrate", "A", "B", "C", "report"])
    ap.add_argument("--strategy")
    ap.add_argument("--shard", type=int, default=0)
    ap.add_argument("--n-shards", type=int, default=1)
    a = ap.parse_args()
    {"calibrate": lambda: run_calibrate(a.strategy), "A": lambda: run_a(a.shard, a.n_shards),
     "B": lambda: run_b(a.shard, a.n_shards), "C": run_c, "report": report}[a.mode]()


if __name__ == "__main__":
    main()
