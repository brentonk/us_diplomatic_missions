"""Build mission status range (interval) datasets."""

import csv
from datetime import timedelta
from pathlib import Path

from .state_codes import StateCodeResolver
from .timeline import build_status_timeline, collect_split_dates, get_status_at

# USA codes to exclude from output
_USA_CODES = {"USA"}


def _col_suffix(system: str) -> str:
    """Column name suffix: '_cow' for COW, '_gw' for GW and GWM."""
    return "_cow" if system == "cow" else "_gw"


def build_range_dataset(
    resolver: StateCodeResolver,
    transitions_csv: Path,
    system: str,
) -> list[dict]:
    """Build interval-level range dataset for one state system.

    Each row has a constant USDOS name and mission status. Intervals are
    split at transition dates and USDOS name-change boundaries.
    """
    timelines = build_status_timeline(transitions_csv)
    raw_intervals = resolver.intervals(system)
    suffix = _col_suffix(system)
    rows = []

    for code, intervals in sorted(raw_intervals.items()):
        if code in _USA_CODES:
            continue

        for iv in sorted(intervals, key=lambda x: x.start):
            split_dates = collect_split_dates(iv, timelines, resolver, system, code)

            if not split_dates:
                usdos_name = resolver.code_to_usdos(system, code, iv.start)
                timeline = timelines.get(usdos_name) if usdos_name else None
                status = get_status_at(timeline, iv.start) if timeline else None
                rows.append({
                    f"country_abbrev{suffix}": iv.code,
                    f"country_code{suffix}": iv.number,
                    f"country_name{suffix}": iv.name,
                    "country_name_usdos": usdos_name or "",
                    "date_start": iv.start.isoformat(),
                    "date_end": iv.end.isoformat(),
                    "us_mission_status": status or "None",
                })
                continue

            boundaries = sorted(set([iv.start] + split_dates + [iv.end]))

            for i in range(len(boundaries) - 1):
                sub_start = boundaries[i]
                if i < len(boundaries) - 2:
                    sub_end = boundaries[i + 1] - timedelta(days=1)
                else:
                    sub_end = boundaries[i + 1]

                usdos_name = resolver.code_to_usdos(system, code, sub_start)
                timeline = timelines.get(usdos_name) if usdos_name else None
                status = get_status_at(timeline, sub_start) if timeline else None

                rows.append({
                    f"country_abbrev{suffix}": iv.code,
                    f"country_code{suffix}": iv.number,
                    f"country_name{suffix}": iv.name,
                    "country_name_usdos": usdos_name or "",
                    "date_start": sub_start.isoformat(),
                    "date_end": sub_end.isoformat(),
                    "us_mission_status": status or "None",
                })

    return rows


def write_range_csv(rows: list[dict], output_path: Path) -> None:
    """Write range dataset to CSV."""
    if not rows:
        return
    with open(output_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
