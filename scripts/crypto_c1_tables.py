"""Print the Phase C1 report.json as compact markdown tables (used to write docs/reports/phase-c1.md)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def f(x, nd=4, pct=False):
    if x is None:
        return "—"
    return f"{x:+.{nd}%}" if pct else f"{x:+.{nd}f}"


def main() -> None:
    run = sys.argv[1] if len(sys.argv) > 1 else "crypto_c1_wf_r2"
    rep = json.loads((ROOT / "runs" / run / "report.json").read_text())
    print(f"n_null={rep['n_null']} dsr_n={rep['dsr_n']} any_edge={rep['any_variant_has_edge']}\n")
    for v, x in rep["variants"].items():
        s = x["summary"]
        print(f"## {v}: has_edge={x['has_edge']} too_good={x['too_good_flag']} evaluated={x['evaluated']}")
        print("| check | ok |\n|---|---|")
        for k, ok in x["checks"].items():
            print(f"| {k} | {'yes' if ok else 'NO'} |")
        p = s["pooled"]
        print(f"\npooled trades {p['trades']} mean R x1 {f(p['mean_r_x1'])} x2 {f(p['mean_r_x2'])} t {p.get('t_x1')} "
              f"win {p.get('win_rate')} funding R/trade {p.get('mean_funding_r')}")
        print(f"excl 2021: {s['excluding_2021']}")
        print(f"p_null {x['p_value_null']:.4f} null {x['null_mean_r_x1']} | p_ctl {x['p_value_matched_control']:.4f} "
              f"ctl {x['control_mean_r_x1']} placed {x['control_placed_share']:.3f}")
        print(f"portfolio {s['portfolio']} PSR {x['portfolio_psr_vs_0']:.3f} DSR {x['portfolio_dsr']:.3f} "
              f"SR* {x['dsr_sr_expected_max_annual']:.2f} | per-coin ok {x['per_coin_positive']} windows ok {x['windows_positive']}")
        print("\n| moneda | trades | mean R x1 | mean R x2 | t |\n|---|---:|---:|---:|---:|")
        for c, y in s["by_coin"].items():
            print(f"| {c} | {y['trades']} | {f(y['mean_r_x1'])} | {f(y['mean_r_x2'])} | {f(y.get('t_x1'), 2)} |")
        print("\n| ventana | trades | mean R x1 | mean R x2 | B&H spot (8 monedas) | B&H perp |\n|---|---:|---:|---:|---:|---:|")
        bh = x["buy_and_hold_by_window_equal_weight"]
        for w, y in s["by_window"].items():
            b = bh.get(w, {})
            print(f"| {w} | {y['trades']} | {f(y['mean_r_x1'])} | {f(y['mean_r_x2'])} | {f(b.get('spot'), 1, True)} | "
                  f"{f(b.get('perp'), 1, True)} |")
        print("\n| sentido | trades | mean R x1 | mean R x2 | funding R/trade |\n|---|---:|---:|---:|---:|")
        for d, y in s["by_direction"].items():
            print(f"| {d} | {y['trades']} | {f(y['mean_r_x1'])} | {f(y['mean_r_x2'])} | {f(y.get('mean_funding_r'))} |")
        print("\nB&H by coin (mean per window):", {c: {k: round(vv, 3) for k, vv in y.items()}
                                                 for c, y in x["buy_and_hold_by_coin_mean_window"].items()})
        print("spot raw check:", x["spot_raw_check"], "\n")


if __name__ == "__main__":
    main()
