"""Diagnostic: compare original CSV and assembled data on legation-or-higher ranges.

For each country, computes date ranges where the US has Nonresident Legation
or higher representation, then reports disagreements between the input CSV
and the pipeline's assembled output.
"""

import csv
import json
from pathlib import Path

from .config import PipelineConfig

# Statuses at or above nonresident legation level
LEGATION_OR_HIGHER = frozenset({
    "Embassy",
    "Ambassador Nonresident",
    "Legation",
    "Envoy Nonresident",
})

_PRESENT = (9999, 12, 31)

DateTuple = tuple[int, int, int]
Range = tuple[DateTuple, DateTuple | None]


def _parse_date(date_str: str) -> DateTuple:
    """Parse YYYY, YYYY-MM, or YYYY-MM-DD into a sortable tuple."""
    parts = date_str.split("-")
    year = int(parts[0]) if parts[0] else 0
    month = int(parts[1]) if len(parts) >= 2 else 1
    day = int(parts[2]) if len(parts) >= 3 else 1
    return (year, month, day)


def _fmt(date: DateTuple) -> str:
    return f"{date[0]:04d}-{date[1]:02d}-{date[2]:02d}"


def _compute_ranges(
    events: list[tuple[DateTuple, str]],
) -> list[Range]:
    """Compute date ranges where status is at legation level or higher."""
    ranges: list[Range] = []
    above = False
    start: DateTuple | None = None

    for date, status in events:
        now_above = status in LEGATION_OR_HIGHER
        if now_above and not above:
            start = date
            above = True
        elif not now_above and above:
            ranges.append((start, date))  # type: ignore[arg-type]
            above = False

    if above and start is not None:
        ranges.append((start, None))

    return ranges


def _compute_disagreements(
    csv_ranges: list[Range],
    asm_ranges: list[Range],
) -> tuple[list[Range], list[Range]]:
    """Find intervals where the two range sets disagree.

    Returns (old_only, new_only):
      old_only: original says relations, assembled does not
      new_only: assembled says relations, original does not
    """
    def to_edges(ranges: list[Range]) -> list[tuple[DateTuple, bool]]:
        edges: list[tuple[DateTuple, bool]] = []
        for start, end in ranges:
            edges.append((start, True))
            edges.append((end or _PRESENT, False))
        return edges

    csv_edges = dict(to_edges(csv_ranges))
    asm_edges = dict(to_edges(asm_ranges))

    all_dates = sorted(set(csv_edges) | set(asm_edges))

    csv_above = False
    asm_above = False
    old_only: list[Range] = []
    new_only: list[Range] = []
    disagree_type: str | None = None
    disagree_start: DateTuple = (0, 0, 0)

    for date in all_dates:
        if date in csv_edges:
            csv_above = csv_edges[date]
        if date in asm_edges:
            asm_above = asm_edges[date]

        if csv_above and not asm_above:
            current = "old"
        elif asm_above and not csv_above:
            current = "new"
        else:
            current = None

        if current != disagree_type:
            end = None if date == _PRESENT else date
            if disagree_type == "old":
                old_only.append((disagree_start, end))
            elif disagree_type == "new":
                new_only.append((disagree_start, end))
            disagree_type = current
            disagree_start = date

    if disagree_type == "old":
        old_only.append((disagree_start, None))
    elif disagree_type == "new":
        new_only.append((disagree_start, None))

    return old_only, new_only


def _build_csv_timelines(
    csv_path: Path,
) -> dict[str, list[tuple[DateTuple, str]]]:
    timelines: dict[str, list[tuple[DateTuple, str]]] = {}
    with open(csv_path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            country = row["state_dept_name"]
            year_s = row["year"].strip() if row["year"] else ""
            if not year_s:
                continue
            year = int(year_s)
            month = int(row["month"]) if row["month"].strip() else 1
            day = int(row["day"]) if row["day"].strip() else 1
            timelines.setdefault(country, []).append(
                ((year, month, day), row["status_change"])
            )
    for country in timelines:
        timelines[country].sort()
    return timelines


def _build_assembled_timelines(
    jsonl_path: Path,
) -> dict[str, list[tuple[DateTuple, str]]]:
    exclude = {"rejected", "removed"}
    timelines: dict[str, list[tuple[DateTuple, str]]] = {}
    with open(jsonl_path) as f:
        for line in f:
            record = json.loads(line)
            if record["validation_status"] in exclude:
                continue
            date_str = record.get("date", "")
            status = record.get("new_status", "")
            if not date_str:
                continue
            date = _parse_date(date_str)
            if date[0] == 0:
                continue
            country = record["country"]
            timelines.setdefault(country, []).append((date, status))
    for country in timelines:
        timelines[country].sort()
    return timelines


def _format_range(r: Range) -> str:
    start, end = r
    if end is None:
        return f"{_fmt(start)} to present"
    return f"{_fmt(start)} to {_fmt(end)}"


def run_diagnose(
    config: PipelineConfig,
    countries_filter: list[str] | None = None,
) -> None:
    """Compare original CSV and assembled data on legation-or-higher ranges."""
    csv_path = config.paths.transitions_csv
    jsonl_path = config.paths.output_dir / "final" / "sourcing_records.jsonl"

    if not jsonl_path.exists():
        print(f"Error: assembled output not found at {jsonl_path}")
        print("Run the full pipeline (including 'assemble') first.")
        return

    csv_timelines = _build_csv_timelines(csv_path)
    assembled_timelines = _build_assembled_timelines(jsonl_path)

    countries = sorted(assembled_timelines.keys())
    if countries_filter:
        countries = [c for c in countries if c in countries_filter]

    csv_only = sorted(set(csv_timelines) - set(assembled_timelines))
    n_disagree = 0

    for country in countries:
        csv_events = csv_timelines.get(country, [])
        asm_events = assembled_timelines[country]

        csv_ranges = _compute_ranges(csv_events)
        asm_ranges = _compute_ranges(asm_events)

        old_only, new_only = _compute_disagreements(csv_ranges, asm_ranges)

        if not old_only and not new_only:
            print(f"{country}: No disagreement")
            continue

        n_disagree += 1
        print(f"{country}:")
        for r in old_only:
            print(f"  R=1 OLD -> R=0 NEW: {_format_range(r)}")
        for r in new_only:
            print(f"  R=0 OLD -> R=1 NEW: {_format_range(r)}")

    print()
    print(
        f"{len(countries)} countries checked, "
        f"{n_disagree} with disagreements."
    )
    if csv_only:
        print(f"{len(csv_only)} CSV countries not yet in assembled output.")
