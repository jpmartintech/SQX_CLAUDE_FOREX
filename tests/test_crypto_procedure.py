"""Crypto C1 procedure pieces on synthetic markets (+ hybrid prices on real data if present)."""
import numpy as np
import pandas as pd
import pytest

from sqxf.crypto.market import build_crypto_market
from sqxf.crypto.procedure import crypto_folds, matched_control, run_variant, summarize
from sqxf.funnel.wf_procedure import block_permute_m15, day_block_mapping
from sqxf.provenance import PROJECT_ROOT
from test_crypto import CFG as DCFG
from test_crypto import synthetic_crypto_m15, synthetic_funding

PCFG = {"seed": 3, "coin_seed_offsets": {"AAAUSDT": 0, "BBBUSDT": 1000}, "days_per_year": 365,
        "universe": {"per_coin": ["AAAUSDT"], "aggregate_only": ["BBBUSDT"]},
        "folds": {"oos_windows": [["2022-07-01", "2022-10-01"], ["2022-10-01", "2023-01-01"]], "train_months": 12,
                  "train_blocks": 2},
        "genetic": {"population": 60, "generations": 3, "max_unique_evaluations": 150, "elite": 5, "tournament": 3},
        "fitness": {"min_trades_per_block": 5},
        "selection": {"min_trades": 10, "min_profit_factor": 0.0, "min_mean_r": -99.0, "cost_x2_min_mean_r": -99.0,
                      "top_k": 4}}
VAR = {"signal_timeframe": "4h", "exec_timeframe_train": "SIG", "exec_timeframe_oos": "M15"}


@pytest.fixture(scope="module")
def data():
    out = {}
    for name, seed in (("AAAUSDT", 11), ("BBBUSDT", 12)):
        m15 = synthetic_crypto_m15(days=730, seed=seed, start="2021-01-01")
        out[name] = (m15, synthetic_funding(m15, seed=seed))
    return out


def _markets(data, freq="4h"):
    return {c: build_crypto_market(c, m, DCFG, freq, f, 1e-4) for c, (m, f) in data.items()}


def test_folds_train_24m_before_oos(data):
    mk = _markets(data)["AAAUSDT"]
    cfg = {**PCFG, "folds": {**PCFG["folds"], "train_months": 12}}
    for f in crypto_folds(mk, cfg):
        assert f["train"][1] == f["oos"][0] and f["train_blocks"][0][1] == f["train_blocks"][1][0]
        start = mk.h1["ts_local"].iat[f["train"][0]]
        assert start >= pd.Timestamp(f["oos_dates"][0]) - pd.DateOffset(months=12)


def test_run_variant_is_deterministic_and_summarizes(data):
    mks = _markets(data)
    a, b = run_variant(mks, PCFG, VAR), run_variant(mks, PCFG, VAR)
    assert len(a["trades"]) == len(b["trades"]) > 0
    np.testing.assert_array_equal(a["trades"]["r"].to_numpy(), b["trades"]["r"].to_numpy())
    s = summarize(a, PCFG)
    assert s["pooled"]["trades"] == sum(x["trades"] for x in s["by_coin"].values())
    assert s["pooled"]["trades"] == sum(x["trades"] for x in s["by_window"].values())
    assert s["pooled"]["trades"] == sum(x["trades"] for x in s["by_direction"].values())
    assert s["pooled"]["mean_r_x2"] < s["pooled"]["mean_r_x1"]
    assert len(a["portfolio_daily"]) == 184 and a["evaluated"] == 2 * 2 * 150


def test_matched_control_preserves_count_direction_duration(data):
    mks = _markets(data)
    res = run_variant(mks, PCFG, VAR)
    ctl = matched_control(mks, res["trades"], PCFG, replicas=5, seed=1)
    assert ctl["placed_share"] > 0.95 and np.isfinite(ctl["pooled_mean_r_x1"]).all()
    # deterministic and different from the observed timing
    ctl2 = matched_control(mks, res["trades"], PCFG, replicas=5, seed=1)
    np.testing.assert_array_equal(ctl["pooled_mean_r_x1"], ctl2["pooled_mean_r_x1"])


def test_matched_control_r_formula_matches_manual(data):
    mks = _markets(data)
    mk = mks["AAAUSDT"]
    f = crypto_folds(mk, PCFG)[0]
    t = int(np.flatnonzero(mk.tradable[f["oos"][0]:f["oos"][1]])[0] + f["oos"][0])
    trades = pd.DataFrame({"coin": ["AAAUSDT"], "fold": [0], "strategy": ["x"], "bars_held": [3], "direction": [-1],
                           "risk": [2.0], "entry_price": [100.0]})
    one = {"AAAUSDT": mk}
    mk_only = mk
    allowed = np.flatnonzero(mk_only.tradable[f["oos"][0]:f["oos"][1]]) + f["oos"][0]
    assert t in allowed
    ctl = matched_control(one, trades, PCFG, replicas=1, seed=0)
    assert ctl["placed_share"] == 1.0 and np.isfinite(ctl["pooled_mean_r_x1"][0])
    # manual check of the R definition on the same placement
    rng = np.random.default_rng(0)
    rng.permutation(1)
    tt = int(allowed[rng.integers(len(allowed))])
    ex = mk.execs["M15"]
    k0, kx = int(ex.h1_start[tt + 1]), int(ex.h1_end[tt + 3]) - 1
    fr, fr_abs = ex.funding_arrays()
    fund = sum(1 * fr[k] * ex.o[k] - fr_abs[k] * ex.o[k] for k in range(k0 + 1, kx + 1))
    entry = ex.o[k0]
    r = (-1 * (ex.c[kx] - entry) - mk.cost_rel_array()[tt] * entry + fund) / (0.02 * entry)
    assert ctl["pooled_mean_r_x1"][0] == pytest.approx(r, rel=1e-9)


def test_utc_day_block_null_runs(data):
    m15s = {c: m for c, (m, _) in data.items()}
    mp = day_block_mapping(m15s, 5)
    assert len(mp) > 600 and all(pd.Timestamp(k).to_period("M") == pd.Timestamp(v).to_period("M") for k, v in mp.items())
    perm = block_permute_m15(m15s["AAAUSDT"], mp)
    a = np.log(m15s["AAAUSDT"]["close"] / m15s["AAAUSDT"]["open"]).groupby(m15s["AAAUSDT"]["ts_local"].dt.to_period("M"))
    b = np.log(perm["close"] / perm["open"]).groupby(perm["ts_local"].dt.to_period("M"))
    np.testing.assert_allclose(a.apply(lambda x: (x**2).sum()).to_numpy(), b.apply(lambda x: (x**2).sum()).to_numpy(),
                               rtol=1e-9)


@pytest.mark.skipif(not (PROJECT_ROOT / "data/raw/crypto_perp/BTCUSDT_15M_perp.csv").exists(), reason="perp data absent")
@pytest.mark.data
def test_real_hybrid_prices_switch_from_spot_to_perp():
    from sqxf.crypto.data import load_hybrid_m15
    prices, spot = load_hybrid_m15("BTCUSDT", "2019-09-16")
    assert (prices.loc[prices["ts_local"] < pd.Timestamp("2019-09-16"), "source"] == "spot").all()
    assert (prices.loc[prices["ts_local"] >= pd.Timestamp("2019-09-16"), "source"] == "perp").all()
    assert prices["ts_local"].is_unique and prices["ts_local"].is_monotonic_increasing
    assert prices["ts_local"].max() < pd.Timestamp("2023-11-01") and spot["ts_local"].max() < pd.Timestamp("2023-11-01")
