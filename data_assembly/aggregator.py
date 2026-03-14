"""Aggregate daily mission status data into monthly and yearly datasets."""

import numpy as np
import pandas as pd

from .range_builder import _col_suffix
from .status import STATUS_ORDER, STATUS_RANK


def _aggregate(daily_df: pd.DataFrame, system: str, period_col: str, monthly: bool) -> pd.DataFrame:
    """Shared aggregation logic for monthly and yearly datasets."""
    suffix = _col_suffix(system)
    abbrev_col = f"country_abbrev{suffix}"
    code_col = f"country_code{suffix}"
    name_col = f"country_name{suffix}"

    # Convert status strings to integer ranks once (vectorized)
    status_cat = pd.Categorical(daily_df["us_mission_status"], categories=STATUS_ORDER)
    rank = pd.array(status_cat.codes, dtype=np.int8)

    # Integer period keys (avoids strftime on millions of rows)
    year = daily_df["date"].dt.year
    if monthly:
        period_key = (year * 100 + daily_df["date"].dt.month).astype(np.int32)
    else:
        period_key = year.astype(np.int16)

    keys = [daily_df[code_col], period_key]
    rank_grouped = pd.Series(rank, index=daily_df.index).groupby(keys, sort=True)

    # Min/max status: fully vectorized C-level aggregation
    # "min status" = highest rank number, "max status" = lowest rank number
    r_min = rank_grouped.max()
    r_max = rank_grouped.min()

    # Median: lower interpolation matches original tie-breaking toward greater status
    r_median = rank_grouped.quantile(0.5, interpolation="lower")

    # Mode: most frequent rank, ties broken toward lowest rank (greatest status)
    # Pivot to (n_groups x n_ranks) count matrix, then find first column matching max
    counts = pd.Series(rank, index=daily_df.index).groupby(keys, sort=True).value_counts().unstack(fill_value=0)
    r_mode = counts.eq(counts.max(axis=1), axis=0).idxmax(axis=1)

    # Map integer ranks back to status strings via numpy indexing
    rank_labels = np.array(STATUS_ORDER)

    # Metadata: first value per group for constant columns
    meta_keys = pd.MultiIndex.from_arrays(keys)
    meta = pd.DataFrame({
        abbrev_col: daily_df[abbrev_col].values,
        name_col: daily_df[name_col].values,
        "country_name_usdos": daily_df["country_name_usdos"].values,
    }, index=meta_keys)
    meta_grouped = meta.groupby(level=[0, 1], sort=True)
    first_meta = meta_grouped[[abbrev_col, name_col]].first()
    usdos = meta_grouped["country_name_usdos"].agg(
        lambda x: " / ".join(v for v in x.unique() if v)
    )

    # Format period integers back to strings for output
    period_ints = first_meta.index.get_level_values(1)
    if monthly:
        period_strs = pd.array([f"{p // 100}-{p % 100:02d}" for p in period_ints.unique()], dtype=str)
        period_map = dict(zip(period_ints.unique(), period_strs))
        period_col_vals = period_ints.map(period_map)
    else:
        period_col_vals = period_ints.astype(str)

    result = pd.DataFrame({
        abbrev_col: first_meta[abbrev_col].values,
        code_col: first_meta.index.get_level_values(0),
        name_col: first_meta[name_col].values,
        "country_name_usdos": usdos.values,
        period_col: period_col_vals,
        "us_mission_min": rank_labels[r_min.values],
        "us_mission_max": rank_labels[r_max.values],
        "us_mission_median": rank_labels[r_median.astype(int).values],
        "us_mission_mode": rank_labels[r_mode.values],
    })
    return result


def build_monthly_dataset(daily_df: pd.DataFrame, system: str) -> pd.DataFrame:
    """Aggregate daily data into monthly observations."""
    return _aggregate(daily_df, system, "month", monthly=True)


def build_yearly_dataset(daily_df: pd.DataFrame, system: str) -> pd.DataFrame:
    """Aggregate daily data into yearly observations."""
    return _aggregate(daily_df, system, "year", monthly=False)
