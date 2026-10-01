"""Pure-Python reference evaluator (the oracle). Deliberately plain: no bitsets, no Numba, one loop.

Contract (docs/DECISIONS.md):
* A signal at signal bar ``t`` requires ``signal[t]`` (predicates AND tradable) inside the window ``[t0, t1)``.
* Entry at the open of the first execution bar of signal bar ``e = t + 1 + delay``. Nothing happens before it.
* Stop/target from ATR at ``t``, anchored on the real entry price. Per execution bar, in order: funding at the bar open
  (bars after the entry bar); open beyond stop -> exit at open; open beyond target -> exit at open; low/high touches stop ->
  exit at stop (stop wins ties); touches target -> exit.
* Otherwise exit at the close of signal bar ``min(e + max_bars - 1, t1 - 1)`` (TIME, or END when clipped by the window).
* One position at a time; the next signal may be the exit bar itself.
* Costs per trade in price units: ``cost_abs + cost_rel[t] * entry`` (forex: cost_rel = 0; crypto: cost_abs = 0).
* Funding (crypto perpetuals) at the open of every execution bar after the entry bar up to the exit bar, in price units per
  unit of position: ``-direction * fr[k] * o[k] - fr_abs[k] * o[k]`` (longs pay a positive rate; ``fr_abs`` is charged to
  both sides); a payment that is a cost is multiplied by ``funding_mult`` (stress).
* R = (direction * (exit - entry) - cost + funding) / risk. Equity fraction at risk per trade:
  ``frac = min(risk_frac, max_lev * risk / entry)`` (max nominal exposure ``max_lev`` x equity; forex: max_lev = inf).
"""
from __future__ import annotations

import math

import numpy as np

from sqxf.backtest.semantics import AGG, END, N_AGG, STOP, STOP_GAP, TARGET, TARGET_GAP, TIME


def simulate_oracle(signal, atr, h1_start, h1_end, h1_of, o, h, l, c, day_id, direction, sl_atr, tp_atr, max_bars,
                    delay, cost, risk_frac, days_per_year, t0, t1, cost_rel=None, fr=None, fr_abs=None,
                    funding_mult=1.0, max_lev=math.inf):
    """Return ``(trades, agg)``: list of trade dicts and the aggregate vector (numpy float64)."""
    n_sig, n_ex = len(signal), len(o)
    cost_rel = np.zeros(n_sig) if cost_rel is None else cost_rel
    fr = np.zeros(n_ex) if fr is None else fr
    fr_abs = np.zeros(n_ex) if fr_abs is None else fr_abs
    trades = []
    equity = 1.0
    peak_m, dd_m = 1.0, 0.0

    def mark(eq, frac, price, entry, cst, fund, risk):
        return eq * (1.0 + frac * ((direction * (price - entry) - cst + fund) / risk))

    t = t0
    while t < t1:
        if not signal[t]:
            t += 1
            continue
        e = t + 1 + delay
        if e >= t1:
            break
        a = float(atr[t])
        risk = sl_atr * a
        k0 = int(h1_start[e])
        entry = float(o[k0])
        cst = cost + float(cost_rel[t]) * entry
        frac = min(risk_frac, max_lev * risk / entry)
        if direction == 1:
            stop, target = entry - risk, entry + tp_atr * a
        else:
            stop, target = entry + risk, entry - tp_atr * a
        last = e + max_bars - 1
        time_reason = TIME
        if last > t1 - 1:
            last, time_reason = t1 - 1, END
        kend = int(h1_end[last])
        reason, px, k = 0, 0.0, k0
        fund = 0.0
        for k in range(k0, kend):
            if k > k0:
                pay = -direction * float(fr[k]) * float(o[k]) - float(fr_abs[k]) * float(o[k])
                if pay < 0:
                    pay *= funding_mult
                fund += pay
            if direction == 1:
                if o[k] <= stop:
                    reason, px = STOP_GAP, float(o[k])
                elif o[k] >= target:
                    reason, px = TARGET_GAP, float(o[k])
                elif l[k] <= stop:
                    reason, px = STOP, stop
                elif h[k] >= target:
                    reason, px = TARGET, target
            else:
                if o[k] >= stop:
                    reason, px = STOP_GAP, float(o[k])
                elif o[k] <= target:
                    reason, px = TARGET_GAP, float(o[k])
                elif h[k] >= stop:
                    reason, px = STOP, stop
                elif l[k] <= target:
                    reason, px = TARGET, target
            if reason:
                break
            dd_m = max(dd_m, 1.0 - mark(equity, frac, l[k] if direction == 1 else h[k], entry, cst, fund, risk) / peak_m)
            peak_m = max(peak_m, mark(equity, frac, c[k], entry, cst, fund, risk))
        if not reason:
            k = kend - 1
            reason, px = time_reason, float(c[k])
        adverse = px if reason in (STOP, STOP_GAP, TARGET_GAP) else (l[k] if direction == 1 else h[k])
        dd_m = max(dd_m, 1.0 - mark(equity, frac, adverse, entry, cst, fund, risk) / peak_m)
        x = int(h1_of[k])
        r = (direction * (px - entry) - cst + fund) / risk
        equity = equity * (1.0 + frac * r)
        peak_m = max(peak_m, equity)
        dd_m = max(dd_m, 1.0 - equity / peak_m)
        trades.append({"signal_idx": t, "entry_idx": e, "exit_idx": x, "entry_exec": k0, "exit_exec": k,
                       "entry_price": entry, "exit_price": px, "stop": stop, "target": target, "risk": risk,
                       "r": r, "reason": reason, "equity_after": equity, "funding": fund, "frac": frac,
                       "day": int(day_id[k])})
        t = x
    agg = aggregate_trades(trades, day_id, h1_start, h1_end, days_per_year, t0, t1)
    agg[AGG["max_dd_mtm"]] = dd_m
    return trades, agg


def aggregate_trades(trades, day_id, h1_start, h1_end, days_per_year, t0, t1) -> np.ndarray:
    """Aggregate vector from a trade list, computed independently of the kernels (numpy statistics)."""
    agg = np.zeros(N_AGG)
    first_day = int(day_id[h1_start[t0]]) if t1 > t0 else 0
    n_days = int(day_id[h1_end[t1 - 1] - 1]) - first_day + 1 if t1 > t0 else 0
    agg[AGG["n_days"]] = n_days
    agg[AGG["final_equity"]] = 1.0
    if not trades:
        return agg
    rs = [tr["r"] for tr in trades]
    agg[AGG["n_trades"]] = len(rs)
    agg[AGG["wins"]] = sum(1 for r in rs if r > 0)
    s = s2 = gw = gl = 0.0
    for r in rs:
        s += r
        s2 += r * r
        if r > 0:
            gw += r
        elif r < 0:
            gl -= r
    agg[AGG["sum_r"]], agg[AGG["sum_r2"]], agg[AGG["gross_win_r"]], agg[AGG["gross_loss_r"]] = s, s2, gw, gl
    eq_path = [1.0] + [tr["equity_after"] for tr in trades]
    agg[AGG["final_equity"]] = eq_path[-1]
    peak, mdd = 1.0, 0.0
    for v in eq_path:
        peak = max(peak, v)
        mdd = max(mdd, 1.0 - v / peak)
    agg[AGG["max_dd"]] = mdd
    agg[AGG["bars_held"]] = sum(tr["exit_idx"] - tr["entry_idx"] + 1 for tr in trades)
    streak = best = 0
    for r in rs:
        streak = streak + 1 if r < 0 else 0
        best = max(best, streak)
    agg[AGG["max_consec_losses"]] = best
    # Daily returns: equity at the end of each trading day vs the end of the previous day with trades.
    daily = np.zeros(n_days)
    prev_eq = 1.0
    i = 0
    while i < len(trades):
        d = trades[i]["day"]
        j = i
        while j + 1 < len(trades) and trades[j + 1]["day"] == d:
            j += 1
        end_eq = trades[j]["equity_after"]
        daily[d - first_day] = end_eq / prev_eq - 1.0
        prev_eq = end_eq
        i = j + 1
    sd = float(np.std(daily))
    agg[AGG["sharpe"]] = float(np.mean(daily)) / sd * math.sqrt(days_per_year) if sd > 0 else 0.0
    return agg
