"""Audit raw M15 forex CSVs (read-only): format, order, duplicates, gaps, weekends, NaN, anomalies.

Usage: python scripts/audit_m15.py [data/raw] > report.txt
Never modifies the input files.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

BAR = pd.Timedelta(minutes=15)


def load(path: Path) -> tuple[pd.DataFrame, dict]:
    raw = pd.read_csv(path, dtype=str, keep_default_na=False)
    info = {"columns": list(raw.columns), "rows": len(raw)}
    ts = pd.to_datetime(raw["Date"] + " " + raw["Time"], format="%Y%m%d %H:%M:%S", errors="coerce")
    info["unparseable_ts"] = int(ts.isna().sum())
    df = pd.DataFrame({"ts": ts})
    for c in ["Open", "High", "Low", "Close", "Volume"]:
        num = pd.to_numeric(raw[c].replace("", np.nan), errors="coerce")
        info[f"nan_{c}"] = int(num.isna().sum())
        df[c.lower()] = num
    return df, info


def audit(path: Path) -> None:
    df, info = load(path)
    name = path.stem
    print(f"\n{'=' * 70}\n{name}  ({path.name}, {info['rows']} rows)")
    print(f"columns: {info['columns']}")
    print(f"unparseable timestamps: {info['unparseable_ts']}; NaN: "
          + ", ".join(f"{k[4:]}={v}" for k, v in info.items() if k.startswith("nan_")))
    ts = df["ts"]
    print(f"range: {ts.iloc[0]} -> {ts.iloc[-1]}  (min {ts.min()}, max {ts.max()})")

    d = ts.diff()
    print(f"strictly increasing: {bool((d.iloc[1:] > pd.Timedelta(0)).all())}; "
          f"backward steps: {int((d < pd.Timedelta(0)).sum())}; zero steps: {int((d == pd.Timedelta(0)).sum())}")
    dup_ts = ts.duplicated(keep=False)
    dup_rows = df.duplicated(keep=False)
    print(f"duplicated timestamps: {int(ts.duplicated().sum())} (rows involved {int(dup_ts.sum())}); "
          f"fully identical rows: {int(df.duplicated().sum())}")
    if dup_ts.any():
        conflicting = df[dup_ts & ~dup_rows]
        print(f"  duplicated timestamps with DIFFERENT values: {conflicting['ts'].nunique()}")
        print("  first duplicates:\n" + df[dup_ts].head(6).to_string())
    off_grid = ts[(ts.dt.minute % 15 != 0) | (ts.dt.second != 0)]
    print(f"off 15-min grid: {len(off_grid)}")

    # Weekday distribution (0=Mon .. 6=Sun)
    wd = ts.dt.dayofweek.value_counts().sort_index()
    print("bars per weekday (Mon..Sun): " + ", ".join(f"{int(k)}:{int(v)}" for k, v in wd.items()))
    sat = df[ts.dt.dayofweek == 5]
    sun = df[ts.dt.dayofweek == 6]
    if len(sat):
        print(f"  Saturday bars: {len(sat)}, e.g. {sat['ts'].head(3).tolist()}")
    if len(sun):
        print(f"  Sunday bars: {len(sun)}; Sunday hours: {sorted(sun['ts'].dt.hour.unique().tolist())}")

    # Weekly open/close time pattern -> timezone inference
    week = ts.dt.to_period("W-SAT")  # weeks Sun..Sat
    g = df.groupby(week)["ts"]
    first = g.min()
    last = g.max()
    fo = (first.dt.dayofweek.astype(str) + " " + first.dt.strftime("%H:%M")).value_counts().head(6)
    lc = (last.dt.dayofweek.astype(str) + " " + last.dt.strftime("%H:%M")).value_counts().head(6)
    print("weekly first bar (dow HH:MM) top: " + "; ".join(f"{k}={v}" for k, v in fo.items()))
    print("weekly last bar  (dow HH:MM) top: " + "; ".join(f"{k}={v}" for k, v in lc.items()))
    # Split by US DST (approx: second Sun of March .. first Sun of Nov, since 2007)
    fdf = pd.DataFrame({"first": first.values, "last": last.values})
    m = fdf["first"].dt.month
    summer = m.between(4, 10)
    winter = m.isin([12, 1, 2])
    for lab, mask in [("summer(Apr-Oct)", summer), ("winter(Dec-Feb)", winter)]:
        sub = fdf[mask]
        a = (sub["first"].dt.dayofweek.astype(str) + " " + sub["first"].dt.strftime("%H:%M")).value_counts().head(3)
        b = (sub["last"].dt.dayofweek.astype(str) + " " + sub["last"].dt.strftime("%H:%M")).value_counts().head(3)
        print(f"  {lab}: first " + "; ".join(f"{k}={v}" for k, v in a.items())
              + " | last " + "; ".join(f"{k}={v}" for k, v in b.items()))
    # Per-year dominant weekly open
    yr = fdf.assign(y=fdf["first"].dt.year, k=fdf["first"].dt.dayofweek.astype(str) + " " + fdf["first"].dt.strftime("%H:%M"))
    dom = yr.groupby("y")["k"].agg(lambda s: s.value_counts().index[0])
    print("  dominant weekly open by year: " + ", ".join(f"{y}:{k}" for y, k in dom.items()))

    # Gaps inside the trading week (exclude weekend gap: > 36h across Fri->Sun/Mon)
    gaps = df.loc[d > BAR, "ts"].to_frame().assign(gap=d[d > BAR])
    gaps["prev"] = gaps["ts"] - gaps["gap"]
    is_weekend = (gaps["gap"] >= pd.Timedelta(hours=36)) & (gaps["prev"].dt.dayofweek >= 4)
    intra = gaps[~is_weekend]
    missing_bars = int(((intra["gap"] / BAR) - 1).sum())
    print(f"gaps > 15m: {len(gaps)} total, weekend {int(is_weekend.sum())}, intra-week {len(intra)} "
          f"(~{missing_bars} missing bars)")
    if len(intra):
        buckets = pd.cut(intra["gap"] / pd.Timedelta(minutes=1), [15, 30, 60, 120, 240, 720, 1440, 4320, 1e9],
                         labels=["30m", "31-60m", "1-2h", "2-4h", "4-12h", "12-24h", "1-3d", ">3d"])
        print("  intra-week gap sizes: " + ", ".join(f"{k}={v}" for k, v in buckets.value_counts().sort_index().items()))
        big = intra[intra["gap"] > pd.Timedelta(hours=4)].sort_values("gap", ascending=False)
        print(f"  gaps > 4h (not weekend): {len(big)}; largest:")
        for _, r in big.head(12).iterrows():
            print(f"    {r['prev']} -> {r['ts']}  ({r['gap']})")
        # Where do small gaps concentrate (hour of day)?
        small = intra[intra["gap"] <= pd.Timedelta(hours=4)]
        hh = small["prev"].dt.hour.value_counts().head(5)
        print("  small gaps by hour (start): " + ", ".join(f"{int(k)}h={v}" for k, v in hh.items()))
    # Holidays: Dec 25 / Jan 1 bars
    xmas = df[(ts.dt.month == 12) & (ts.dt.day == 25)]
    ny = df[(ts.dt.month == 1) & (ts.dt.day == 1)]
    print(f"bars on Dec-25: {len(xmas)}, on Jan-01: {len(ny)}")
    # Bars per year
    by = ts.dt.year.value_counts().sort_index()
    print("bars per year: " + ", ".join(f"{int(k)}:{int(v)}" for k, v in by.items()))

    # OHLC sanity
    o, h, l, c, v = (df[k] for k in ["open", "high", "low", "close", "volume"])
    bad_hl = h < l
    bad_h = h < np.maximum(o, c)
    bad_l = l > np.minimum(o, c)
    print(f"OHLC violations: high<low={int(bad_hl.sum())}, high<max(o,c)={int(bad_h.sum())}, "
          f"low>min(o,c)={int(bad_l.sum())}, nonpositive price={int(((df[['open','high','low','close']] <= 0).any(axis=1)).sum())}")
    flat = (h == l)
    print(f"flat bars (high==low): {int(flat.sum())} ({flat.mean():.3%}); volume<=0: {int((v <= 0).sum())}; "
          f"volume min/median/max: {v.min():.0f}/{v.median():.0f}/{v.max():.0f}")
    # Price decimals
    dec = pd.read_csv(path, dtype=str, nrows=2000)["Close"].str.split(".").str[1].str.len().value_counts()
    print(f"close decimals (first 2000 rows): {dict(dec)}")

    # Returns / spikes
    lr = np.log(c).diff()
    rng = np.log(h / l)
    sd = lr.std()
    print(f"close-close log ret: std={sd:.6f}, max|r|={lr.abs().max():.4f} at {ts[lr.abs().idxmax()]}")
    thr = 12 * sd
    spikes = df.loc[lr.abs() > thr, ["ts", "open", "high", "low", "close"]].assign(r=lr[lr.abs() > thr])
    print(f"|ret| > 12 sd ({thr:.4f}): {len(spikes)}")
    for _, r in spikes.sort_values("r", key=np.abs, ascending=False).head(8).iterrows():
        print(f"    {r['ts']}  r={r['r']:+.4f}  O={r['open']} H={r['high']} L={r['low']} C={r['close']}")
    # Isolated spikes: large wick relative to neighbours (range > 20x rolling median range)
    med = rng.rolling(96, min_periods=20).median()
    wick = df.loc[rng > 20 * med, ["ts", "open", "high", "low", "close"]].assign(x=(rng / med)[rng > 20 * med])
    print(f"bars with range > 20x rolling median range: {len(wick)}")
    for _, r in wick.sort_values("x", ascending=False).head(8).iterrows():
        print(f"    {r['ts']}  x{r['x']:.0f}  O={r['open']} H={r['high']} L={r['low']} C={r['close']}")
    # Open vs previous close jump (intra-week, contiguous bars)
    contig = d == BAR
    oc = (np.log(o) - np.log(c.shift())).where(contig)
    print(f"open vs prev close (contiguous): median|.|={oc.abs().median():.6f}, "
          f"share==0: {(oc == 0).mean() / contig.mean():.2%}, max|.|={oc.abs().max():.4f}")


def main() -> None:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else "data/raw")
    for p in sorted(root.glob("*_15M.csv")):
        audit(p)


if __name__ == "__main__":
    main()
