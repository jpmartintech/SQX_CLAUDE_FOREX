"""Forex overnight swap as funding-style arrays for the evaluator (charged at the open of execution bars).

Rollover = 00:00 local (EET/EEST, i.e. 17:00 New York). Charged at the 00:00 bar of Tuesday, Wednesday and Friday (x1) and
Thursday (x3, the weekend triple swap of the Wednesday rollover); Monday 00:00 carries no rollover. ``swap_long_pips`` and
``swap_short_pips`` are COSTS per night in pips (positive = the position pays; negative = it earns).
Encoding: ``fr * o = (L - S) / 2`` and ``fr_abs * o = (L + S) / 2`` so a long pays L and a short pays S (see oracle contract).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

ROLLOVER_MULT = {1: 1.0, 2: 1.0, 3: 3.0, 4: 1.0}   # weekday of the 00:00 bar (Mon=0): Tue, Wed, Thu (triple), Fri


def forex_swap_arrays(bar_open_local: pd.Series, open_price: np.ndarray, swap_long_pips: float, swap_short_pips: float,
                      pip: float) -> tuple[np.ndarray, np.ndarray]:
    ts = pd.DatetimeIndex(bar_open_local)
    at_midnight = (ts.hour == 0) & (ts.minute == 0)
    mult = np.where(at_midnight, pd.Series(ts.dayofweek).map(ROLLOVER_MULT).fillna(0.0).to_numpy(), 0.0)
    long_p, short_p = swap_long_pips * pip * mult, swap_short_pips * pip * mult
    o = np.asarray(open_price, dtype=float)
    return (long_p - short_p) / 2.0 / o, (long_p + short_p) / 2.0 / o
