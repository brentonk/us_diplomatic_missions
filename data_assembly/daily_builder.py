"""Expand range datasets into daily rows."""

import polars as pl

from .range_builder import _col_suffix


def build_daily_dataset(range_rows: list[dict], system: str) -> pl.DataFrame:
    """Expand range rows into one row per country-day.

    Used as an intermediate for monthly/yearly aggregation.
    Not written to disk as a data product (too large).
    """
    suffix = _col_suffix(system)
    abbrev_col = f"country_abbrev{suffix}"
    code_col = f"country_code{suffix}"
    name_col = f"country_name{suffix}"

    return (
        pl.DataFrame(range_rows)
        .with_columns(
            pl.col(code_col).cast(pl.Int32),
            pl.col("date_start", "date_end").str.to_date("%Y-%m-%d"),
        )
        .with_columns(date=pl.date_ranges("date_start", "date_end"))
        .explode("date", empty_as_null=False)
        .select(abbrev_col, code_col, name_col, "country_name_usdos", "date", "us_mission_status")
    )
