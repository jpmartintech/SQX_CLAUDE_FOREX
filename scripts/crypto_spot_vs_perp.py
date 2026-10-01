"""Is spot a valid proxy for Binance USDT-M perpetuals? Real-data comparison BEFORE the selection block (< 2023-11-01).

Per coin, on M15 bars present in both series: basis (perp/spot - 1), return correlation and tracking error (M15, H4),
wick divergence, disagreement of hypothetical 1.5 x ATR(14) H4 stops, the LINK 2020-03-12 10:45 bar, and funding statistics.
Writes docs/reports/crypto_spot_vs_perp.json and prints a summary (the report is written from it).
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
END = pd.Timestamp("2023-11-01")
COINS = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "LINKUSDT", "ADAUSDT", "SOLUSDT", "DOGEUSDT", "AVAXUSDT", "TRXUSDT"]


def load(path: Path) -> pd.DataFrame:
    d = pd.read_csv(path)
    d["ts"] = pd.to_datetime(d["datetime"])
    return d[d["ts"] < END].set_index("ts")[["open", "high", "low", "close"]].astype(float)


def h4(d: pd.DataFrame) -> pd.DataFrame:
    g = d.groupby(d.index.floor("4h"))
    out = pd.DataFrame({"open": g["open"].first(), "high": g["high"].max(), "low": g["low"].min(),
                        "close": g["close"].last(), "n": g.size()})
    return out[out["n"] == 16]


def main() -> None:
    res = {}
    for c in COINS:
        spot = load(ROOT / "data/raw/crypto" / f"{c}_15M.csv")
        perp = load(ROOT / "data/raw/crypto_perp" / f"{c}_15M_perp.csv")
        perp = perp[perp.index >= perp.index[0] + pd.Timedelta(days=7)]  # skip the listing week (flat placeholder bars)
        j = spot.join(perp, how="inner", lsuffix="_s", rsuffix="_p")
        basis = j["close_p"] / j["close_s"] - 1
        by_year = basis.groupby(basis.index.year).agg(lambda x: float(np.median(x)))
        rs, rp = np.log(j["close_s"]).diff(), np.log(j["close_p"]).diff()
        sh, ph = h4(spot.loc[j.index]), h4(perp.loc[j.index])
        hj = sh.join(ph, how="inner", lsuffix="_s", rsuffix="_p")
        hrs, hrp = np.log(hj["close_s"]).diff(), np.log(hj["close_p"]).diff()
        te = (hrp - hrs).std() / hrs.std()
        prev = hj["close_s"].shift()
        tr = np.maximum(hj["high_s"] - hj["low_s"], np.maximum((hj["high_s"] - prev).abs(), (hj["low_s"] - prev).abs()))
        atr = tr.rolling(14).mean().shift(1)
        long_stop = prev - 1.5 * atr
        short_stop = prev + 1.5 * atr
        hit_s = (hj["low_s"] <= long_stop) | (hj["high_s"] >= short_stop)
        hit_p = (hj["low_p"] <= long_stop) | (hj["high_p"] >= short_stop)
        valid = atr.notna()
        either = (hit_s | hit_p) & valid
        disagree = (hit_s != hit_p) & valid
        low_div = (j["low_p"] / j["low_s"] - 1).abs()
        high_div = (j["high_p"] / j["high_s"] - 1).abs()
        top = basis.abs().sort_values(ascending=False).head(3)
        f = pd.read_csv(ROOT / "data/raw/crypto_perp" / f"{c}_funding.csv")
        ft = pd.to_datetime(f["fundingTime"], unit="ms")
        fr = f["fundingRate"].astype(float)
        pre = ft < END
        frp, ftp = fr[pre], ft[pre]
        res[c] = {
            "overlap": [str(j.index.min()), str(j.index.max())], "bars": int(len(j)),
            "basis_median": float(basis.median()), "basis_mean_abs": float(basis.abs().mean()),
            "basis_p01": float(basis.quantile(0.01)), "basis_p99": float(basis.quantile(0.99)),
            "basis_median_by_year": {int(k): float(v) for k, v in by_year.items()},
            "top_abs_basis": {str(k): float(basis[k]) for k in top.index},
            "corr_m15": float(rs.corr(rp)), "corr_h4": float(hrs.corr(hrp)), "h4_tracking_error_vs_vol": float(te),
            "wick_low_div_gt_0p5pct": float((low_div > 0.005).mean()), "wick_high_div_gt_0p5pct": float((high_div > 0.005).mean()),
            "wick_low_div_p999": float(low_div.quantile(0.999)),
            "h4_stop_hits_spot": int((hit_s & valid).sum()), "h4_stop_hits_perp": int((hit_p & valid).sum()),
            "h4_stop_disagreement_share_of_hits": float(disagree.sum() / max(either.sum(), 1)),
            "funding_events_pre_selection": int(pre.sum()), "funding_first": str(ft.min()),
            "funding_mean": float(frp.mean()), "funding_mean_abs": float(frp.abs().mean()),
            "funding_annualized_mean": float(frp.mean() * 3 * 365), "funding_share_positive": float((frp > 0).mean()),
            "funding_non_8h_hours_events": int((~ftp.dt.floor("min").dt.hour.isin([0, 8, 16])).sum()),
            "funding_mean_by_year_annualized": {int(y): float(v * 3 * 365) for y, v in frp.groupby(ftp.dt.year).mean().items()},
        }
        if c == "LINKUSDT":
            t = pd.Timestamp("2020-03-12 10:45:00")
            res[c]["link_2020_03_12_1045"] = {"spot": spot.loc[t].to_dict(),
                                              "perp": perp.loc[t].to_dict() if t in perp.index else None}
        r = res[c]
        print(f"{c:9} bars {r['bars']:6d} basis med {r['basis_median']:+.5f} mean|b| {r['basis_mean_abs']:.5f} "
              f"p1/p99 {r['basis_p01']:+.4f}/{r['basis_p99']:+.4f} | corr M15 {r['corr_m15']:.4f} H4 {r['corr_h4']:.5f} "
              f"TE/vol {r['h4_tracking_error_vs_vol']:.3f} | low-wick div>0.5% {r['wick_low_div_gt_0p5pct']:.4%} | "
              f"stop disagree {r['h4_stop_disagreement_share_of_hits']:.2%} of {r['h4_stop_hits_spot']} hits | "
              f"funding mean {r['funding_mean']:+.6f} |.| {r['funding_mean_abs']:.6f} ann {r['funding_annualized_mean']:+.1%} "
              f"pos {r['funding_share_positive']:.0%} non8h {r['funding_non_8h_hours_events']}")
    (ROOT / "docs/reports/crypto_spot_vs_perp.json").write_text(json.dumps(res, indent=1, default=str))
    print(json.dumps({c: {"by_year": res[c]["basis_median_by_year"], "top": res[c]["top_abs_basis"],
                          "funding_by_year": res[c]["funding_mean_by_year_annualized"]} for c in COINS}, indent=0))
    print("LINK bar:", res["LINKUSDT"].get("link_2020_03_12_1045"))


if __name__ == "__main__":
    main()
