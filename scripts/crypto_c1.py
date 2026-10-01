"""Crypto C1 Part 2 runner (pre-registered: the config must be committed first).

  observed                      genetic WF procedure on real data (h4 and d1), matched control, buy & hold, spot-raw check
  null --shard i --n-shards n   day-block permutation null runs j = i, i+n, ... (resumable)
  report                        p-values, DSR and the acceptance verdict -> runs/<run>/report.json
Data: M15 < 2023-11-01 only (selection block and holdout never loaded).
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from sqxf.crypto.data import CryptoConfig, load_spot_m15, read_funding
from sqxf.crypto.market import build_crypto_market, funding_mean_abs, load_hybrid_market
from sqxf.crypto.procedure import buy_and_hold, crypto_folds, matched_control, run_variant, summarize, trade_window
from sqxf.funnel.wf_procedure import block_permute_m15, day_block_mapping
from sqxf.provenance import PROJECT_ROOT, code_version, load_yaml_strict, require_committed
from sqxf.stats.dsr import expected_max_sharpe, moments, probabilistic_sharpe
from sqxf.trials import record_evaluations

PROC_LEDGER = PROJECT_ROOT / "trials" / "crypto_procedure_ledger.jsonl"


def coins(cfg):
    return cfg["universe"]["per_coin"] + cfg["universe"]["aggregate_only"]


def load_all(cfg, freq, dcfg):
    out = {}
    for c in coins(cfg):
        mk, prices, spot = load_hybrid_market(c, cfg["prices"]["perp_from_utc"][c], freq, dcfg)
        out[c] = (mk, prices, spot)
    return out


def observed(cfg, out: Path) -> None:
    target = out / "observed.json"
    if target.exists():
        sys.exit(f"{target} exists: run once per run_name")
    dcfg = CryptoConfig.load()
    result = {"code_version": code_version(), "started_utc": datetime.now(UTC).isoformat(), "variants": {}}
    for vname, v in cfg["variants"].items():
        data = load_all(cfg, v["signal_timeframe"], dcfg)
        markets = {c: d[0] for c, d in data.items()}
        res = run_variant(markets, cfg, v, log=lambda m, vn=vname: print(f"[{vn}] {m}", flush=True))
        record_evaluations(f"crypto C1 genetic ({vname})", "+".join(coins(cfg)), res["evaluated"], selection=True,
                           run=cfg["run_name"])
        summ = summarize(res, cfg)
        ctl = matched_control(markets, res["trades"], cfg, cfg["control_matched_random"]["replicas"],
                              cfg["seed"] + 777)
        bh = buy_and_hold(markets, {c: d[2] for c, d in data.items()}, cfg)
        # report-only: the same selected strategies re-traded on raw (unrepaired) SPOT prices
        spot_raw = []
        for c in coins(cfg):
            raw = load_spot_m15(c, dcfg, repair=False)
            end = raw["ts_local"].max() + pd.Timedelta(minutes=15)
            win_end = pd.Timestamp(dcfg["funding"]["mean_abs_window_end_utc"])
            mk_raw = build_crypto_market(c, raw, dcfg, v["signal_timeframe"], read_funding(c, dcfg, end),
                                         funding_mean_abs(read_funding(c, dcfg, win_end), win_end))
            for fold in crypto_folds(mk_raw, cfg):
                tr, _ = trade_window(mk_raw, res["strategies"][(c, fold["fold"])], fold, c, v["exec_timeframe_oos"])
                if len(tr):
                    spot_raw.append(tr)
        sr = pd.concat(spot_raw) if spot_raw else pd.DataFrame()
        trades = res["trades"]
        out.mkdir(parents=True, exist_ok=True)
        if len(trades):
            trades.drop(columns=["entry_time"]).assign(entry_time=trades["entry_time"].astype(str)).to_csv(
                out / f"trades_{vname}.csv", index=False)
        res["portfolio_daily"].to_csv(out / f"portfolio_{vname}.csv")
        result["variants"][vname] = {
            "summary": summ, "evaluated": res["evaluated"],
            "selected_counts": {f"{c}|{f}": len(h) for (c, f), h in res["selected"].items()},
            "control_pooled_mean_r_x1": ctl["pooled_mean_r_x1"].tolist(), "control_placed_share": ctl["placed_share"],
            "buy_and_hold": bh.to_dict("records"),
            "spot_raw_check": {"trades": int(len(sr)), "mean_r_x1": float(sr["r"].mean()) if len(sr) else None,
                               "mean_r_x2": float(sr["r_x2"].mean()) if len(sr) else None},
            "portfolio_daily": res["portfolio_daily"].tolist()}
        print(f"[{vname}] pooled {summ['pooled']} | portfolio {summ['portfolio']}", flush=True)
    PROC_LEDGER.parent.mkdir(parents=True, exist_ok=True)
    with PROC_LEDGER.open("a") as fh:
        fh.write(json.dumps({"utc": datetime.now(UTC).isoformat(), "run_name": cfg["run_name"],
                             "procedures": list(cfg["variants"]), "independent_series": cfg["effective_trials"]
                             ["independent_series"], "code_version": code_version()}) + "\n")
    result["finished_utc"] = datetime.now(UTC).isoformat()
    target.write_text(json.dumps(result, indent=1, default=str))


def null(cfg, out: Path, shard: int, n_shards: int) -> None:
    dcfg = CryptoConfig.load()
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"null_shard{shard}.jsonl"
    done = {json.loads(x)["j"] for x in path.read_text().splitlines()} if path.exists() else set()
    base = {}
    for c in coins(cfg):
        _, prices, spot = load_hybrid_market(c, cfg["prices"]["perp_from_utc"][c], "4h", dcfg)
        end = prices["ts_local"].max() + pd.Timedelta(minutes=15)
        win_end = pd.Timestamp(dcfg["funding"]["mean_abs_window_end_utc"])
        base[c] = (prices, spot, read_funding(c, dcfg, end), funding_mean_abs(read_funding(c, dcfg, win_end), win_end))
    nc = cfg["null"]
    for j in range(shard, nc["n_permutations"], n_shards):
        if j in done:
            continue
        mapping = day_block_mapping({c: b[0] for c, b in base.items()}, nc["seed_base"] + j)
        perm = {c: block_permute_m15(b[0], mapping) for c, b in base.items()}
        row = {"j": j, "seed": nc["seed_base"] + j, "variants": {}}
        for vname, v in cfg["variants"].items():
            markets = {c: build_crypto_market(c, perm[c], dcfg, v["signal_timeframe"], base[c][2], base[c][3],
                                              liquidity_m15=base[c][1]) for c in coins(cfg)}
            s = summarize(run_variant(markets, cfg, v), cfg)
            row["variants"][vname] = {"pooled": s["pooled"], "portfolio": s["portfolio"],
                                      "by_coin_mean_r_x1": {c: x["mean_r_x1"] for c, x in s["by_coin"].items()}}
        with path.open("a") as fh:
            fh.write(json.dumps(row) + "\n")
        print(f"null {j}: " + ", ".join(f"{v} {row['variants'][v]['pooled']['mean_r_x1']}" for v in row["variants"]),
              flush=True)


def report(cfg, out: Path) -> dict:
    obs = json.loads((out / "observed.json").read_text())
    rows = [json.loads(x) for p in sorted(out.glob("null_shard*.jsonl")) for x in p.read_text().splitlines()]
    rows = sorted({r["j"]: r for r in rows}.values(), key=lambda r: r["j"])
    acc = cfg["acceptance"]
    dpy = cfg["days_per_year"]
    et = cfg["effective_trials"]
    n_dsr = et["n_procedures"] * et["independent_series"]
    rep = {"run_name": cfg["run_name"], "n_null": len(rows), "dsr_n": n_dsr, "variants": {}}

    def fin(x):
        return -math.inf if x is None or (isinstance(x, float) and math.isnan(x)) else x

    for vname, o in obs["variants"].items():
        s = o["summary"]
        g = fin(s["pooled"]["mean_r_x1"])
        nul = np.array([fin(r["variants"][vname]["pooled"]["mean_r_x1"]) for r in rows])
        p_null = (1 + int((nul >= g).sum())) / (1 + len(rows))
        ctl = np.array([fin(x) for x in o["control_pooled_mean_r_x1"]])
        p_ctl = (1 + int((ctl >= g).sum())) / (1 + len(ctl))
        nsr = np.array([r["variants"][vname]["portfolio"]["sharpe"] for r in rows]) / math.sqrt(dpy)
        daily = np.array(o["portfolio_daily"])
        sr, skew, kurt = moments(daily)
        sr0 = expected_max_sharpe(n_dsr, float(np.var(nsr))) if len(rows) > 1 else 0.0
        dsr = probabilistic_sharpe(sr, sr0, len(daily), skew, kurt)
        per_coin = {c: s["by_coin"].get(c, {"trades": 0, "mean_r_x1": None}) for c in cfg["universe"]["per_coin"]}
        coins_ok = sum(1 for x in per_coin.values()
                       if x["trades"] >= acc["per_coin_min_oos_trades"] and fin(x["mean_r_x1"]) > 0)
        win_ok = sum(1 for x in s["by_window"].values() if fin(x.get("mean_r_x1")) > 0)
        checks = {
            "pooled_mean_r_x1_gt": g > acc["pooled_mean_r_x1_gt"],
            "pooled_mean_r_x2_gt": fin(s["pooled"]["mean_r_x2"]) > acc["pooled_mean_r_x2_gt"],
            "pooled_mean_r_x1_excluding_2021_gt": fin(s["excluding_2021"]["mean_r_x1"]) > acc["pooled_mean_r_x1_excluding_2021_gt"],
            "p_value_null_le": p_null <= acc["p_value_null_le"],
            "p_value_matched_control_le": p_ctl <= acc["p_value_matched_control_le"],
            "portfolio_dsr_ge": dsr >= acc["portfolio_dsr_ge"],
            "per_coin_positive_min": coins_ok >= acc["per_coin_positive_x1_min"],
            "windows_positive_min": win_ok >= acc["windows_positive_min"],
        }
        bh = pd.DataFrame(o["buy_and_hold"])
        tg = cfg["too_good"]
        too_good = bool(s["portfolio"]["sharpe"] > tg["max_sharpe"])
        rep["variants"][vname] = {
            "summary": s, "p_value_null": p_null, "p_value_matched_control": p_ctl,
            "null_mean_r_x1": {"mean": float(np.mean(nul)), "p95": float(np.percentile(nul, 95)), "max": float(np.max(nul))}
            if len(rows) else None,
            "control_mean_r_x1": {"mean": float(np.nanmean(ctl)), "p95": float(np.nanpercentile(ctl, 95))},
            "control_placed_share": o["control_placed_share"],
            "portfolio_psr_vs_0": probabilistic_sharpe(sr, 0.0, len(daily), skew, kurt), "portfolio_dsr": dsr,
            "dsr_sr_expected_max_annual": sr0 * math.sqrt(dpy), "per_coin_positive": coins_ok, "windows_positive": win_ok,
            "checks": checks, "has_edge": bool(all(checks.values())), "too_good_flag": too_good,
            "buy_and_hold_by_window_equal_weight": bh.groupby("window")[["spot", "perp"]].mean().to_dict("index"),
            "buy_and_hold_by_coin_mean_window": bh.groupby("coin")[["spot", "perp"]].mean().to_dict("index"),
            "spot_raw_check": o["spot_raw_check"], "evaluated": o["evaluated"]}
    rep["any_variant_has_edge"] = any(v["has_edge"] for v in rep["variants"].values())
    (out / "report.json").write_text(json.dumps(rep, indent=1, default=str))
    return rep


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["observed", "null", "report"])
    ap.add_argument("--config", default=str(PROJECT_ROOT / "configs" / "crypto_c1.yaml"))
    ap.add_argument("--shard", type=int, default=0)
    ap.add_argument("--n-shards", type=int, default=1)
    args = ap.parse_args()
    require_committed(Path(args.config))
    cfg = load_yaml_strict(Path(args.config))
    out = PROJECT_ROOT / "runs" / cfg["run_name"]
    {"observed": lambda: observed(cfg, out), "null": lambda: null(cfg, out, args.shard, args.n_shards),
     "report": lambda: print(json.dumps(report(cfg, out), indent=1, default=str))}[args.mode]()


if __name__ == "__main__":
    main()
