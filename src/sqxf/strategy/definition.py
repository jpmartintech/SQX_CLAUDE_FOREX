"""Portable strategy definition with a canonical hash (dedupe and traceability)."""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass

OPERATORS = (">", "<", "==")
DIRECTIONS = ("LONG", "SHORT")


@dataclass(frozen=True, order=True)
class Predicate:
    feature: str
    operator: str
    value: float

    def __post_init__(self):
        if self.operator not in OPERATORS:
            raise ValueError(f"unsupported operator {self.operator!r}")
        object.__setattr__(self, "value", float(self.value))
        if self.feature.startswith("trend.ema_pair."):
            fast, slow = map(int, self.feature.split(".")[2:])
            if fast == slow or self.value != 0 or self.operator == "==":
                raise ValueError("EMA pairs need distinct periods and a '>'/'<' comparison with 0")
            if fast > slow:  # canonical orientation: fast < slow
                object.__setattr__(self, "feature", f"trend.ema_pair.{slow}.{fast}")
                object.__setattr__(self, "operator", "<" if self.operator == ">" else ">")

    def key(self) -> str:
        return f"{self.feature}{self.operator}{self.value!r}"


@dataclass(frozen=True)
class StrategyDefinition:
    """Entry = AND of 1..4 predicates on the closed H1 bar; exits = ATR stop/target and a time stop in H1 bars."""

    pair: str
    direction: str
    predicates: tuple[Predicate, ...]
    sl_atr: float
    tp_atr: float
    max_bars: int
    timeframe: str = "H1"
    grammar_version: str = "g1"

    def __post_init__(self):
        if self.direction not in DIRECTIONS:
            raise ValueError(f"direction must be one of {DIRECTIONS}")
        preds = tuple(sorted(set(self.predicates)))
        if not 1 <= len(preds) <= 4:
            raise ValueError("1..4 distinct predicates required")
        object.__setattr__(self, "predicates", preds)
        object.__setattr__(self, "sl_atr", float(self.sl_atr))
        object.__setattr__(self, "tp_atr", float(self.tp_atr))
        object.__setattr__(self, "max_bars", int(self.max_bars))
        if self.sl_atr <= 0 or self.tp_atr <= 0 or self.max_bars < 1:
            raise ValueError("sl_atr, tp_atr > 0 and max_bars >= 1 required")

    @property
    def sign(self) -> int:
        return 1 if self.direction == "LONG" else -1

    def payload(self) -> dict:
        d = asdict(self)
        d["predicates"] = [asdict(p) for p in self.predicates]
        return d

    @property
    def canonical_json(self) -> str:
        return json.dumps(self.payload(), sort_keys=True, separators=(",", ":"))

    @property
    def canonical_hash(self) -> str:
        """SHA256 of the canonical JSON; cached on the (immutable) instance, outside the dataclass fields."""
        h = self.__dict__.get("_canonical_hash")
        if h is None:
            h = hashlib.sha256(self.canonical_json.encode()).hexdigest()
            object.__setattr__(self, "_canonical_hash", h)
        return h

    @property
    def readable_id(self) -> str:
        return f"SQXF-{self.pair}-{self.timeframe}-{self.canonical_hash[:12]}"

    @classmethod
    def from_json(cls, raw: str) -> StrategyDefinition:
        p = json.loads(raw)
        preds = tuple(Predicate(**x) for x in p.pop("predicates"))
        return cls(predicates=preds, **p)
