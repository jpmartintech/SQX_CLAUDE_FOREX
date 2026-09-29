"""Persistent evaluation ledger (AUTONOMY.md 4.2: every evaluated strategy is counted, never reset).

Append-only JSONL at ``trials/ledger.jsonl`` (versioned in git; moved from ``runs/`` in Phase 2 with its full history).
Every evaluation of a real-data strategy is recorded: engineering (tests, benchmarks) and discovery (generator, funnel).
The Deflated Sharpe uses the grand total (conservative: engineering evaluations also inflate N).
"""
from __future__ import annotations

import json
from datetime import UTC, datetime

from sqxf.provenance import PROJECT_ROOT, code_version

LEDGER = PROJECT_ROOT / "trials" / "ledger.jsonl"


def record_evaluations(purpose: str, pair: str, n_strategies: int, selection: bool, **extra) -> None:
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    row = {"utc": datetime.now(UTC).isoformat(), "purpose": purpose, "pair": pair, "n_strategies": int(n_strategies),
           "used_for_selection": bool(selection), "code_version": code_version(), **extra}
    with LEDGER.open("a") as fh:
        fh.write(json.dumps(row) + "\n")


def total_evaluations(selection_only: bool = False) -> int:
    if not LEDGER.exists():
        return 0
    total = 0
    for line in LEDGER.read_text().splitlines():
        row = json.loads(line)
        if not selection_only or row["used_for_selection"]:
            total += row["n_strategies"]
    return total
