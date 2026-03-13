"""Stage 3: Quote Verification.

Verify every quote returned in Stage 2 by comparing it against the actual
source text at the claimed line range. Flag citation errors below the threshold.
"""

import json
from pathlib import Path

from .config import PipelineConfig
from .models import WorkUnit
from .text_utils import country_slug, fuzzy_match


def _get_lines_text(numbered_text_lines: list[str], line_start: int, line_end: int) -> str:
    """Get the text at a line range from the original (unnumbered) lines."""
    # line numbers are 1-indexed
    start_idx = max(0, line_start - 1)
    end_idx = min(len(numbered_text_lines), line_end)
    selected = numbered_text_lines[start_idx:end_idx]
    return " ".join(line.strip() for line in selected if line.strip())


def verify_country(
    work_unit: WorkUnit,
    extractions_dir: Path,
    threshold: float,
) -> dict:
    """Verify all quotes for a single country.

    Returns a verification report dict.
    """
    slug = country_slug(work_unit.country)
    report = {
        "country": work_unit.country,
        "sources": {},
        "total_citations": 0,
        "citation_errors": 0,
        "details": [],
    }

    for source_type, numbered_text in [("rdcr", work_unit.rdcr_text), ("pocom", work_unit.pocom_text)]:
        extraction_path = extractions_dir / f"{slug}_{source_type}.json"
        if not extraction_path.exists() or numbered_text is None:
            continue

        with open(extraction_path) as f:
            extraction_data = json.load(f)

        result = extraction_data.get("result")
        if result is None:
            continue

        events = result.get("events", [])
        source_report = {
            "source_file": numbered_text.source_file,
            "events_count": len(events),
            "citations_checked": 0,
            "citation_errors": 0,
        }

        for event_idx, event in enumerate(events):
            for ev in event.get("evidence", []):
                line_start = ev.get("line_start", 0)
                line_end = ev.get("line_end", 0)
                claimed_quote = ev.get("quote", "")

                if not claimed_quote or line_start <= 0 or line_end <= 0:
                    continue

                actual_text = _get_lines_text(numbered_text.lines, line_start, line_end)
                ratio = fuzzy_match(claimed_quote, actual_text)

                report["total_citations"] += 1
                source_report["citations_checked"] += 1

                is_error = ratio < threshold
                if is_error:
                    report["citation_errors"] += 1
                    source_report["citation_errors"] += 1

                detail = {
                    "source_type": source_type,
                    "event_index": event_idx,
                    "line_start": line_start,
                    "line_end": line_end,
                    "claimed_quote": claimed_quote,
                    "actual_text": actual_text,
                    "match_ratio": round(ratio, 4),
                    "is_error": is_error,
                }
                report["details"].append(detail)

                # Annotate the extraction event with verification info
                ev["_verification"] = {
                    "match_ratio": round(ratio, 4),
                    "is_citation_error": is_error,
                }

        report["sources"][source_type] = source_report

    return report


def _load_work_units(config: PipelineConfig, countries_filter: list[str] | None = None) -> list[WorkUnit]:
    """Load work units from Stage 1 output."""
    work_units_dir = config.paths.output_dir / "work_units"
    work_units = []
    for path in sorted(work_units_dir.glob("*.json")):
        with open(path) as f:
            data = json.load(f)
        wu = WorkUnit.model_validate(data)
        if countries_filter and wu.country not in countries_filter:
            continue
        work_units.append(wu)
    return work_units


def run_stage3(config: PipelineConfig, countries_filter: list[str] | None = None) -> None:
    """Run Stage 3 quote verification."""
    work_units = _load_work_units(config, countries_filter)
    extractions_dir = config.paths.output_dir / "extractions"
    verifications_dir = config.paths.output_dir / "verifications"
    verifications_dir.mkdir(parents=True, exist_ok=True)

    threshold = config.verification.quote_match_threshold

    total_citations = 0
    total_errors = 0
    countries_checked = 0

    print(f"Stage 3: Quote Verification (threshold={threshold})")

    for wu in work_units:
        slug = country_slug(wu.country)
        report = verify_country(wu, extractions_dir, threshold)

        if report["total_citations"] == 0:
            continue

        countries_checked += 1
        total_citations += report["total_citations"]
        total_errors += report["citation_errors"]

        # Write verification report
        output_path = verifications_dir / f"{slug}.json"
        with open(output_path, "w") as f:
            json.dump(report, f, indent=2)

        if report["citation_errors"] > 0:
            print(f"  {wu.country}: {report['citation_errors']}/{report['total_citations']} citation errors")

    print(f"\n  Countries checked: {countries_checked}")
    print(f"  Total citations: {total_citations}")
    print(f"  Citation errors: {total_errors}")
    if total_citations > 0:
        error_rate = total_errors / total_citations * 100
        print(f"  Error rate: {error_rate:.1f}%")
    print(f"  Output: {verifications_dir}/")
