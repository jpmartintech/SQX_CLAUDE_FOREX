"""Genetic search over the g1 grammar.

The GA only sees what ``fitness_fn`` returns; the caller decides which windows that function may touch (training windows
only). Every unique strategy is evaluated exactly once (archive keyed by canonical hash) and counted.
Deterministic for a given seed and config.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

import numpy as np

from sqxf.grammar import CATALOG, MAX_BARS_GRID, MAX_PREDICATES, SL_ATR_GRID, TP_ATR_GRID, random_strategy
from sqxf.strategy.definition import DIRECTIONS, StrategyDefinition


@dataclass(frozen=True)
class GAConfig:
    population: int = 1000
    generations: int = 100
    max_unique_evaluations: int = 100_000
    elite: int = 20
    tournament: int = 4
    crossover_rate: float = 0.7
    mutation_rate: float = 0.4
    immigrant_rate: float = 0.1
    max_predicates: int = MAX_PREDICATES

    @classmethod
    def from_dict(cls, d: dict) -> GAConfig:
        return cls(**{k: d[k] for k in cls.__dataclass_fields__ if k in d})


@dataclass
class GAResult:
    archive: dict[str, tuple[StrategyDefinition, float]] = field(default_factory=dict)
    history: list[dict] = field(default_factory=list)

    @property
    def n_evaluated(self) -> int:
        return len(self.archive)


def _pick(rng, grid):
    return grid[int(rng.integers(len(grid)))]


def mutate(rng: np.random.Generator, s: StrategyDefinition, max_predicates: int) -> StrategyDefinition:
    preds = list(s.predicates)
    direction, sl, tp, mb = s.direction, s.sl_atr, s.tp_atr, s.max_bars
    op = int(rng.integers(6))
    if op == 0 or (op == 1 and len(preds) >= max_predicates) or (op == 2 and len(preds) <= 1):
        preds[int(rng.integers(len(preds)))] = CATALOG[int(rng.integers(len(CATALOG)))]
    elif op == 1:
        preds.append(CATALOG[int(rng.integers(len(CATALOG)))])
    elif op == 2:
        preds.pop(int(rng.integers(len(preds))))
    elif op == 3:
        sl = _pick(rng, SL_ATR_GRID)
    elif op == 4:
        tp = _pick(rng, TP_ATR_GRID)
    else:
        mb = _pick(rng, MAX_BARS_GRID)
    return StrategyDefinition(s.pair, direction, tuple(preds), sl, tp, mb, grammar_version=s.grammar_version)


def crossover(rng: np.random.Generator, a: StrategyDefinition, b: StrategyDefinition, max_predicates: int) -> StrategyDefinition:
    pool = list(dict.fromkeys(a.predicates + b.predicates))
    k = int(rng.integers(1, min(max_predicates, len(pool)) + 1))
    chosen = [pool[i] for i in sorted(rng.choice(len(pool), size=k, replace=False))]
    pick = lambda x, y: x if rng.random() < 0.5 else y  # noqa: E731
    direction = a.direction if a.direction == b.direction else DIRECTIONS[int(rng.integers(2))]
    return StrategyDefinition(a.pair, direction, tuple(chosen), pick(a.sl_atr, b.sl_atr), pick(a.tp_atr, b.tp_atr),
                              pick(a.max_bars, b.max_bars), grammar_version=a.grammar_version)


def run_genetic(pair: str, fitness_fn: Callable[[list[StrategyDefinition]], np.ndarray], cfg: GAConfig, seed: int,
                log: Callable[[str], None] | None = None) -> GAResult:
    rng = np.random.default_rng(seed)
    res = GAResult()

    def fresh(make, tries=20):
        for _ in range(tries):
            s = make()
            if s.canonical_hash not in res.archive and s.canonical_hash not in pending:
                return s
        return None

    def evaluate(batch):
        if not batch:
            return
        fit = np.asarray(fitness_fn(batch), dtype=float)
        for s, f in zip(batch, fit, strict=True):
            res.archive[s.canonical_hash] = (s, float(f))

    pending: set[str] = set()
    batch = []
    while len(batch) < min(cfg.population, cfg.max_unique_evaluations):
        s = fresh(lambda: random_strategy(rng, pair, cfg.max_predicates))
        if s is None:
            break
        batch.append(s)
        pending.add(s.canonical_hash)
    evaluate(batch)
    population = [s.canonical_hash for s in batch]

    for gen in range(cfg.generations):
        budget = cfg.max_unique_evaluations - res.n_evaluated
        if budget <= 0:
            break
        fits = np.array([res.archive[h][1] for h in population])
        order = np.argsort(-fits, kind="stable")
        elite = [population[i] for i in order[: cfg.elite]]

        def tournament(population=population, fits=fits):
            idx = rng.integers(len(population), size=cfg.tournament)
            best = idx[np.argmax(fits[idx])]
            return res.archive[population[best]][0]

        pending = set()
        children: list[StrategyDefinition] = []
        n_children = min(cfg.population - len(elite), budget)
        while len(children) < n_children:
            if rng.random() < cfg.immigrant_rate:
                make = lambda: random_strategy(rng, pair, cfg.max_predicates)  # noqa: E731
            else:
                a, b = tournament(), tournament()

                def make(a=a, b=b):
                    child = crossover(rng, a, b, cfg.max_predicates) if rng.random() < cfg.crossover_rate else a
                    if rng.random() < cfg.mutation_rate or child.canonical_hash in res.archive:
                        child = mutate(rng, child, cfg.max_predicates)
                    return child
            s = fresh(make) or fresh(lambda: random_strategy(rng, pair, cfg.max_predicates))
            if s is None:
                break
            children.append(s)
            pending.add(s.canonical_hash)
        evaluate(children)
        population = elite + [s.canonical_hash for s in children]
        fits = np.array([res.archive[h][1] for h in population])
        finite = fits[np.isfinite(fits)]
        row = {"generation": gen + 1, "evaluated": res.n_evaluated,
               "best": float(finite.max()) if len(finite) else None,
               "median": float(np.median(finite)) if len(finite) else None}
        res.history.append(row)
        if log:
            log(f"gen {row['generation']:3d} evaluated {row['evaluated']:7d} best {row['best']} median {row['median']}")
    return res
