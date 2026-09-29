"""Numba kernels. Same contract as :mod:`sqxf.backtest.oracle`, verified against it by tests.

* ``_core``: one strategy, one window; optionally records trades. Shared by the light and the rich kernel, so both give
  identical numbers by construction.
* ``evaluate_batch_light``: ``prange`` over a batch of strategies, aggregates only (funnel metrics).
* ``simulate_rich``: one strategy, full trade records.

Signals come from predicate bitsets: ``pred_bits[row, w]`` bit ``b`` is bar ``64 w + b``; ``base_bits`` holds the tradable mask.
"""
from __future__ import annotations

import math

import numpy as np
from numba import njit, prange

from sqxf.backtest.semantics import N_AGG, N_TRADE

_U1 = np.uint64(1)
_U0 = np.uint64(0)


@njit(cache=True, inline="always")
def _ctz(x):
    """Count trailing zeros of a non-zero uint64."""
    n = 0
    if (x & np.uint64(0xFFFFFFFF)) == _U0:
        n += 32
        x >>= np.uint64(32)
    if (x & np.uint64(0xFFFF)) == _U0:
        n += 16
        x >>= np.uint64(16)
    if (x & np.uint64(0xFF)) == _U0:
        n += 8
        x >>= np.uint64(8)
    if (x & np.uint64(0xF)) == _U0:
        n += 4
        x >>= np.uint64(4)
    if (x & np.uint64(0x3)) == _U0:
        n += 2
        x >>= np.uint64(2)
    if (x & _U1) == _U0:
        n += 1
    return n


@njit(cache=True)
def next_signal(pred_bits, rows, n_rows, base_bits, t, t1):
    """First bar ``>= t`` and ``< t1`` whose bits are set in base and every predicate row; ``t1`` if none."""
    while t < t1:
        w = t >> 6
        word = base_bits[w]
        for j in range(n_rows):
            word &= pred_bits[rows[j], w]
        b = t & 63
        if b != 0:
            word &= ~((_U1 << np.uint64(b)) - _U1)
        if word != _U0:
            pos = (w << 6) + _ctz(word)
            return pos if pos < t1 else t1
        t = (w + 1) << 6
    return t1


@njit(cache=True)
def _core(pred_bits, rows, n_rows, base_bits, atr, h1_start, h1_end, h1_of, o, h, l, c, day_id,
          direction, sl_atr, tp_atr, max_bars, delay, cost, risk_frac, days_per_year, t0, t1, record, trades, agg):
    equity = 1.0
    peak = 1.0
    max_dd = 0.0
    n = 0
    wins = 0
    sum_r = 0.0
    sum_r2 = 0.0
    gross_win = 0.0
    gross_loss = 0.0
    bars_held = 0
    streak = 0
    max_streak = 0
    peak_m = 1.0
    max_dd_m = 0.0
    cur_day = -1
    day_start_eq = 1.0
    s_daily = 0.0
    s2_daily = 0.0
    t = next_signal(pred_bits, rows, n_rows, base_bits, t0, t1)
    while t < t1:
        e = t + 1 + delay
        if e >= t1:
            break
        a = atr[t]
        risk = sl_atr * a
        k0 = h1_start[e]
        entry = o[k0]
        if direction == 1:
            stop = entry - risk
            target = entry + tp_atr * a
        else:
            stop = entry + risk
            target = entry - tp_atr * a
        last = e + max_bars - 1
        time_reason = 5
        if last > t1 - 1:
            last = t1 - 1
            time_reason = 6
        kend = h1_end[last]
        reason = 0
        px = 0.0
        k = k0
        while k < kend:
            if direction == 1:
                if o[k] <= stop:
                    reason = 2
                    px = o[k]
                elif o[k] >= target:
                    reason = 4
                    px = o[k]
                elif l[k] <= stop:
                    reason = 1
                    px = stop
                elif h[k] >= target:
                    reason = 3
                    px = target
            else:
                if o[k] >= stop:
                    reason = 2
                    px = o[k]
                elif o[k] <= target:
                    reason = 4
                    px = o[k]
                elif h[k] >= stop:
                    reason = 1
                    px = stop
                elif l[k] <= target:
                    reason = 3
                    px = target
            if reason != 0:
                break
            # Still open after bar k: mark to market (adverse extreme for drawdown, close for the peak).
            adv = l[k] if direction == 1 else h[k]
            mtm = equity * (1.0 + risk_frac * ((direction * (adv - entry) - cost) / risk))
            if 1.0 - mtm / peak_m > max_dd_m:
                max_dd_m = 1.0 - mtm / peak_m
            mtm = equity * (1.0 + risk_frac * ((direction * (c[k] - entry) - cost) / risk))
            if mtm > peak_m:
                peak_m = mtm
            k += 1
        if reason == 0:
            k = kend - 1
            reason = time_reason
            px = c[k]
        # Exit bar: worst price seen before leaving (the exit price itself for stops and gaps).
        if reason == 1 or reason == 2 or reason == 4:
            adv = px
        else:
            adv = l[k] if direction == 1 else h[k]
        mtm = equity * (1.0 + risk_frac * ((direction * (adv - entry) - cost) / risk))
        if 1.0 - mtm / peak_m > max_dd_m:
            max_dd_m = 1.0 - mtm / peak_m
        x = h1_of[k]
        r = (direction * (px - entry) - cost) / risk
        d = day_id[k]
        if d != cur_day:
            if cur_day >= 0:
                dr = equity / day_start_eq - 1.0
                s_daily += dr
                s2_daily += dr * dr
            cur_day = d
            day_start_eq = equity
        equity = equity * (1.0 + risk_frac * r)
        if equity > peak_m:
            peak_m = equity
        if 1.0 - equity / peak_m > max_dd_m:
            max_dd_m = 1.0 - equity / peak_m
        if equity > peak:
            peak = equity
        dd = 1.0 - equity / peak
        if dd > max_dd:
            max_dd = dd
        sum_r += r
        sum_r2 += r * r
        if r > 0:
            wins += 1
            gross_win += r
        elif r < 0:
            gross_loss -= r
        if r < 0:
            streak += 1
            if streak > max_streak:
                max_streak = streak
        else:
            streak = 0
        bars_held += x - e + 1
        if record:
            trades[n, 0] = t
            trades[n, 1] = e
            trades[n, 2] = x
            trades[n, 3] = k0
            trades[n, 4] = k
            trades[n, 5] = entry
            trades[n, 6] = px
            trades[n, 7] = stop
            trades[n, 8] = target
            trades[n, 9] = risk
            trades[n, 10] = r
            trades[n, 11] = reason
            trades[n, 12] = equity
        n += 1
        t = next_signal(pred_bits, rows, n_rows, base_bits, x, t1)
    if cur_day >= 0:
        dr = equity / day_start_eq - 1.0
        s_daily += dr
        s2_daily += dr * dr
    n_days = 0
    if t1 > t0:
        n_days = day_id[h1_end[t1 - 1] - 1] - day_id[h1_start[t0]] + 1
    sharpe = 0.0
    if n_days > 0:
        mean = s_daily / n_days
        var = s2_daily / n_days - mean * mean
        if var > 0.0:
            sharpe = mean / math.sqrt(var) * math.sqrt(days_per_year)
    agg[0] = n
    agg[1] = wins
    agg[2] = sum_r
    agg[3] = sum_r2
    agg[4] = gross_win
    agg[5] = gross_loss
    agg[6] = equity
    agg[7] = max_dd
    agg[8] = sharpe
    agg[9] = bars_held
    agg[10] = n_days
    agg[11] = max_streak
    agg[12] = max_dd_m
    return n


@njit(cache=True, parallel=True)
def evaluate_batch_light(pred_bits, rows, n_rows, base_bits, atr, h1_start, h1_end, h1_of, o, h, l, c, day_id,
                         directions, sl_atr, tp_atr, max_bars, delay, cost, risk_frac, days_per_year, t0, t1):
    """Aggregates for a batch of strategies (one row each). ``rows[s, :n_rows[s]]`` are predicate rows."""
    n_strat = rows.shape[0]
    out = np.zeros((n_strat, N_AGG))
    for s in prange(n_strat):
        dummy = np.empty((0, N_TRADE))
        agg = np.zeros(N_AGG)
        _core(pred_bits, rows[s], n_rows[s], base_bits, atr, h1_start, h1_end, h1_of, o, h, l, c, day_id,
              directions[s], sl_atr[s], tp_atr[s], max_bars[s], delay, cost, risk_frac, days_per_year, t0, t1,
              False, dummy, agg)
        out[s, :] = agg
    return out


@njit(cache=True)
def simulate_rich(pred_bits, rows, n_rows, base_bits, atr, h1_start, h1_end, h1_of, o, h, l, c, day_id,
                  direction, sl_atr, tp_atr, max_bars, delay, cost, risk_frac, days_per_year, t0, t1):
    """Full trade records (``float64[n, N_TRADE]``) and the aggregate vector for one strategy."""
    cap = max(t1 - t0, 0) + 1
    trades = np.empty((cap, N_TRADE))
    agg = np.zeros(N_AGG)
    n = _core(pred_bits, rows, n_rows, base_bits, atr, h1_start, h1_end, h1_of, o, h, l, c, day_id,
              direction, sl_atr, tp_atr, max_bars, delay, cost, risk_frac, days_per_year, t0, t1,
              True, trades, agg)
    return trades[:n].copy(), agg
