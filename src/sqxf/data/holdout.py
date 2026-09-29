"""Sealed holdout access (AUTONOMY.md 4.3).

The holdout (local time >= ``holdout_start_local``) is evaluated once, at the end of Phase 5. Every access is appended to
``runs/holdout_access.jsonl`` with a reason; nothing else in the package returns holdout bars.
"""
from __future__ import annotations

import json
import os
from datetime import UTC, datetime

import pandas as pd

from sqxf.data.m15 import DataConfig, raw_path, read_raw_csv, validate_m15
from sqxf.provenance import PROJECT_ROOT, code_version, file_sha256

ACCESS_LOG = PROJECT_ROOT / "runs" / "holdout_access.jsonl"
UNSEAL_ENV = "SQXF_UNSEAL_HOLDOUT"


class HoldoutSealedError(PermissionError):
    pass


def load_sealed_holdout(pair: str, reason: str, cfg: DataConfig | None = None) -> pd.DataFrame:
    """Return raw holdout M15 bars. Requires ``SQXF_UNSEAL_HOLDOUT=I_UNDERSTAND`` and a non-empty reason."""
    if os.environ.get(UNSEAL_ENV) != "I_UNDERSTAND" or not reason.strip():
        raise HoldoutSealedError("Holdout is sealed: set SQXF_UNSEAL_HOLDOUT=I_UNDERSTAND and give a reason.")
    cfg = cfg or DataConfig.load()
    src = raw_path(pair, cfg)
    raw = read_raw_csv(src)
    validate_m15(raw, pair)
    ACCESS_LOG.parent.mkdir(parents=True, exist_ok=True)
    with ACCESS_LOG.open("a") as fh:
        fh.write(json.dumps({"utc": datetime.now(UTC).isoformat(), "pair": pair, "reason": reason,
                             "source_sha256": file_sha256(src), "code_version": code_version()}) + "\n")
    return raw.loc[raw["ts_local"] >= cfg.holdout_start_local].reset_index(drop=True)
