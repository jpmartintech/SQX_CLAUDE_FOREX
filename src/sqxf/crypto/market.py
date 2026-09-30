"""Build an evaluator ``Market`` for a crypto coin: perpetual USDT-M modelled on spot prices.

Signal bars (H1/H4/D1) come from UTC M15; execution on the signal bars (key "SIG", alias "H1" for the generic funnel code)
or on the M15 path ("M15"). Costs are relative (taker fee + liquidity-band slippage, both sides), funding is applied at bar
opens, nominal exposure is capped at ``max_leverage`` x equity, and a coin can only signal on days whose trailing 90-day
median USD volume (up to the previous day) reaches the liquidity threshold.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from sqxf.backtest.evaluator import Costs, ExecData, Market
from sqxf.crypto.data import (
    CryptoConfig,
    build_bars,
    daily_liquidity,
    funding_arrays,
    load_spot_m15,
    read_funding,
    slippage_for,
)
from sqxf.data.m15 import utc_int_ns
from sqxf.features.bank import ATR_PERIOD, compute_features
from sqxf.features.predicates import pack_bits, predicate_matrix
from sqxf.grammar import CATALOG

NO_COST = Costs(pip=0.0, spread_pips=0.0, slippage_pips_per_side=0.0)


def build_crypto_market(coin: str, m15: pd.DataFrame, cfg: CryptoConfig, freq: str = "4h",
                        funding: pd.Series | None = None, funding_mean_abs: float = 0.0) -> Market:
    bars = build_bars(m15, freq)
    feats = compute_features(bars)
    atr = feats[f"atr.{ATR_PERIOD}"]
    liq = daily_liquidity(m15, cfg["liquidity"]["window_days"])
    med = liq["trailing_median"].reindex(bars["day_id"].to_numpy()).to_numpy()
    slip = slippage_for(np.nan_to_num(med, nan=-1.0), cfg["liquidity"]["slippage_bands"])
    liquid = med >= cfg["liquidity"]["min_median_usd"]
    with np.errstate(invalid="ignore"):
        tradable = bars["complete"].to_numpy() & liquid & np.isfinite(atr) & (atr > 0) & np.isfinite(slip)
    fee = cfg["costs"]["taker_fee_per_side"]
    cost_rel = 2.0 * (fee + np.nan_to_num(slip, nan=0.0))
    rates = funding if funding is not None else pd.Series(dtype=float, index=pd.DatetimeIndex([]))
    hours = cfg["funding"]["event_hours_utc"]
    fr_m, fra_m, miss_m = funding_arrays(pd.DatetimeIndex(m15["ts_local"]), rates, funding_mean_abs, hours)
    fr_s, fra_s, miss_s = funding_arrays(pd.DatetimeIndex(bars["ts_local"]), rates, funding_mean_abs, hours)
    idx = np.arange(len(bars), dtype=np.int64)
    sig = ExecData(*(bars[k].to_numpy(np.float64) for k in ("open", "high", "low", "close")),
                   day_id=bars["day_id"].to_numpy(np.int64), h1_of=idx, h1_start=idx.copy(), h1_end=idx + 1,
                   fr=fr_s, fr_abs=fra_s)
    starts, ends = bars["m15_start"].to_numpy(np.int64), bars["m15_end"].to_numpy(np.int64)
    m15x = ExecData(*(m15[k].to_numpy(np.float64) for k in ("open", "high", "low", "close")),
                    day_id=m15["day_id"].to_numpy(np.int64), h1_of=np.repeat(idx, ends - starts), h1_start=starts,
                    h1_end=ends, fr=fr_m, fr_abs=fra_m)
    pred_bool = predicate_matrix(feats, CATALOG)
    ex = cfg["execution"]
    meta = {**m15.attrs, "freq": freq, "calendar": "utc", "funding_unplaced_m15": miss_m, "funding_unplaced_sig": miss_s,
            "funding_mean_abs": funding_mean_abs}
    return Market(pair=coin, h1=bars, features=feats, atr=atr, tradable=tradable, pred_bool=pred_bool,
                  pred_bits=pack_bits(pred_bool), base_bits=pack_bits(tradable),
                  execs={"SIG": sig, "H1": sig, "M15": m15x}, costs=NO_COST, t0=0, t1=len(bars),
                  risk_per_trade=float(ex["risk_per_trade"]), days_per_year=float(ex["days_per_year"]), meta=meta,
                  ts_utc=utc_int_ns(bars["ts_utc"]).astype("datetime64[ns]"), cost_rel=cost_rel,
                  max_lev=float(ex["max_leverage"]))


def funding_mean_abs(rates: pd.Series, end: pd.Timestamp) -> float:
    r = rates[rates.index < end]
    return float(r.abs().mean()) if len(r) else 0.0


def load_crypto_market(coin: str, freq: str = "4h", cfg: CryptoConfig | None = None, repair: bool = True,
                       until: str = "development", reason: str = "") -> Market:
    """Development market (data < selection block by default) with funding and the pre-listing funding rule."""
    cfg = cfg or CryptoConfig.load()
    m15 = load_spot_m15(coin, cfg, repair=repair, until=until, reason=reason)
    end = m15["ts_local"].max() + pd.Timedelta(minutes=15)
    rates = read_funding(coin, cfg, end)
    mean_abs = funding_mean_abs(read_funding(coin, cfg, pd.Timestamp(cfg["funding"]["mean_abs_window_end_utc"])),
                                pd.Timestamp(cfg["funding"]["mean_abs_window_end_utc"]))
    return build_crypto_market(coin, m15, cfg, freq, rates, mean_abs)
