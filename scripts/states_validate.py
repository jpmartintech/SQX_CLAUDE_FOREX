"""Phase S Part 2 — the ONE pre-registered pass on validation 2015-2018: (A) predictive test, (B) calibration hypothesis 1,
(C) rules R1-R4, (D) acceptance and too-good checks. Refuses to run twice or if the pre-registration changed.
Usage: python scripts/states_validate.py
"""
from __future__ import annotations

import json
import math
import subprocess
import sys
from datetime import UTC, datetime

import numpy as np
import pandas as pd

from sqxf.backtest.evaluator import Costs
from sqxf.data.m15 import DataConfig, load_m15
from sqxf.provenance import PROJECT_ROOT, code_version, load_yaml_strict, require_committed
from sqxf.states.pipeline import compute_states
from sqxf.states.validate import (
    bars_market,
    block_bootstrap_means,
    calibration_signals,
    daily_series,
    forward_net,
    holm,
    matched_control,
    rule_signals,
    run_signal,
    window_of,
)
from sqxf.states.wf_guard import truncate_to
from sqxf.stats.dsr import expected_max_sharpe, moments, probabilistic_sharpe
from sqxf.trials import record_evaluations as _record

CONFIG = PROJECT_ROOT / "configs" / "states_ribbon.yaml"
OUT = PROJECT_ROOT / "runs" / "states_ribbon_s1"
PREREG_COMMIT = "1748f2d"
CONTROL_REPLICAS = 200


def direction_of_state(k: int) -> int:
    regime, h4 = k // 9 - 1, (k // 3) % 3 - 1
    return regime if regime != 0 else h4


def main() -> None:
    require_committed(CONFIG)
    if subprocess.run(["git", "diff", "--quiet", PREREG_COMMIT, "HEAD", "--", str(CONFIG.relative_to(PROJECT_ROOT))],
                      cwd=PROJECT_ROOT).returncode != 0:
        sys.exit("BLOQUEADO: configs/states_ribbon.yaml differs from the pre-registration commit")
    if (OUT / "results.json").exists():
        sys.exit("single pass: results already exist")
    cfg = load_yaml_strict(CONFIG)
    swap = load_yaml_strict(PROJECT_ROOT / "configs" / "swap.yaml")
    v0, v1 = cfg["periods"]["validation"]
    pairs = [cfg["pairs"]["primary"], *cfg["pairs"]["replica"]]
    desc = json.loads((PROJECT_ROOT / "docs/reports/states_descriptive.json").read_text())
    usable = desc["pairs"]["EURUSD"]["combined"]["usable_states"]
    tested = [k for k in usable if direction_of_state(k) != 0]
    if len(tested) != 15:
        sys.exit(f"BLOQUEADO: expected 15 tested states, found {len(tested)}")
    eff = json.loads((PROJECT_ROOT / "docs/reports/states_effective_pairs.json").read_text())["n_eff_pairs"]
    pt = cfg["predictive_test"]
    horizons = pt["horizons_h1_bars"]
    OUT.mkdir(parents=True, exist_ok=True)
    started = datetime.now(UTC).isoformat()
    ledger = []

    def record_evaluations(*a, **k):
        ledger.append((a, k))

    data = {}
    for p in pairs:
        m15 = truncate_to(load_m15(p, DataConfig.load()), cfg["periods"]["data_end"])
        assert m15["ts_local"].max() < pd.Timestamp(cfg["periods"]["data_end"])
        costs = Costs.for_pair(p)
        sw = swap["pairs"].get(p, swap["default"])
        st = compute_states(m15, cfg["ribbon"])
        h1 = bars_market(p, m15, "H1", costs, sw["long"], sw["short"])
        h4 = bars_market(p, m15, "H4", costs, sw["long"], sw["short"])
        assert (h1.h1["ts_local"].to_numpy() == st["bars"]["H1"]["ts_local"].to_numpy()).all()
        data[p] = {"m15": m15, "states": st, "H1": h1, "H4": h4, "costs": costs}

    # ------------------------------------------------------------------ (A) predictive test
    pred = {"tested_states": tested, "horizons": horizons, "rows": []}
    nets = {}
    for p in pairs:
        st, bars = data[p]["states"], data[p]["states"]["bars"]["H1"]
        comb = st["combined"]
        reg, h4s = comb["regime"].to_numpy(), comb["h4_slope"].to_numpy()
        d = np.where(reg != 0, reg, h4s)
        in_val = ((bars["ts_local"] >= pd.Timestamp(v0)) & (bars["ts_local"] < pd.Timestamp(v1))).to_numpy()
        for h in horizons:
            net = forward_net(bars, d, h, data[p]["costs"].pip, 1.5)
            net[~in_val] = np.nan
            nets[(p, h)] = (comb["state"].to_numpy(), net, bars["ts_local"].dt.year.to_numpy())
    record_evaluations("states S2 predictive test EURUSD (state x horizon)", "EURUSD", len(tested) * len(horizons),
                       selection=True, run=cfg["run_name"])
    record_evaluations("states S2 predictive replica (same tests, 5 pairs)", "+".join(pairs[1:]),
                       len(tested) * len(horizons) * len(pairs[1:]), selection=False, run=cfg["run_name"])
    bs = pt["bootstrap"]
    rows = []
    for h in horizons:
        state, net, years = nets[("EURUSD", h)]
        boot = block_bootstrap_means(state, net, 27, max(5 * h, 120), bs["resamples"], bs["seed"])
        for k in tested:
            m = (state == k) & np.isfinite(net)
            mean = float(net[m].mean()) if m.any() else float("nan")
            col = boot[:, k]
            col = col[np.isfinite(col)]
            p_raw = float((col <= 0).mean()) if len(col) else 1.0
            yr = {int(y): float(net[m & (years == y)].mean()) if (m & (years == y)).any() else None for y in range(2015, 2019)}
            rep = {}
            for q in pairs[1:]:
                s2, n2, _ = nets[(q, h)]
                mm = (s2 == k) & np.isfinite(n2)
                rep[q] = {"n": int(mm.sum()), "mean": float(n2[mm].mean()) if mm.any() else None}
            rows.append({"state": k, "direction": direction_of_state(k), "horizon": h, "n": int(m.sum()),
                         "mean_net_pips": mean, "p_raw": p_raw, "years": yr, "replica": rep})
    adj = holm(np.array([r["p_raw"] for r in rows]))
    acc = pt["acceptance"]
    for r, a in zip(rows, adj, strict=True):
        r["p_holm"] = float(a)
        r["years_positive"] = sum(1 for v in r["years"].values() if v is not None and v > 0)
        r["replica_positive"] = sum(1 for v in r["replica"].values() if v["mean"] is not None and v["mean"] > 0)
        r["pass"] = {"holm": a <= acc["holm_p_le"], "min_mean": (r["mean_net_pips"] or -1e9) >= acc["min_mean_net_pips"],
                     "stability": r["years_positive"] >= 3, "replica": r["replica_positive"] >= 3}
        r["predictive"] = all(r["pass"].values())
    pred["rows"] = rows
    pred["n_predictive"] = sum(r["predictive"] for r in rows)

    # ------------------------------------------------------------------ (B, C) strategies
    rules = cfg["rules"]
    specs = {"CAL1_H4_EMA50_200_ADX": {"tf": "H4", "sl": cfg["calibration_hypothesis_1"]["initial_stop_atr"],
                                       "trail": cfg["calibration_hypothesis_1"]["trailing_atr"],
                                       "max_bars": cfg["calibration_hypothesis_1"]["max_bars_h4"]}}
    for name in ("R1_trend_continuation", "R2_pullback_end", "R3_compression_release", "R4_regime_change"):
        specs[name] = {"tf": "H1", "sl": rules[name]["safety_stop_atr"], "trail": rules[name].get("trailing_atr", 0.0),
                       "max_bars": rules["common"]["max_bars_h1"]}
    strat = {}
    sr_all = []
    for name, sp in specs.items():
        per_pair, trades_all, port = {}, [], {}
        ctl_sum = np.zeros(CONTROL_REPLICAS)
        ctl_w = 0.0
        for p in pairs:
            mk = data[p][sp["tf"]]
            w = window_of(mk, v0, v1)
            if name.startswith("CAL1"):
                sig = calibration_signals(mk)
            else:
                st = data[p]["states"]
                sig = rule_signals(st["combined"], st["aligned"]["H4"], name)
            legs1, daily = [], None
            for d in (1, -1):
                t1, _ = run_signal(mk, sig[d], d, sp["sl"], sp["max_bars"], sp["trail"], sig[f"exit_{d}"], w)
                t2, _ = run_signal(mk, sig[d], d, sp["sl"], sp["max_bars"], sp["trail"], sig[f"exit_{d}"], w,
                                   cost_mult=2.0, swap_mult=2.0)
                ds = daily_series(mk, t1, w)
                daily = ds if daily is None else daily.add(ds, fill_value=0.0)
                if len(t1):
                    t1 = t1.assign(r_x2=t2["r"].to_numpy(), pair=p)
                    legs1.append(t1)
                    c = matched_control(mk, t1, w, CONTROL_REPLICAS, seed=20261002 + 7 * d + len(per_pair))
                    ctl_sum += np.nan_to_num(c) * len(t1)
                    ctl_w += len(t1)
            tr = pd.concat(legs1, ignore_index=True) if legs1 else pd.DataFrame()
            port[p] = daily
            mom = moments(daily.to_numpy())
            sr_all.append(mom[0])
            eq = np.cumprod(1 + daily.to_numpy())
            dd = float((1 - eq / np.maximum.accumulate(np.r_[1.0, eq])[1:]).max())
            per_pair[p] = {"trades": int(len(tr)), "mean_r_x1": float(tr["r"].mean()) if len(tr) else None,
                           "mean_r_x2": float(tr["r_x2"].mean()) if len(tr) else None,
                           "pf": float(tr.loc[tr.r > 0, "r"].sum() / -tr.loc[tr.r < 0, "r"].sum()) if len(tr) and (tr.r < 0).any() else None,
                           "max_dd": dd, "sharpe": mom[0] * math.sqrt(260), "mean_pips": float(tr["pips"].mean()) if len(tr) else None}
            if len(tr):
                trades_all.append(tr)
        t = pd.concat(trades_all, ignore_index=True) if trades_all else pd.DataFrame(
            {c: pd.Series(dtype=float) for c in ("r", "r_x2", "pips", "direction")}
            | {"reason": pd.Series(dtype=str), "pair": pd.Series(dtype=str), "entry_local": pd.Series(dtype="datetime64[ns]")})
        pf_daily = pd.concat(port, axis=1).fillna(0.0).mean(axis=1)
        eq = np.cumprod(1 + pf_daily.to_numpy())
        record_evaluations(f"states S2 strategy {name}", "+".join(pairs), len(pairs), selection=True, run=cfg["run_name"])
        if len(t) and "entry_time" in t:
            t.drop(columns=["entry_time", "exit_bar_time"]).to_csv(OUT / f"trades_{name}.csv", index=False)
        win, loss = t.loc[t.r > 0, "r"], t.loc[t.r < 0, "r"]
        by_year = t.groupby(pd.to_datetime(t["entry_local"]).dt.year)["r"].mean() if len(t) else pd.Series(dtype=float)
        strat[name] = {
            "spec": sp, "trades": int(len(t)), "mean_r_x1": float(t["r"].mean()) if len(t) else None,
            "mean_r_x2": float(t["r_x2"].mean()) if len(t) else None,
            "pf": float(win.sum() / -loss.sum()) if len(loss) else None,
            "win_rate": float((t.r > 0).mean()) if len(t) else None,
            "payoff": float(win.mean() / -loss.mean()) if len(win) and len(loss) else None,
            "mean_pips": float(t["pips"].mean()) if len(t) else None,
            "exit_reasons": t["reason"].value_counts(normalize=True).to_dict() if len(t) else {},
            "by_direction": {int(d): {"trades": int((t.direction == d).sum()), "mean_r_x1": float(t.loc[t.direction == d, "r"].mean())
                                      if (t.direction == d).any() else None} for d in (1, -1)} if len(t) else {},
            "by_year": {int(k): float(v) for k, v in by_year.items()},
            "per_pair": per_pair,
            "portfolio": {"sharpe": float(pf_daily.mean() / pf_daily.std(ddof=0) * math.sqrt(260)) if pf_daily.std(ddof=0) > 0 else 0.0,
                          "return": float(eq[-1] - 1), "max_dd": float((1 - eq / np.maximum.accumulate(np.r_[1.0, eq])[1:]).max()),
                          "daily": pf_daily.to_numpy().tolist()},
            "control_pooled_mean_r_x1": (ctl_sum / ctl_w).tolist() if ctl_w else None,
        }
        if name.startswith("CAL1"):
            e = t[t.pair == "EURUSD"]
            ew, el = e.loc[e.r > 0, "r"], e.loc[e.r < 0, "r"]
            strat[name]["signature_eurusd"] = {
                "trades": int(len(e)), "win_rate": float((e.r > 0).mean()) if len(e) else None,
                "payoff": float(ew.mean() / -el.mean()) if len(ew) and len(el) else None,
                "trail_or_signal_share": float(e["reason"].isin(["TRAIL", "SIGNAL"]).mean()) if len(e) else None,
                "exit_reasons": e["reason"].value_counts().to_dict()}
    # ------------------------------------------------------------------ (D) acceptance
    var_sr = float(np.var(sr_all))
    n_dsr = cfg["trials"]["strategies"] * eff
    a = cfg["acceptance_strategies"]
    tg = cfg["too_good"]
    for s in strat.values():
        daily = np.array(s["portfolio"]["daily"])
        sr, skew, kurt = moments(daily)
        sr0 = expected_max_sharpe(n_dsr, var_sr)
        s["dsr"] = probabilistic_sharpe(sr, sr0, len(daily), skew, kurt)
        s["dsr_sr_expected_max_annual"] = sr0 * math.sqrt(260)
        pos_pairs = sum(1 for v in s["per_pair"].values() if v["trades"] >= a["pair_min_trades"] and (v["mean_r_x1"] or -1) > 0)
        pos_years = sum(1 for v in s["by_year"].values() if v > 0)
        ctl = np.array(s["control_pooled_mean_r_x1"] or [np.nan])
        s["control_p"] = float((1 + np.sum(ctl >= (s["mean_r_x1"] or -1e9))) / (1 + len(ctl)))
        s["checks"] = {"pooled_mean_r_x1_gt": (s["mean_r_x1"] or -1) > a["pooled_mean_r_x1_gt"],
                       "pooled_mean_r_x2_gt": (s["mean_r_x2"] or -1) > a["pooled_mean_r_x2_gt"],
                       "pooled_profit_factor_ge": (s["pf"] or 0) >= a["pooled_profit_factor_ge"],
                       "pairs_positive_min": pos_pairs >= a["pairs_positive_min"],
                       "years_positive_min": pos_years >= a["years_positive_min"],
                       "pooled_min_trades": s["trades"] >= a["pooled_min_trades"],
                       "dsr_ge": s["dsr"] >= a["dsr_ge"]}
        s["pairs_positive"], s["years_positive"] = pos_pairs, pos_years
        s["accepted"] = all(s["checks"].values())
        flags = []
        if (s["pf"] or 0) > tg["max_profit_factor"] and s["trades"] >= tg["min_trades_for_pf_check"]:
            flags.append("pooled_pf")
        if s["portfolio"]["sharpe"] > tg["max_sharpe"]:
            flags.append("portfolio_sharpe")
        for p, v in s["per_pair"].items():
            if (v["pf"] or 0) > tg["max_profit_factor"] and v["trades"] >= tg["min_trades_for_pf_check"]:
                flags.append(f"pf_{p}")
            if v["sharpe"] > tg["max_sharpe"]:
                flags.append(f"sharpe_{p}")
        s["too_good_flags"] = flags
    cal = cfg["calibration_hypothesis_1"]["expected_signature"]
    sg = strat["CAL1_H4_EMA50_200_ADX"]["signature_eurusd"]
    sig_checks = {"win_rate_between": sg["win_rate"] is not None and cal["win_rate_between"][0] <= sg["win_rate"] <= cal["win_rate_between"][1],
                  "payoff_ratio_min": (sg["payoff"] or 0) >= cal["payoff_ratio_min"],
                  "min_trades_eurusd": sg["trades"] >= cal["min_trades_eurusd"],
                  "trail_or_signal_exit_share_min": (sg["trail_or_signal_share"] or 0) >= cal["trail_or_signal_exit_share_min"]}
    res = {"run_name": cfg["run_name"], "code_version": code_version(), "started_utc": started,
           "finished_utc": datetime.now(UTC).isoformat(), "validation": [v0, v1], "n_eff_pairs": eff, "dsr_n": n_dsr,
           "dsr_var_sr_daily": var_sr, "control_replicas": CONTROL_REPLICAS, "predictive": pred, "strategies": strat,
           "calibration_signature_checks": sig_checks}
    (OUT / "results.json").write_text(json.dumps(res, indent=1, default=str))
    for a_, k_ in ledger:  # only after the single pass completed
        _record(*a_, **k_)
    print(json.dumps({"n_predictive": pred["n_predictive"], "signature": sig_checks,
                      "strategies": {k: {"accepted": v["accepted"], "checks": v["checks"], "too_good": v["too_good_flags"]}
                                     for k, v in strat.items()}}, indent=1, default=str))


if __name__ == "__main__":
    main()
