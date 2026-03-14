"""Expand range datasets into daily rows."""

import numpy as np
import pandas as pd

from .range_builder import _col_suffix


def build_daily_dataset(range_rows: list[dict], system: str) -> pd.DataFrame:
    """Expand range rows into one row per country-day.

    Used as an intermediate for monthly/yearly aggregation.
    Not written to disk as a data product (too large).
    """
    suffix = _col_suffix(system)
    abbrev_col = f"country_abbrev{suffix}"
    code_col = f"country_code{suffix}"
    name_col = f"country_name{suffix}"

    # Pre-compute day counts per range row
    starts_np = np.array([r["date_start"] for r in range_rows], dtype="datetime64[D]")
    ends_np = np.array([r["date_end"] for r in range_rows], dtype="datetime64[D]")
    day_counts = (ends_np - starts_np).astype(int) + 1
    total_days = int(day_counts.sum())

    # Pre-allocate arrays
    dates = np.empty(total_days, dtype="datetime64[D]")
    abbrevs = np.empty(total_days, dtype=object)
    codes = np.empty(total_days, dtype=np.int32)
    names = np.empty(total_days, dtype=object)
    usdos_names = np.empty(total_days, dtype=object)
    statuses = np.empty(total_days, dtype=object)

    pos = 0
    for i, row in enumerate(range_rows):
        n = int(day_counts[i])
        date_range = np.arange(starts_np[i], ends_np[i] + np.timedelta64(1, "D"), dtype="datetime64[D]")
        dates[pos:pos + n] = date_range
        abbrevs[pos:pos + n] = row[abbrev_col]
        codes[pos:pos + n] = row[code_col]
        names[pos:pos + n] = row[name_col]
        usdos_names[pos:pos + n] = row["country_name_usdos"]
        statuses[pos:pos + n] = row["us_mission_status"]
        pos += n

    return pd.DataFrame({
        abbrev_col: abbrevs,
        code_col: codes,
        name_col: names,
        "country_name_usdos": usdos_names,
        "date": pd.to_datetime(dates),
        "us_mission_status": statuses,
    })
