"""Shared constants of the evaluator contract (see docs/DECISIONS.md, "Semántica de ejecución").

Aggregate vector (one float64 row per strategy) and trade record layout, used by the oracle and the Numba kernels.
"""
from __future__ import annotations

# Exit reasons
STOP, STOP_GAP, TARGET, TARGET_GAP, TIME, END = 1, 2, 3, 4, 5, 6
REASON_NAMES = {STOP: "STOP", STOP_GAP: "STOP_GAP", TARGET: "TARGET", TARGET_GAP: "TARGET_GAP", TIME: "TIME", END: "END"}

# Aggregate vector layout
AGG_FIELDS = (
    "n_trades",          # closed trades
    "wins",              # trades with R > 0
    "sum_r",             # sum of R (after costs)
    "sum_r2",            # sum of R^2
    "gross_win_r",       # sum of positive R
    "gross_loss_r",      # -sum of negative R (>= 0)
    "final_equity",      # compounded equity multiple with risk_per_trade (starts at 1.0)
    "max_dd",            # max drawdown of closed-trade equity, fraction of peak (0.05 = 5 %)
    "sharpe",            # annualised Sharpe of daily returns (all trading days in the window)
    "bars_held",         # sum over trades of H1 bars held (exit_idx - entry_idx + 1)
    "n_days",            # trading days in the evaluation window
    "max_consec_losses",
    "max_dd_mtm",        # max drawdown of mark-to-market equity on execution bars (adverse extreme of each bar), fraction
)
AGG = {name: i for i, name in enumerate(AGG_FIELDS)}
N_AGG = len(AGG_FIELDS)

# Trade record layout (float64 columns)
TRADE_FIELDS = ("signal_idx", "entry_idx", "exit_idx", "entry_exec", "exit_exec", "entry_price", "exit_price",
                "stop", "target", "risk", "r", "reason", "equity_after", "funding", "frac")
TRADE = {name: i for i, name in enumerate(TRADE_FIELDS)}
N_TRADE = len(TRADE_FIELDS)
