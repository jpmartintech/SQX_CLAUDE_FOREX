"""Crypto M15 data audit (read-only; no strategy, no backtest).

Holdout: the LAST 18 MONTHS of each coin are sealed. Quality checks (integrity, gaps, anomalies, volume, format) may read
them; performance statistics (returns, volatility, drift, buy & hold, correlations, PCA) use ONLY pre-holdout data.
Every run appends a quality-only access record to trials/crypto_holdout_access.jsonl.

Usage: python scripts/audit_crypto.py [data/raw/crypto] > runs/audit_crypto.txt
Writes docs/crypto_manifest.json (hashes, rows, ranges, holdout starts).
"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
BAR = pd.Timedelta(minutes=15)
HOLDOUT_MONTHS = 18
ACCESS_LOG = ROOT / "trials" / "crypto_holdout_access.jsonl"
EVENTS = {"covid_crash": ("2020-03-12", "2020-03-13"), "may_2021": ("2021-05-19", "2021-05-20"),
          "luna": ("2022-05-09", "2022-05-13"), "ftx": ("2022-11-08", "2022-11-10")}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def load(path: Path) -> tuple[pd.DataFrame, dict]:
    raw = pd.read_csv(path, dtype=str, keep_default_na=False)
    info = {"columns": list(raw.columns), "rows": len(raw)}
    ts = pd.to_datetime(raw["datetime"], format="%Y-%m-%d %H:%M:%S", errors="coerce")
    info["unparseable_ts"] = int(ts.isna().sum())
    df = pd.DataFrame({"ts": ts})
    for c in ("open", "high", "low", "close", "volume"):
        v = pd.to_numeric(raw[c].replace("", np.nan), errors="coerce")
        info[f"nan_{c}"] = int(v.isna().sum())
        df[c] = v.astype(float)
    info["volume_integer_share"] = float((raw["volume"].str.fullmatch(r"-?\d+")).mean())
    info["price_decimals_max"] = int(raw["close"].str.split(".").str[1].fillna("").str.len().max())
    return df, info


def section(title: str) -> None:
    print(f"\n{'=' * 100}\n{title}\n{'=' * 100}")


def daily_close(df: pd.DataFrame) -> pd.Series:
    """UTC daily close = close of the last M15 bar of complete days (96 bars); incomplete days dropped."""
    g = df.groupby(df["ts"].dt.floor("D"))
    return g["close"].last()[g.size() == 96]


def main() -> None:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else ROOT / "data" / "raw" / "crypto")
    coins = sorted(p.name.replace("_15M.csv", "") for p in root.glob("*_15M.csv"))
    data, infos, h1files = {}, {}, {}
    for c in coins:
        data[c], infos[c] = load(root / f"{c}_15M.csv")
        h1files[c], _ = load(root / f"{c}_1H.csv")

    # ---------------------------------------------------------------- holdout first
    holdout = {c: (data[c]["ts"].max() - pd.DateOffset(months=HOLDOUT_MONTHS)).normalize() for c in coins}
    ACCESS_LOG.parent.mkdir(parents=True, exist_ok=True)
    with ACCESS_LOG.open("a") as fh:
        fh.write(json.dumps({"utc": datetime.now(UTC).isoformat(), "script": "scripts/audit_crypto.py",
                             "purpose": "data quality audit only (integrity, gaps, anomalies, volume/liquidity, format)",
                             "performance_stats_on_holdout": False,
                             "holdout_start_utc": {c: str(h) for c, h in holdout.items()}}) + "\n")
    pre = {c: data[c][data[c]["ts"] < holdout[c]].reset_index(drop=True) for c in coins}

    # ---------------------------------------------------------------- 1. inventory + manifest
    section("1. INVENTORY")
    manifest = {"generated_utc": datetime.now(UTC).isoformat(), "holdout_months": HOLDOUT_MONTHS, "files": {}}
    for c in coins:
        for tf in ("15M", "1H"):
            p = root / f"{c}_{tf}.csv"
            d = data[c] if tf == "15M" else h1files[c]
            manifest["files"][p.name] = {"sha256": sha256(p), "rows": int(len(d)), "first_utc": str(d["ts"].min()),
                                         "last_utc": str(d["ts"].max()), "bytes": p.stat().st_size}
        manifest["files"][f"{c}_15M.csv"]["holdout_start_utc"] = str(holdout[c])
        i = infos[c]
        print(f"{c:9} rows {i['rows']:7d}  {data[c]['ts'].min()} -> {data[c]['ts'].max()}  holdout from {holdout[c].date()}  "
              f"cols {i['columns']}  price decimals<= {i['price_decimals_max']}  integer-volume share {i['volume_integer_share']:.3f}")
    (ROOT / "docs" / "crypto_manifest.json").write_text(json.dumps(manifest, indent=1))

    print("\nTimezone evidence:")
    # (a) DST transition days (US + EU) must have exactly 96 bars if timestamps are UTC (a DST local zone gives 92/100 or dup/gap)
    dst_days = []
    for y in range(2018, 2026):
        mar, nov = pd.Timestamp(f"{y}-03-01"), pd.Timestamp(f"{y}-11-01")
        us_start = mar + pd.Timedelta(days=(6 - mar.dayofweek) % 7 + 7)
        us_end = nov + pd.Timedelta(days=(6 - nov.dayofweek) % 7)
        eu_start = pd.Timestamp(f"{y}-03-31") - pd.Timedelta(days=(pd.Timestamp(f"{y}-03-31").dayofweek + 1) % 7)
        eu_end = pd.Timestamp(f"{y}-10-31") - pd.Timedelta(days=(pd.Timestamp(f"{y}-10-31").dayofweek + 1) % 7)
        dst_days += [us_start, us_end, eu_start, eu_end]
    for c in ("BTCUSDT", "ETHUSDT"):
        cnt = data[c].groupby(data[c]["ts"].dt.floor("D")).size()
        vals = [int(cnt.get(d, 0)) for d in dst_days]
        print(f"  {c}: bars on the {len(dst_days)} US/EU DST switch days 2018-2025: {sorted(set(vals))} (96 expected in UTC)")
    # (b) intraday volume profile: peak should move with the US equity open (13:30 UTC summer / 14:30 UTC winter)
    b = data["BTCUSDT"]
    b = b[b["ts"] < holdout["BTCUSDT"]]
    hr = b["ts"].dt.hour
    us_summer = b["ts"].dt.month.between(4, 10)
    for lab, m in (("US summer (Apr-Oct)", us_summer), ("US winter (Dec-Feb)", b["ts"].dt.month.isin([12, 1, 2]))):
        prof = b.loc[m].groupby(hr[m])["volume"].sum()
        prof = prof / prof.sum()
        top = prof.sort_values(ascending=False).head(4)
        print(f"  BTCUSDT volume share by UTC hour, {lab}: top " + ", ".join(f"{h:02d}h={v:.3f}" for h, v in top.items())
              + f" | 13h={prof.get(13, 0):.3f} 14h={prof.get(14, 0):.3f} 15h={prof.get(15, 0):.3f} 00h={prof.get(0, 0):.3f}")
    # (c) first bars vs known Binance spot listing times (UTC)
    for c in coins:
        print(f"  {c} first bar {data[c]['ts'].iat[0]}")

    # ---------------------------------------------------------------- 2. integrity
    section("2. INTEGRITY")
    for c in coins:
        d, i = data[c], infos[c]
        dt = d["ts"].diff()
        o, h, l, cl, v = (d[k] for k in ("open", "high", "low", "close", "volume"))
        flat = (o == h) & (h == l) & (l == cl)
        frozen = flat & (o == cl.shift())
        run_id = (~frozen).cumsum()
        runs = frozen.groupby(run_id).sum()
        runs = runs[runs > 0]
        print(f"{c:9} unparseable {i['unparseable_ts']} NaN {sum(i[k] for k in i if k.startswith('nan_'))} "
              f"dup_ts {int(d['ts'].duplicated().sum())} backward {int((dt < pd.Timedelta(0)).sum())} "
              f"off-grid {int(((d['ts'].dt.minute % 15) != 0).sum())} | high<low {int((h < l).sum())} "
              f"high<max(o,c) {int((h < np.maximum(o, cl)).sum())} low>min(o,c) {int((l > np.minimum(o, cl)).sum())} "
              f"price<=0 {int(((d[['open','high','low','close']] <= 0).any(axis=1)).sum())} | vol==0 {int((v == 0).sum())} "
              f"({(v == 0).mean():.3%}) vol<0 {int((v < 0).sum())} | flat bars {int(flat.sum())} frozen runs>=8 "
              f"{int((runs >= 8).sum())} longest frozen {int(runs.max()) if len(runs) else 0} bars")

    # ---------------------------------------------------------------- 3. gaps
    section("3. GAPS (24/7 15-minute grid)")
    gap_rows = []
    for c in coins:
        d = data[c]
        dt = d["ts"].diff()
        g = d.loc[dt > BAR, "ts"].to_frame("end")
        g["start"] = g["end"] - dt[dt > BAR]
        g["missing"] = (dt[dt > BAR] / BAR - 1).astype(int)
        g["coin"] = c
        gap_rows.append(g)
        expected = int((d["ts"].max() - d["ts"].min()) / BAR) + 1
        hours = d["ts"].dt.floor("h").value_counts()
        full_hours = int((d["ts"].max().floor("h") - d["ts"].min().floor("h")) / pd.Timedelta(hours=1)) + 1
        by_year = g.groupby(g["end"].dt.year)["missing"].agg(["count", "sum"])
        print(f"{c:9} bars {len(d)} / expected {expected} (missing {expected - len(d)}, {1 - len(d) / expected:.3%}) "
              f"gaps {len(g)} | H1: hours with data {len(hours)}, incomplete (<4 bars) {int((hours < 4).sum())}, "
              f"hours without any bar {full_hours - len(hours)}")
        print("          by year (gaps/missing bars): " + ", ".join(f"{y}:{r['count']}/{r['sum']}" for y, r in by_year.iterrows()))
    gaps = pd.concat(gap_rows, ignore_index=True)
    shared = gaps.groupby(["start", "end"])["coin"].agg(["count", lambda s: ",".join(sorted(s))]).reset_index()
    shared.columns = ["start", "end", "n_coins", "coins"]
    shared["hours"] = (shared["end"] - shared["start"]) / pd.Timedelta(hours=1)
    shared["alive"] = [sum(1 for c in coins if data[c]["ts"].iat[0] < r.start) for r in shared.itertuples()]
    shared["exchange_wide"] = shared["n_coins"] == shared["alive"]
    print(f"\nDistinct gap intervals {len(shared)}: in ALL coins listed at that time (exchange-wide) "
          f"{int(shared['exchange_wide'].sum())}, in a subset {int((~shared['exchange_wide']).sum())}")
    print("All gap intervals >= 1 h (start -> end, hours, coins affected / coins listed):")
    for _, r in shared[shared["hours"] >= 1].sort_values("start").iterrows():
        print(f"   {r['start']} -> {r['end']}  {r['hours']:6.2f} h  {r['n_coins']}/{r['alive']}"
              f"{'' if r['exchange_wide'] else '  subset: ' + r['coins']}")
    short = shared[shared["hours"] < 1]
    print(f"Gaps < 1 h: {len(short)} (exchange-wide {int(short['exchange_wide'].sum())})")

    # 1H files vs M15 aggregation
    print("\n1H files vs H1 aggregated from M15 (complete hours):")
    for c in coins:
        d = data[c]
        g = d.groupby(d["ts"].dt.floor("h"))
        agg = pd.DataFrame({"open": g["open"].first(), "high": g["high"].max(), "low": g["low"].min(),
                            "close": g["close"].last(), "volume": g["volume"].sum(), "n": g.size()})
        agg = agg[agg["n"] == 4]
        h1 = h1files[c].set_index("ts")
        j = agg.join(h1, rsuffix="_1h", how="inner")
        rel = {k: float((j[k] / j[f"{k}_1h"] - 1).abs().max()) for k in ("open", "high", "low", "close", "volume")}
        print(f"  {c:9} 1H rows {len(h1)}, M15-complete hours {len(agg)}, matched {len(j)}, 1H-only hours "
              f"{len(h1.index.difference(agg.index))} | max rel diff " + " ".join(f"{k}={v:.2e}" for k, v in rel.items()))

    # ---------------------------------------------------------------- 4. anomalies
    section("4. ANOMALIES")
    for c in coins:
        d = data[c]
        cl = d["close"]
        r1 = np.log(cl / cl.shift())
        r2 = r1.shift(-1)
        sd = r1.rolling(96 * 7, min_periods=96).std()
        spike = (r1.abs() > np.maximum(0.08, 12 * sd)) & ((r1 + r2).abs() < 0.25 * r1.abs())
        body_hi = np.maximum(d["open"], cl)
        body_lo = np.minimum(d["open"], cl)
        nb_hi = pd.concat([d["high"].shift(), d["high"].shift(-1)], axis=1).max(axis=1)
        nb_lo = pd.concat([d["low"].shift(), d["low"].shift(-1)], axis=1).min(axis=1)
        wick_up = (d["high"] / body_hi - 1 > 0.10) & (d["high"] / nb_hi - 1 > 0.08)
        wick_dn = (1 - d["low"] / body_lo > 0.10) & (1 - d["low"] / nb_lo > 0.08)
        after = [r1.shift(-k) for k in range(1, 5)]
        scale = (r1.abs() > np.log(3)) & (sum(a.abs() for a in after) < 0.2 * r1.abs())
        vmed = d["volume"].rolling(96 * 7, min_periods=96).median()
        vext = d["volume"] > 100 * vmed
        print(f"{c:9} reverting close spikes {int(spike.sum())} | isolated wicks up {int(wick_up.sum())} down "
              f"{int(wick_dn.sum())} | persistent jumps >x3 (scale change?) {int(scale.sum())} | volume >100x weekly median "
              f"{int(vext.sum())} | max|r| {r1.abs().max():.3f} at {d['ts'][r1.abs().idxmax()]}")
        for lab, m in (("spike", spike), ("wick_up", wick_up), ("wick_dn", wick_dn), ("scale", scale)):
            for k in d.index[m][:4]:
                print(f"      {lab:8} {d['ts'][k]} O={d['open'][k]} H={d['high'][k]} L={d['low'][k]} C={cl[k]} "
                      f"prevC={cl.get(k - 1)} nextC={cl.get(k + 1)} r={r1[k]:+.3f}")
        top_v = d.loc[vext].nlargest(3, "volume")
        for k, row in top_v.iterrows():
            print(f"      volume  {row['ts']} vol={row['volume']:.4g} ({row['volume'] / vmed[k]:.0f}x weekly median)")
    print("\nKnown market events (real moves, kept): largest 15m drop and day range by coin")
    for ev, (a, b_) in EVENTS.items():
        row = []
        for c in coins:
            d = data[c]
            m = (d["ts"] >= a) & (d["ts"] < pd.Timestamp(b_) + pd.Timedelta(days=1))
            if m.sum() < 10:
                row.append(f"{c}: n/a")
                continue
            x = d.loc[m]
            row.append(f"{c}: min15m {np.log(x['close'] / x['close'].shift()).min():+.3f} range "
                       f"{x['low'].min() / x['high'].max() - 1:+.2f}")
        print(f"  {ev:12} {a}..{b_}: " + "; ".join(row))

    # ---------------------------------------------------------------- 5. volume & liquidity
    section("5. VOLUME AND LIQUIDITY (volume units test + median daily USD volume by year, all data incl. holdout)")
    for c in coins:
        d = data[c]
        usd = d["volume"] * (d["open"] + d["high"] + d["low"] + d["close"]) / 4
        day = usd.groupby(d["ts"].dt.floor("D")).sum()
        med = day.groupby(day.index.year).median()
        ratio = float((d["volume"] / d["close"]).median())
        print(f"{c:9} median volume/close {ratio:.3g} | median daily USD (base volume x price), by year: "
              + ", ".join(f"{y}:{v / 1e6:.1f}M" for y, v in med.items()))

    section("10. LIQUIDITY-OPERABLE START (trailing 90-day median daily USD volume; causal; pre-holdout)")
    for c in coins:
        d = pre[c]
        usd = d["volume"] * (d["open"] + d["high"] + d["low"] + d["close"]) / 4
        day = usd.groupby(d["ts"].dt.floor("D")).sum()
        roll = day.rolling(90, min_periods=90).median()
        out = []
        for thr in (5e6, 20e6, 50e6):
            ok = roll[roll >= thr]
            if len(ok):
                y = (holdout[c] - ok.index[0]).days / 365.25
                out.append(f">=${thr / 1e6:.0f}M from {ok.index[0].date()} ({y:.1f} y to holdout)")
            else:
                out.append(f">=${thr / 1e6:.0f}M never")
        below = (roll.dropna() < 20e6).mean()
        print(f"{c:9} " + " | ".join(out) + f" | days below $20M after first reaching it: "
              f"{float((roll[roll.index >= (roll[roll >= 20e6].index[0] if (roll >= 20e6).any() else roll.index[-1])] < 20e6).mean()):.1%}"
              f" (all: {below:.1%})")

    # ---------------------------------------------------------------- 8/9. cross-coin structure and regimes (pre-holdout)
    section("8. CROSS-COIN STRUCTURE (pre-holdout only)")
    dc = pd.DataFrame({c: daily_close(pre[c]) for c in coins}).sort_index()
    ret = np.log(dc / dc.shift())
    print("Date-overlap matrix (years of common pre-holdout daily data):")
    ov = pd.DataFrame(index=coins, columns=coins, dtype=float)
    for a in coins:
        for b_ in coins:
            ov.loc[a, b_] = (dc[a].notna() & dc[b_].notna()).sum() / 365.25
    print(ov.round(1).to_string())
    print("\nCorrelation of daily log returns with BTC, by year:")
    cy = {}
    for y, grp in ret.groupby(ret.index.year):
        cy[y] = grp.corr()["BTCUSDT"]
    print(pd.DataFrame(cy).round(2).to_string())
    common = ret.dropna()
    ev = np.linalg.eigvalsh(common.corr().to_numpy())[::-1]
    print(f"\nPCA on {len(common)} common days ({common.index.min().date()} -> {common.index.max().date()}): eigenvalues "
          + " ".join(f"{e:.2f}" for e in ev) + f" | PC1 share {ev[0] / ev.sum():.1%} | N_eff (participation ratio) "
          f"{ev.sum() ** 2 / (ev ** 2).sum():.2f} of {len(coins)}")

    section("9. REGIMES BY YEAR (pre-holdout only; daily UTC closes)")
    rows = []
    for c in coins:
        s = dc[c].dropna()
        for y, g in s.groupby(s.index.year):
            r = np.log(g / g.shift()).dropna()
            if len(g) < 20:
                continue
            dd = (g / g.cummax() - 1).min()
            rows.append({"coin": c, "year": y, "days": len(g), "return": g.iat[-1] / g.iat[0] - 1,
                         "vol_ann": r.std() * np.sqrt(365), "max_dd": dd})
        bh = s.iat[-1] / s.iat[0] - 1
        print(f"{c:9} buy&hold {s.index[0].date()} -> {s.index[-1].date()}: {bh:+.1%} "
              f"(CAGR {(s.iat[-1] / s.iat[0]) ** (365.25 / (s.index[-1] - s.index[0]).days) - 1:+.1%}), "
              f"max DD {(s / s.cummax() - 1).min():.1%}")
    reg = pd.DataFrame(rows)
    for col in ("return", "vol_ann", "max_dd"):
        print(f"\n{col} by year:")
        print(reg.pivot(index="coin", columns="year", values=col).round(2).to_string())

    # ---------------------------------------------------------------- 13. bar counts pre-holdout
    section("13. BAR COUNTS BEFORE THE HOLDOUT (complete bars only)")
    for c in coins:
        d = pre[c]
        n_h1 = int((d["ts"].dt.floor("h").value_counts() == 4).sum())
        n_h4 = int((d["ts"].dt.floor("4h").value_counts() == 16).sum())
        n_d1 = int((d["ts"].dt.floor("D").value_counts() == 96).sum())
        wk = d["ts"].dt.to_period("W-SUN")  # ISO weeks Monday 00:00 -> Sunday 23:45 UTC
        n_w1 = int((wk.value_counts() == 672).sum())
        print(f"{c:9} pre-holdout {d['ts'].min().date()} -> {d['ts'].max().date()} ({(d['ts'].max() - d['ts'].min()).days / 365.25:.1f} y): "
              f"H1 {n_h1}  H4 {n_h4}  D1 {n_d1}  W1 {n_w1}")
    print(f"\nManifest: docs/crypto_manifest.json; holdout access logged in {ACCESS_LOG.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
