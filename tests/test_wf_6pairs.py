"""Phase 2c: block-permutation null and multi-pair procedure on synthetic markets."""
import numpy as np
import pandas as pd
import pytest

from conftest import make_config, synthetic_raw_m15
from sqxf.backtest.evaluator import Costs, build_market
from sqxf.data.m15 import canonicalize, trading_date, validate_m15
from sqxf.funnel.wf_procedure import block_permute_m15, day_block_mapping, run_multi, run_procedure
from test_wf_procedure import CFG


@pytest.fixture(scope="module")
def pairs():
    return {name: canonicalize(synthetic_raw_m15(n_weeks=160, seed=s, start="2010-01-04", drop_frac=0.0005), make_config())
            for name, s in (("AAA", 41), ("BBB", 42))}


def _mk(m15):
    return build_market("EURUSD", m15, Costs(0.0001, 1.0, 0.25))


def _day_shapes(m15):
    td = trading_date(m15["ts_local"]).to_numpy()
    cc = np.log(m15["close"] / m15["open"]).to_numpy()
    return td, cc


def test_block_mapping_is_a_within_month_permutation_shared_by_pairs(pairs):
    mp = day_block_mapping(pairs, seed=3)
    assert sorted(mp.keys()) == sorted(mp.values())
    assert all(pd.Timestamp(k).to_period("M") == pd.Timestamp(v).to_period("M") for k, v in mp.items())
    assert sum(k != v for k, v in mp.items()) > 0.8 * len(mp)
    assert mp == day_block_mapping(pairs, seed=3)


def test_block_permutation_keeps_monthly_volatility_and_moves_whole_days(pairs):
    m15 = pairs["AAA"]
    mp = day_block_mapping(pairs, seed=3)
    out = block_permute_m15(m15, mp)
    validate_m15(out, "perm")
    td, cc0 = _day_shapes(m15)
    _, cc1 = _day_shapes(out)
    month = pd.Series(td).dt.to_period("M").to_numpy()
    rv0 = pd.Series(cc0**2).groupby(month).sum()
    rv1 = pd.Series(cc1**2).groupby(month).sum()
    np.testing.assert_allclose(rv1.to_numpy(), rv0.to_numpy(), rtol=1e-9)  # volatility clustering at month scale kept
    # a moved day carries the whole intraday path of its source day, bar by bar
    tgt, src = next((k, v) for k, v in mp.items() if k != v)
    np.testing.assert_allclose(cc1[td == np.datetime64(tgt)], cc0[td == np.datetime64(src)], atol=1e-12)
    # days outside the mapping keep their own shapes
    fixed = ~np.isin(td, np.array(list(mp.keys()), dtype=td.dtype))
    assert fixed.any()
    np.testing.assert_allclose(cc1[fixed], cc0[fixed], atol=1e-12)
    assert not np.allclose(out["close"], m15["close"])


def test_run_multi_single_pair_reproduces_the_2b_procedure(pairs):
    mk = _mk(pairs["AAA"])
    multi = run_multi({"AAA": mk}, CFG, {"base": CFG["selection"]}, generators=("genetic",))
    single = run_procedure(mk, CFG, "genetic")
    m = multi["genetic"]["base"]
    assert m["oos_trades"] == single["oos_trades"] and m["mean_r_x1"] == single["mean_r_x1"]
    assert m["mean_r_x2"] == single["mean_r_x2"]


def test_run_multi_pools_pairs_and_variants(pairs):
    mks = {k: _mk(v) for k, v in pairs.items()}
    strict = {**CFG["selection"], "cost_x2_min_profit_factor": 1.1, "cost_x2_min_mean_r": 0.0}
    res = run_multi(mks, CFG, {"base": CFG["selection"], "x2": strict})
    for gen in ("genetic", "random"):
        for v in ("base", "x2"):
            r = res[gen][v]
            assert r["oos_trades"] == sum(p["oos_trades"] for p in r["per_pair"].values())
            assert set(r["per_pair"]) == {"AAA", "BBB"} and r["portfolio_days"] > 200
    # the stricter variant can only select a subset of the base candidates' pool -> never more trades per strategy set size
    assert res["genetic"]["x2"]["evaluated"] == res["genetic"]["base"]["evaluated"]
