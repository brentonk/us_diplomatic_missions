"""Load raw state system data and USDOS mapping, resolve codes ↔ names."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import yaml


@dataclass
class Interval:
    code: str
    number: int
    name: str
    start: date
    end: date


@dataclass
class NameRule:
    """A USDOS name mapping for a code, optionally date-bounded."""
    name: str
    before: date | None = None
    after: date | None = None


# code -> simple name (str) or list of date-bounded names
CodeMapping = dict[str, str | list[NameRule]]

# name -> [(code, rule_or_None), ...] for reverse lookups
NameIndex = dict[str, list[tuple[str, NameRule | None]]]


def _load_cow(cow_csv: Path) -> dict[str, list[Interval]]:
    """Load COW state list. Returns {stateabb: [Interval, ...]}."""
    intervals: dict[str, list[Interval]] = {}
    with open(cow_csv, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            code = row["stateabb"].strip()
            iv = Interval(
                code=code,
                number=int(row["ccode"]),
                name=row["statenme"].strip(),
                start=date(int(row["styear"]), int(row["stmonth"]), int(row["stday"])),
                end=date(int(row["endyear"]), int(row["endmonth"]), int(row["endday"])),
            )
            intervals.setdefault(code, []).append(iv)
    return intervals


def _load_gw_file(path: Path, intervals: dict[str, list[Interval]]) -> None:
    """Load a single GW-format TSV file into the intervals dict."""
    with open(path, encoding="latin-1", newline="") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            code = row["stateid"].strip()
            iv = Interval(
                code=code,
                number=int(row["statenumber"]),
                name=row["countryname"].strip(),
                start=date.fromisoformat(row["start"].strip()),
                end=date.fromisoformat(row["end"].strip()),
            )
            intervals.setdefault(code, []).append(iv)


def _load_gw(gw_tsv: Path, supplement: Path | None = None) -> dict[str, list[Interval]]:
    """Load Gleditsch-Ward state list, plus optional supplement. Returns {stateid: [Interval, ...]}."""
    intervals: dict[str, list[Interval]] = {}
    _load_gw_file(gw_tsv, intervals)
    if supplement is not None and supplement.exists():
        _load_gw_file(supplement, intervals)
    return intervals


def _load_mapping(mapping_yaml: Path) -> tuple[CodeMapping, CodeMapping]:
    """Load code-keyed state_system_codes.yaml.

    Returns (cow_mapping, gw_mapping).
    """
    with open(mapping_yaml) as f:
        raw = yaml.safe_load(f)

    cow_mapping: CodeMapping = {}
    gw_mapping: CodeMapping = {}

    for system_key, mapping in [("cow", cow_mapping), ("gw", gw_mapping)]:
        section = raw.get(system_key, {})
        for code, value in section.items():
            code = str(code)
            if isinstance(value, str):
                mapping[code] = value
            elif isinstance(value, list):
                rules: list[NameRule] = []
                for item in value:
                    rules.append(NameRule(
                        name=item["name"],
                        before=date.fromisoformat(item["before"]) if "before" in item else None,
                        after=date.fromisoformat(item["after"]) if "after" in item else None,
                    ))
                mapping[code] = rules
            else:
                raise ValueError(f"Unexpected value for {system_key}.{code}: {value!r}")

    return cow_mapping, gw_mapping


def _build_name_index(mapping: CodeMapping) -> NameIndex:
    """Build name → [(code, rule_or_None), ...] reverse index for usdos_to_code lookups."""
    index: NameIndex = {}
    for code, entry in mapping.items():
        if isinstance(entry, str):
            index.setdefault(entry, []).append((code, None))
        else:
            for rule in entry:
                index.setdefault(rule.name, []).append((code, rule))
    return index


def _check_name_rule(rule: NameRule, query_date: date) -> bool:
    """Return True if query_date satisfies the name rule's date bounds."""
    if rule.before is not None and query_date >= rule.before:
        return False
    if rule.after is not None and query_date < rule.after:
        return False
    return True


def _date_ranges_overlap(r1: NameRule, r2: NameRule) -> bool:
    """Return True if two name rules have overlapping date ranges.

    Each rule defines a half-open interval [after, before). If either bound
    is None, that side is unbounded.
    """
    # r1's range starts at r1.after (or -inf) and ends at r1.before (or +inf)
    # r2's range starts at r2.after (or -inf) and ends at r2.before (or +inf)
    # They overlap unless one ends before the other starts.
    if r1.before is not None and r2.after is not None and r1.before <= r2.after:
        return False
    if r2.before is not None and r1.after is not None and r2.before <= r1.after:
        return False
    return True


class StateCodeResolver:
    def __init__(self, cow_csv: Path, gw_tsv: Path, mapping_yaml: Path,
                 gw_supplement: Path | None = None):
        self._cow = _load_cow(cow_csv)
        self._gw_base = _load_gw(gw_tsv)
        self._gw_full = _load_gw(gw_tsv, gw_supplement)
        self._cow_mapping, self._gw_mapping = _load_mapping(mapping_yaml)
        self._cow_name_index = _build_name_index(self._cow_mapping)
        self._gw_name_index = _build_name_index(self._gw_mapping)

    def intervals(self, system: str) -> dict[str, list[Interval]]:
        if system == "cow":
            return self._cow
        if system == "gwm":
            return self._gw_full
        return self._gw_base

    def code_name_entries(self, system: str, code: str) -> list[tuple[str, NameRule | None]]:
        """Return all (usdos_name, rule_or_None) entries for a given code.

        Used by panel.py to determine split dates for interval subdivision.
        """
        mapping = self._cow_mapping if system == "cow" else self._gw_mapping
        entry = mapping.get(code)
        if entry is None:
            return []
        if isinstance(entry, str):
            return [(entry, None)]
        return [(rule.name, rule) for rule in entry]

    def code_to_usdos(self, system: str, code: str, query_date: date) -> str | None:
        """State system code + date → USDOS name."""
        mapping = self._cow_mapping if system == "cow" else self._gw_mapping
        entry = mapping.get(code)
        if entry is None:
            return None
        if isinstance(entry, str):
            return entry
        for rule in entry:
            if _check_name_rule(rule, query_date):
                return rule.name
        return None

    def usdos_to_code(self, usdos_name: str, system: str, query_date: date) -> tuple[str, int] | None:
        """USDOS name + date → (code, number). Returns None if no mapping exists."""
        name_index = self._cow_name_index if system == "cow" else self._gw_name_index
        candidates = name_index.get(usdos_name)
        if not candidates:
            return None
        raw = self.intervals(system)
        for code, rule in candidates:
            if rule is not None and not _check_name_rule(rule, query_date):
                continue
            for iv in raw.get(code, []):
                if iv.start <= query_date <= iv.end:
                    return (code, iv.number)
        return None

    def validate(self) -> list[str]:
        """Check mapping integrity. Returns list of warnings.

        Checks:
        1. All mapped codes exist in raw state system data.
        2. No date range overlaps for multi-name code entries.
        """
        warnings: list[str] = []
        for system_key, mapping in [("cow", self._cow_mapping), ("gw", self._gw_mapping)]:
            raw = self._cow if system_key == "cow" else self._gw_full
            for code, entry in mapping.items():
                if code not in raw:
                    if isinstance(entry, str):
                        warnings.append(f"{system_key} code {code} ({entry}) not in raw data")
                    else:
                        names = ", ".join(r.name for r in entry)
                        warnings.append(f"{system_key} code {code} ({names}) not in raw data")
                if isinstance(entry, list) and len(entry) > 1:
                    for i, r1 in enumerate(entry):
                        for r2 in entry[i + 1:]:
                            if _date_ranges_overlap(r1, r2):
                                warnings.append(
                                    f"{system_key} code {code}: overlapping date ranges "
                                    f"for '{r1.name}' and '{r2.name}'"
                                )
        return warnings

    def diagnose_coverage(self, usdos_names: set[str]) -> list[str]:
        """Diagnose coverage gaps between state systems and USDOS names.

        Returns list of diagnostic messages for:
        1. State system codes with no USDOS mapping.
        2. USDOS names with no state system mapping.
        """
        messages: list[str] = []

        # Direction 1: state system codes with no USDOS mapping
        for label, mapping, raw in [
            ("COW", self._cow_mapping, self._cow),
            ("GW", self._gw_mapping, self._gw_base),
            ("GWM", self._gw_mapping, self._gw_full),
        ]:
            unmapped_codes = []
            for code in sorted(raw.keys()):
                if code not in mapping:
                    names = sorted(set(iv.name for iv in raw[code]))
                    unmapped_codes.append(f"    {code} ({', '.join(names)})")
            if unmapped_codes:
                messages.append(
                    f"{label}: {len(unmapped_codes)} code(s) with no USDOS mapping:\n"
                    + "\n".join(unmapped_codes)
                )

        # Direction 2: USDOS names with no state system mapping
        # GW and GWM share the same mapping, so only report COW and GW.
        for label, name_index in [
            ("COW", self._cow_name_index),
            ("GW", self._gw_name_index),
        ]:
            unmatched = sorted(
                n for n in usdos_names
                if n not in name_index
            )
            if unmatched:
                messages.append(
                    f"{label}: {len(unmatched)} USDOS name(s) with no mapping:\n"
                    + "\n".join(f"    {n}" for n in unmatched)
                )

        return messages
