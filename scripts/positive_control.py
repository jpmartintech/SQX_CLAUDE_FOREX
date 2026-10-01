"""Positive control of the Phase S funnel (configs/positive_control.yaml, pre-registered).

  B --shard i --n-shards n   predictive-test control: null world + injected state edges (resumable)
  C                          strategy-pipeline control: H4 AR(1) momentum levels + pipeline checks
  report                     aggregate B and C -> docs/reports/positive_control_results.json + figures
Synthetic evaluations are logged ONLY in trials/synthetic_ledger.jsonl.
"""
from __future__ import annotations

import argparse
import json
import math
from datetime import UTC, datetime

import matplotlib
import numpy as np

from sqxf.backtest.evaluator import Costs
from sqxf.backtest.oracle import simulate_oracle
from sqxf.control.funnel import calibration_run, direction_of_state, predictive_test, state_nets
from sqxf.control.synthetic import (
    calendar,
    inject_h4_ar,
    inject_state_edge,
    load_dev_shapes,
    null_world_shapes,
    to_m15,
)
from sqxf.data.m15 import DataConfig
from sqxf.provenance import PROJECT_ROOT, code_version, load_yaml_strict, require_committed
from sqxf.states.pipeline import compute_states
from sqxf.states.validate import bars_market, calibration_signals, run_signal, window_of

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

CONFIG = PROJECT_ROOT / "configs" / "positive_control.yaml"
OUT = PROJECT_ROOT / "runs" / "positive_control_s1"
SYN_LEDGER = PROJECT_ROOT / "trials" / "synthetic_ledger.jsonl"


def setup():
    require_committed(CONFIG)
    pc = load_yaml_strict(CONFIG)
    st = load_yaml_strict(PROJECT_ROOT / pc["funnel_config"])
    dev = load_dev_shapes(pc["source_data"]["pairs"], *pc["source_data"]["period"])
    desc = json.loads((PROJECT_ROOT / "docs/reports/states_descriptive.json").read_text())
    tested = [k for k in desc["pairs"]["EURUSD"]["combined"]["usable_states"] if direction_of_state(k) != 0]
    assert len(tested) == 15
    return pc, st, dev, tested


def syn_log(purpose: str, n: int, **extra) -> None:
    SYN_LEDGER.parent.mkdir(parents=True, exist_ok=True)
    with SYN_LEDGER.open("a") as fh:
        fh.write(json.dumps({"utc": datetime.now(UTC).isoformat(), "purpose": purpose, "n_evaluations": n,
                             "code_version": code_version(), **extra}) + "\n")


def world_m15(shapes: dict, pc: dict, dcfg: DataConfig) -> dict:
    cal = calendar(pc["null_world"]["calendar_start_local"], pc["null_world"]["days"])
    return {p: to_m15(s, cal, dcfg) for p, s in shapes.items()}


def run_b(shard: int, n_shards: int) -> None:
    pc, st, dev, tested = setup()
    dcfg = DataConfig.load()
    pt, ribbon = st["predictive_test"], st["ribbon"]
    win = pc["null_world"]["validation_window"]
    years = list(range(int(win[0][:4]), int(win[1][:4])))
    b = pc["part_B"]
    pips = {p: Costs.for_pair(p).pip for p in pc["source_data"]["pairs"]}
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"B_shard{shard}.jsonl"
    done = {json.loads(x)["replica"] for x in path.read_text().splitlines()} if path.exists() else set()
    target, h_edge = b["edge"]["target_state"], b["edge"]["horizon_h1"]
    sign = direction_of_state(target)
    for i in range(shard, b["replicas"], n_shards):
        if i in done:
            continue
        w0 = null_world_shapes(dev, b["world_seed_base"] + i, pc["null_world"]["days"])
        m0 = world_m15(w0, pc, dcfg)
        s0 = {p: compute_states(m, ribbon) for p, m in m0.items()}
        n0 = {p: state_nets(s, pips[p], pt["horizons_h1_bars"], win) for p, s in s0.items()}
        rows0 = predictive_test(n0, "EURUSD", tested, pt["horizons_h1_bars"], pt, years)
        tgt0 = next(r for r in rows0 if r["state"] == target and r["horizon"] == h_edge)
        rec = {"replica": i, "seed": b["world_seed_base"] + i,
               "null": {"n_predictive": sum(r["predictive"] for r in rows0),
                        "per_test": {f"{r['state']}_{r['horizon']}": r["predictive"] for r in rows0},
                        "components": {k: sum(r["pass"][k] for r in rows0) for k in rows0[0]["pass"]},
                        "target": {k: tgt0[k] for k in ("mean", "p_raw", "p_holm", "years_positive", "replica_positive",
                                                       "predictive", "pass", "n")}},
               "edges": {}}
        for size in b["edge"]["net_sizes_pips"]:
            gross = size + 1.5
            wi = {p: inject_state_edge(w0[p], s0[p]["combined"]["state"].to_numpy(), target, sign, gross, pips[p], h_edge)
                  for p in w0}
            mi = world_m15(wi, pc, dcfg)
            si = {p: compute_states(m, ribbon) for p, m in mi.items()}
            ni = {p: state_nets(s, pips[p], pt["horizons_h1_bars"], win) for p, s in si.items()}
            rows = predictive_test(ni, "EURUSD", tested, pt["horizons_h1_bars"], pt, years)
            tgt = next(r for r in rows if r["state"] == target and r["horizon"] == h_edge)
            rec["edges"][str(size)] = {
                "target": {k: tgt[k] for k in ("mean", "p_raw", "p_holm", "years_positive", "replica_positive", "predictive",
                                               "pass", "n")},
                "realised_edge_pips": float(tgt["mean"] - tgt0["mean"]),
                "other_predictive": sum(r["predictive"] for r in rows if not (r["state"] == target and r["horizon"] == h_edge)),
                "state_agreement": float(np.mean(si["EURUSD"]["combined"]["state"].to_numpy()[:len(s0["EURUSD"]["combined"])]
                                                 == s0["EURUSD"]["combined"]["state"].to_numpy()))}
        with path.open("a") as fh:
            fh.write(json.dumps(rec) + "\n")
        syn_log("positive control B (null + 4 edge sizes, 45 tests each, 6 pairs)", 5 * 45 * 6, replica=i)
        print(f"B replica {i}: null predictive {rec['null']['n_predictive']} | " + ", ".join(
            f"{s}: {'DET' if v['target']['predictive'] else 'miss'} (real {v['realised_edge_pips']:+.1f})"
            for s, v in rec["edges"].items()), flush=True)


def pipeline_checks(pc, st, dev, dcfg) -> dict:
    """Oracle == Numba on a synthetic AR world and causality of states + calibration trades."""
    cal_cfg = st["calibration_hypothesis_1"]
    w0 = null_world_shapes(dev, pc["part_C"]["world_seed_base"], pc["null_world"]["days"])
    shapes = inject_h4_ar(w0["EURUSD"], max(pc["part_C"]["ar_phi_levels"]))
    m15 = world_m15({"EURUSD": shapes}, pc, dcfg)["EURUSD"]
    mk = bars_market("EURUSD", m15, "H4", Costs.for_pair("EURUSD"), 1.0, 1.0)
    w = window_of(mk, *pc["null_world"]["validation_window"])
    sig = calibration_signals(mk)
    ex = mk.execs["M15"]
    fr, fr_abs = ex.funding_arrays()
    out = {"python_equals_numba": True, "trades_compared": 0}
    for d in (1, -1):
        t, agg = run_signal(mk, sig[d], d, cal_cfg["initial_stop_atr"], cal_cfg["max_bars_h4"], cal_cfg["trailing_atr"],
                            sig[f"exit_{d}"], w)
        tr, oagg = simulate_oracle(sig[d] & mk.tradable, mk.atr, ex.h1_start, ex.h1_end, ex.h1_of, ex.o, ex.h, ex.l, ex.c,
                                   ex.day_id, d, cal_cfg["initial_stop_atr"], math.inf, cal_cfg["max_bars_h4"], 0,
                                   mk.costs.round_trip, 0.005, 260.0, w[0], w[1], np.zeros(mk.n_h1), fr, fr_abs, 1.0,
                                   math.inf, cal_cfg["trailing_atr"], sig[f"exit_{d}"])
        same = len(t) == len(tr) and np.array_equal(t["r"].to_numpy(), np.array([x["r"] for x in tr])) and \
            np.allclose(agg, oagg, rtol=1e-9, atol=1e-15)
        out["python_equals_numba"] &= bool(same)
        out["trades_compared"] += len(t)
    # causality: perturb the last 3 synthetic months
    cut = int(len(m15) * 0.96)
    s2 = {**shapes, "shapes": shapes["shapes"].copy()}
    s2["shapes"][cut:, 3] += np.random.default_rng(9).normal(0, 2e-3, len(m15) - cut)
    m15b = world_m15({"EURUSD": s2}, pc, dcfg)["EURUSD"]
    sa, sb = compute_states(m15, st["ribbon"]), compute_states(m15b, st["ribbon"])
    t_cut = m15["ts_utc"].iat[cut]
    closed = (sa["bars"]["H1"]["available_utc"] <= t_cut).to_numpy()
    out["states_unchanged_before_cut"] = bool(np.array_equal(sa["combined"]["state"].to_numpy()[closed],
                                                             sb["combined"]["state"].to_numpy()[closed], equal_nan=True))
    mkb = bars_market("EURUSD", m15b, "H4", Costs.for_pair("EURUSD"), 1.0, 1.0)
    sigb = calibration_signals(mkb)
    ta, _ = run_signal(mk, sig[1], 1, 3.0, 500, 3.0, sig["exit_1"], (0, mk.n_h1))
    tb, _ = run_signal(mkb, sigb[1], 1, 3.0, 500, 3.0, sigb["exit_1"], (0, mkb.n_h1))
    h4_cut = int(ex.h1_of[cut])
    pa, pb = ta[ta["exit_idx"] < h4_cut], tb[tb["exit_idx"] < h4_cut]
    out["trades_unchanged_before_cut"] = bool(len(pa) == len(pb) and np.array_equal(pa["r"].to_numpy(), pb["r"].to_numpy()))
    out["trades_before_cut"] = int(len(pa))
    return out


def run_c() -> None:
    pc, st, dev, _ = setup()
    dcfg = DataConfig.load()
    c = pc["part_C"]
    swap = load_yaml_strict(PROJECT_ROOT / "configs" / "swap.yaml")
    win = pc["null_world"]["validation_window"]
    years = list(range(int(win[0][:4]), int(win[1][:4])))
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / "C.jsonl"
    done = {(json.loads(x)["replica"], json.loads(x)["phi"]) for x in path.read_text().splitlines()} if path.exists() else set()
    checks = pipeline_checks(pc, st, dev, dcfg)
    (OUT / "C_pipeline_checks.json").write_text(json.dumps(checks, indent=1))
    print("pipeline checks:", checks, flush=True)
    for i in range(c["replicas"]):
        w0 = null_world_shapes(dev, c["world_seed_base"] + i, pc["null_world"]["days"])
        for phi in [0.0, *c["ar_phi_levels"]]:
            if (i, phi) in done:
                continue
            m15 = world_m15({p: inject_h4_ar(s, phi) for p, s in w0.items()}, pc, dcfg)
            res = calibration_run(m15, swap, st["calibration_hypothesis_1"], st["acceptance_strategies"], win, years,
                                  c["dsr"]["n"], c["dsr"]["var_sr_daily"])
            res.pop("per_pair", None)
            with path.open("a") as fh:
                fh.write(json.dumps({"replica": i, "phi": phi, **res}, default=float) + "\n")
            print(f"C replica {i} phi {phi}: R {res['mean_r_x1']:+.3f} PF {res['pf']:.2f} accepted {res['accepted']}", flush=True)
        syn_log("positive control C (calibration, 4 phi levels, 6 pairs)", 4 * 6, replica=i)


def report() -> None:
    pc = load_yaml_strict(CONFIG)
    rows = [json.loads(x) for p in sorted(OUT.glob("B_shard*.jsonl")) for x in p.read_text().splitlines()]
    rows = sorted({r["replica"]: r for r in rows}.values(), key=lambda r: r["replica"])
    sizes = [str(s) for s in pc["part_B"]["edge"]["net_sizes_pips"]]
    n = len(rows)
    out = {"B": {"replicas": n}, "C": {}}
    fw = np.mean([r["null"]["n_predictive"] > 0 for r in rows])
    per_test = np.mean([np.mean(list(r["null"]["per_test"].values())) for r in rows])
    out["B"]["null"] = {"family_wise_fpr": float(fw), "per_test_fpr": float(per_test),
                        "target_null_mean_net": float(np.mean([r["null"]["target"]["mean"] for r in rows])),
                        "components_mean_count": {k: float(np.mean([r["null"]["components"][k] for r in rows]))
                                                  for k in rows[0]["null"]["components"]}}
    out["B"]["edges"] = {}
    for s in sizes:
        e = [r["edges"][s] for r in rows]
        out["B"]["edges"][s] = {
            "power": float(np.mean([x["target"]["predictive"] for x in e])),
            "components": {k: float(np.mean([x["target"]["pass"][k] for x in e])) for k in e[0]["target"]["pass"]},
            "realised_edge_pips_mean": float(np.mean([x["realised_edge_pips"] for x in e])),
            "realised_edge_pips_sd": float(np.std([x["realised_edge_pips"] for x in e])),
            "target_mean_net_mean": float(np.mean([x["target"]["mean"] for x in e])),
            "p_raw_median": float(np.median([x["target"]["p_raw"] for x in e])),
            "p_holm_median": float(np.median([x["target"]["p_holm"] for x in e])),
            "other_predictive_any": float(np.mean([x["other_predictive"] > 0 for x in e])),
            "state_agreement_mean": float(np.mean([x["state_agreement"] for x in e])),
            "target_bars_mean": float(np.mean([x["target"]["n"] for x in e]))}
    cr = [json.loads(x) for x in (OUT / "C.jsonl").read_text().splitlines()] if (OUT / "C.jsonl").exists() else []
    for phi in sorted({r["phi"] for r in cr}):
        g = [r for r in cr if r["phi"] == phi]
        out["C"][str(phi)] = {"replicas": len(g), "accepted_share": float(np.mean([r["accepted"] for r in g])),
                              "mean_r_x1": float(np.mean([r["mean_r_x1"] for r in g])),
                              "mean_r_x2": float(np.mean([r["mean_r_x2"] for r in g])),
                              "pf_median": float(np.median([r["pf"] for r in g])),
                              "dsr_median": float(np.median([r["dsr"] for r in g])),
                              "trades_mean": float(np.mean([r["trades"] for r in g])),
                              "checks_share": {k: float(np.mean([r["checks"][k] for r in g])) for k in g[0]["checks"]}}
    if (OUT / "C_pipeline_checks.json").exists():
        out["C_pipeline_checks"] = json.loads((OUT / "C_pipeline_checks.json").read_text())
    (PROJECT_ROOT / "docs/reports/positive_control_results.json").write_text(json.dumps(out, indent=1))
    plt.style.use("dark_background")
    fig, ax = plt.subplots(1, 2, figsize=(11, 4.2))
    xs = [float(s) for s in sizes]
    ax[0].plot(xs, [out["B"]["edges"][s]["power"] for s in sizes], "o-", label="potencia (todos los criterios)")
    ax[0].plot(xs, [out["B"]["edges"][s]["components"]["holm"] for s in sizes], "s--", label="solo Holm <= 0,05")
    ax[0].axhline(0.8, color="grey", lw=0.8, ls=":")
    ax[0].set_xscale("log")
    ax[0].set_xlabel("edge neto inyectado a 24 h (pips)")
    ax[0].set_ylabel("tasa de detección")
    ax[0].set_title(f"Test predictivo (n={n} réplicas; FPR familia {fw:.2f})")
    ax[0].legend(fontsize=8)
    if out["C"]:
        phis = sorted(out["C"], key=float)
        ax[1].plot([float(p) for p in phis], [out["C"][p]["accepted_share"] for p in phis], "o-", label="aceptada")
        ax[1].plot([float(p) for p in phis], [out["C"][p]["mean_r_x1"] for p in phis], "s--", label="mean R x1")
        ax[1].axhline(0, color="white", lw=0.6)
        ax[1].set_xlabel("persistencia AR(1) de retornos H4 (phi)")
        ax[1].set_title("Calibración H4 en mundos con momentum")
        ax[1].legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(PROJECT_ROOT / "docs/reports/figures/pc_power_and_momentum.png", dpi=120)
    print(json.dumps(out, indent=1))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("part", choices=["B", "C", "report"])
    ap.add_argument("--shard", type=int, default=0)
    ap.add_argument("--n-shards", type=int, default=1)
    args = ap.parse_args()
    if args.part == "B":
        run_b(args.shard, args.n_shards)
    elif args.part == "C":
        run_c()
    else:
        report()


if __name__ == "__main__":
    main()
