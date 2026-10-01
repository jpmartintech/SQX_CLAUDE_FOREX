"""User-facing evaluator: market preparation, strategy encoding, light/rich/oracle evaluation and metrics."""
from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from sqxf.backtest.kernels import evaluate_batch_light, simulate_rich
from sqxf.backtest.oracle import simulate_oracle
from sqxf.backtest.semantics import AGG, AGG_FIELDS, REASON_NAMES, TRADE_FIELDS
from sqxf.data.h1 import build_h1
from sqxf.data.m15 import DataConfig, load_m15, utc_int_ns
from sqxf.features.bank import ATR_PERIOD, compute_features
from sqxf.features.predicates import pack_bits, predicate_mask, predicate_matrix
from sqxf.grammar import CATALOG, PREDICATE_INDEX
from sqxf.provenance import load_config
from sqxf.strategy.definition import StrategyDefinition

EXEC_TIMEFRAMES = ("H1", "M15")


@dataclass(frozen=True)
class ExecData:
    """Execution bars plus the H1 -> execution-bar index map (``[h1_start[i], h1_end[i])``)."""

    o: np.ndarray
    h: np.ndarray
    l: np.ndarray
    c: np.ndarray
    day_id: np.ndarray
    h1_of: np.ndarray
    h1_start: np.ndarray
    h1_end: np.ndarray
    fr: np.ndarray | None = None       # signed funding rate charged at the open of each execution bar (crypto)
    fr_abs: np.ndarray | None = None   # funding rate charged to BOTH sides at the bar open (before a perpetual existed)

    def funding_arrays(self) -> tuple[np.ndarray, np.ndarray]:
        z = np.zeros(len(self.o))
        return (z if self.fr is None else self.fr), (z if self.fr_abs is None else self.fr_abs)


@dataclass(frozen=True)
class Costs:
    pip: float
    spread_pips: float
    slippage_pips_per_side: float

    @property
    def round_trip(self) -> float:
        """Round-trip cost in price units."""
        return (self.spread_pips + 2.0 * self.slippage_pips_per_side) * self.pip

    @classmethod
    def for_pair(cls, pair: str) -> Costs:
        cfg = load_config("costs")
        p = cfg["pairs"][pair]
        return cls(float(p["pip"]), float(p["spread_pips"]),
                   float(p.get("slippage_pips_per_side", cfg["default_slippage_pips_per_side"])))


@dataclass
class Market:
    pair: str
    h1: pd.DataFrame
    features: dict[str, np.ndarray]
    atr: np.ndarray
    tradable: np.ndarray
    pred_bool: np.ndarray            # bool[len(CATALOG), n_h1]
    pred_bits: np.ndarray            # uint64[len(CATALOG), n_words]
    base_bits: np.ndarray            # uint64[n_words]
    execs: dict[str, ExecData]
    costs: Costs
    t0: int
    t1: int
    risk_per_trade: float
    days_per_year: float
    meta: dict = field(default_factory=dict)
    ts_utc: np.ndarray = field(default=None)  # datetime64[ns] (naive UTC) of every H1 bar
    cost_rel: np.ndarray | None = None        # round-trip cost as a fraction of the entry price, per signal bar (crypto)
    max_lev: float = math.inf                 # max nominal exposure as a multiple of equity (crypto 1.0)

    def cost_rel_array(self) -> np.ndarray:
        return np.zeros(self.n_h1) if self.cost_rel is None else self.cost_rel

    @property
    def n_h1(self) -> int:
        return len(self.h1)


def exec_data(h1: pd.DataFrame, m15: pd.DataFrame | None, timeframe: str) -> ExecData:
    n = len(h1)
    if timeframe == "H1":
        idx = np.arange(n, dtype=np.int64)
        return ExecData(*(h1[k].to_numpy(np.float64) for k in ("open", "high", "low", "close")),
                        day_id=h1["day_id"].to_numpy(np.int64), h1_of=idx, h1_start=idx.copy(), h1_end=idx + 1)
    if timeframe == "M15":
        starts = h1["m15_start"].to_numpy(np.int64)
        ends = h1["m15_end"].to_numpy(np.int64)
        h1_of = np.repeat(np.arange(n, dtype=np.int64), ends - starts)
        return ExecData(*(m15[k].to_numpy(np.float64) for k in ("open", "high", "low", "close")),
                        day_id=m15["day_id"].to_numpy(np.int64), h1_of=h1_of, h1_start=starts, h1_end=ends)
    raise ValueError(f"exec timeframe must be one of {EXEC_TIMEFRAMES}")


def build_market(pair: str, m15: pd.DataFrame, costs: Costs, dev_start_local: pd.Timestamp | None = None,
                 risk_per_trade: float | None = None, days_per_year: float | None = None) -> Market:
    """Prepare H1, features, predicate bitsets and execution arrays from canonical (pre-holdout) M15."""
    ev = load_config("evaluator")
    h1 = build_h1(m15)
    feats = compute_features(h1)
    atr = feats[f"atr.{ATR_PERIOD}"]
    with np.errstate(invalid="ignore"):
        tradable = h1["complete"].to_numpy() & ~h1["no_trade"].to_numpy() & np.isfinite(atr) & (atr > 0)
    pred_bool = predicate_matrix(feats, CATALOG)
    t0 = 0 if dev_start_local is None else int(np.searchsorted(h1["ts_local"].to_numpy(), np.datetime64(dev_start_local)))
    return Market(pair=pair, h1=h1, features=feats, atr=atr, tradable=tradable, pred_bool=pred_bool,
                  pred_bits=pack_bits(pred_bool), base_bits=pack_bits(tradable),
                  execs={tf: exec_data(h1, m15, tf) for tf in EXEC_TIMEFRAMES}, costs=costs, t0=t0, t1=len(h1),
                  risk_per_trade=float(risk_per_trade if risk_per_trade is not None else ev["risk_per_trade"]),
                  days_per_year=float(days_per_year if days_per_year is not None else ev["days_per_year"]),
                  meta={k: v for k, v in m15.attrs.items()},
                  ts_utc=utc_int_ns(h1["ts_utc"]).astype("datetime64[ns]"))


def load_market(pair: str, cfg: DataConfig | None = None) -> Market:
    """Development market for a pair (pre-holdout data, evaluation window from ``dev_start_local``)."""
    cfg = cfg or DataConfig.load()
    return build_market(pair, load_m15(pair, cfg), Costs.for_pair(pair), dev_start_local=cfg.dev_start_local)


# ------------------------------------------------------------------ encoding
def encode(strategies: Sequence[StrategyDefinition]) -> dict[str, np.ndarray]:
    n = len(strategies)
    rows = np.full((n, 4), -1, dtype=np.int64)
    n_rows = np.zeros(n, dtype=np.int64)
    for i, s in enumerate(strategies):
        idx = [PREDICATE_INDEX[p] for p in s.predicates]
        rows[i, : len(idx)] = idx
        n_rows[i] = len(idx)
    return {"rows": rows, "n_rows": n_rows,
            "directions": np.array([s.sign for s in strategies], dtype=np.int64),
            "sl_atr": np.array([s.sl_atr for s in strategies], dtype=np.float64),
            "tp_atr": np.array([s.tp_atr for s in strategies], dtype=np.float64),
            "max_bars": np.array([s.max_bars for s in strategies], dtype=np.int64)}


def _window(market: Market, window: tuple[int, int] | None) -> tuple[int, int]:
    t0, t1 = window if window is not None else (market.t0, market.t1)
    if not 0 <= t0 <= t1 <= market.n_h1:
        raise ValueError("invalid window")
    return int(t0), int(t1)


def _cost(market: Market, cost_multiplier: float) -> float:
    return market.costs.round_trip * float(cost_multiplier)


def _extra(market: Market, ex: ExecData, cost_multiplier: float, funding_multiplier: float, trail_atr: float = 0.0,
           exit_signal: np.ndarray | None = None) -> tuple:
    """Kernel arguments beyond the core contract (all neutral by default): relative costs, funding/swap, funding stress,
    leverage cap, trailing stop in ATR (0 = off) and an exit signal per signal bar (exit at the next execution bar open)."""
    fr, fr_abs = ex.funding_arrays()
    xs = np.zeros(market.n_h1, dtype=np.bool_) if exit_signal is None else np.asarray(exit_signal, dtype=np.bool_)
    return (market.cost_rel_array() * float(cost_multiplier), fr, fr_abs, float(funding_multiplier), float(market.max_lev),
            float(trail_atr), xs)


# ------------------------------------------------------------------ evaluation
def evaluate_light(market: Market, strategies: Sequence[StrategyDefinition], exec_tf: str = "H1", delay: int = 0,
                   cost_multiplier: float = 1.0, window: tuple[int, int] | None = None,
                   funding_multiplier: float = 1.0, trail_atr: float = 0.0,
                   exit_signal: np.ndarray | None = None) -> np.ndarray:
    """Aggregate matrix ``float64[len(strategies), N_AGG]`` (Numba, parallel over strategies)."""
    enc = encode(strategies)
    ex = market.execs[exec_tf]
    t0, t1 = _window(market, window)
    return evaluate_batch_light(market.pred_bits, enc["rows"], enc["n_rows"], market.base_bits, market.atr,
                                ex.h1_start, ex.h1_end, ex.h1_of, ex.o, ex.h, ex.l, ex.c, ex.day_id,
                                enc["directions"], enc["sl_atr"], enc["tp_atr"], enc["max_bars"], int(delay),
                                _cost(market, cost_multiplier), market.risk_per_trade, market.days_per_year, t0, t1,
                                *_extra(market, ex, cost_multiplier, funding_multiplier, trail_atr, exit_signal))


@dataclass
class RichResult:
    strategy: StrategyDefinition
    trades: pd.DataFrame
    agg: np.ndarray
    days_per_year: float = 260.0

    @property
    def metrics(self) -> dict:
        return derive_metrics(self.agg, self.days_per_year)


def evaluate_rich(market: Market, strategy: StrategyDefinition, exec_tf: str = "M15", delay: int = 0,
                  cost_multiplier: float = 1.0, window: tuple[int, int] | None = None,
                  funding_multiplier: float = 1.0, trail_atr: float = 0.0,
                  exit_signal: np.ndarray | None = None) -> RichResult:
    enc = encode([strategy])
    ex = market.execs[exec_tf]
    t0, t1 = _window(market, window)
    rec, agg = simulate_rich(market.pred_bits, enc["rows"][0], enc["n_rows"][0], market.base_bits, market.atr,
                             ex.h1_start, ex.h1_end, ex.h1_of, ex.o, ex.h, ex.l, ex.c, ex.day_id,
                             int(enc["directions"][0]), float(enc["sl_atr"][0]), float(enc["tp_atr"][0]),
                             int(enc["max_bars"][0]), int(delay), _cost(market, cost_multiplier),
                             market.risk_per_trade, market.days_per_year, t0, t1,
                             *_extra(market, ex, cost_multiplier, funding_multiplier, trail_atr, exit_signal))
    return RichResult(strategy, trades_frame(market, rec), agg, market.days_per_year)


def strategy_signal(market: Market, strategy: StrategyDefinition) -> np.ndarray:
    """Boolean signal computed directly from features (independent of the bitsets)."""
    sig = market.tradable.copy()
    for p in strategy.predicates:
        sig &= predicate_mask(market.features[p.feature], p)
    return sig


def evaluate_oracle(market: Market, strategy: StrategyDefinition, exec_tf: str = "M15", delay: int = 0,
                    cost_multiplier: float = 1.0, window: tuple[int, int] | None = None,
                    funding_multiplier: float = 1.0, trail_atr: float = 0.0,
                    exit_signal: np.ndarray | None = None) -> tuple[list[dict], np.ndarray]:
    ex = market.execs[exec_tf]
    t0, t1 = _window(market, window)
    return simulate_oracle(strategy_signal(market, strategy), market.atr, ex.h1_start, ex.h1_end, ex.h1_of,
                           ex.o, ex.h, ex.l, ex.c, ex.day_id, strategy.sign, strategy.sl_atr, strategy.tp_atr,
                           strategy.max_bars, int(delay), _cost(market, cost_multiplier), market.risk_per_trade,
                           market.days_per_year, t0, t1,
                           *_extra(market, ex, cost_multiplier, funding_multiplier, trail_atr, exit_signal))


# ------------------------------------------------------------------ outputs
def trades_frame(market: Market, rec: np.ndarray) -> pd.DataFrame:
    df = pd.DataFrame(rec, columns=list(TRADE_FIELDS))
    for col in ("signal_idx", "entry_idx", "exit_idx", "entry_exec", "exit_exec", "reason"):
        df[col] = df[col].astype(np.int64)
    df["bars_held"] = df["exit_idx"] - df["entry_idx"] + 1
    df["reason"] = df["reason"].map(REASON_NAMES)
    ts = market.ts_utc
    df["entry_time"] = ts[df["entry_idx"].to_numpy()]
    df["exit_bar_time"] = ts[df["exit_idx"].to_numpy()]
    return df


def derive_metrics(agg: np.ndarray, days_per_year: float = 260.0) -> dict:
    """Human metrics from an aggregate vector (R units, equity/drawdown as fractions)."""
    a = {name: float(agg[AGG[name]]) for name in AGG_FIELDS}
    n = a["n_trades"]
    mean_r = a["sum_r"] / n if n else 0.0
    var_r = a["sum_r2"] / n - mean_r * mean_r if n else 0.0
    years = a["n_days"] / days_per_year if a["n_days"] else 0.0
    ret = a["final_equity"] - 1.0
    cagr = a["final_equity"] ** (1 / years) - 1 if years > 0 and a["final_equity"] > 0 else float("nan")
    return {
        "n_trades": int(n),
        "win_rate": a["wins"] / n if n else 0.0,
        "total_r": a["sum_r"],
        "mean_r": mean_r,
        "std_r": math.sqrt(var_r) if var_r > 0 else 0.0,
        "profit_factor": a["gross_win_r"] / a["gross_loss_r"] if a["gross_loss_r"] > 0 else (math.inf if n else 0.0),
        "return": ret,
        "cagr": cagr,
        "max_dd": a["max_dd"],
        "max_dd_mtm": a["max_dd_mtm"],
        "calmar": cagr / a["max_dd"] if a["max_dd"] > 0 and not math.isnan(cagr) else float("nan"),
        "sharpe": a["sharpe"],
        "mean_bars_held": a["bars_held"] / n if n else 0.0,
        "max_consec_losses": int(a["max_consec_losses"]),
        "n_days": int(a["n_days"]),
    }
