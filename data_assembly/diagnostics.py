"""Compare generated panel output against old _mod reference files."""

import csv
from datetime import date
from pathlib import Path


def _load_reference_cow(ref_path: Path) -> list[dict]:
    """Load cowstates_mod.csv as reference data."""
    rows = []
    with open(ref_path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append({
                "code": row["stateabb"].strip(),
                "number": int(row["ccode"]),
                "name": row["statenme"].strip(),
                "start": date(int(row["styear"]), int(row["stmonth"]), int(row["stday"])),
                "end": date(int(row["endyear"]), int(row["endmonth"]), int(row["endday"])),
                "usdos_name": row["state_dept_name"].strip(),
            })
    return rows


def _load_reference_gw(ref_path: Path) -> list[dict]:
    """Load gwstates_mod.csv as reference data."""
    rows = []
    with open(ref_path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append({
                "code": row["stateid"].strip(),
                "number": int(row["statenumber"]),
                "name": row["countryname"].strip(),
                "start": date.fromisoformat(row["start"].strip()),
                "end": date.fromisoformat(row["end"].strip()),
                "usdos_name": row["state_dept_name"].strip(),
            })
    return rows


def print_diagnostics(panel_rows: list[dict], ref_path: Path, system: str) -> None:
    """Print auditable diagnostics comparing panel output to old _mod reference."""
    if system == "cow":
        ref_rows = _load_reference_cow(ref_path)
    else:
        ref_rows = _load_reference_gw(ref_path)

    print(f"\n{'=' * 60}")
    print(f"DIAGNOSTICS: comparing against {ref_path.name}")
    print(f"{'=' * 60}")

    # 1. Code coverage: which codes appear in ref but not in panel (and vice versa)
    ref_codes = {r["code"] for r in ref_rows}
    panel_codes = {r["code"] for r in panel_rows}
    missing_from_panel = ref_codes - panel_codes
    new_in_panel = panel_codes - ref_codes

    if missing_from_panel:
        print(f"\nCodes in reference but NOT in panel ({len(missing_from_panel)}):")
        for code in sorted(missing_from_panel):
            ref_names = {r["name"] for r in ref_rows if r["code"] == code}
            print(f"  {code} ({', '.join(ref_names)})")

    if new_in_panel:
        print(f"\nCodes in panel but NOT in reference ({len(new_in_panel)}):")
        for code in sorted(new_in_panel):
            panel_names = {r["name"] for r in panel_rows if r["code"] == code}
            print(f"  {code} ({', '.join(panel_names)})")

    # 2. USDOS name mapping differences
    # Build ref mapping: (code, interval_midpoint) → usdos_name
    ref_mapping: dict[tuple[str, date], str] = {}
    for r in ref_rows:
        mid = r["start"] + (r["end"] - r["start"]) / 2
        ref_mapping[(r["code"], mid)] = r["usdos_name"]

    # Build panel mapping: for each ref interval midpoint, find the panel's usdos_name
    panel_by_code: dict[str, list[dict]] = {}
    for r in panel_rows:
        panel_by_code.setdefault(r["code"], []).append(r)

    name_diffs: list[str] = []
    name_agreements = 0
    for (code, mid), ref_name in sorted(ref_mapping.items()):
        if code not in panel_by_code:
            continue
        panel_name = None
        for pr in panel_by_code[code]:
            ps = date.fromisoformat(pr["interval_start"])
            pe = date.fromisoformat(pr["interval_end"])
            if ps <= mid <= pe:
                panel_name = pr["usdos_name"]
                break
        if panel_name is None:
            # Mid-date of ref interval not covered by any panel interval
            if ref_name:
                name_diffs.append(
                    f"  {code} on {mid}: ref='{ref_name}', panel has no covering interval"
                )
        elif ref_name != panel_name:
            name_diffs.append(
                f"  {code} on {mid}: ref='{ref_name}', panel='{panel_name}'"
            )
        else:
            name_agreements += 1

    print(f"\nUSDOS name mapping: {name_agreements} agreements, {len(name_diffs)} differences")
    if name_diffs:
        for d in name_diffs:
            print(d)

    # 3. Interval boundary differences
    # Compare raw interval boundaries: ref vs panel
    # The panel splits intervals at transition dates, so it has MORE intervals.
    # We check that ref interval boundaries are a subset of panel boundaries.
    ref_boundaries: dict[str, set[date]] = {}
    for r in ref_rows:
        ref_boundaries.setdefault(r["code"], set()).update([r["start"], r["end"]])

    panel_boundaries: dict[str, set[date]] = {}
    for r in panel_rows:
        ps = date.fromisoformat(r["interval_start"])
        pe = date.fromisoformat(r["interval_end"])
        panel_boundaries.setdefault(r["code"], set()).update([ps, pe])

    boundary_diffs: list[str] = []
    for code in sorted(ref_boundaries.keys() & panel_boundaries.keys()):
        ref_starts = {r["start"] for r in ref_rows if r["code"] == code}
        panel_starts = {date.fromisoformat(r["interval_start"])
                        for r in panel_rows if r["code"] == code}

        # Check if ref interval starts are present in panel
        missing_starts = ref_starts - panel_starts
        if missing_starts:
            boundary_diffs.append(
                f"  {code}: ref start dates not in panel: {sorted(missing_starts)}"
            )

    if boundary_diffs:
        print(f"\nInterval boundary mismatches ({len(boundary_diffs)}):")
        for d in boundary_diffs:
            print(d)
    else:
        common = len(ref_boundaries.keys() & panel_boundaries.keys())
        print(f"\nInterval boundaries: all ref start dates preserved ({common} codes checked)")

    # 4. Summary statistics
    panel_mapped = sum(1 for r in panel_rows if r["usdos_name"])
    panel_unmapped = sum(1 for r in panel_rows if not r["usdos_name"])
    panel_with_status = sum(1 for r in panel_rows if r["us_mission_status"])
    ref_mapped = sum(1 for r in ref_rows if r["usdos_name"])
    ref_unmapped = sum(1 for r in ref_rows if not r["usdos_name"])

    print(f"\nSummary:")
    print(f"  Reference: {len(ref_rows)} rows, {len(ref_codes)} codes, "
          f"{ref_mapped} mapped, {ref_unmapped} unmapped")
    print(f"  Panel: {len(panel_rows)} rows, {len(panel_codes)} codes, "
          f"{panel_mapped} mapped, {panel_unmapped} unmapped, "
          f"{panel_with_status} with status")
