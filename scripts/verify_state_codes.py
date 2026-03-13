"""Verify new state_system_codes.yaml reproduces old _mod file mappings.

Round-trip test: for each row in old cowstates_mod.csv and gwstates_mod.csv
with non-empty state_dept_name, check that code_to_usdos returns the expected name.
"""

import csv
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from data_assembly.state_codes import StateCodeResolver
COW_MOD = ROOT / "input" / "cowstates_mod.csv"
GW_MOD = ROOT / "input" / "gwstates_mod.csv"
COW_RAW = ROOT / "input" / "cow_statelist2024.csv"
GW_RAW = ROOT / "input" / "ksgmdw.txt"
GW_SUPPLEMENT = ROOT / "input" / "microstates.txt"
MAPPING = ROOT / "input" / "state_system_codes.yaml"
TRANSITIONS = ROOT / "input" / "2024-01-16_transitions.csv"


def mid_date(start: date, end: date) -> date:
    return start + (end - start) / 2


def verify_cow(resolver: StateCodeResolver) -> list[str]:
    """Verify COW mapping against old _mod file."""
    mismatches = []
    with open(COW_MOD, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            expected_name = row["state_dept_name"].strip()
            if not expected_name:
                continue
            code = row["stateabb"].strip()
            start = date(int(row["styear"]), int(row["stmonth"]), int(row["stday"]))
            end = date(int(row["endyear"]), int(row["endmonth"]), int(row["endday"]))
            query = mid_date(start, end)
            actual = resolver.code_to_usdos("cow", code, query)
            if actual != expected_name:
                mismatches.append(
                    f"COW {code} on {query}: expected '{expected_name}', got '{actual}'"
                )
    return mismatches


def verify_gw(resolver: StateCodeResolver) -> list[str]:
    """Verify GW mapping against old _mod file."""
    mismatches = []
    with open(GW_MOD, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            expected_name = row["state_dept_name"].strip()
            if not expected_name:
                continue
            code = row["stateid"].strip()
            start = date.fromisoformat(row["start"].strip())
            end = date.fromisoformat(row["end"].strip())
            query = mid_date(start, end)
            actual = resolver.code_to_usdos("gw", code, query)
            if actual != expected_name:
                mismatches.append(
                    f"GW {code} on {query}: expected '{expected_name}', got '{actual}'"
                )
    return mismatches


def verify_transitions(resolver: StateCodeResolver) -> list[str]:
    """Verify all transition CSV names can resolve to a code (or are known nulls)."""
    known_nulls = {
        "Brunswick and Lüneburg", "Hanseatic Republics", "Hawaii",
        "Holy See", "Nassau", "Republic of Genoa", "Texas",
    }
    issues = []
    seen_names: set[str] = set()
    with open(TRANSITIONS, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = row["state_dept_name"].strip()
            if name in seen_names:
                continue
            seen_names.add(name)
            year = int(row["year"])
            month_str = row["month"].strip()
            day_str = row["day"].strip()
            month = int(month_str) if month_str else 1
            day = int(day_str) if day_str else 1
            query = date(year, month, day)
            if name in known_nulls:
                entry = resolver.mapping.get(name)
                if entry is not None:
                    issues.append(f"'{name}' expected null mapping but found {entry}")
                continue
            cow_result = resolver.usdos_to_code(name, "cow", query)
            gw_result = resolver.usdos_to_code(name, "gw", query)
            if cow_result is None and gw_result is None:
                issues.append(f"'{name}' on {query}: no code in either system")
    return issues


def main():
    resolver = StateCodeResolver(COW_RAW, GW_RAW, MAPPING, gw_supplement=GW_SUPPLEMENT)

    # Validate YAML codes exist in raw data
    warnings = resolver.validate()
    if warnings:
        print("YAML validation warnings:")
        for w in warnings:
            print(f"  {w}")
        print()

    # Round-trip checks
    cow_mismatches = verify_cow(resolver)
    gw_mismatches = verify_gw(resolver)
    transition_issues = verify_transitions(resolver)

    print(f"COW round-trip: {len(cow_mismatches)} mismatches")
    for m in cow_mismatches:
        print(f"  {m}")

    print(f"\nGW round-trip: {len(gw_mismatches)} mismatches")
    for m in gw_mismatches:
        print(f"  {m}")

    print(f"\nTransitions coverage: {len(transition_issues)} issues")
    for i in transition_issues:
        print(f"  {i}")

    total = len(cow_mismatches) + len(gw_mismatches) + len(transition_issues)
    if total == 0:
        print("\nAll checks passed.")
    else:
        print(f"\n{total} total issues found.")


if __name__ == "__main__":
    main()
