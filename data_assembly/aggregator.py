"""Aggregate daily mission status data into monthly and yearly datasets."""

import polars as pl

from .range_builder import _col_suffix
from .status import STATUS_ORDER, STATUS_RANK


def _aggregate(daily_df: pl.DataFrame, system: str, period_col: str, monthly: bool) -> pl.DataFrame:
    """Shared aggregation logic for monthly and yearly datasets."""
    suffix = _col_suffix(system)
    abbrev_col = f"country_abbrev{suffix}"
    code_col = f"country_code{suffix}"
    name_col = f"country_name{suffix}"

    # Integer status ranks (0 = greatest status) and integer period keys
    rank = pl.col("rank")
    year = pl.col("date").dt.year()
    period_key = year * 100 + pl.col("date").dt.month() if monthly else year
    keyed = daily_df.with_columns(
        rank=pl.col("us_mission_status").replace_strict(STATUS_RANK, return_dtype=pl.Int8),
        period_key=period_key,
    )

    usdos = pl.col("country_name_usdos")
    grouped = keyed.group_by(code_col, "period_key").agg(
        pl.col(abbrev_col).first(),
        pl.col(name_col).first(),
        usdos.filter(usdos != "").unique(maintain_order=True).str.join(" / "),
        # "min status" = highest rank number, "max status" = lowest rank number
        us_mission_min=rank.max(),
        us_mission_max=rank.min(),
        # Median: lower middle element, so ties break toward greater status
        us_mission_median=rank.sort().get((pl.len() - 1) // 2),
        # Mode: ties broken toward lowest rank (greatest status)
        us_mission_mode=rank.mode().min(),
    ).sort(code_col, "period_key")

    if monthly:
        period_str = pl.format(
            "{}-{}",
            pl.col("period_key") // 100,
            (pl.col("period_key") % 100).cast(pl.String).str.zfill(2),
        )
    else:
        period_str = pl.col("period_key").cast(pl.String)

    rank_labels = dict(enumerate(STATUS_ORDER))
    stat_cols = ["us_mission_min", "us_mission_max", "us_mission_median", "us_mission_mode"]
    return grouped.select(
        abbrev_col,
        code_col,
        name_col,
        # Null rather than "" so write_csv leaves the field unquoted, as in the range CSVs
        pl.when(usdos != "").then(usdos).alias("country_name_usdos"),
        period_str.alias(period_col),
        *(pl.col(c).replace_strict(rank_labels, return_dtype=pl.String) for c in stat_cols),
    )


def build_monthly_dataset(daily_df: pl.DataFrame, system: str) -> pl.DataFrame:
    """Aggregate daily data into monthly observations."""
    return _aggregate(daily_df, system, "month", monthly=True)


def build_yearly_dataset(daily_df: pl.DataFrame, system: str) -> pl.DataFrame:
    """Aggregate daily data into yearly observations."""
    return _aggregate(daily_df, system, "year", monthly=False)
