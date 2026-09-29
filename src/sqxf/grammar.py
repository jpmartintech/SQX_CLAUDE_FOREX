"""Finite grammar g1: predicate catalog and exit grids, fixed ex ante (never fitted to data)."""
from __future__ import annotations

import numpy as np

from sqxf.features import bank as fb
from sqxf.strategy.definition import DIRECTIONS, Predicate, StrategyDefinition

GRAMMAR_VERSION = "g1"
SL_ATR_GRID = (1.0, 1.5, 2.0, 3.0)
TP_ATR_GRID = (1.0, 1.5, 2.0, 3.0, 4.0)
MAX_BARS_GRID = (12, 24, 48, 96)
MAX_PREDICATES = 4


def _catalog() -> tuple[Predicate, ...]:
    out: list[Predicate] = []

    def add(feature, values=(0.0,), operators=(">", "<")):
        out.extend(Predicate(feature, op, v) for v in values for op in operators)

    for n in fb.EMA_PERIODS:
        add(f"trend.close_ema.{n}")
        for k in fb.SLOPE_HORIZONS:
            add(f"trend.ema_slope.{n}.{k}")
        for slow in fb.EMA_PERIODS:
            if n < slow:
                add(f"trend.ema_pair.{n}.{slow}")
    for n in fb.BREAKOUT_PERIODS:
        add(f"trend.breakout_high.{n}", operators=(">",))
        add(f"trend.breakout_low.{n}", operators=("<",))
    for n in fb.ROC_PERIODS:
        add(f"momentum.roc_atr.{n}", (-1.0, 0.0, 1.0))
    for n in fb.RSI_PERIODS:
        add(f"momentum.rsi.{n}", (30.0, 40.0, 50.0, 60.0, 70.0))
    for n in fb.WILLR_PERIODS:
        add(f"momentum.willr.{n}", (-80.0, -50.0, -20.0))
    for n in fb.ATR_REGIME_PERIODS:
        add(f"volatility.atr_regime.{n}.50")
    for n in fb.BB_PERIODS:
        add(f"volatility.bb_upper.{n}.2", operators=(">",))
        add(f"volatility.bb_lower.{n}.2", operators=("<",))
        add(f"volatility.bb_middle.{n}.2")
        add(f"volatility.compression.{n}.2.1.5", (-1.0, 1.0), ("==",))
    for d in fb.FRACTAL_DEPTHS:
        add(f"structure.last.{d}", (1.0, 2.0, 3.0, 4.0), ("==",))
        add(f"structure.break_high.{d}", operators=(">",))
        add(f"structure.break_low.{d}", operators=("<",))
        add(f"structure.fractal_high.{d}", (1.0,), ("==",))
        add(f"structure.fractal_low.{d}", (1.0,), ("==",))
    return tuple(sorted(set(out)))


CATALOG: tuple[Predicate, ...] = _catalog()
PREDICATE_INDEX: dict[Predicate, int] = {p: i for i, p in enumerate(CATALOG)}


def random_strategy(rng: np.random.Generator, pair: str, max_predicates: int = MAX_PREDICATES) -> StrategyDefinition:
    """Uniform draw: number of predicates, distinct predicates, direction and exit grid values."""
    k = int(rng.integers(1, max_predicates + 1))
    idx = rng.choice(len(CATALOG), size=k, replace=False)
    return StrategyDefinition(
        pair=pair,
        direction=DIRECTIONS[int(rng.integers(2))],
        predicates=tuple(CATALOG[i] for i in idx),
        sl_atr=SL_ATR_GRID[int(rng.integers(len(SL_ATR_GRID)))],
        tp_atr=TP_ATR_GRID[int(rng.integers(len(TP_ATR_GRID)))],
        max_bars=MAX_BARS_GRID[int(rng.integers(len(MAX_BARS_GRID)))],
        grammar_version=GRAMMAR_VERSION,
    )
