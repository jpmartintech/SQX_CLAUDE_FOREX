"""Walk-forward evaluation of the discovery PROCEDURE (Phase 2b).

For every out-of-sample year Y: a generator (genetic, or the random-search control with the same budget) is trained only on
the preceding ``train_years``; the top-K strategies by a pre-registered criterion are frozen and traded in year Y. Only the
out-of-sample years are concatenated. The same procedure on bar-permuted data gives the null distribution and a p-value.
All thresholds come from a committed YAML (``configs/wf_procedure.yaml``).
"""
from __future__ import annotations

import math
from collections.abc import Callable

import numpy as np
import pandas as pd

from sqxf.backtest.evaluator import Market, build_market, evaluate_light, evaluate_rich
from sqxf.data.m15 import trading_date
from sqxf.funnel.pipeline import daily_returns, make_fitness, stats, window
from sqxf.generators.genetic import GAConfig, run_genetic
from sqxf.grammar import random_strategy
from sqxf.strategy.definition import StrategyDefinition


# ------------------------------------------------------------------ data
def truncate_m15(m15: pd.DataFrame, end_local: str) -> pd.DataFrame:
    """Drop every bar at or after ``end_local`` (so later data is never inside the market at all)."""
    out = m15.loc[m15["ts_local"] < pd.Timestamp(end_local)].reset_index(drop=True)
    out.attrs.update(m15.attrs)
    return out


def rebuild_from_shapes(m15: pd.DataFrame, source: np.ndarray) -> pd.DataFrame:
    """Rebuild prices so that bar ``p`` has the shape (open gap, high/low/close vs open) of original bar ``source[p]``."""
    o, h, l, c = (m15[k].to_numpy(np.float64) for k in ("open", "high", "low", "close"))
    prev_c = np.r_[o[0], c[:-1]]
    shape = np.stack([np.log(o / prev_c), np.log(h / o), np.log(l / o), np.log(c / o)], axis=1)
    g, hh, ll, cc = (x.copy() for x in shape[source].T)
    g[0] = 0.0
    opn = np.exp(np.log(o[0]) + np.r_[0.0, np.cumsum(cc)[:-1]] + np.cumsum(g))
    out = m15.copy()
    out["open"], out["close"] = opn, opn * np.exp(cc)
    out["high"] = np.maximum(opn * np.exp(hh), np.maximum(out["open"], out["close"]))
    out["low"] = np.minimum(opn * np.exp(ll), np.minimum(out["open"], out["close"]))
    return out


def calendar_dates(m15: pd.DataFrame) -> pd.Series:
    """Trading date of each bar: UTC date for crypto (``attrs['calendar'] == 'utc'``), FX trading date (EET) otherwise."""
    if m15.attrs.get("calendar") == "utc":
        return m15["ts_local"].dt.normalize()
    return trading_date(m15["ts_local"])


def full_day_dates(m15: pd.DataFrame, bars_per_day: int = 96) -> set:
    counts = calendar_dates(m15).value_counts()
    return set(counts.index[counts == bars_per_day])


def day_block_mapping(m15s: dict[str, pd.DataFrame], seed: int) -> dict:
    """Target date -> source date: complete trading days (96 M15 bars in EVERY pair) permuted within each calendar month.

    One mapping for all pairs (cross-pair correlation kept); monthly strata keep volatility clustering at the month scale and
    every intraday pattern; day-to-day sequencing inside a month is destroyed. Other days stay in place.
    """
    common = set.intersection(*(full_day_dates(m) for m in m15s.values()))
    dates = sorted(common)
    rng = np.random.default_rng(seed)
    mapping = {}
    months = pd.Series(dates).dt.to_period("M")
    for _, grp in pd.Series(dates).groupby(months.to_numpy()):
        d = list(grp)
        for tgt, src in zip(d, [d[i] for i in rng.permutation(len(d))], strict=True):
            mapping[tgt] = src
    return mapping


def block_permute_m15(m15: pd.DataFrame, mapping: dict) -> pd.DataFrame:
    """Apply a day mapping: the 96 bars of each mapped target day take the shapes of its source day, bar by bar."""
    td = calendar_dates(m15).to_numpy()
    starts = pd.Series(np.arange(len(td))).groupby(td).first()
    source = np.arange(len(td))
    for tgt, src in mapping.items():
        a, b = int(starts[np.datetime64(tgt)]), int(starts[np.datetime64(src)])
        source[a:a + 96] = np.arange(b, b + 96)
    return rebuild_from_shapes(m15, source)


def permute_m15(m15: pd.DataFrame, seed: int) -> pd.DataFrame:
    """Null market (Phase 2b): permute bar shapes jointly (open gap, high/low/close relative to open) over all bars.

    Keeps timestamps, flags, the multiset of bar shapes and the total log drift; destroys every temporal dependence
    (trend, momentum, mean reversion, volatility clustering, intraday seasonality).
    """
    return rebuild_from_shapes(m15, np.random.default_rng(seed).permutation(len(m15)))


# ------------------------------------------------------------------ folds
def folds(market: Market, cfg: dict) -> list[dict]:
    f = cfg["folds"]
    out = []
    for y in f["oos_years"]:
        start = y - f["train_years"]
        edges = np.linspace(start, y, f["train_blocks"] + 1).round().astype(int)
        blocks = [window(market, f"{a}-01-01", f"{b}-01-01") for a, b in zip(edges[:-1], edges[1:], strict=True)]
        out.append({"year": y, "train_blocks": blocks, "train": (blocks[0][0], blocks[-1][1]),
                    "oos": window(market, f"{y}-01-01", f"{y + 1}-01-01")})
    return out


# ------------------------------------------------------------------ one fold
def generate(market: Market, fold: dict, cfg: dict, generator: str, seed: int) -> tuple[list[StrategyDefinition], np.ndarray]:
    fitness = make_fitness(market, fold["train_blocks"], cfg["fitness"]["min_trades_per_block"], cfg["exec_timeframe_train"])
    ga_cfg = GAConfig.from_dict(cfg["genetic"])
    if generator == "genetic":
        res = run_genetic(market.pair, fitness, ga_cfg, seed=seed)
        strategies = [s for s, _ in res.archive.values()]
        return strategies, np.array([f for _, f in res.archive.values()])
    if generator == "random":
        rng = np.random.default_rng(seed)
        seen: dict[str, StrategyDefinition] = {}
        while len(seen) < ga_cfg.max_unique_evaluations:
            s = random_strategy(rng, market.pair, ga_cfg.max_predicates)
            seen.setdefault(s.canonical_hash, s)
        strategies = list(seen.values())
        return strategies, fitness(strategies)
    raise ValueError(generator)


def select_top_k(market: Market, fold: dict, strategies: list[StrategyDefinition], fit: np.ndarray, cfg: dict
                 ) -> list[StrategyDefinition]:
    """Pre-registered selection, inside the training window only: gates, then top-K by fitness."""
    sel = cfg["selection"]
    tf = cfg["exec_timeframe_train"]
    idx = np.flatnonzero(np.isfinite(fit))
    if len(idx) == 0:
        return []
    cand = [strategies[i] for i in idx]
    s1 = stats(evaluate_light(market, cand, exec_tf=tf, window=fold["train"]))
    s2 = stats(evaluate_light(market, cand, exec_tf=tf, window=fold["train"], cost_multiplier=2.0))
    ok = ((s1["n"] >= sel["min_trades"]) & (s1["pf"] >= sel["min_profit_factor"]) & (s1["mean_r"] > sel["min_mean_r"])
          & (s2["mean_r"] > sel["cost_x2_min_mean_r"]))
    if "cost_x2_min_profit_factor" in sel:
        ok &= s2["pf"] >= sel["cost_x2_min_profit_factor"]
    idx = idx[ok]
    order = idx[np.argsort(-fit[idx], kind="stable")]
    return [strategies[i] for i in order[: sel["top_k"]]]


def trade_oos(market: Market, fold: dict, chosen: list[StrategyDefinition], cfg: dict) -> dict:
    """Frozen strategies traded in the OOS year: pooled trade R (costs x1 and x2) and equal-weight daily returns."""
    tf = cfg["exec_timeframe_oos"]
    w = fold["oos"]
    ex = market.execs[tf]
    n_days = int(ex.day_id[ex.h1_end[w[1] - 1] - 1] - ex.day_id[ex.h1_start[w[0]]] + 1)
    out = {"year": fold["year"], "n_selected": len(chosen), "hashes": [s.canonical_hash for s in chosen]}
    for mult in (1.0, 2.0):
        rs, dd = [], []
        for s in chosen:
            rich = evaluate_rich(market, s, exec_tf=tf, window=w, cost_multiplier=mult)
            rs.append(rich.trades["r"].to_numpy())
            dd.append(float(rich.agg[12]))
        r = np.concatenate(rs) if rs else np.zeros(0)
        key = f"x{int(mult)}"
        out[f"r_{key}"] = r
        out[f"max_dd_mtm_mean_{key}"] = float(np.mean(dd)) if dd else 0.0
    daily = np.zeros(n_days)
    for s in chosen:
        daily += daily_returns(market, s, tf, w) / len(chosen)
    out["daily_x1"] = daily
    first = int(ex.day_id[ex.h1_start[w[0]]])
    out["dates"] = day_dates(market)[first:first + n_days]
    return out


# ------------------------------------------------------------------ procedure
def run_procedure(market: Market, cfg: dict, generator: str, seed_offset: int = 0,
                  log: Callable[[str], None] | None = None) -> dict:
    """Walk-forward with re-optimisation. Returns per-fold results and the concatenated OOS statistics."""
    per_fold, evaluated = [], 0
    for i, fold in enumerate(folds(market, cfg)):
        seed = cfg["seed"] + seed_offset + i
        strategies, fit = generate(market, fold, cfg, generator, seed)
        evaluated += len(strategies)
        chosen = select_top_k(market, fold, strategies, fit, cfg)
        res = trade_oos(market, fold, chosen, cfg)
        res["evaluated"] = len(strategies)
        res["finite_fitness"] = int(np.isfinite(fit).sum())
        per_fold.append(res)
        if log:
            r = res["r_x1"]
            log(f"{generator} {fold['year']}: evaluated {len(strategies)} selected {len(chosen)} oos trades {len(r)} "
                f"mean R {r.mean() if len(r) else float('nan'):+.4f}")
    return summarize(per_fold, evaluated, cfg)


def summarize(per_fold: list[dict], evaluated: int, cfg: dict) -> dict:
    r1 = np.concatenate([f["r_x1"] for f in per_fold])
    r2 = np.concatenate([f["r_x2"] for f in per_fold])
    daily = np.concatenate([f["daily_x1"] for f in per_fold])
    eq = np.cumprod(1.0 + daily)
    peak = np.maximum.accumulate(np.r_[1.0, eq])[1:]
    sd = daily.std()
    dpy = float(cfg.get("days_per_year", 260))
    return {
        "evaluated": evaluated,
        "oos_trades": int(len(r1)),
        "mean_r_x1": float(r1.mean()) if len(r1) else float("nan"),
        "mean_r_x2": float(r2.mean()) if len(r2) else float("nan"),
        "tstat_x1": float(r1.mean() / r1.std() * math.sqrt(len(r1))) if len(r1) > 1 and r1.std() > 0 else float("nan"),
        "portfolio_sharpe": float(daily.mean() / sd * math.sqrt(dpy)) if sd > 0 else 0.0,
        "portfolio_return": float(eq[-1] - 1.0) if len(eq) else 0.0,
        "portfolio_max_dd": float((1 - eq / peak).max()) if len(eq) else 0.0,
        "positive_years_x1": int(sum(1 for f in per_fold if len(f["r_x1"]) and f["r_x1"].mean() > 0)),
        "per_year": [{"year": f["year"], "selected": f["n_selected"], "trades": int(len(f["r_x1"])),
                      "mean_r_x1": float(f["r_x1"].mean()) if len(f["r_x1"]) else None,
                      "mean_r_x2": float(f["r_x2"].mean()) if len(f["r_x2"]) else None,
                      "max_dd_mtm_mean_x1": f["max_dd_mtm_mean_x1"], "evaluated": f["evaluated"],
                      "finite_fitness": f["finite_fitness"], "hashes": f["hashes"]} for f in per_fold],
        "_daily_x1": daily,
    }


def null_market(m15_truncated: pd.DataFrame, market: Market, seed: int) -> Market:
    return build_market(market.pair, permute_m15(m15_truncated, seed), market.costs,
                        risk_per_trade=market.risk_per_trade, days_per_year=market.days_per_year)


def effective_trials_rho(market: Market, strategies: list[StrategyDefinition], w: tuple[int, int], tf: str,
                         sample: int, seed: int) -> dict:
    """N_eff = rho + (1 - rho) * N, rho = mean pairwise correlation of daily returns in a random sample of trials."""
    rng = np.random.default_rng(seed)
    pick = rng.choice(len(strategies), size=min(sample, len(strategies)), replace=False)
    mat = np.array([daily_returns(market, strategies[i], tf, w) for i in pick])
    mat = mat[mat.std(axis=1) > 0]
    if len(mat) < 2:
        return {"rho": float("nan"), "n": len(strategies), "n_eff": float(len(strategies))}
    cm = np.corrcoef(mat)
    rho = float(cm[np.triu_indices(len(cm), 1)].mean())
    return {"rho": rho, "n": len(strategies), "n_eff": rho + (1 - rho) * len(strategies), "sample": int(len(mat))}


# ------------------------------------------------------------------ Phase 2c: several pairs, selection variants
def day_dates(market: Market) -> np.ndarray:
    """Trading date (datetime64[D]) of every ``day_id``."""
    h1 = market.h1
    if market.meta.get("calendar") == "utc":
        d = h1["ts_local"].dt.normalize().to_numpy().astype("datetime64[D]")
    else:
        d = trading_date(h1["ts_local"]).to_numpy().astype("datetime64[D]")
    ids = h1["day_id"].to_numpy()
    out = np.empty(ids.max() + 1, dtype="datetime64[D]")
    out[ids] = d
    return out


def run_multi(markets: dict[str, Market], cfg: dict, variants: dict[str, dict], generators=("genetic", "random"),
              pair_seed_offsets: dict[str, int] | None = None, log: Callable[[str], None] | None = None) -> dict:
    """For each pair and fold: generate once per generator, then select with every variant and trade the OOS year.

    Returns ``{generator: {variant: summary}}`` with the pooled (all pairs) statistics and a per-pair breakdown.
    """
    offsets = pair_seed_offsets or {p: 1000 * i for i, p in enumerate(markets)}
    per = {g: {v: {p: [] for p in markets} for v in variants} for g in generators}
    evaluated = {g: 0 for g in generators}
    for pair, market in markets.items():
        for i, fold in enumerate(folds(market, cfg)):
            for gen in generators:
                strategies, fit = generate(market, fold, cfg, gen, cfg["seed"] + offsets[pair] + i)
                evaluated[gen] += len(strategies)
                for v, sel in variants.items():
                    chosen = select_top_k(market, fold, strategies, fit, {**cfg, "selection": sel})
                    res = trade_oos(market, fold, chosen, cfg)
                    res["evaluated"] = len(strategies)
                    res["finite_fitness"] = int(np.isfinite(fit).sum())
                    per[gen][v][pair].append(res)
                    if log:
                        r = res["r_x1"]
                        log(f"{pair} {fold['year']} {gen}/{v}: selected {len(chosen)} trades {len(r)} "
                            f"mean R {r.mean() if len(r) else float('nan'):+.4f}")
    return {g: {v: summarize_multi(per[g][v], evaluated[g], cfg) for v in variants} for g in generators}


def summarize_multi(per_pair: dict[str, list[dict]], evaluated: int, cfg: dict) -> dict:
    pooled = summarize([f for folds_ in per_pair.values() for f in folds_], evaluated, cfg)
    series = {}
    for pair, folds_ in per_pair.items():
        series[pair] = pd.Series(np.concatenate([f["daily_x1"] for f in folds_]),
                                 index=np.concatenate([f["dates"] for f in folds_]))
    port = pd.concat(series, axis=1).sort_index().mean(axis=1, skipna=True).to_numpy()
    eq = np.cumprod(1.0 + port)
    peak = np.maximum.accumulate(np.r_[1.0, eq])[1:]
    sd = port.std()
    dpy = float(cfg.get("days_per_year", 260))
    out = {k: v for k, v in pooled.items() if k not in ("_daily_x1", "portfolio_sharpe", "portfolio_return",
                                                        "portfolio_max_dd", "per_year", "positive_years_x1")}
    out.update({"portfolio_sharpe": float(port.mean() / sd * math.sqrt(dpy)) if sd > 0 else 0.0,
                "portfolio_return": float(eq[-1] - 1.0), "portfolio_max_dd": float((1 - eq / peak).max()),
                "portfolio_days": int(len(port)), "_daily_portfolio": port})
    out["per_pair"] = {}
    for pair, folds_ in per_pair.items():
        sp = summarize(folds_, sum(f["evaluated"] for f in folds_), cfg)
        out["per_pair"][pair] = {k: sp[k] for k in ("oos_trades", "mean_r_x1", "mean_r_x2", "tstat_x1", "portfolio_sharpe",
                                                   "positive_years_x1")}
        out["per_pair"][pair]["per_year"] = sp["per_year"]
    yrs = {}
    for folds_ in per_pair.values():
        for f in folds_:
            yrs.setdefault(f["year"], []).append(f["r_x1"])
    out["per_year_pooled_mean_r_x1"] = {int(y): float(np.concatenate(v).mean()) if sum(map(len, v)) else None
                                        for y, v in sorted(yrs.items())}
    return out
