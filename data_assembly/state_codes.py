"""Load raw state system data and USDOS mapping, resolve codes ↔ names."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import TypeGuard, cast

import yaml


@dataclass
class Interval:
    code: str
    number: int
    name: str
    start: date
    end: date


@dataclass
class DateRule:
    code: str
    before: date | None = None
    after: date | None = None


@dataclass
class MappingEntry:
    cow: list[str] | list[DateRule] | None = None
    gw: list[str] | list[DateRule] | None = None


def _parse_mapping_codes(raw: object) -> list[str] | list[DateRule] | None:
    """Parse a cow/gw value from YAML into either a list of codes or date rules."""
    if raw is None:
        return None
    if isinstance(raw, str):
        return [raw]
    if isinstance(raw, list):
        if all(isinstance(x, str) for x in raw):
            return [str(x) for x in raw]
        rules: list[DateRule] = []
        for item in raw:
            rules.append(DateRule(
                code=item["code"],
                before=date.fromisoformat(item["before"]) if "before" in item else None,
                after=date.fromisoformat(item["after"]) if "after" in item else None,
            ))
        return rules
    raise ValueError(f"Unexpected mapping value: {raw!r}")


def _is_date_rules(codes: list[str] | list[DateRule]) -> TypeGuard[list[DateRule]]:
    return len(codes) > 0 and isinstance(codes[0], DateRule)


def _get_code_strings(codes: list[str] | list[DateRule]) -> list[str]:
    """Extract code strings from either a plain list or date rules."""
    if _is_date_rules(codes):
        return [r.code for r in codes]
    return codes  # type: ignore[return-value]


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


def _load_mapping(mapping_yaml: Path) -> dict[str, MappingEntry | None]:
    """Load state_system_codes.yaml. Returns {usdos_name: MappingEntry | None}."""
    with open(mapping_yaml) as f:
        raw = yaml.safe_load(f)
    mapping: dict[str, MappingEntry | None] = {}
    for name, entry in raw.items():
        if entry is None:
            mapping[name] = None
        else:
            mapping[name] = MappingEntry(
                cow=_parse_mapping_codes(entry.get("cow")),
                gw=_parse_mapping_codes(entry.get("gw")),
            )
    return mapping


def _build_reverse_index(
    mapping: dict[str, MappingEntry | None],
    system: str,
) -> dict[str, list[tuple[str, DateRule | None]]]:
    """Build code → [(usdos_name, date_rule_or_None), ...] reverse index."""
    reverse: dict[str, list[tuple[str, DateRule | None]]] = {}
    for usdos_name, entry in mapping.items():
        if entry is None:
            continue
        codes = entry.cow if system == "cow" else entry.gw
        if codes is None:
            continue
        if _is_date_rules(codes):
            for rule in codes:
                reverse.setdefault(rule.code, []).append((usdos_name, rule))
        else:
            for code_str in cast(list[str], codes):
                reverse.setdefault(code_str, []).append((usdos_name, None))
    return reverse


def _check_date_rule(rule: DateRule, query_date: date) -> bool:
    """Return True if query_date satisfies the date rule."""
    if rule.before is not None and query_date >= rule.before:
        return False
    if rule.after is not None and query_date < rule.after:
        return False
    return True


class StateCodeResolver:
    def __init__(self, cow_csv: Path, gw_tsv: Path, mapping_yaml: Path,
                 gw_supplement: Path | None = None):
        self._cow = _load_cow(cow_csv)
        self._gw = _load_gw(gw_tsv, gw_supplement)
        self._mapping = _load_mapping(mapping_yaml)
        self._reverse_cow = _build_reverse_index(self._mapping, "cow")
        self._reverse_gw = _build_reverse_index(self._mapping, "gw")

    @property
    def mapping(self) -> dict[str, MappingEntry | None]:
        return self._mapping

    def intervals(self, system: str) -> dict[str, list[Interval]]:
        return self._cow if system == "cow" else self._gw

    def code_to_usdos(self, system: str, code: str, query_date: date) -> str | None:
        """State system code + date → USDOS name."""
        reverse = self._reverse_cow if system == "cow" else self._reverse_gw
        candidates = reverse.get(code)
        if not candidates:
            return None
        if len(candidates) == 1:
            name, rule = candidates[0]
            if rule is not None and not _check_date_rule(rule, query_date):
                return None
            return name
        # Multiple candidates — disambiguate by date
        matched: list[str] = []
        for name, rule in candidates:
            if rule is not None:
                if not _check_date_rule(rule, query_date):
                    continue
                matched.append(name)
            else:
                matched.append(name)
        if len(matched) == 1:
            return matched[0]
        if len(matched) > 1:
            return matched[0]
        return None

    def usdos_to_code(self, usdos_name: str, system: str, query_date: date) -> tuple[str, int] | None:
        """USDOS name + date → (code, number). Returns None if unmapped."""
        entry = self._mapping.get(usdos_name)
        if entry is None:
            return None
        codes = entry.cow if system == "cow" else entry.gw
        if codes is None:
            return None
        raw = self._cow if system == "cow" else self._gw
        if _is_date_rules(codes):
            for rule in codes:
                if not _check_date_rule(rule, query_date):
                    continue
                for iv in raw.get(rule.code, []):
                    if iv.start <= query_date <= iv.end:
                        return (rule.code, iv.number)
            return None
        # Simple code list — find which code has an active interval
        for code_str in cast(list[str], codes):
            for iv in raw.get(code_str, []):
                if iv.start <= query_date <= iv.end:
                    return (code_str, iv.number)
        return None

    def validate(self) -> list[str]:
        """Check all YAML codes exist in raw data. Returns list of warnings."""
        warnings: list[str] = []
        for name, entry in self._mapping.items():
            if entry is None:
                continue
            for system_key, codes in [("cow", entry.cow), ("gw", entry.gw)]:
                if codes is None:
                    continue
                raw = self._cow if system_key == "cow" else self._gw
                for code_str in _get_code_strings(codes):
                    if code_str not in raw:
                        warnings.append(f"{name}: {system_key} code {code_str} not in raw data")
        return warnings
