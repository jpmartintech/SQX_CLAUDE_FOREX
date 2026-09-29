import numpy as np
import pytest

from sqxf.data.h1 import build_h1
from sqxf.features.bank import compute_features, confirmed_structure
from sqxf.features.predicates import pack_bits, predicate_matrix, unpack_bits
from sqxf.grammar import CATALOG, random_strategy
from sqxf.strategy.definition import Predicate, StrategyDefinition


@pytest.fixture(scope="module")
def h1_synth():
    from conftest import make_config, synthetic_raw_m15
    from sqxf.data.m15 import canonicalize
    return build_h1(canonicalize(synthetic_raw_m15(n_weeks=40, seed=7), make_config()))


@pytest.mark.parametrize("cut", [300, 1234, 2999])
def test_features_are_prefix_invariant(h1_synth, cut):
    """Features at bar t computed on data truncated after t equal those computed on the full data (no look-ahead)."""
    full = compute_features(h1_synth)
    part = compute_features(h1_synth.iloc[:cut].reset_index(drop=True))
    assert set(full) == set(part)
    for name in full:
        np.testing.assert_array_equal(part[name], full[name][:cut], err_msg=name)


def test_every_catalog_feature_exists_and_fires(h1_synth):
    feats = compute_features(h1_synth)
    m = predicate_matrix(feats, CATALOG)
    missing = [p for p in CATALOG if p.feature not in feats]
    assert not missing
    assert m.any(axis=1).mean() > 0.95  # nearly every predicate fires somewhere on 40 weeks


def test_fractal_is_published_depth_bars_after_pivot():
    high = np.array([1, 2, 3, 9, 3, 2, 1, 1, 1], dtype=float)
    low = high - 0.5
    close = high - 0.25
    out = confirmed_structure(high, low, close, depth=2)
    # Pivot high at index 3 is confirmed at index 5 (= 3 + 2), never earlier.
    assert out["fractal_high"][5] == 1
    assert np.nansum(out["fractal_high"][:5]) == 0
    # The swing is only usable for breakouts strictly after confirmation.
    assert np.isnan(out["break_high"][5]) and out["break_high"][6] == close[6] - 9


def test_bitset_roundtrip_and_layout():
    rng = np.random.default_rng(0)
    m = rng.random((5, 200)) < 0.3
    bits = pack_bits(m)
    assert bits.dtype == np.uint64 and bits.shape == (5, 4)
    np.testing.assert_array_equal(unpack_bits(bits, 200), m)
    one = np.zeros(130, dtype=bool)
    one[[0, 63, 64, 129]] = True
    w = pack_bits(one)
    assert w[0] == (1 | (1 << 63)) and w[1] == 1 and w[2] == 2


def test_next_signal_matches_naive_scan():
    from sqxf.backtest.kernels import next_signal
    rng = np.random.default_rng(3)
    n = 1000
    m = rng.random((3, n)) < 0.5
    base = rng.random(n) < 0.8
    bits, bb = pack_bits(m), pack_bits(base)
    rows = np.array([0, 2, -1, -1], dtype=np.int64)
    sig = base & m[0] & m[2]
    for t in range(0, n, 7):
        for t1 in (n, n - 5, t + 3):
            nxt = np.flatnonzero(sig[t:t1])
            expected = t + nxt[0] if len(nxt) else max(t1, t)
            assert next_signal(bits, rows, 2, bb, t, t1) == min(expected, max(t1, t))


def test_strategy_hash_is_canonical():
    p1, p2 = Predicate("trend.close_ema.20", ">", 0), Predicate("momentum.rsi.14", "<", 30)
    a = StrategyDefinition("EURUSD", "LONG", (p1, p2), 1.5, 2.0, 24)
    b = StrategyDefinition("EURUSD", "LONG", (p2, p1, p2), 1.5, 2, 24.0)
    assert a == b and a.canonical_hash == b.canonical_hash
    assert StrategyDefinition.from_json(a.canonical_json) == a
    # EMA pair orientation is normalised.
    assert Predicate("trend.ema_pair.50.20", ">", 0) == Predicate("trend.ema_pair.20.50", "<", 0)
    s = random_strategy(np.random.default_rng(1), "EURUSD")
    assert StrategyDefinition.from_json(s.canonical_json).canonical_hash == s.canonical_hash
