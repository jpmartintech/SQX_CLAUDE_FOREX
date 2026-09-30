"""Crypto module: UTC bars without look-ahead, causal liquidity, funding direction, leverage cap, oracle == Numba with
relative costs and funding, end-to-end causality, sealing and derived-copy repairs."""
import math

import numpy as np
import pandas as pd
import pytest

from conftest import raw_available
from sqxf.backtest.evaluator import evaluate_light, evaluate_oracle, evaluate_rich
from sqxf.backtest.kernels import simulate_rich
from sqxf.backtest.oracle import simulate_oracle
from sqxf.backtest.semantics import TRADE
from sqxf.crypto.data import CryptoConfig, build_bars, daily_liquidity, funding_arrays
from sqxf.crypto.market import build_crypto_market
from sqxf.features.bank import compute_features
from sqxf.features.predicates import pack_bits
from sqxf.grammar import random_strategy

CFG = CryptoConfig({
    "liquidity": {"window_days": 10, "min_median_usd": 2.0e7,
                  "slippage_bands": [[5.0e8, 0.0001], [1.0e8, 0.0003], [2.0e7, 0.0005]]},
    "costs": {"taker_fee_per_side": 0.0005},
    "funding": {"event_hours_utc": [0, 8, 16]},
    "execution": {"max_leverage": 1.0, "risk_per_trade": 0.005, "days_per_year": 365},
})


def synthetic_crypto_m15(days=240, seed=0, start="2021-01-01", drop=(), vol_usd=6e7):
    rng = np.random.default_rng(seed)
    ts = pd.date_range(start, periods=days * 96, freq="15min")
    if drop:
        ts = ts.delete(list(drop))
    n = len(ts)
    r = rng.standard_t(4, n) * 0.004
    close = 100 * np.exp(np.cumsum(r))
    open_ = np.r_[100.0, close[:-1]]
    high = np.maximum(open_, close) * np.exp(np.abs(rng.normal(0, 0.002, n)))
    low = np.minimum(open_, close) * np.exp(-np.abs(rng.normal(0, 0.002, n)))
    volume = vol_usd / 96 / close * np.exp(rng.normal(0, 0.5, n))
    df = pd.DataFrame({"ts_local": ts, "open": open_, "high": high, "low": low, "close": close, "volume": volume})
    df["ts_utc"] = df["ts_local"].dt.tz_localize("UTC")
    df["no_trade"] = False
    df["day_id"] = pd.factorize(df["ts_local"].dt.normalize(), sort=True)[0]
    df.attrs["calendar"] = "utc"
    return df


def synthetic_funding(m15, seed=1, start=None):
    idx = m15["ts_local"][(m15["ts_local"].dt.minute == 0) & m15["ts_local"].dt.hour.isin([0, 8, 16])]
    if start is not None:
        idx = idx[idx >= pd.Timestamp(start)]
    rng = np.random.default_rng(seed)
    return pd.Series(rng.normal(1e-4, 2e-4, len(idx)), index=pd.DatetimeIndex(idx))


@pytest.fixture(scope="module")
def m15():
    return synthetic_crypto_m15(drop=(5000, 5001, 12345))


@pytest.fixture(scope="module")
def market(m15):
    f = synthetic_funding(m15, start="2021-03-01")  # perpetual "listed" two months in: pre-listing rule before that
    return build_crypto_market("SYNUSDT", m15, CFG, "4h", f, funding_mean_abs=1.5e-4)


# ------------------------------------------------------------------ bars
@pytest.mark.parametrize("freq,nb", [("1h", 4), ("4h", 16), ("1D", 96)])
def test_bars_match_groupby_and_utc_alignment(m15, freq, nb):
    b = build_bars(m15, freq)
    g = m15.groupby(m15["ts_local"].dt.floor(freq))
    np.testing.assert_array_equal(b["high"].to_numpy(), g["high"].max().to_numpy())
    np.testing.assert_array_equal(b["low"].to_numpy(), g["low"].min().to_numpy())
    np.testing.assert_array_equal(b["open"].to_numpy(), g["open"].first().to_numpy())
    np.testing.assert_array_equal(b["close"].to_numpy(), g["close"].last().to_numpy())
    assert (b["complete"] == (b["n_m15"] == nb)).all() and (~b["complete"]).sum() >= 1
    if freq == "4h":
        assert set(b["ts_local"].dt.hour) == {0, 4, 8, 12, 16, 20}
    if freq == "1D":
        assert (b["ts_local"].dt.hour == 0).all() and (b["close_ts_utc"].dt.hour == 0).all()


@pytest.mark.parametrize("freq", ["1h", "4h", "1D"])
@pytest.mark.parametrize("cut", [3000, 9001])
def test_bars_and_features_prefix_invariance(m15, freq, cut):
    full, part = build_bars(m15, freq), build_bars(m15.iloc[:cut].reset_index(drop=True), freq)
    closed = part["close_ts_utc"] <= m15["ts_utc"].iat[cut]
    cols = ["ts_utc", "open", "high", "low", "close", "n_m15"]
    pd.testing.assert_frame_equal(part.loc[closed, cols].reset_index(drop=True),
                                  full.loc[: closed.sum() - 1, cols].reset_index(drop=True))
    ff, fp = compute_features(full), compute_features(part)
    k = int(closed.sum())
    for name in ff:
        np.testing.assert_array_equal(fp[name][:k], ff[name][:k], err_msg=name)


# ------------------------------------------------------------------ liquidity
def test_liquidity_median_uses_only_previous_days(m15):
    a = daily_liquidity(m15, 10)
    m2 = m15.copy()
    day = 100
    m2.loc[m2["day_id"] >= day, "volume"] *= 1000
    b = daily_liquidity(m2, 10)
    pd.testing.assert_series_equal(a["trailing_median"].loc[:day], b["trailing_median"].loc[:day])
    assert b["trailing_median"].loc[day + 1] > a["trailing_median"].loc[day + 1]


def test_illiquid_days_cannot_signal():
    thin = synthetic_crypto_m15(days=60, vol_usd=5e6)
    mk = build_crypto_market("THIN", thin, CFG, "4h")
    assert not mk.tradable.any()


# ------------------------------------------------------------------ funding and leverage golden cases
def _run(signal, o, h, l, c, atr, direction, fr, fr_abs, funding_mult=1.0, max_lev=math.inf, cost_rel=None,
         sl=1.0, tp=5.0, max_bars=6):
    n = len(o)
    idx = np.arange(n, dtype=np.int64)
    arrs = [np.asarray(x, float) for x in (o, h, l, c)]
    cost_rel = np.zeros(n) if cost_rel is None else cost_rel
    trades, agg = simulate_oracle(signal, np.asarray(atr, float), idx, idx + 1, idx, *arrs, idx, direction, sl, tp,
                                  max_bars, 0, 0.0, 0.005, 365.0, 0, n, cost_rel, fr, fr_abs, funding_mult, max_lev)
    rec, kagg = simulate_rich(pack_bits(signal[None, :]), np.array([0, -1, -1, -1]), 1, pack_bits(np.ones(n, bool)),
                              np.asarray(atr, float), idx, idx + 1, idx, *arrs, idx, direction, sl, tp, max_bars, 0, 0.0,
                              0.005, 365.0, 0, n, cost_rel, fr, fr_abs, funding_mult, max_lev)
    for row, tr in zip(rec, trades, strict=True):
        for name, j in TRADE.items():
            assert row[j] == tr[name], name
    np.testing.assert_allclose(kagg, agg, rtol=1e-12, atol=1e-15)
    return trades


def _flat(n=10, p=100.0):
    o = np.full(n, p)
    return o, o + 0.01, o - 0.01, o.copy()


@pytest.mark.parametrize("direction", [1, -1])
def test_funding_longs_pay_positive_rate_shorts_receive(direction):
    o, h, l, c = _flat()
    sig = np.zeros(10, bool)
    sig[1] = True
    fr = np.zeros(10)
    fr[2], fr[4], fr[6] = 0.001, 0.001, -0.0005   # bar 2 is the entry bar (not charged); 4 and 6 are held
    (tr,) = _run(sig, o, h, l, c, np.full(10, 1.0), direction, fr, np.zeros(10), max_bars=6)
    expected = -direction * (0.001 * 100 - 0.0005 * 100)
    assert tr["entry_idx"] == 2 and tr["funding"] == pytest.approx(expected)
    assert tr["r"] == pytest.approx(expected / 1.0)
    assert (tr["funding"] < 0) == (direction == 1)


def test_funding_stress_multiplies_only_payments_and_pre_listing_rule_hits_both_sides():
    o, h, l, c = _flat()
    sig = np.zeros(10, bool)
    sig[1] = True
    fr = np.zeros(10)
    fr[4], fr[6] = 0.001, -0.001
    long_ = _run(sig, o, h, l, c, np.full(10, 1.0), 1, fr, np.zeros(10), funding_mult=2.0)[0]
    assert long_["funding"] == pytest.approx(-2 * 0.1 + 0.1)      # payment doubled, income unchanged
    fr_abs = np.zeros(10)
    fr_abs[4] = 0.0002
    for d in (1, -1):
        t = _run(sig, o, h, l, c, np.full(10, 1.0), d, np.zeros(10), fr_abs)[0]
        assert t["funding"] == pytest.approx(-0.0002 * 100)


def test_leverage_cap_limits_the_equity_fraction():
    o, h, l, c = _flat()
    h[3] = 100.5
    sig = np.zeros(10, bool)
    sig[1] = True
    # stop 0.1 % away: 0.5 % risk would need 5x notional; capped at 1x -> frac = 1 * 0.1 / 100 = 0.001
    (tr,) = _run(sig, o, h, l, c, np.full(10, 0.1), 1, np.zeros(10), np.zeros(10), max_lev=1.0, tp=2.0)
    assert tr["frac"] == pytest.approx(0.001) and tr["equity_after"] == pytest.approx(1 + 0.001 * tr["r"])


def test_relative_costs_scale_with_price():
    o, h, l, c = _flat()
    sig = np.zeros(10, bool)
    sig[1] = True
    (tr,) = _run(sig, o, h, l, c, np.full(10, 1.0), 1, np.zeros(10), np.zeros(10), cost_rel=np.full(10, 0.0012))
    assert tr["r"] == pytest.approx(-0.0012 * 100 / 1.0)


def test_funding_arrays_place_events_on_bar_opens(m15):
    f = synthetic_funding(m15, start="2021-03-01")
    fr, fr_abs, unplaced = funding_arrays(pd.DatetimeIndex(m15["ts_local"]), f, 1e-4, [0, 8, 16])
    assert unplaced == 0 and np.count_nonzero(fr) == len(f)
    before = m15["ts_local"] < pd.Timestamp("2021-03-01")
    assert (fr_abs[~before.to_numpy()] == 0).all() and (fr_abs[before.to_numpy()] > 0).sum() == 59 * 3


# ------------------------------------------------------------------ oracle == Numba on a crypto market
@pytest.mark.parametrize("exec_tf", ["SIG", "M15"])
@pytest.mark.parametrize("delay,cm,fm", [(0, 1.0, 1.0), (1, 2.0, 2.0)])
def test_crypto_oracle_equals_numba(market, exec_tf, delay, cm, fm):
    rng = np.random.default_rng(5)
    strategies = [random_strategy(rng, "SYNUSDT", max_predicates=2) for _ in range(60)]
    light = evaluate_light(market, strategies, exec_tf=exec_tf, delay=delay, cost_multiplier=cm, funding_multiplier=fm)
    total = funded = 0
    for i, s in enumerate(strategies):
        trades, agg = evaluate_oracle(market, s, exec_tf=exec_tf, delay=delay, cost_multiplier=cm, funding_multiplier=fm)
        rich = evaluate_rich(market, s, exec_tf=exec_tf, delay=delay, cost_multiplier=cm, funding_multiplier=fm)
        df = rich.trades
        assert len(df) == len(trades)
        for col in ("entry_idx", "exit_idx", "entry_price", "exit_price", "r", "funding", "frac", "equity_after"):
            np.testing.assert_array_equal(df[col].to_numpy(), np.array([t[col] for t in trades]), err_msg=col)
        np.testing.assert_allclose(rich.agg, agg, rtol=1e-9, atol=1e-15)
        np.testing.assert_array_equal(light[i], rich.agg)
        if len(df):
            assert (df["exit_idx"] >= df["entry_idx"]).all() and (df["frac"] <= 0.005 + 1e-15).all()
            assert market.tradable[df["signal_idx"]].all()
        total += len(df)
        funded += int((df["funding"] != 0).sum()) if len(df) else 0
    assert total > 300 and funded > 100


def test_crypto_future_perturbation_leaves_past_trades(m15):
    cut = 15000
    scr = m15.copy()
    fac = np.exp(np.cumsum(np.random.default_rng(2).normal(0, 3e-3, len(m15) - cut)))
    for col in ("open", "high", "low", "close"):
        scr.loc[cut:, col] = m15.loc[cut:, col].to_numpy() * fac
    f = synthetic_funding(m15, start="2021-03-01")
    a_m = build_crypto_market("S", m15, CFG, "4h", f, 1.5e-4)
    b_m = build_crypto_market("S", scr, CFG, "4h", f, 1.5e-4)
    t_cut = a_m.execs["M15"].h1_of[cut]
    rng = np.random.default_rng(9)
    n = 0
    for _ in range(40):
        s = random_strategy(rng, "S", max_predicates=2)
        a = evaluate_rich(a_m, s, exec_tf="M15").trades
        b = evaluate_rich(b_m, s, exec_tf="M15").trades
        pd.testing.assert_frame_equal(a[a["exit_idx"] < t_cut].reset_index(drop=True),
                                      b[b["exit_idx"] < t_cut].reset_index(drop=True))
        n += int((a["exit_idx"] < t_cut).sum())
    assert n > 50


# ------------------------------------------------------------------ real data: sealing and repairs
needs_crypto = pytest.mark.skipif(not raw_available("crypto/LINKUSDT"), reason="crypto data not present")


@needs_crypto
@pytest.mark.data
def test_real_link_repair_only_in_derived_copy_and_sealing(monkeypatch):
    from sqxf.crypto.data import SealedError, load_spot_m15, read_spot_csv
    from sqxf.provenance import PROJECT_ROOT
    cfg = CryptoConfig.load()
    bar = pd.Timestamp("2020-03-12 10:45:00")
    raw = read_spot_csv(PROJECT_ROOT / "data/raw/crypto/LINKUSDT_15M.csv")
    assert raw.loc[raw["ts_local"] == bar, "low"].item() == 0.0001  # the source file is untouched
    d = load_spot_m15("LINKUSDT", cfg)
    row = d.loc[d["ts_local"] == bar].iloc[0]
    assert row["low"] == min(row["open"], row["close"]) and row["repaired"] and d["repaired"].sum() == 1
    stress = load_spot_m15("LINKUSDT", cfg, repair=False)
    assert stress.loc[stress["ts_local"] == bar, "low"].item() == 0.0001
    assert d["ts_local"].max() < cfg.selection_start
    with pytest.raises(SealedError):
        load_spot_m15("LINKUSDT", cfg, until="selection")
    monkeypatch.delenv("SQXF_UNSEAL_CRYPTO", raising=False)
    with pytest.raises(SealedError):
        load_spot_m15("LINKUSDT", cfg, until="holdout", reason="x")
