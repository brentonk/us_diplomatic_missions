"""Aggregate daily mission status data into monthly and yearly datasets."""

import pandas as pd

from .range_builder import _col_suffix
from .status import status_max, status_median, status_min, status_mode


def _aggregate(daily_df: pd.DataFrame, system: str, period_col: str, period_fmt: str) -> pd.DataFrame:
    """Shared aggregation logic for monthly and yearly datasets."""
    suffix = _col_suffix(system)
    abbrev_col = f"country_abbrev{suffix}"
    code_col = f"country_code{suffix}"
    name_col = f"country_name{suffix}"

    df = daily_df.copy()
    df[period_col] = df["date"].dt.strftime(period_fmt)

    def agg_group(g: pd.DataFrame) -> dict:
        statuses = g["us_mission_status"].tolist()
        usdos_vals = g["country_name_usdos"].unique()
        usdos_vals = [v for v in usdos_vals if v]
        return {
            abbrev_col: g[abbrev_col].iloc[0],
            code_col: g[code_col].iloc[0],
            name_col: g[name_col].iloc[0],
            "country_name_usdos": " / ".join(usdos_vals) if usdos_vals else "",
            period_col: g[period_col].iloc[0],
            "us_mission_min": status_min(statuses),
            "us_mission_max": status_max(statuses),
            "us_mission_median": status_median(statuses),
            "us_mission_mode": status_mode(statuses),
        }

    groups = df.groupby([code_col, period_col], sort=True)
    result_rows = [agg_group(g) for _, g in groups]

    columns = [abbrev_col, code_col, name_col, "country_name_usdos",
               period_col, "us_mission_min", "us_mission_max",
               "us_mission_median", "us_mission_mode"]
    return pd.DataFrame(result_rows, columns=columns)


def build_monthly_dataset(daily_df: pd.DataFrame, system: str) -> pd.DataFrame:
    """Aggregate daily data into monthly observations."""
    return _aggregate(daily_df, system, "month", "%Y-%m")


def build_yearly_dataset(daily_df: pd.DataFrame, system: str) -> pd.DataFrame:
    """Aggregate daily data into yearly observations."""
    return _aggregate(daily_df, system, "year", "%Y")
