"""Download Binance USDT-M perpetual M15 klines and funding history from the PUBLIC API (no keys), strictly before the
crypto holdout (2024-11-01 00:00 UTC). Every request carries explicit startTime/endTime < holdout and rows are filtered again
locally. Writes data/raw/crypto_perp/{SYMBOL}_15M_perp.csv, {SYMBOL}_funding.csv, SHA256SUMS.txt and
docs/crypto_perp_manifest.json; appends an access record to trials/crypto_holdout_access.jsonl.

Usage: python scripts/fetch_binance_perp.py [SYMBOL ...]
"""
from __future__ import annotations

import hashlib
import json
import sys
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "raw" / "crypto_perp"
API = "https://fapi.binance.com"
HOLDOUT_MS = int(pd.Timestamp("2024-11-01", tz="UTC").timestamp() * 1000)
SYMBOLS = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "LINKUSDT", "ADAUSDT", "SOLUSDT", "DOGEUSDT", "AVAXUSDT", "TRXUSDT"]
FIRST_MS = int(pd.Timestamp("2019-01-01", tz="UTC").timestamp() * 1000)  # before any USDT-M perpetual existed


def get(path: str, params: dict) -> list:
    url = f"{API}{path}?" + "&".join(f"{k}={v}" for k, v in params.items())
    for attempt in range(6):
        try:
            with urllib.request.urlopen(url, timeout=30) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code in (418, 429) or e.code >= 500:
                time.sleep(5 * (attempt + 1))
                continue
            raise
        except urllib.error.URLError:
            time.sleep(5 * (attempt + 1))
    raise RuntimeError(f"failed: {url}")


def klines(sym: str) -> pd.DataFrame:
    rows, start = [], FIRST_MS
    while start < HOLDOUT_MS:
        batch = get("/fapi/v1/klines", {"symbol": sym, "interval": "15m", "startTime": start,
                                        "endTime": HOLDOUT_MS - 1, "limit": 1500})
        if not batch:
            break
        rows += batch
        start = batch[-1][0] + 15 * 60 * 1000
        time.sleep(0.12)
    df = pd.DataFrame(rows, columns=["open_time", "open", "high", "low", "close", "volume", "close_time", "quote_volume",
                                     "trades", "taker_base", "taker_quote", "ignore"])
    df = df[df["open_time"] < HOLDOUT_MS].drop_duplicates("open_time")
    df["datetime"] = pd.to_datetime(df["open_time"], unit="ms", utc=True).dt.strftime("%Y-%m-%d %H:%M:%S")
    return df[["datetime", "open", "high", "low", "close", "volume", "quote_volume", "trades"]]


def funding(sym: str) -> pd.DataFrame:
    rows, start = [], FIRST_MS
    while start < HOLDOUT_MS:
        batch = get("/fapi/v1/fundingRate", {"symbol": sym, "startTime": start, "endTime": HOLDOUT_MS - 1, "limit": 1000})
        batch = [b for b in batch if b["fundingTime"] < HOLDOUT_MS]
        if not batch:
            break
        rows += batch
        start = batch[-1]["fundingTime"] + 1
        time.sleep(0.12)
    df = pd.DataFrame(rows).drop_duplicates("fundingTime")
    df = df[df["fundingTime"] < HOLDOUT_MS]
    df["datetime"] = pd.to_datetime(df["fundingTime"], unit="ms", utc=True).dt.strftime("%Y-%m-%d %H:%M:%S.%f").str[:-3]
    return df[["datetime", "fundingTime", "fundingRate", "markPrice"]]


def sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main() -> None:
    syms = sys.argv[1:] or SYMBOLS
    OUT.mkdir(parents=True, exist_ok=True)
    for sym in syms:
        k = klines(sym)
        k.to_csv(OUT / f"{sym}_15M_perp.csv", index=False)
        f = funding(sym)
        f.to_csv(OUT / f"{sym}_funding.csv", index=False)
        print(f"{sym}: klines {len(k)} {k['datetime'].iat[0]} -> {k['datetime'].iat[-1]} | funding {len(f)} "
              f"{f['datetime'].iat[0]} -> {f['datetime'].iat[-1]}", flush=True)
    files = sorted(OUT.glob("*.csv"))
    (OUT / "SHA256SUMS.txt").write_text("".join(f"{sha256(p)}  {p.name}\n" for p in files))
    manifest = {"generated_utc": datetime.now(UTC).isoformat(), "source": f"{API} public endpoints (no keys)",
                "holdout_start_utc": "2024-11-01T00:00:00Z", "files": {}}
    for p in files:
        d = pd.read_csv(p)
        manifest["files"][p.name] = {"sha256": sha256(p), "rows": len(d), "first_utc": str(d["datetime"].iat[0]),
                                     "last_utc": str(d["datetime"].iat[-1])}
    (ROOT / "docs" / "crypto_perp_manifest.json").write_text(json.dumps(manifest, indent=1))
    log = ROOT / "trials" / "crypto_holdout_access.jsonl"
    with log.open("a") as fh:
        fh.write(json.dumps({"utc": datetime.now(UTC).isoformat(), "script": "scripts/fetch_binance_perp.py",
                             "purpose": "download perp klines + funding strictly before 2024-11-01 (holdout not downloaded)",
                             "performance_stats_on_holdout": False, "symbols": syms}) + "\n")


if __name__ == "__main__":
    main()
