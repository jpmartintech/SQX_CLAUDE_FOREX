"""Data guard for Phase S: M15 truncated at the pre-registered data end (2019-01-01); later data is never in memory."""
from __future__ import annotations

import pandas as pd


def truncate_to(m15: pd.DataFrame, end_local: str) -> pd.DataFrame:
    out = m15.loc[m15["ts_local"] < pd.Timestamp(end_local)].reset_index(drop=True)
    out.attrs.update(m15.attrs)
    return out
