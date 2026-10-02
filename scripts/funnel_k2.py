"""Phase K2: combined 6-pair funnel calibrated by simulation (configs/funnel_k2.yaml, pre-registered).

  calibrate --strategy NAME --pair PAIR   delta per target Sharpe on the calibration world (seed 89999)
  worlds --shard i --n-shards n           200 calibration nulls, 100 FP nulls, planted worlds (resumable, checkpoint jsonl)
  report                                  thresholds, FP, survival, design choice, validity, figures
Synthetic evaluations -> trials/synthetic_ledger.jsonl only.
"""
from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime

import matplotlib
import numpy as np

from sqxf.backtest.evaluator import Costs, strategy_signal
from sqxf.control.factory import planted, strategy_sharpe
from sqxf.control.funnel_v2 import plant_edge_compensated, price_ratio
from sqxf.control.k2 import combined_daily, masked_series, multi_world_shapes, on_pair, pair_market, run_boundary, tstat
from sqxf.control.synthetic import load_dev_shapes, rebuild
from sqxf.data.m15 import DataConfig
from sqxf.funnel.pipeline import window
from sqxf.provenance import PROJECT_ROOT, code_version, load_yaml_strict, require_committed

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

CONFIG = PROJECT_ROOT / "configs" / "funnel_k2.yaml"
SYN = PROJECT_ROOT / "trials" / "synthetic_ledger.jsonl"
FIG = PROJECT_ROOT / "docs" / "reports" / "figures"
OOS = ("2009-01-01", "2019-01-01")
BLOCK = 20
TOP_CAND = 25


def setup():
    require_committed(CONFIG)
    cfg = load_yaml_strict(CONFIG)
    dev = load_dev_shapes(cfg["pairs"], "2004-01-01", cfg["data_end"])
    return cfg, dev, DataConfig.load(), PROJECT_ROOT / "runs" / cfg["run_name"]


def syn(purpose, n, **kw):
    with SYN.open("a") as fh:
        fh.write(json.dumps({"utc": datetime.now(UTC).isoformat(), "purpose": purpose, "n_evaluations": int(n),
                             "code_version": code_version(), **kw}) + "\n")


def plant_pair(shapes_p, pair, s, delta, cfg, dcfg):
    w = cfg["world"]
    mk0 = pair_market(shapes_p, pair, w["cal_start"], w["n_days"], dcfg)
    sp = on_pair(s, pair)
    return plant_edge_compensated(shapes_p, strategy_signal(mk0, sp), sp.sign, delta, Costs.for_pair(pair).pip, sp.max_bars)


# ------------------------------------------------------------------ calibration
def run_calibrate(name, pair):
    cfg, dev, dcfg, out = setup()
    w = cfg["world"]
    s = on_pair(planted(cfg["planted"]["strategies"][name]), pair)
    w0 = multi_world_shapes(dev, [pair], 89999, w["n_days"])[pair]
    mk0 = pair_market(w0, pair, w["cal_start"], w["n_days"], dcfg)
    dw = window(mk0, "2004-01-01", cfg["data_end"])
    c0 = rebuild(w0["o0"], w0["shapes"])[3]
    lo0, hi0 = float(c0.min()), float(c0.max())
    sig = strategy_signal(mk0, s)
    pip = Costs.for_pair(pair).pip
    evals = 0

    def measure(delta):
        nonlocal evals
        wp = plant_edge_compensated(w0, sig, s.sign, delta, pip, s.max_bars)
        c = rebuild(wp["o0"], wp["shapes"])[3]
        sh, mr, n = float("nan"), float("nan"), 0
        if np.isfinite(c).all() and c.min() >= 0.05 * lo0 and c.max() <= 20 * hi0:
            try:
                sh, mr, n = strategy_sharpe(pair_market(wp, pair, w["cal_start"], w["n_days"], dcfg), s, dw)
                evals += 1
            except (ZeroDivisionError, SystemError, FloatingPointError):
                pass
        deg = not np.isfinite(sh) or not np.isfinite(mr) or abs(mr) > 10
        return {"delta_pips_per_h1": float(delta), "sharpe": float(sh), "mean_r": float(mr), "trades": int(n),
                "ratio": price_ratio(wp), "degenerate": bool(deg)}

    grid = [measure(d) for d in np.arange(0.0, 8.0 + 1e-9, 0.25)]
    res = {"strategy": name, "pair": pair, "null_ratio": price_ratio(w0), "grid": grid, "targets": {}}
    for target in cfg["planted"]["target_net_sharpe"]:
        k = next((k for k in range(1, len(grid)) if not grid[k]["degenerate"] and not grid[k - 1]["degenerate"]
                  and grid[k - 1]["sharpe"] < target <= grid[k]["sharpe"]), None)
        if k is None:
            res["targets"][str(target)] = {"unreachable": True}
            print(f"{name} {pair} {target}: UNREACHABLE (max {max(g['sharpe'] for g in grid if not g['degenerate']):.2f})")
            continue
        lo, hi, best = grid[k - 1]["delta_pips_per_h1"], grid[k]["delta_pips_per_h1"], grid[k]
        if abs(best["sharpe"] - target) > 0.05:
            for _ in range(30):
                best = measure((lo + hi) / 2)
                if not best["degenerate"] and abs(best["sharpe"] - target) <= 0.05:
                    break
                lo, hi = (best["delta_pips_per_h1"], hi) if (best["sharpe"] < target and not best["degenerate"]) \
                    else (lo, best["delta_pips_per_h1"])
        res["targets"][str(target)] = {**best, "unreachable": False}
        print(f"{name} {pair} {target}: delta {best['delta_pips_per_h1']:.4f} sharpe {best['sharpe']:.3f} "
              f"R {best['mean_r']:+.3f} n {best['trades']} ratio {best['ratio']:.3f}", flush=True)
    out.mkdir(parents=True, exist_ok=True)
    (out / f"calibration_{name}_{pair}.json").write_text(json.dumps(res, indent=1))
    syn("phase K2 calibration", evals, strategy=name, pair=pair)


def load_cal(cfg, out):
    return {(n, p): json.loads((out / f"calibration_{n}_{p}.json").read_text())
            for n in cfg["planted"]["strategies"] for p in cfg["pairs"]}


def reachable(cal, name, target, pairs):
    return all(not cal[(name, p)]["targets"][str(target)]["unreachable"] for p in pairs)


def jobs(cfg, cal):
    nw = cfg["null_worlds"]
    out = [("cal", i, nw["calibration"]["seed_base"] + i, None, None, None) for i in range(nw["calibration"]["count"])]
    out += [("fp", i, nw["false_positive"]["seed_base"] + i, None, None, None) for i in range(nw["false_positive"]["count"])]
    p = cfg["planted"]
    for r in range(p["replicas"]["count"]):
        for sc in p["scenarios"]:
            pairs = cfg["pairs"] if sc == "six_pairs" else ["EURUSD"]
            for name in p["strategies"]:
                for t in p["target_net_sharpe"]:
                    if reachable(cal, name, t, pairs):
                        out.append(("planted", r, p["replicas"]["seed_base"] + r, name, str(t), sc))
    return out


# ------------------------------------------------------------------ one world
def run_world(cfg, dev, dcfg, cal, job):
    kind, _, seed, name, t, sc = job
    w = cfg["world"]
    pairs = cfg["pairs"]
    shapes = multi_world_shapes(dev, pairs, seed, w["n_days"])
    rec = {"job": list(job), "null_ratio": {p: price_ratio(shapes[p]) for p in pairs}}
    s = None
    if kind == "planted":
        s = planted(cfg["planted"]["strategies"][name])
        for p in (pairs if sc == "six_pairs" else ["EURUSD"]):
            shapes[p] = plant_pair(shapes[p], p, s, cal[(name, p)]["targets"][t]["delta_pips_per_h1"], cfg, dcfg)
        rec["price_ratio"] = {p: price_ratio(shapes[p]) for p in pairs}
    markets = {p: pair_market(shapes[p], p, w["cal_start"], w["n_days"], dcfg) for p in pairs}
    evaluated = 0
    per_b, rules = {}, {}
    for bi, b in enumerate(cfg["walk_forward"]["boundaries_all"]):
        strategies, sel, n = run_boundary(markets["EURUSD"], b, cfg, cfg["gates"], seed * 16 + bi, planted=s)
        evaluated += n
        top = [strategies[i] for i in sel["top"]]
        for x in top:
            rules.setdefault(x.canonical_hash, x)
        per_b[b] = {"top": [x.canonical_hash for x in top], "counts": sel["counts"], "finite": sel["finite"],
                    "planted": sel.get("planted")}
    if s is not None:
        rules.setdefault(s.canonical_hash, s)
    hashes = list(rules)
    daily, dates = combined_daily(markets, [rules[h] for h in hashes], *OOS, "M15")
    pos = {h: i for i, h in enumerate(hashes)}
    rec["n_union"] = len(hashes)
    rec["boundaries"] = {str(b): {k: v for k, v in d.items() if k != "top"} for b, d in per_b.items()}
    rec["designs"] = {}
    if s is not None:
        ip = pos[s.canonical_hash]
        ref = daily[ip]
        with np.errstate(invalid="ignore", divide="ignore"):
            corr = np.array([np.corrcoef(ref, x)[0, 1] if x.std() > 0 and ref.std() > 0 else 0.0 for x in daily])
        real = {p: strategy_sharpe(markets[p], on_pair(s, p), window(markets[p], "2004-01-01", cfg["data_end"]))
                for p in (pairs if sc == "six_pairs" else ["EURUSD"])}
        rec["realised"] = {p: {"sharpe": v[0], "mean_r": v[1], "trades": v[2]} for p, v in real.items()}
        rec["combined_sharpe_oos_unmasked"] = float(ref.mean() / ref.std() * np.sqrt(260)) if ref.std() > 0 else 0.0
    for dname, segs in cfg["walk_forward"]["designs"].items():
        for k in cfg["preselection"]["k_values"]:
            member = np.zeros((len(hashes), len(segs)), bool)
            for f, (a, _) in enumerate(segs):
                for h in per_b[a]["top"][:k]:
                    member[pos[h], f] = True
            ser = masked_series(daily, dates, member, [(f"{a}-01-01", f"{b}-01-01") for a, b in segs])
            cand = np.flatnonzero(member.any(axis=1))
            tt = tstat(ser[cand], BLOCK) if len(cand) else np.zeros(0)
            d = {"n_candidates": int(len(cand)), "max_t": float(tt.max()) if len(cand) else float("-inf")}
            if s is not None:
                d["planted_t"] = float(tstat(ser[ip], BLOCK)[0]) if member[ip].any() else None
                d["planted_segments"] = int(member[ip].sum())
                order = np.argsort(-tt)[:TOP_CAND]
                d["top"] = [{"t": float(tt[j]), "corr": float(corr[cand[j]])} for j in order if cand[j] != ip]
            rec["designs"][f"{dname}|K{k}"] = d
    rec["evaluated"] = evaluated
    return rec


def run_worlds(shard, n_shards):
    cfg, dev, dcfg, out = setup()
    cal = load_cal(cfg, out)
    path = out / f"worlds_shard{shard}.jsonl"
    done = {tuple(json.loads(x)["job"]) for x in path.read_text().splitlines()} if path.exists() else set()
    for j, job in enumerate(jobs(cfg, cal)):
        if j % n_shards != shard or tuple(job) in done:
            continue
        rec = run_world(cfg, dev, dcfg, cal, job)
        with path.open("a") as fh:
            fh.write(json.dumps(rec, default=float) + "\n")
        syn(f"phase K2 world {job[0]}", rec["evaluated"] + rec["n_union"] * len(cfg["pairs"]), job=list(job))
        best = max(rec["designs"].items(), key=lambda kv: kv[1]["max_t"])
        print(f"{job}: union {rec['n_union']} best {best[0]} max_t {best[1]['max_t']:.2f}"
              + (f" planted W5x2|K35 t {rec['designs']['W5x2|K35'].get('planted_t')}" if job[0] == "planted" else ""),
              flush=True)


# ------------------------------------------------------------------ report
def load_worlds(out):
    rows = [json.loads(x) for p in sorted(out.glob("worlds_shard*.jsonl")) for x in p.read_text().splitlines()]
    return {tuple(r["job"]): r for r in rows}


def survives(rec, combo, thr):
    d = rec["designs"][combo]
    if d.get("planted_t") is not None and d["planted_t"] > thr:
        return True
    return any(c["t"] > thr and c["corr"] > 0.8 for c in d.get("top", []))


def killer(rec, combo, thr):
    if survives(rec, combo, thr):
        return "survived"
    d = rec["designs"][combo]
    if d.get("planted_t") is not None:
        return "decision_gate"
    stages = [v["planted"]["stage"] or "top_k" for v in rec["boundaries"].values()]
    return max(set(stages), key=stages.count)          # most frequent eliminating stage over the boundaries


def report():
    cfg = load_yaml_strict(CONFIG)
    out = PROJECT_ROOT / "runs" / cfg["run_name"]
    W = load_worlds(out)
    cal_rows = [r for k, r in W.items() if k[0] == "cal"]
    fp_rows = [r for k, r in W.items() if k[0] == "fp"]
    pl = [r for k, r in W.items() if k[0] == "planted"]
    combos = list(cal_rows[0]["designs"])
    names = list(cfg["planted"]["strategies"])
    targets = [str(t) for t in cfg["planted"]["target_net_sharpe"]]
    res = {"n_cal": len(cal_rows), "n_fp": len(fp_rows), "n_planted": len(pl), "combos": {}}
    for c in combos:
        mx = np.array([r["designs"][c]["max_t"] for r in cal_rows], float)
        mx = np.where(np.isfinite(mx), mx, -1e9)
        thr = float(np.percentile(mx, 95))
        fp = float(np.mean([r["designs"][c]["max_t"] > thr for r in fp_rows]))
        surv = {}
        for sc in cfg["planted"]["scenarios"]:
            for n in names:
                for t in targets:
                    g = [r for r in pl if r["job"][3] == n and r["job"][4] == t and r["job"][5] == sc]
                    if not g:
                        continue
                    kills = {}
                    for r in g:
                        k = killer(r, c, thr)
                        kills[k] = kills.get(k, 0) + 1
                    rs = [np.mean([v["sharpe"] for v in r["realised"].values()]) for r in g]
                    pt = [r["designs"][c]["planted_t"] for r in g if r["designs"][c]["planted_t"] is not None]
                    surv[f"{sc}|{n}|{t}"] = {
                        "replicas": len(g), "survival": float(np.mean([survives(r, c, thr) for r in g])), "killers": kills,
                        "realised_sharpe_mean": float(np.mean(rs)), "realised_sharpe_sd": float(np.std(rs)),
                        "realised_mean_r": float(np.mean([np.mean([v["mean_r"] for v in r["realised"].values()]) for r in g])),
                        "planted_t_median": float(np.median(pt)) if pt else None,
                        "planted_segments_mean": float(np.mean([r["designs"][c]["planted_segments"] for r in g])),
                        "price_ratio_eurusd": [float(min(r["price_ratio"]["EURUSD"] for r in g)),
                                               float(max(r["price_ratio"]["EURUSD"] for r in g))]}
        key10 = [f"six_pairs|{n}|1.0" for n in names]
        min10 = min(surv[k]["survival"] for k in key10) if all(k in surv for k in key10) else 0.0
        res["combos"][c] = {"threshold": thr, "fp_rate": fp, "min_survival_six_1_0": min10, "survival": surv,
                            "null_max_q": {q: float(np.percentile(mx, q)) for q in (50, 90, 95, 99)}}
    order = {d: i for i, d in enumerate(cfg["walk_forward"]["designs"])}
    elig = [c for c in combos if res["combos"][c]["fp_rate"] <= cfg["validity"]["false_positive_rate_max"]]
    chosen = max(elig, key=lambda c: (res["combos"][c]["min_survival_six_1_0"], -order[c.split("|")[0]],
                                      -int(c.split("|K")[1]))) if elig else None
    res["chosen"] = chosen
    meet = {}
    if chosen:
        sv = res["combos"][chosen]["survival"]
        for n in names:
            meet[n] = [t for t in targets if f"six_pairs|{n}|{t}" in sv
                       and sv[f"six_pairs|{n}|{t}"]["survival"] >= cfg["validity"]["six_pairs_survival_min"]
                       and sv[f"six_pairs|{n}|{t}"]["realised_sharpe_mean"] <= cfg["validity"]["realised_sharpe_max"]]
    res["validity"] = {"fp_ok": chosen is not None, "targets_meeting": meet,
                       "valid": bool(chosen is not None and all(meet.get(n) for n in names))}
    res["null_union_mean"] = float(np.mean([r["n_union"] for r in cal_rows]))
    (PROJECT_ROOT / "docs/reports/funnel_k2_results.json").write_text(json.dumps(res, indent=1, default=float))
    figures(cfg, res, cal_rows, pl, chosen or combos[0])
    for c in combos:
        rc = res["combos"][c]
        print(f"{c} thr {rc['threshold']:.2f} fp {rc['fp_rate']:.2f} min surv six 1.0 {rc['min_survival_six_1_0']:.2f}")
    print("chosen", chosen, "validity", res["validity"])


def figures(cfg, res, cal_rows, pl, c):
    plt.style.use("dark_background")
    names = list(cfg["planted"]["strategies"])
    targets = [str(t) for t in cfg["planted"]["target_net_sharpe"]]
    sv = res["combos"][c]["survival"]
    fig, ax = plt.subplots(1, 3, figsize=(16, 4.6))
    for k, sc in enumerate(cfg["planted"]["scenarios"]):
        for n in names:
            ks = [f"{sc}|{n}|{t}" for t in targets if f"{sc}|{n}|{t}" in sv]
            ax[k].plot([sv[x]["realised_sharpe_mean"] for x in ks], [sv[x]["survival"] for x in ks], "o-", label=n)
        ax[k].axhline(0.8, color="grey", ls=":")
        ax[k].axvline(1.0, color="grey", ls=":")
        ax[k].set_ylim(-0.03, 1.03)
        ax[k].set_xlabel("Sharpe neto realizado por par (media)")
        ax[k].set_title(f"{sc} — {c}")
    ax[0].set_ylabel("supervivencia")
    ax[0].legend(fontsize=7)
    kres = PROJECT_ROOT / "docs/reports/funnel_calibration_results.json"
    if kres.exists():
        kr = json.loads(kres.read_text())["designs"]["D1_tstat_r"]["survival"]
        for n in names:
            ks = [x for x in kr if x.startswith(n)]
            ax[2].plot([kr[x]["realised_sharpe_mean"] for x in ks], [kr[x]["survival"] for x in ks], "o--", label=f"K: {n}")
        ax[2].axhline(0.8, color="grey", ls=":")
        ax[2].axvline(1.0, color="grey", ls=":")
        ax[2].set_title("Fase K (D1, solo EURUSD) para comparar")
        ax[2].set_xlabel("Sharpe neto realizado (media)")
        ax[2].legend(fontsize=7)
    fig.tight_layout()
    fig.savefig(FIG / "k2_survival.png", dpi=120)
    fig, ax = plt.subplots(figsize=(8, 4.2))
    mx = np.array([r["designs"][c]["max_t"] for r in cal_rows], float)
    ax.hist(mx[np.isfinite(mx)], bins=30, color="tab:cyan")
    ax.axvline(res["combos"][c]["threshold"], color="tab:orange", label=f"umbral p95 {res['combos'][c]['threshold']:.2f}")
    pts = [r["designs"][c]["planted_t"] for r in pl if r["job"][5] == "six_pairs" and r["job"][4] == "1.0"
           and r["designs"][c]["planted_t"] is not None]
    ax.hist(pts, bins=30, color="tab:pink", alpha=0.6, label="plantada, 6 pares, objetivo 1,0")
    ax.set_xlabel("t combinado fuera de muestra 2009-2018")
    ax.set_title(f"Máximo nulo frente a la plantada ({c})")
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(FIG / "k2_threshold.png", dpi=120)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["calibrate", "worlds", "report"])
    ap.add_argument("--strategy")
    ap.add_argument("--pair")
    ap.add_argument("--shard", type=int, default=0)
    ap.add_argument("--n-shards", type=int, default=1)
    a = ap.parse_args()
    {"calibrate": lambda: run_calibrate(a.strategy, a.pair), "worlds": lambda: run_worlds(a.shard, a.n_shards),
     "report": report}[a.mode]()
