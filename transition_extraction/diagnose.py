"""Diagnostic: compare original CSV and assembled data on legation-or-higher ranges.

For each country, computes date ranges where the US has Nonresident Legation
or higher representation, then reports disagreements between the input CSV
and the pipeline's assembled output. Also generates an HTML report with
per-country event-level diffs.
"""

import csv
import json
from difflib import SequenceMatcher
from html import escape
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


def _duration_str(start: DateTuple, end: DateTuple) -> str:
    """Human-readable duration at an appropriate granularity."""
    from datetime import date
    d0 = date(start[0], max(start[1], 1), max(start[2], 1))
    d1 = date(end[0], max(end[1], 1), max(end[2], 1))
    days = (d1 - d0).days
    if days < 0:
        return ""
    if days <= 90:
        return f"({days} day{'s' if days != 1 else ''})"
    months = (end[0] - start[0]) * 12 + (end[1] - start[1])
    if months < 24:
        return f"({months} month{'s' if months != 1 else ''})"
    years = months // 12
    return f"({years} year{'s' if years != 1 else ''})"


def _format_range(r: Range) -> str:
    start, end = r
    if end is None:
        return f"{_fmt(start)} to present"
    return f"{_fmt(start)} to {_fmt(end)} {_duration_str(start, end)}"


Event = tuple[DateTuple, str]


def _diff_events(
    before: list[Event], after: list[Event],
) -> list[tuple[str, str, str]]:
    """Diff two event lists. Returns list of (tag, date_str, status).

    tag is one of: "unchanged", "added", "removed", "modified_old", "modified_new".
    """
    b_strs = [f"{_fmt(d)}|{s}" for d, s in before]
    a_strs = [f"{_fmt(d)}|{s}" for d, s in after]

    sm = SequenceMatcher(None, b_strs, a_strs)
    rows: list[tuple[str, str, str]] = []

    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "equal":
            for k in range(i1, i2):
                d, s = before[k]
                rows.append(("unchanged", _fmt(d), s))
        elif op == "replace":
            for k in range(i1, i2):
                d, s = before[k]
                rows.append(("modified_old", _fmt(d), s))
            for k in range(j1, j2):
                d, s = after[k]
                rows.append(("modified_new", _fmt(d), s))
        elif op == "delete":
            for k in range(i1, i2):
                d, s = before[k]
                rows.append(("removed", _fmt(d), s))
        elif op == "insert":
            for k in range(j1, j2):
                d, s = after[k]
                rows.append(("added", _fmt(d), s))

    return rows


def _generate_diagnose_html(
    csv_timelines: dict[str, list[Event]],
    assembled_timelines: dict[str, list[Event]],
    countries: list[str],
) -> str:
    """Generate HTML report with per-country event-level diffs."""
    country_sections = []
    n_changed = 0
    n_unchanged = 0

    for country in countries:
        before = csv_timelines.get(country, [])
        after = assembled_timelines.get(country, [])
        diff = _diff_events(before, after)

        has_changes = any(t != "unchanged" for t, _, _ in diff)
        if has_changes:
            n_changed += 1
        else:
            n_unchanged += 1

        # Build before table
        before_rows = []
        for d, s in before:
            before_rows.append(
                f"<tr><td>{escape(_fmt(d))}</td><td>{escape(s)}</td></tr>"
            )

        # Build after table from diff
        after_rows = []
        for tag, date_str, status in diff:
            cls = {
                "unchanged": "",
                "added": ' class="diff-added"',
                "removed": ' class="diff-removed"',
                "modified_old": ' class="diff-removed"',
                "modified_new": ' class="diff-added"',
            }.get(tag, "")
            marker = {
                "unchanged": "",
                "added": "+",
                "removed": "&minus;",
                "modified_old": "&minus;",
                "modified_new": "+",
            }.get(tag, "")
            after_rows.append(
                f"<tr{cls}>"
                f"<td class=\"diff-marker\">{marker}</td>"
                f"<td>{escape(date_str)}</td>"
                f"<td>{escape(status)}</td></tr>"
            )

        change_badge = (
            ' <span class="badge changed">changed</span>' if has_changes
            else ""
        )
        anchor = country.lower().replace(" ", "-").replace("(", "").replace(")", "")
        open_attr = " open" if has_changes else ""
        country_sections.append(f"""
<details class="country-section"{open_attr} id="{escape(anchor)}">
  <summary><h3>{escape(country)}{change_badge}</h3></summary>
  <div class="diff-tables">
    <div class="diff-panel">
      <div class="panel-label">CSV (before)</div>
      <table>
        <thead><tr><th>Date</th><th>Status</th></tr></thead>
        <tbody>{"".join(before_rows) if before_rows else "<tr><td colspan='2' class='empty'>No events</td></tr>"}</tbody>
      </table>
    </div>
    <div class="diff-panel">
      <div class="panel-label">Assembled (after)</div>
      <table>
        <thead><tr><th></th><th>Date</th><th>Status</th></tr></thead>
        <tbody>{"".join(after_rows) if after_rows else "<tr><td colspan='3' class='empty'>No events</td></tr>"}</tbody>
      </table>
    </div>
  </div>
</details>""")

    nav_items = []
    for country in countries:
        before = csv_timelines.get(country, [])
        after = assembled_timelines.get(country, [])
        has_changes = any(t != "unchanged" for t, _, _ in _diff_events(before, after))
        anchor = country.lower().replace(" ", "-").replace("(", "").replace(")", "")
        badge = ' <span class="badge changed">changed</span>' if has_changes else ""
        nav_items.append(f'<li><a href="#{escape(anchor)}">{escape(country)}</a>{badge}</li>')

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Diagnostic Report: CSV vs Assembled</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: system-ui, -apple-system, sans-serif; line-height: 1.5; color: #1a1a1a; max-width: 1100px; margin: 0 auto; padding: 2rem 1rem; }}
  h1 {{ margin-bottom: 0.5rem; }}
  .summary {{ background: #f5f5f5; padding: 1rem 1.5rem; border-radius: 8px; margin-bottom: 2rem; }}
  .summary-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 1rem; margin-top: 0.75rem; }}
  .summary-item {{ text-align: center; }}
  .summary-item .number {{ font-size: 2rem; font-weight: 700; }}
  .summary-item .label {{ font-size: 0.85rem; color: #666; }}
  .summary-item.changed .number {{ color: #d97706; }}
  .summary-item.same .number {{ color: #16a34a; }}
  nav ul {{ list-style: none; columns: 3; margin-bottom: 2rem; }}
  nav li {{ margin-bottom: 0.25rem; }}
  nav a {{ color: #2563eb; text-decoration: none; }}
  nav a:hover {{ text-decoration: underline; }}
  .badge {{ font-size: 0.7rem; padding: 0.1rem 0.45rem; border-radius: 10px; font-weight: 600; }}
  .badge.changed {{ background: #fef3c7; color: #92400e; }}
  .country-section {{ margin-bottom: 1.5rem; }}
  .country-section > summary {{ cursor: pointer; padding: 0.4rem 0; border-bottom: 1px solid #e5e7eb; }}
  .country-section > summary::marker {{ color: #9ca3af; }}
  .country-section > summary h3 {{ display: inline; font-size: 1rem; }}
  .diff-tables {{ display: flex; gap: 1.5rem; padding: 0.75rem 0; }}
  .diff-panel {{ flex: 1; min-width: 0; }}
  .panel-label {{ font-size: 0.75rem; font-weight: 600; color: #666; text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 0.3rem; }}
  .diff-tables table {{ width: 100%; border-collapse: collapse; font-size: 0.82rem; }}
  .diff-tables th {{ text-align: left; padding: 0.3rem 0.5rem; background: #f9fafb; border-bottom: 2px solid #e5e7eb; font-weight: 600; color: #374151; }}
  .diff-tables td {{ padding: 0.25rem 0.5rem; border-bottom: 1px solid #f3f4f6; }}
  .diff-tables td.empty {{ color: #9ca3af; font-style: italic; }}
  .diff-marker {{ width: 1.2em; text-align: center; font-weight: 700; }}
  .diff-added {{ background: #f0fdf4; }}
  .diff-added .diff-marker {{ color: #16a34a; }}
  .diff-removed {{ background: #fef2f2; text-decoration: line-through; color: #9ca3af; }}
  .diff-removed .diff-marker {{ color: #dc2626; text-decoration: none; }}
</style>
</head>
<body>
<h1>Diagnostic Report</h1>
<p style="color:#666; margin-bottom:1.5rem;">CSV vs Assembled Event-Level Comparison</p>

<div class="summary">
  <strong>{len(countries)} countries</strong>
  <div class="summary-grid">
    <div class="summary-item changed"><div class="number">{n_changed}</div><div class="label">Changed</div></div>
    <div class="summary-item same"><div class="number">{n_unchanged}</div><div class="label">Unchanged</div></div>
  </div>
</div>

<nav>
  <h3>Countries</h3>
  <ul>{"".join(nav_items)}</ul>
</nav>

{"".join(country_sections)}

<footer style="margin-top:2rem; padding-top:1rem; border-top:1px solid #e5e7eb; color:#999; font-size:0.85rem;">
  Run <code>python main.py assemble</code> to update the assembled data, then <code>python main.py diagnose</code> to regenerate this report.
</footer>
</body>
</html>"""


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

    # Stdout: legation-or-higher range disagreements
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

    # HTML: event-level diff report
    html = _generate_diagnose_html(csv_timelines, assembled_timelines, countries)
    output_path = config.paths.output_dir / "final" / "diagnose_report.html"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        f.write(html)
    print(f"Diagnostic report: {output_path}")
