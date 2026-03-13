"""Build interval-level panel datasets with merged US mission status."""

import csv
from datetime import date, timedelta
from pathlib import Path

from .state_codes import Interval, StateCodeResolver


def build_status_timeline(transitions_csv: Path) -> dict[str, list[tuple[date, str]]]:
    """Convert transitions CSV into per-country status step functions.

    Returns {usdos_name: [(date, status), ...]} sorted by date.
    Status on any day = most recent change <= that day. Before first change = None.
    """
    timelines: dict[str, list[tuple[date, str]]] = {}
    with open(transitions_csv, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = row["state_dept_name"].strip()
            year = int(row["year"])
            month_str = row["month"].strip()
            day_str = row["day"].strip()
            month = int(month_str) if month_str else 1
            day = int(day_str) if day_str else 1
            status = row["status_change"].strip()
            timelines.setdefault(name, []).append((date(year, month, day), status))
    for name in timelines:
        timelines[name].sort(key=lambda x: x[0])
    return timelines


def _get_status_at(timeline: list[tuple[date, str]], query_date: date) -> str | None:
    """Get the status at a given date from a sorted timeline."""
    result = None
    for d, status in timeline:
        if d > query_date:
            break
        result = status
    return result


def _collect_split_dates(
    interval: Interval,
    timelines: dict[str, list[tuple[date, str]]],
    resolver: StateCodeResolver,
    system: str,
    code: str,
) -> list[date]:
    """Collect all dates where we need to split a state system interval.

    Includes both transition dates (status changes) and USDOS name-change
    boundaries (before/after dates from the mapping).
    """
    split_dates: set[date] = set()

    # Add USDOS name-change boundaries from the mapping's before/after rules
    candidates = resolver.code_name_entries(system, code)
    for _, rule in candidates:
        if rule is not None:
            if rule.before is not None and interval.start < rule.before <= interval.end:
                split_dates.add(rule.before)
            if rule.after is not None and interval.start < rule.after <= interval.end:
                split_dates.add(rule.after)

    # Add transition dates for all possible USDOS names this code can map to
    seen_names: set[str] = set()
    for name, _ in candidates:
        if name in seen_names:
            continue
        seen_names.add(name)
        timeline = timelines.get(name)
        if timeline:
            for d, _ in timeline:
                if interval.start < d <= interval.end:
                    split_dates.add(d)

    return sorted(split_dates)


def build_panel(
    resolver: StateCodeResolver,
    transitions_csv: Path,
    system: str,
) -> list[dict]:
    """Build interval-level panel for one state system.

    Each output row:
      - code, number, name (from raw state system data)
      - interval_start, interval_end
      - usdos_name (from mapping, or None)
      - us_mission_status (from transitions, or None)

    State system intervals are split at both transition dates and USDOS
    name-change boundaries, so each sub-interval has a constant USDOS name
    and mission status.
    """
    timelines = build_status_timeline(transitions_csv)
    raw_intervals = resolver.intervals(system)
    rows = []

    for code, intervals in sorted(raw_intervals.items()):
        for iv in sorted(intervals, key=lambda x: x.start):
            split_dates = _collect_split_dates(iv, timelines, resolver, system, code)

            if not split_dates:
                # No splits needed — single sub-interval
                usdos_name = resolver.code_to_usdos(system, code, iv.start)
                timeline = timelines.get(usdos_name) if usdos_name else None
                status = _get_status_at(timeline, iv.start) if timeline else None
                rows.append({
                    "code": iv.code,
                    "number": iv.number,
                    "name": iv.name,
                    "interval_start": iv.start.isoformat(),
                    "interval_end": iv.end.isoformat(),
                    "usdos_name": usdos_name or "",
                    "us_mission_status": status or "",
                })
                continue

            # Build sub-intervals from boundaries
            boundaries = [iv.start] + split_dates + [iv.end]
            # Deduplicate and sort (in case a split_date == interval boundary)
            boundaries = sorted(set(boundaries))

            for i in range(len(boundaries) - 1):
                sub_start = boundaries[i]
                # Intermediate sub-intervals end the day before the next boundary
                if i < len(boundaries) - 2:
                    sub_end = boundaries[i + 1] - timedelta(days=1)
                else:
                    sub_end = boundaries[i + 1]

                # Resolve USDOS name at this sub-interval's start date
                usdos_name = resolver.code_to_usdos(system, code, sub_start)
                timeline = timelines.get(usdos_name) if usdos_name else None
                status = _get_status_at(timeline, sub_start) if timeline else None

                rows.append({
                    "code": iv.code,
                    "number": iv.number,
                    "name": iv.name,
                    "interval_start": sub_start.isoformat(),
                    "interval_end": sub_end.isoformat(),
                    "usdos_name": usdos_name or "",
                    "us_mission_status": status or "",
                })

    return rows


def write_panel_csv(rows: list[dict], output_path: Path) -> None:
    """Write panel data to CSV."""
    if not rows:
        return
    fieldnames = ["code", "number", "name", "interval_start", "interval_end",
                  "usdos_name", "us_mission_status"]
    with open(output_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
