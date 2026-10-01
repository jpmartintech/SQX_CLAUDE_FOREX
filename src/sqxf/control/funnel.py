"""The Phase S Part 2 procedures applied to synthetic worlds, unchanged (thresholds from configs/states_ribbon.yaml).

``predictive_test`` mirrors section (A) of scripts/states_validate.py; ``calibration_run`` mirrors (B)/(C) for the calibration
hypothesis (H4 EMA50/200 + ADX, stop and trailing 3 ATR) including acceptance and DSR.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from sqxf.backtest.evaluator import Costs
from sqxf.states.validate import (
    bars_market,
    block_bootstrap_means,
    calibration_signals,
    daily_series,
    forward_net,
    holm,
    run_signal,
    window_of,
)
from sqxf.stats.dsr import expected_max_sharpe, moments, probabilistic_sharpe


def direction_of_state(k: int) -> int:
    regime, h4 = k // 9 - 1, (k // 3) % 3 - 1
    return regime if regime != 0 else h4


def state_nets(states: dict, pip: float, horizons, window) -> dict:
    bars = states["bars"]["H1"]
    comb = states["combined"]
    reg, h4s = comb["regime"].to_numpy(), comb["h4_slope"].to_numpy()
    d = np.where(reg != 0, reg, h4s)
    in_val = ((bars["ts_local"] >= pd.Timestamp(window[0])) & (bars["ts_local"] < pd.Timestamp(window[1]))).to_numpy()
    out = {}
    for h in horizons:
        net = forward_net(bars, d, h, pip, 1.5)
        net[~in_val] = np.nan
        out[h] = (comb["state"].to_numpy(), net, bars["ts_local"].dt.year.to_numpy())
    return out


def predictive_test(nets_by_pair: dict, primary: str, tested: list[int], horizons, pt_cfg: dict, years: list[int]) -> list[dict]:
    acc, bs = pt_cfg["acceptance"], pt_cfg["bootstrap"]
    replicas = [p for p in nets_by_pair if p != primary]
    rows = []
    for h in horizons:
        state, net, yrs = nets_by_pair[primary][h]
        boot = block_bootstrap_means(state, net, 27, max(5 * h, 120), bs["resamples"], bs["seed"])
        for k in tested:
            m = (state == k) & np.isfinite(net)
            mean = float(net[m].mean()) if m.any() else float("nan")
            col = boot[:, k]
            col = col[np.isfinite(col)]
            p_raw = float((col <= 0).mean()) if len(col) else 1.0
            ypos = sum(1 for y in years if (m & (yrs == y)).any() and net[m & (yrs == y)].mean() > 0)
            rpos = 0
            for q in replicas:
                s2, n2, _ = nets_by_pair[q][h]
                mm = (s2 == k) & np.isfinite(n2)
                rpos += int(mm.any() and n2[mm].mean() > 0)
            rows.append({"state": k, "horizon": h, "n": int(m.sum()), "mean": mean, "p_raw": p_raw,
                         "years_positive": ypos, "replica_positive": rpos})
    adj = holm(np.array([r["p_raw"] for r in rows]))
    for r, a in zip(rows, adj, strict=True):
        r["p_holm"] = float(a)
        r["pass"] = {"holm": bool(a <= acc["holm_p_le"]),
                     "min_mean": bool(np.isfinite(r["mean"]) and r["mean"] >= acc["min_mean_net_pips"]),
                     "stability": bool(r["years_positive"] >= 3), "replica": bool(r["replica_positive"] >= 3)}
        r["predictive"] = bool(all(r["pass"].values()))
    return rows


def calibration_run(m15_by_pair: dict, swap: dict, cal_cfg: dict, acc: dict, window, years: list[int],
                    dsr_n: float, var_sr: float) -> dict:
    """Calibration hypothesis 1 on (synthetic) M15 worlds of several pairs: pooled metrics, acceptance and DSR."""
    trades_all, port, per_pair = [], {}, {}
    for p, m15 in m15_by_pair.items():
        sw = swap["pairs"].get(p, swap["default"])
        mk = bars_market(p, m15, "H4", Costs.for_pair(p), sw["long"], sw["short"])
        w = window_of(mk, *window)
        sig = calibration_signals(mk)
        legs, daily = [], None
        for d in (1, -1):
            t1, _ = run_signal(mk, sig[d], d, cal_cfg["initial_stop_atr"], cal_cfg["max_bars_h4"], cal_cfg["trailing_atr"],
                               sig[f"exit_{d}"], w)
            t2, _ = run_signal(mk, sig[d], d, cal_cfg["initial_stop_atr"], cal_cfg["max_bars_h4"], cal_cfg["trailing_atr"],
                               sig[f"exit_{d}"], w, cost_mult=2.0, swap_mult=2.0)
            ds = daily_series(mk, t1, w)
            daily = ds if daily is None else daily.add(ds, fill_value=0.0)
            if len(t1):
                legs.append(t1.assign(r_x2=t2["r"].to_numpy(), pair=p))
        tr = pd.concat(legs, ignore_index=True) if legs else pd.DataFrame({"r": [], "r_x2": []})
        port[p] = daily
        per_pair[p] = {"trades": int(len(tr)), "mean_r_x1": float(tr["r"].mean()) if len(tr) else None}
        if len(tr):
            trades_all.append(tr)
    t = pd.concat(trades_all, ignore_index=True)
    win, loss = t.loc[t.r > 0, "r"], t.loc[t.r < 0, "r"]
    yr = pd.to_datetime(t["entry_local"]).dt.year
    by_year = {int(y): float(t.loc[yr == y, "r"].mean()) for y in years if (yr == y).any()}
    pf_daily = pd.concat(port, axis=1).fillna(0.0).mean(axis=1).to_numpy()
    sr, skew, kurt = moments(pf_daily)
    dsr = probabilistic_sharpe(sr, expected_max_sharpe(dsr_n, var_sr), len(pf_daily), skew, kurt)
    eq = np.cumprod(1 + pf_daily)
    res = {"trades": int(len(t)), "mean_r_x1": float(t["r"].mean()), "mean_r_x2": float(t["r_x2"].mean()),
           "pf": float(win.sum() / -loss.sum()) if len(loss) else float("inf"),
           "win_rate": float((t.r > 0).mean()), "payoff": float(win.mean() / -loss.mean()) if len(win) and len(loss) else None,
           "pairs_positive": sum(1 for v in per_pair.values()
                                 if v["trades"] >= acc["pair_min_trades"] and (v["mean_r_x1"] or -1) > 0),
           "years_positive": sum(1 for v in by_year.values() if v > 0), "by_year": by_year, "per_pair": per_pair,
           "dsr": dsr, "portfolio_sharpe": sr * math.sqrt(260),
           "max_dd": float((1 - eq / np.maximum.accumulate(np.r_[1.0, eq])[1:]).max())}
    res["checks"] = {"pooled_mean_r_x1_gt": res["mean_r_x1"] > acc["pooled_mean_r_x1_gt"],
                     "pooled_mean_r_x2_gt": res["mean_r_x2"] > acc["pooled_mean_r_x2_gt"],
                     "pooled_profit_factor_ge": res["pf"] >= acc["pooled_profit_factor_ge"],
                     "pairs_positive_min": res["pairs_positive"] >= acc["pairs_positive_min"],
                     "years_positive_min": res["years_positive"] >= acc["years_positive_min"],
                     "pooled_min_trades": res["trades"] >= acc["pooled_min_trades"], "dsr_ge": dsr >= acc["dsr_ge"]}
    res["accepted"] = bool(all(res["checks"].values()))
    return res
