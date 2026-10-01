"""States pipeline: M15 -> H1/H4/H8/D1 bars -> per-timeframe descriptors -> aligned on H1 (closed bars only) -> combined."""
from __future__ import annotations

import numpy as np
import pandas as pd

from sqxf.states.bars import align_closed, build_local_bars
from sqxf.states.ribbon import combined_state, descriptors

COLUMNS = ("order", "width_level", "slope_dir", "state")


def compute_states(m15: pd.DataFrame, cfg: dict) -> dict:
    bars = {tf: build_local_bars(m15, tf) for tf in ("H1", "H4", "H8", "D1")}
    desc = {tf: descriptors(b, cfg) for tf, b in bars.items()}
    base = bars["H1"]
    aligned = {}
    for tf in bars:
        aligned[tf] = pd.DataFrame({c: align_closed(base, bars[tf], desc[tf][c].to_numpy()) for c in COLUMNS})
    comb = combined_state(base, aligned)
    return {"bars": bars, "desc": desc, "aligned": aligned, "combined": comb}


def spells(states: np.ndarray) -> pd.DataFrame:
    """Runs of identical non-NaN states: (state, start, length)."""
    s = np.asarray(states, dtype=float)
    valid = ~np.isnan(s)
    change = np.r_[True, (s[1:] != s[:-1]) | (valid[1:] != valid[:-1])]
    starts = np.flatnonzero(change)
    lengths = np.diff(np.r_[starts, len(s)])
    out = pd.DataFrame({"state": s[starts], "start": starts, "length": lengths})
    return out[~np.isnan(out["state"])].reset_index(drop=True)


def describe(states: np.ndarray, n_states: int = 27) -> dict:
    """Descriptive statistics (no returns): time fraction, mean duration, spells, changes per 100 bars, transition matrices."""
    s = np.asarray(states, dtype=float)
    valid = ~np.isnan(s)
    sp = spells(s)
    n_valid = int(valid.sum())
    frac = {int(k): float(v) for k, v in pd.Series(s[valid]).value_counts(normalize=True).items()}
    dur = sp.groupby("state")["length"].agg(["mean", "median", "count"])
    pair = valid[:-1] & valid[1:]
    a, b = s[:-1][pair].astype(int), s[1:][pair].astype(int)
    m = np.zeros((n_states, n_states))
    np.add.at(m, (a, b), 1)
    rows = m.sum(axis=1, keepdims=True)
    p_bar = np.divide(m, rows, out=np.zeros_like(m), where=rows > 0)
    off = m.copy()
    np.fill_diagonal(off, 0)
    rs = off.sum(axis=1, keepdims=True)
    p_change = np.divide(off, rs, out=np.zeros_like(off), where=rs > 0)
    changes = int((a != b).sum())
    return {"valid_bars": n_valid, "fraction": frac,
            "mean_duration": {int(k): float(v) for k, v in dur["mean"].items()},
            "median_duration": {int(k): float(v) for k, v in dur["median"].items()},
            "spells": {int(k): int(v) for k, v in dur["count"].items()},
            "changes_per_100_bars": 100.0 * changes / max(int(pair.sum()), 1),
            "transition_per_bar": p_bar.tolist(), "transition_on_change": p_change.tolist()}
