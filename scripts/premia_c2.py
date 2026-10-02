"""Phase C2 — structural premia, 5 pre-registered hypotheses (configs/premia_c2.yaml).

  panels   data sanity only (coverage, eligibility, missing days, funding): no strategy return is computed
  run      the SINGLE pass: 5 hypotheses x1 / x2, block bootstrap, subperiods, years, matched random control, ledger
  report   figures (dark theme) from runs/premia_c2_r1
"""
from __future__ import annotations

import argparse
import json
import sys

import matplotlib
import numpy as np
import pandas as pd

from sqxf.premia.build import crypto_hypothesis, crypto_panel, forex_hypothesis, forex_panel
from sqxf.premia.engine import bootstrap_stats, max_drawdown, simulate, spell_flips
from sqxf.provenance import PROJECT_ROOT, code_version, load_yaml_strict, require_committed
from sqxf.trials import record_evaluations

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

CONFIG = PROJECT_ROOT / "configs" / "premia_c2.yaml"
C1 = PROJECT_ROOT / "configs" / "crypto_c1.yaml"
FIG = PROJECT_ROOT / "docs" / "reports" / "figures"
HYPS = ["H1_funding_carry", "H2_funding_extreme_xs", "H3_tsmom_crypto", "H4_xsmom_crypto", "H5_tsmom_forex"]


def setup():
    require_committed(CONFIG)
    c2 = load_yaml_strict(CONFIG)
    return c2, load_yaml_strict(C1), PROJECT_ROOT / "runs" / c2["run_name"]


def panels():
    c2, c1, _ = setup()
    cp = crypto_panel(c2, c1)
    w0, w1 = (pd.Timestamp(x) for x in c2["evaluation_windows"]["crypto"])
    m = (cp["cal"] >= w0) & (cp["cal"] < w1)
    print("crypto calendar", cp["cal"][0].date(), "->", cp["cal"][-1].date(), "window days", int(m.sum()))
    for j, c in enumerate(cp["coins"]):
        e = cp["eligible"][m, j]
        first = cp["cal"][m][e][0].date() if e.any() else None
        print(f"  {c}: eligible {e.mean():.2f} of window (first {first}), missing {cp['missing'][c]}, "
              f"funding days>0 {(cp['funding'][m, j] != 0).mean():.2f}, mean slip {cp['slip'][m, j][e].mean() if e.any() else 0:.5f}")
    n_el = cp["eligible"][m].sum(axis=1)
    print("  eligible coins per day: min", n_el.min(), "median", np.median(n_el), "max", n_el.max())
    fp = forex_panel(c2)
    w0, w1 = (pd.Timestamp(x) for x in c2["evaluation_windows"]["forex"])
    m = (fp["cal"] >= w0) & (fp["cal"] < w1)
    print("forex calendar", fp["cal"][0].date(), "->", fp["cal"][-1].date(), "window days", int(m.sum()),
          "missing", fp["missing"], "eligible share", fp["eligible"][m].mean(axis=0).round(3).tolist())


def window_mask(cal, w):
    return np.asarray((cal >= pd.Timestamp(w[0])) & (cal < pd.Timestamp(w[1])))


def summarise(x: np.ndarray, cal: pd.DatetimeIndex, per_year: float, st: dict, seed: int) -> dict:
    b = bootstrap_stats(x, st["block_days"], st["resamples"], seed, per_year)
    pos, neg = x[x > 0].sum(), -x[x < 0].sum()
    years = {}
    for y in sorted(set(cal.year)):
        r = x[cal.year == y]
        years[int(y)] = {"return": float(np.prod(1 + r) - 1), "sharpe": float(r.mean() / r.std(ddof=1) * np.sqrt(per_year))
                         if r.std() > 0 else 0.0, "max_dd": max_drawdown(r), "days": int(len(r))}
    thirds = np.array_split(np.arange(len(x)), 3)
    sub = [{"start": str(cal[t[0]].date()), "end": str(cal[t[-1]].date()), "mean": float(x[t].mean()),
            "sharpe": float(x[t].mean() / x[t].std(ddof=1) * np.sqrt(per_year))} for t in thirds]
    n_years = len(x) / per_year
    return {**b, "cagr": float(np.prod(1 + x) ** (1 / n_years) - 1), "vol_ann": float(x.std(ddof=1) * np.sqrt(per_year)),
            "max_dd": max_drawdown(x), "pf_daily": float(pos / neg) if neg > 0 else float("inf"), "years": years,
            "subperiods": sub, "per_year": per_year}


def run():
    c2, c1, out = setup()
    if (out / "results.json").exists():
        sys.exit("results.json exists: C2 is a single pass (no relaunch)")
    out.mkdir(parents=True, exist_ok=True)
    st, acc, seed = c2["statistics"]["bootstrap"], c2["acceptance"], c2["seed"]
    fees = {"perp": c2["costs"]["perp_fee_per_side"], "spot": c2["costs"]["spot_fee_per_side"]}
    cp, fp = crypto_panel(c2, c1), forex_panel(c2)
    res = {"run_name": c2["run_name"], "code_version": code_version(), "seed": seed, "hypotheses": {}}
    daily = {}
    for hi, name in enumerate(HYPS):
        if name == "H5_tsmom_forex":
            w, cal = c2["evaluation_windows"]["forex"], fp["cal"]
            a = forex_hypothesis(fp, w[0])
        else:
            w, cal = c2["evaluation_windows"]["crypto"], cp["cal"]
            a = crypto_hypothesis(cp, name, fees, w[0])
        m = window_mask(cal, w)
        per_year = 365.0 if name != "H5_tsmom_forex" else m.sum() / ((pd.Timestamp(w[1]) - pd.Timestamp(w[0])).days / 365.25)
        args = (a["ret"], a["c_lin"], a["c_abs"], a["cost"], a["targets"])
        x1, x2 = simulate(*args), simulate(*args, cost_mult=2.0, pay_mult=2.0)
        s1 = summarise(x1["ret"][m], cal[m], per_year, st, seed + hi)
        s2 = summarise(x2["ret"][m], cal[m], per_year, st, seed + 100 + hi)
        reb = ~np.isnan(a["targets"]).all(axis=1) & m
        npos = (np.abs(np.nan_to_num(a["targets"][reb])) > 0).sum(axis=1)
        ctl = []
        for r in range(c2["control_matched_random"]["replicas"]):
            tg = spell_flips(a["targets"], a["groups"], np.random.default_rng(seed + 10_000 * (hi + 1) + r))
            xr = simulate(a["ret"], a["c_lin"], a["c_abs"], a["cost"], tg)["ret"][m]
            ctl.append(float(xr.mean() / xr.std(ddof=1) * np.sqrt(per_year)) if xr.std() > 0 else 0.0)
        ctl = np.array(ctl)
        verdict = {"p_value": s1["p_one_sided"] <= acc["p_value_one_sided_le"],
                   "subperiods": sum(sp["mean"] > 0 for sp in s1["subperiods"]) >= acc["positive_subperiods_min"],
                   "stress_x2": s2["mean"] > acc["stress_x2_mean_gt"]}
        too_good = s1["sharpe"] > c2["too_good"]["max_sharpe"] or s1["pf_daily"] > c2["too_good"]["max_profit_factor_daily"]
        res["hypotheses"][name] = {
            "window": w, "x1": s1, "x2": s2, "passes": bool(all(verdict.values())), "criteria": verdict, "too_good": too_good,
            "exposure": {"mean_gross": float(x1["gross"][m].mean()), "mean_positions_at_rebalance": float(npos.mean()),
                         "rebalances": int(reb.sum()), "turnover_per_year": float(x1["turnover"][m].sum() / (m.sum() / per_year))},
            "components_sum": {k: float(x1[k][m].sum()) for k in ("price", "carry", "cost")},
            "control": {"sharpe_mean": float(ctl.mean()), "sharpe_p95": float(np.percentile(ctl, 95)),
                        "observed_percentile": float((ctl < s1["sharpe"]).mean()),
                        "p_value": float((1 + (ctl >= s1["sharpe"]).sum()) / (1 + len(ctl))), "sharpes": ctl.tolist()}}
        daily[name] = pd.Series(x1["ret"][m], index=cal[m])
        daily[name + "_x2"] = pd.Series(x2["ret"][m], index=cal[m])
        pair = "+".join(c2["data"]["forex_pairs"] if name == "H5_tsmom_forex" else c2["data"]["crypto_universe"])
        record_evaluations(f"C2 premia {name} (pre-registered hypothesis)", pair, 1, selection=True, run=c2["run_name"])
        record_evaluations(f"C2 premia {name} costs/funding x2 stress", pair, 1, selection=False, run=c2["run_name"])
        record_evaluations(f"C2 premia {name} matched random control", pair, len(ctl), selection=False, run=c2["run_name"])
        print(f"{name}: Sharpe {s1['sharpe']:.2f} p {s1['p_one_sided']:.4f} x2 mean {s2['mean']:.2e} subp "
              f"{[round(sp['mean'] * 1e4, 2) for sp in s1['subperiods']]} maxDD {s1['max_dd']:.3f} passes {res['hypotheses'][name]['passes']}"
              f"{' TOO GOOD' if too_good else ''}", flush=True)
    # effective number of series (PCA participation ratio, pairwise-complete correlations)
    def pr(df):
        lam = np.clip(np.linalg.eigvalsh(df.corr().to_numpy()), 0, None)
        return float(lam.sum() ** 2 / (lam ** 2).sum())
    mc = window_mask(cp["cal"], c2["evaluation_windows"]["crypto"])
    coins = pd.DataFrame(np.where(cp["eligible"], cp["ret_perp"], np.nan)[mc], columns=cp["coins"])
    mf = window_mask(fp["cal"], c2["evaluation_windows"]["forex"])
    fx = pd.DataFrame(fp["ret"][mf], columns=fp["pairs"])
    hyp = pd.DataFrame({h: daily[h] for h in HYPS[:4]})
    res["effective_series"] = {"crypto_coins": pr(coins), "forex_pairs": pr(fx), "crypto_hypotheses_H1_H4": pr(hyp),
                               "hypothesis_correlation_H1_H4": hyp.corr().round(3).to_dict()}
    passing = [h for h in HYPS if res["hypotheses"][h]["passes"]]
    res["passing"] = passing
    if len(passing) >= 2:
        df = pd.DataFrame({h: daily[h] for h in passing}).dropna()
        scaled = df / df.std() * df.std().mean()
        naive = scaled.mean(axis=1).to_numpy()
        res["final_step"] = {"correlation": df.corr().round(3).to_dict(), "naive_equal_risk": summarise(
            naive, df.index, 365.0, st, seed + 999) if len(df) else None}
    res["missing_days"] = {"crypto": cp["missing"], "forex": fp["missing"]}
    pd.DataFrame(daily).to_csv(out / "daily_returns.csv")
    (out / "results.json").write_text(json.dumps(res, indent=1, default=float))
    print("passing:", passing)


def report():
    c2, _, out = setup()
    res = json.loads((out / "results.json").read_text())
    daily = pd.read_csv(out / "daily_returns.csv", index_col=0, parse_dates=True)
    plt.style.use("dark_background")
    fig, ax = plt.subplots(2, 2, figsize=(13, 8))
    for h in HYPS:
        s = daily[h].dropna()
        k = 1 if h == "H5_tsmom_forex" else 0
        eq = (1 + s).cumprod()
        ax[0, k].plot(eq.index, eq, label=h)
        ax[1, k].plot(eq.index, (eq / eq.cummax() - 1) * 100, label=h)
        s2 = daily[h + "_x2"].dropna()
        ax[0, k].plot(s2.index, (1 + s2).cumprod(), ls=":", lw=0.8, color=ax[0, k].lines[-1].get_color())
    ax[0, 0].set_title("Cripto 2019-09 → 2023-10: equity (línea continua x1, punteada x2)")
    ax[0, 1].set_title("Forex 2004 → 2018: H5 equity")
    for a in ax[0]:
        a.set_yscale("log")
        a.legend(fontsize=7)
    for a in ax[1]:
        a.set_ylabel("drawdown % del capital")
    fig.tight_layout()
    fig.savefig(FIG / "c2_equity_drawdown.png", dpi=120)
    fig, ax = plt.subplots(1, 5, figsize=(16, 3.6))
    for a, h in zip(ax, HYPS, strict=True):
        r = res["hypotheses"][h]
        a.hist(r["control"]["sharpes"], bins=25, color="tab:cyan")
        a.axvline(r["x1"]["sharpe"], color="tab:orange", label="observado")
        a.set_title(f"{h.split('_')[0]}: pct {r['control']['observed_percentile']:.2f}", fontsize=9)
        a.set_xlabel("Sharpe del control")
    ax[0].legend(fontsize=7)
    fig.tight_layout()
    fig.savefig(FIG / "c2_control.png", dpi=120)
    fig, ax = plt.subplots(figsize=(13, 4))
    width = 0.17
    years = sorted({int(y) for h in HYPS for y in res["hypotheses"][h]["x1"]["years"]})
    for i, h in enumerate(HYPS):
        ys = res["hypotheses"][h]["x1"]["years"]
        ax.bar(np.arange(len(years)) + (i - 2) * width, [ys.get(str(y), {}).get("return", 0) * 100 for y in years], width,
               label=h)
    ax.set_xticks(range(len(years)), years, fontsize=7)
    ax.set_ylabel("retorno anual neto %")
    ax.axhline(0, color="grey", lw=0.6)
    ax.legend(fontsize=7)
    fig.tight_layout()
    fig.savefig(FIG / "c2_years.png", dpi=120)
    print("figures written")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["panels", "run", "report"])
    {"panels": panels, "run": run, "report": report}[ap.parse_args().mode]()
