"""Orchestrate generation of all data product files."""

import tarfile
import zipfile
from pathlib import Path

from .aggregator import build_monthly_dataset, build_yearly_dataset
from .codebook_builder import build_codebook
from .daily_builder import build_daily_dataset
from .range_builder import build_range_dataset, write_range_csv
from .state_codes import StateCodeResolver


def _create_archives(output_dir: Path, version: str) -> None:
    """Create ZIP and tar.gz archives of all distributable files."""
    # Collect distributable files (CSVs + codebook)
    csv_files = sorted(output_dir.glob(f"mission_status_*_v{version}.csv"))
    codebook_files = sorted(output_dir.glob(f"CODEBOOK_*_v{version}.*"))
    all_files = csv_files + codebook_files

    zip_path = output_dir / f"us_mission_status_v{version}.zip"
    tar_path = output_dir / f"us_mission_status_v{version}.tar.gz"

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in all_files:
            zf.write(f, f.name)
    print(f"  Created {zip_path.name} ({len(all_files)} files)")

    with tarfile.open(tar_path, "w:gz") as tf:
        for f in all_files:
            tf.add(f, arcname=f.name)
    print(f"  Created {tar_path.name} ({len(all_files)} files)")


def generate_all_datasets(
    resolver: StateCodeResolver,
    transitions_csv: Path,
    output_dir: Path,
    version: str,
) -> None:
    """Generate all data product files: 9 CSVs, codebook, and archives."""
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
    md_path, pdf_path = build_codebook(version, output_dir)
    print(f"  {md_path.name} ({md_path.stat().st_size:,} bytes)")
    print(f"  {pdf_path.name} ({pdf_path.stat().st_size:,} bytes)")
    print()

    print("Creating archives...")
    _create_archives(output_dir, version)
