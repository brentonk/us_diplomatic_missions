"""Orchestrate generation of all data product files."""

from pathlib import Path

from .aggregator import build_monthly_dataset, build_yearly_dataset
from .codebook_builder import build_codebook
from .daily_builder import build_daily_dataset
from .range_builder import build_range_dataset, write_range_csv
from .state_codes import StateCodeResolver


def generate_all_datasets(
    resolver: StateCodeResolver,
    transitions_csv: Path,
    output_dir: Path,
    version: str,
    release_date: str | None = None,
) -> None:
    """Generate all data product files: 9 CSVs and codebook."""
    output_dir.mkdir(parents=True, exist_ok=True)

    for system in ("cow", "gw", "gwm"):
        sys_label = system.upper()
        print(f"  [{sys_label}] Building range dataset...")
        range_rows = build_range_dataset(resolver, transitions_csv, system)

        range_path = output_dir / f"mission_status_range_{system}_v{version}.csv"
        write_range_csv(range_rows, range_path)
        print(f"  [{sys_label}] Wrote {len(range_rows)} rows to {range_path.name}")

        print(f"  [{sys_label}] Expanding to daily (in memory)...")
        daily_df = build_daily_dataset(range_rows, system)
        print(f"  [{sys_label}] {len(daily_df)} daily rows")

        print(f"  [{sys_label}] Aggregating monthly...")
        monthly_df = build_monthly_dataset(daily_df, system)
        monthly_path = output_dir / f"mission_status_monthly_{system}_v{version}.csv"
        monthly_df.to_csv(monthly_path, index=False)
        print(f"  [{sys_label}] Wrote {len(monthly_df)} rows to {monthly_path.name}")

        print(f"  [{sys_label}] Aggregating yearly...")
        yearly_df = build_yearly_dataset(daily_df, system)
        yearly_path = output_dir / f"mission_status_yearly_{system}_v{version}.csv"
        yearly_df.to_csv(yearly_path, index=False)
        print(f"  [{sys_label}] Wrote {len(yearly_df)} rows to {yearly_path.name}")

        del daily_df
        print()

    print("Building codebook...")
    md_path, pdf_path = build_codebook(version, output_dir, release_date=release_date)
    print(f"  {md_path.name} ({md_path.stat().st_size:,} bytes)")
    print(f"  {pdf_path.name} ({pdf_path.stat().st_size:,} bytes)")
