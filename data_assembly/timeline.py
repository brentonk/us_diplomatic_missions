"""Shared timeline logic for building status step functions from transitions."""

import csv
from datetime import date
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


def get_status_at(timeline: list[tuple[date, str]], query_date: date) -> str | None:
    """Get the status at a given date from a sorted timeline."""
    result = None
    for d, status in timeline:
        if d > query_date:
            break
        result = status
    return result


def collect_split_dates(
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
