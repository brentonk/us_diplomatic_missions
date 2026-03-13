"""Stage 1: Preprocessing.

Parse CSV into events grouped by country, convert XML to numbered-line text,
compute token estimates, and write per-country work unit JSON files.
"""

import json
import subprocess
from pathlib import Path

import pandas as pd

from .config import PipelineConfig
from .models import CountryMapping, CsvEvent, NumberedText, WorkUnit
from .text_utils import country_slug, estimate_tokens, number_lines
from .xml_parsers import parse_pocom_missions, parse_rdcr_tei

TOKEN_LIMIT = 60_000


def _parse_csv_events(config: PipelineConfig) -> dict[str, list[CsvEvent]]:
    """Parse the transitions CSV into CsvEvent records grouped by country."""
    df = pd.read_csv(config.paths.transitions_csv)

    events_by_country: dict[str, list[CsvEvent]] = {}
    for country_name, group in df.groupby("state_dept_name", sort=True):
        events = []
        for row_idx, (_, row) in enumerate(group.iterrows(), start=1):
            year = int(row["year"]) if pd.notna(row["year"]) else None
            month = int(row["month"]) if pd.notna(row["month"]) else None
            day = int(row["day"]) if pd.notna(row["day"]) else None
            events.append(CsvEvent(
                state_dept_name=str(row["state_dept_name"]),
                status_change=str(row["status_change"]),
                year=year,
                month=month,
                day=day,
                last_verified=str(row["last_verified"]) if pd.notna(row["last_verified"]) else "",
                notes=str(row["notes"]) if pd.notna(row["notes"]) else "",
                row_index=row_idx,
            ))
        events_by_country[str(country_name)] = events

    return events_by_country


def _get_submodule_commit(submodule_dir: Path) -> str:
    """Get the current commit hash of a git submodule."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=submodule_dir,
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "unknown"


def _load_country_mapping(config: PipelineConfig) -> dict[str, CountryMapping]:
    """Load the country mapping from Stage 0 output."""
    mapping_path = config.paths.output_dir / "country_mapping.json"
    with open(mapping_path) as f:
        data = json.load(f)

    mappings = {}
    for csv_name, d in data.items():
        mappings[csv_name] = CountryMapping.from_dict(csv_name, d)
    return mappings


def _build_numbered_text(
    raw_text: str,
    source_file: str,
    repo_commit: str,
) -> NumberedText:
    """Build a NumberedText from raw parsed text."""
    numbered_text, lines, line_to_offset = number_lines(raw_text)
    return NumberedText(
        text=numbered_text,
        lines=lines,
        line_to_byte_offset=line_to_offset,
        source_file=source_file,
        repo_commit=repo_commit,
    )


def preprocess(config: PipelineConfig, countries_filter: list[str] | None = None) -> list[WorkUnit]:
    """Run Stage 1 preprocessing for all (or filtered) countries.

    Returns the list of WorkUnit objects created.
    """
    # Parse CSV
    events_by_country = _parse_csv_events(config)

    # Load mapping
    mappings = _load_country_mapping(config)

    # Get submodule commits
    rdcr_commit = _get_submodule_commit(config.paths.rdcr_articles.parent)
    pocom_commit = _get_submodule_commit(config.paths.pocom_missions.parent)

    # Set up output directory
    work_units_dir = config.paths.output_dir / "work_units"
    work_units_dir.mkdir(parents=True, exist_ok=True)

    work_units: list[WorkUnit] = []
    flagged_count = 0

    for country_name in sorted(events_by_country.keys()):
        if countries_filter and country_name not in countries_filter:
            continue

        mapping = mappings.get(country_name)
        if mapping is None:
            continue

        # Skip countries with no sources
        if mapping.rdcr_path is None and mapping.pocom_path is None:
            continue

        csv_events = events_by_country[country_name]
        token_estimates = {}
        rdcr_numbered = None
        pocom_numbered = None
        flagged = False

        # Parse rdcr
        if mapping.rdcr_path:
            rdcr_full_path = config.repo_root / mapping.rdcr_path
            if rdcr_full_path.exists():
                raw_text = parse_rdcr_tei(rdcr_full_path)
                rdcr_numbered = _build_numbered_text(raw_text, mapping.rdcr_path, rdcr_commit)
                tokens = estimate_tokens(raw_text)
                token_estimates["rdcr"] = tokens
                if tokens > TOKEN_LIMIT:
                    flagged = True

        # Parse pocom
        if mapping.pocom_path:
            pocom_full_path = config.repo_root / mapping.pocom_path
            if pocom_full_path.exists():
                raw_text = parse_pocom_missions(pocom_full_path, config.paths.pocom_roles)
                pocom_numbered = _build_numbered_text(raw_text, mapping.pocom_path, pocom_commit)
                tokens = estimate_tokens(raw_text)
                token_estimates["pocom"] = tokens
                if tokens > TOKEN_LIMIT:
                    flagged = True

        if flagged:
            flagged_count += 1

        wu = WorkUnit(
            country=country_name,
            csv_events=csv_events,
            rdcr_text=rdcr_numbered,
            pocom_text=pocom_numbered,
            token_estimates=token_estimates,
            flagged_large=flagged,
        )

        # Write to disk
        slug = country_slug(country_name)
        output_path = work_units_dir / f"{slug}.json"
        with open(output_path, "w") as f:
            json.dump(wu.to_dict(), f, indent=2)

        work_units.append(wu)

    return work_units


def run_stage1(config: PipelineConfig, countries_filter: list[str] | None = None) -> None:
    """Run Stage 1 and print summary."""
    work_units = preprocess(config, countries_filter)

    total_rdcr_tokens = sum(wu.token_estimates.get("rdcr", 0) for wu in work_units)
    total_pocom_tokens = sum(wu.token_estimates.get("pocom", 0) for wu in work_units)
    flagged = [wu.country for wu in work_units if wu.flagged_large]

    print(f"Stage 1: Preprocessing")
    print(f"  Work units created: {len(work_units)}")
    print(f"  Total estimated tokens (rdcr): {total_rdcr_tokens:,}")
    print(f"  Total estimated tokens (pocom): {total_pocom_tokens:,}")
    if flagged:
        print(f"  Flagged as large (>{TOKEN_LIMIT:,} tokens):")
        for name in flagged:
            print(f"    - {name}")
    else:
        print(f"  No files flagged as large")
    print(f"  Output: {config.paths.output_dir / 'work_units'}/")
