"""Phase S descriptive run (development period only; NO returns are read): per-timeframe and combined state statistics and
the pre-registered persistence criteria. Writes docs/reports/states_descriptive.json and prints a summary.
Usage: python scripts/states_describe.py
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from sqxf.data.m15 import DataConfig, load_m15
from sqxf.provenance import PROJECT_ROOT, code_version, load_yaml_strict, require_committed
from sqxf.states.pipeline import compute_states, describe
from sqxf.states.wf_guard import truncate_to

CONFIG = PROJECT_ROOT / "configs" / "states_ribbon.yaml"


def main() -> None:
    require_committed(CONFIG)
    cfg = load_yaml_strict(CONFIG)
    dev0, dev1 = (pd.Timestamp(x) for x in cfg["periods"]["development"])
    per = cfg["descriptive"]["persistence"]
    out = {"code_version": code_version(), "run_name": cfg["run_name"], "period": [str(dev0), str(dev1)], "pairs": {}}
    pairs = [cfg["pairs"]["primary"], *cfg["pairs"]["replica"]]
    for pair in pairs:
        m15 = truncate_to(load_m15(pair, DataConfig.load()), cfg["periods"]["data_end"])
        st = compute_states(m15, cfg["ribbon"])
        res = {"per_tf": {}}
        for tf, bars in st["bars"].items():
            m = ((bars["ts_local"] >= dev0) & (bars["ts_local"] < dev1)).to_numpy()
            d = describe(st["desc"][tf]["state"].to_numpy()[m])
            big = [k for k, f in d["fraction"].items() if f >= 0.01]
            res["per_tf"][tf] = {**{k: d[k] for k in ("valid_bars", "fraction", "mean_duration", "changes_per_100_bars")},
                                 "min_mean_duration_states_ge_1pct": min(d["mean_duration"][k] for k in big),
                                 "pass_duration": all(d["mean_duration"][k] >= per["per_timeframe_min_mean_duration_bars"]
                                                      for k in big),
                                 "pass_changes": d["changes_per_100_bars"] <= per["per_timeframe_max_changes_per_100_bars"],
                                 "levels": {c: st["desc"][tf][c].to_numpy()[m][~np.isnan(st["desc"][tf][c].to_numpy()[m])]
                                            .tolist().count(1.0) / max(1, int((~np.isnan(st["desc"][tf][c].to_numpy()[m])).sum()))
                                            for c in ("order", "slope_dir")}}
        base = st["bars"]["H1"]
        m = ((base["ts_local"] >= dev0) & (base["ts_local"] < dev1)).to_numpy()
        d = describe(st["combined"]["state"].to_numpy()[m])
        usable = sorted(k for k in d["fraction"] if d["fraction"][k] >= per["combined_usable_min_fraction"]
                        and d["mean_duration"][k] >= per["combined_usable_min_mean_duration_h1"])
        res["combined"] = {**d, "usable_states": usable, "usable_time_share": float(sum(d["fraction"][k] for k in usable)),
                           "pass_system_changes": d["changes_per_100_bars"] <= per["combined_max_changes_per_100_h1"],
                           "regime_fraction": {str(int(k)): float(v) for k, v in pd.Series(
                               st["combined"]["regime"].to_numpy()[m]).value_counts(normalize=True).items()}}
        out["pairs"][pair] = res
        c = res["combined"]
        print(f"{pair}: combined valid {c['valid_bars']} changes/100 {c['changes_per_100_bars']:.2f} "
              f"(pass {c['pass_system_changes']}) usable {len(c['usable_states'])} states covering {c['usable_time_share']:.1%} "
              f"| regime {c['regime_fraction']}")
        for tf, r in res["per_tf"].items():
            print(f"   {tf}: valid {r['valid_bars']} changes/100 {r['changes_per_100_bars']:.2f} (pass {r['pass_changes']}) "
                  f"min mean dur (states>=1%) {r['min_mean_duration_states_ge_1pct']:.2f} (pass {r['pass_duration']}) "
                  f"share bull order {r['levels']['order']:.2f} up slope {r['levels']['slope_dir']:.2f}")
    Path(PROJECT_ROOT / "docs/reports/states_descriptive.json").write_text(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
