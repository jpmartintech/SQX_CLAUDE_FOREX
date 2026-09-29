"""Walk-forward procedure evaluation on synthetic markets."""
import numpy as np
import pandas as pd
import pytest

from conftest import make_config, synthetic_raw_m15
from sqxf.backtest.evaluator import Costs, build_market
from sqxf.data.m15 import canonicalize, validate_m15
from sqxf.funnel.wf_procedure import folds, generate, permute_m15, run_procedure, select_top_k, truncate_m15

CFG = {"seed": 5, "exec_timeframe_train": "H1", "exec_timeframe_oos": "M15", "days_per_year": 260,
       "folds": {"oos_years": [2012], "train_years": 2, "train_blocks": 2},
       "genetic": {"population": 60, "generations": 4, "max_unique_evaluations": 250, "elite": 5, "tournament": 3},
       "fitness": {"min_trades_per_block": 5},
       "selection": {"min_trades": 10, "min_profit_factor": 0.0, "min_mean_r": -99.0, "cost_x2_min_mean_r": -99.0,
                     "top_k": 5}}


@pytest.fixture(scope="module")
def m15():
    return canonicalize(synthetic_raw_m15(n_weeks=160, seed=41, start="2010-01-04"), make_config())


def _mk(m15):
    return build_market("EURUSD", m15, Costs(0.0001, 1.0, 0.25))


def test_permutation_keeps_valid_bars_and_shapes_but_breaks_order(m15):
    p = permute_m15(m15, seed=1)
    validate_m15(p.rename(columns={}), "perm")
    assert (p["ts_local"].to_numpy() == m15["ts_local"].to_numpy()).all()
    assert (p["no_trade"].to_numpy() == m15["no_trade"].to_numpy()).all()
    cc = np.sort(np.log(m15["close"] / m15["open"]).to_numpy())
    np.testing.assert_allclose(np.sort(np.log(p["close"] / p["open"]).to_numpy()), cc, atol=1e-12)
    assert not np.allclose(p["close"].to_numpy(), m15["close"].to_numpy())
    pd.testing.assert_frame_equal(permute_m15(m15, seed=1), p)


def test_truncation_removes_later_bars(m15):
    t = truncate_m15(m15, "2011-06-01")
    assert t["ts_local"].max() < pd.Timestamp("2011-06-01") and len(t) < len(m15)


def test_folds_train_strictly_before_oos(m15):
    mk = _mk(m15)
    (f,) = folds(mk, CFG)
    assert f["train"][1] == f["oos"][0]
    assert mk.h1["ts_local"].iat[f["train"][0]] >= pd.Timestamp("2010-01-01")
    assert mk.h1["ts_local"].iat[f["oos"][0]] >= pd.Timestamp("2012-01-01")
    assert f["train_blocks"][0][1] == f["train_blocks"][1][0]


@pytest.mark.parametrize("generator", ["genetic", "random"])
def test_selection_never_sees_the_oos_year(m15, generator):
    """Scrambling every bar from the OOS year on leaves generation and selection identical."""
    mk = _mk(m15)
    (f,) = folds(mk, CFG)
    cut = int(np.searchsorted(m15["ts_local"].to_numpy(), np.datetime64("2012-01-01")))
    scr = m15.copy()
    k = np.arange(cut, len(m15))
    fac = np.exp(np.cumsum(np.random.default_rng(0).normal(0, 3e-3, len(k))))
    for c in ("open", "high", "low", "close"):
        scr.loc[k, c] = m15.loc[k, c].to_numpy() * fac
    mk2 = _mk(scr)
    sa, fa = generate(mk, f, CFG, generator, 9)
    sb, fb = generate(mk2, folds(mk2, CFG)[0], CFG, generator, 9)
    assert [s.canonical_hash for s in sa] == [s.canonical_hash for s in sb]
    np.testing.assert_array_equal(fa, fb)
    ca = select_top_k(mk, f, sa, fa, CFG)
    cb = select_top_k(mk2, folds(mk2, CFG)[0], sb, fb, CFG)
    assert [s.canonical_hash for s in ca] == [s.canonical_hash for s in cb] and len(ca) > 0


def test_procedure_is_deterministic_and_counts(m15):
    mk = _mk(m15)
    a = run_procedure(mk, CFG, "genetic")
    b = run_procedure(mk, CFG, "genetic")
    assert a["evaluated"] == b["evaluated"] and a["oos_trades"] == b["oos_trades"] > 0
    assert a["mean_r_x1"] == b["mean_r_x1"] and a["mean_r_x2"] < a["mean_r_x1"]
    r = run_procedure(mk, CFG, "random")
    assert r["evaluated"] == CFG["genetic"]["max_unique_evaluations"]
    assert len(a["_daily_x1"]) == len(r["_daily_x1"]) > 200
