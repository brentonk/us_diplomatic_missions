"""One-time migration: extract USDOS→state system code mapping from old _mod files.

Reads cowstates_mod.csv and gwstates_mod.csv, cross-references against the
transitions CSV, and writes a draft state_system_codes.yaml.
"""

import csv
from collections import defaultdict
from datetime import date
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parent.parent
COW_MOD = ROOT / "input" / "cowstates_mod.csv"
GW_MOD = ROOT / "input" / "gwstates_mod.csv"
COW_RAW = ROOT / "input" / "cow_statelist2024.csv"
GW_RAW = ROOT / "input" / "ksgmdw.txt"
TRANSITIONS = ROOT / "input" / "2024-01-16_transitions.csv"
OUTPUT = ROOT / "input" / "state_system_codes.yaml"


def parse_cow_mod():
    """Extract usdos_name → set of COW codes from cowstates_mod.csv."""
    mapping = defaultdict(set)
    with open(COW_MOD, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = row["state_dept_name"].strip()
            code = row["stateabb"].strip()
            if name:
                mapping[name].add(code)
    return dict(mapping)


def parse_gw_mod():
    """Extract usdos_name → set of GW codes from gwstates_mod.csv."""
    mapping = defaultdict(set)
    with open(GW_MOD, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = row["state_dept_name"].strip()
            code = row["stateid"].strip()
            if name:
                mapping[name].add(code)
    return dict(mapping)


def parse_cow_raw_intervals():
    """Load COW 2024 raw data to check for interval overlaps."""
    intervals = defaultdict(list)
    with open(COW_RAW, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            code = row["stateabb"].strip()
            start = date(int(row["styear"]), int(row["stmonth"]), int(row["stday"]))
            end = date(int(row["endyear"]), int(row["endmonth"]), int(row["endday"]))
            intervals[code].append((start, end))
    return dict(intervals)


def parse_gw_raw_intervals():
    """Load GW raw data to check for interval overlaps."""
    intervals = defaultdict(list)
    with open(GW_RAW, encoding="latin-1", newline="") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            code = row["stateid"].strip()
            start = date.fromisoformat(row["start"].strip())
            end = date.fromisoformat(row["end"].strip())
            intervals[code].append((start, end))
    return dict(intervals)


def get_all_usdos_names():
    """Get all unique USDOS names from the transitions CSV."""
    names = set()
    with open(TRANSITIONS, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            names.add(row["state_dept_name"].strip())
    return sorted(names)


def intervals_overlap(intervals_list):
    """Check if any intervals in a list overlap."""
    sorted_intervals = sorted(intervals_list)
    for i in range(len(sorted_intervals) - 1):
        if sorted_intervals[i][1] >= sorted_intervals[i + 1][0]:
            return True
    return False


def check_multi_code_overlap(codes, raw_intervals):
    """For a set of codes, check if their combined intervals overlap."""
    all_intervals = []
    for code in codes:
        if code in raw_intervals:
            all_intervals.extend(raw_intervals[code])
    return intervals_overlap(all_intervals)


def main():
    cow_map = parse_cow_mod()
    gw_map = parse_gw_mod()
    all_names = get_all_usdos_names()
    cow_raw = parse_cow_raw_intervals()
    gw_raw = parse_gw_raw_intervals()

    # Build unified mapping
    yaml_entries = {}
    needs_review = []

    for name in all_names:
        cow_codes = cow_map.get(name, set())
        gw_codes = gw_map.get(name, set())

        if not cow_codes and not gw_codes:
            yaml_entries[name] = None
            continue

        entry = {}

        # COW
        if len(cow_codes) == 1:
            entry["cow"] = cow_codes.pop()
        elif len(cow_codes) > 1:
            sorted_codes = sorted(cow_codes)
            if check_multi_code_overlap(sorted_codes, cow_raw):
                needs_review.append((name, "cow", sorted_codes, "OVERLAP"))
            entry["cow"] = sorted_codes

        # GW
        if len(gw_codes) == 1:
            entry["gw"] = gw_codes.pop()
        elif len(gw_codes) > 1:
            sorted_codes = sorted(gw_codes)
            if check_multi_code_overlap(sorted_codes, gw_raw):
                needs_review.append((name, "gw", sorted_codes, "OVERLAP"))
            entry["gw"] = sorted_codes

        yaml_entries[name] = entry if entry else None

    # Check for USDOS names in transitions but not in either mod file
    cow_names = set(cow_map.keys())
    gw_names = set(gw_map.keys())
    all_mapped = cow_names | gw_names
    unmapped = [n for n in all_names if n not in all_mapped]

    # Write YAML
    with open(OUTPUT, "w") as f:
        f.write("# USDOS state_dept_name → state system code mapping\n")
        f.write("# Generated by scripts/migrate_state_codes.py\n")
        f.write("#\n")
        f.write("# Format:\n")
        f.write("#   Simple: CountryName: {cow: CODE, gw: CODE}\n")
        f.write("#   Multi-code (date-resolved): CountryName: {cow: [CODE1, CODE2]}\n")
        f.write("#   Date-disambiguated: CountryName: {cow: [{code: X, before: DATE}, {code: Y, after: DATE}]}\n")
        f.write("#   Not in system: CountryName: null\n")
        f.write("#   Only in one system: omit the missing system's key\n")
        f.write("\n")
        yaml.dump(yaml_entries, f, default_flow_style=False, allow_unicode=True, sort_keys=True)

    # Report
    print(f"Wrote {len(yaml_entries)} entries to {OUTPUT}")
    print(f"\nMapped in both systems: {sum(1 for v in yaml_entries.values() if v and 'cow' in v and 'gw' in v)}")
    print(f"COW only: {sum(1 for v in yaml_entries.values() if v and 'cow' in v and 'gw' not in v)}")
    print(f"GW only: {sum(1 for v in yaml_entries.values() if v and 'gw' in v and 'cow' not in v)}")
    print(f"Null (neither system): {sum(1 for v in yaml_entries.values() if v is None)}")

    if unmapped:
        print(f"\nUSDOS names in transitions but not in either _mod file:")
        for name in unmapped:
            print(f"  - {name}")

    if needs_review:
        print(f"\nEntries with overlapping intervals (need before/after rules):")
        for name, system, codes, note in needs_review:
            print(f"  - {name} ({system}): {codes} [{note}]")

    # Multi-code entries (for review even without overlap)
    multi_code = [(n, v) for n, v in yaml_entries.items()
                  if v and (isinstance(v.get("cow"), list) or isinstance(v.get("gw"), list))]
    if multi_code:
        print(f"\nAll multi-code entries:")
        for name, entry in multi_code:
            print(f"  - {name}: {entry}")


if __name__ == "__main__":
    main()
