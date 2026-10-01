"""Positive control, Part A: gross R / costs / swap decomposition of the saved Part 2 trades (no re-evaluation).
Usage: python scripts/control_part_a.py  -> docs/reports/positive_control_part_a.json + figure
"""
from __future__ import annotations

import json

import matplotlib
import numpy as np
import pandas as pd

from sqxf.backtest.evaluator import Costs
from sqxf.data.m15 import load_m15_period
from sqxf.provenance import PROJECT_ROOT, load_yaml_strict

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

CFG = load_yaml_strict(PROJECT_ROOT / "configs" / "positive_control.yaml")
RUN = PROJECT_ROOT / "runs" / "states_ribbon_s1"


def main() -> None:
    pairs = CFG["source_data"]["pairs"]
    midnight_cum = {}
    for p in pairs:  # timestamps only, up to the Part 2 data end (same index as the Part 2 M15 frames)
        ts = load_m15_period(p, None, "2019-01-01")["ts_local"]
        midnight_cum[p] = np.cumsum(((ts.dt.hour == 0) & (ts.dt.minute == 0)).to_numpy())
    out = {}
    for name in CFG["part_A"]["strategies"]:
        t = pd.read_csv(RUN / f"trades_{name}.csv")
        rows = {}
        for key, g in [("ALL", t), *list(t.groupby("pair"))]:
            pip = np.array([Costs.for_pair(p).pip for p in g["pair"]])
            cost = np.array([Costs.for_pair(p).round_trip for p in g["pair"]])
            gross = g["direction"] * (g["exit_price"] - g["entry_price"]) / g["risk"]
            after_cost = gross - cost / g["risk"]
            swap_r = g["funding"] / g["risk"]
            recon = after_cost + swap_r
            cal_nights = np.array([midnight_cum[p][x] - midnight_cum[p][e] for p, e, x in
                                   zip(g["pair"], g["entry_exec"], g["exit_exec"], strict=True)])
            rows[key] = {"trades": int(len(g)), "gross_r": float(gross.mean()), "after_costs_r": float(after_cost.mean()),
                         "after_swap_r": float(g["r"].mean()), "reconstruction_max_abs_err": float((recon - g["r"]).abs().max()),
                         "cost_r": float((cost / g["risk"]).mean()), "swap_r": float(swap_r.mean()),
                         "swap_pips_per_trade": float((-g["funding"] / pip).mean()),
                         "charged_nights_per_trade": float((-g["funding"] / pip / 1.0).mean()),
                         "calendar_rollovers_per_trade": float(cal_nights.mean()),
                         "gross_pips": float((gross * g["risk"] / pip).mean()),
                         "gross_positive": bool(gross.mean() > 0), "after_costs_positive": bool(after_cost.mean() > 0)}
        out[name] = rows
        a = rows["ALL"]
        print(f"{name}: n {a['trades']} gross {a['gross_r']:+.3f} | -cost {a['cost_r']:.3f} -> {a['after_costs_r']:+.3f} | "
              f"swap {a['swap_r']:+.3f} -> {a['after_swap_r']:+.3f} (recon err {a['reconstruction_max_abs_err']:.1e}) | "
              f"swap pips {a['swap_pips_per_trade']:.2f} charged nights {a['charged_nights_per_trade']:.2f} "
              f"rollovers {a['calendar_rollovers_per_trade']:.2f}")
    (PROJECT_ROOT / "docs/reports/positive_control_part_a.json").write_text(json.dumps(out, indent=1))
    plt.style.use("dark_background")
    fig, ax = plt.subplots(figsize=(9, 4.5))
    names = list(out)
    x = np.arange(len(names))
    for i, (lab, key) in enumerate([("R bruto", "gross_r"), ("tras costes", "after_costs_r"), ("tras swap", "after_swap_r")]):
        ax.bar(x + (i - 1) * 0.27, [out[n]["ALL"][key] for n in names], 0.27, label=lab)
    ax.axhline(0, color="white", lw=0.8)
    ax.set_xticks(x, [n.split("_")[0] for n in names])
    ax.set_ylabel("R medio por trade (6 pares, 2015-2018)")
    ax.set_title("Parte 2: descomposición R bruto / costes / swap")
    ax.legend()
    fig.tight_layout()
    fig.savefig(PROJECT_ROOT / "docs/reports/figures/pc_part_a_decomposition.png", dpi=120)


if __name__ == "__main__":
    main()
