"""Output Assembly.

Build final sourcing records from reconciliation, extraction, and verification results.
Apply manual reconciliation decisions from input/manual_reconciliation.yaml when present.
Write sourcing_records.jsonl and summary.csv.
"""

import csv
import json
from pathlib import Path

import yaml

from .config import PipelineConfig
from .models import WorkUnit
from .text_utils import country_slug


def _load_work_units(config: PipelineConfig, countries_filter: list[str] | None = None) -> list[WorkUnit]:
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


def _load_decisions(decisions_path: Path) -> dict[str, dict]:
    """Load human decisions, keyed by 'country|csv_row' or 'country|addition|date'."""
    if not decisions_path.exists():
        return {}
    with open(decisions_path) as f:
        raw = yaml.safe_load(f) or []
    decisions = {}
    for entry in raw:
        country = entry.get("country", "")
        if entry.get("type") == "addition":
            key = f"{country}|addition|{entry.get('date', '')}"
        else:
            key = f"{country}|{entry.get('csv_row', '')}"
        decisions[key] = entry
    return decisions


def _apply_decision(record: dict, decision: dict) -> list[dict]:
    """Apply a human decision to a sourcing record.

    Returns a list of records (usually one, but split decisions produce multiple).
    """
    choice = decision.get("decision", "")
    notes = decision.get("notes", "")

    if record["validation_status"] == "discrepancy":
        if choice == "accept_csv":
            record["validation_status"] = "confirmed"
            record["validation_notes"] = f"Human decision: accept CSV value. {notes}".strip()
        elif choice == "accept_source":
            record["validation_status"] = "confirmed"
            if decision.get("override_date"):
                record["date"] = decision["override_date"]
            if decision.get("override_status"):
                record["new_status"] = decision["override_status"]
            record["validation_notes"] = f"Human decision: accept source value. {notes}".strip()
        elif choice == "custom":
            record["validation_status"] = "confirmed"
            if decision.get("override_date"):
                record["date"] = decision["override_date"]
            if decision.get("override_status"):
                record["new_status"] = decision["override_status"]
            record["validation_notes"] = f"Human decision: custom override. {notes}".strip()
        elif choice == "split":
            entries = decision.get("entries", [])
            if entries:
                split_records = []
                for entry in entries:
                    new_record = record.copy()
                    new_record["date"] = entry.get("date", record["date"])
                    new_record["new_status"] = entry.get("status", record["new_status"])
                    new_record["validation_status"] = "confirmed"
                    new_record["validation_notes"] = f"Human decision: split. {notes}".strip()
                    split_records.append(new_record)
                return split_records

    elif record["validation_status"] == "candidate_addition":
        if choice == "add":
            if decision.get("override_date"):
                record["date"] = decision["override_date"]
            if decision.get("override_status"):
                record["new_status"] = decision["override_status"]
            record["validation_status"] = "confirmed_addition"
            record["validation_notes"] = f"Human decision: add to dataset. {notes}".strip()
        elif choice == "reject":
            record["validation_status"] = "rejected"
            record["validation_notes"] = f"Human decision: reject addition. {notes}".strip()

    elif record["validation_status"] == "unsupported":
        if choice == "keep":
            record["validation_status"] = "confirmed"
            record["validation_notes"] = f"Human decision: keep despite no source. {notes}".strip()
        elif choice == "remove":
            record["validation_status"] = "removed"
            record["validation_notes"] = f"Human decision: remove from dataset. {notes}".strip()

    return [record]


def assemble_country(
    work_unit: WorkUnit,
    config: PipelineConfig,
    run_timestamp: str,
    decisions: dict[str, dict] | None = None,
) -> list[dict]:
    """Assemble sourcing records for a single country.

    Returns a list of sourcing record dicts.
    """
    slug = country_slug(work_unit.country)
    extractions_dir = config.paths.output_dir / "extractions"
    reconciliations_dir = config.paths.output_dir / "reconciliations"

    # Load reconciliation
    recon_path = reconciliations_dir / f"{slug}.json"
    if not recon_path.exists():
        return []

    with open(recon_path) as f:
        recon_data = json.load(f)

    recon_result = recon_data.get("result")
    if recon_result is None:
        return []

    recon_metadata = recon_data.get("api_metadata", {})
    merged_events = recon_data.get("merged_events", [])

    # Load extraction metadata for each source
    extraction_metadata = {}
    for source_type in ["rdcr", "pocom"]:
        ext_path = extractions_dir / f"{slug}_{source_type}.json"
        if ext_path.exists():
            with open(ext_path) as f:
                ext_data = json.load(f)
            extraction_metadata[source_type] = ext_data.get("api_metadata", {})


    records = []

    # Process matched events
    for match in recon_result.get("matched", []):
        csv_row = match.get("csv_row")
        csv_event = None
        for ev in work_unit.csv_events:
            if ev.row_index == csv_row:
                csv_event = ev
                break

        extracted_indices = match.get("extracted_event_indices", [])
        sources = _build_sources(extracted_indices, merged_events, work_unit)

        # Use the first extraction's metadata
        ext_meta = _get_extraction_metadata(extracted_indices, merged_events, extraction_metadata)

        record = {
            "run_timestamp": run_timestamp,
            "country": work_unit.country,
            "date": csv_event.date_str() if csv_event else "",
            "new_status": csv_event.status_change if csv_event else "",
            "event_description": _get_event_description(extracted_indices, merged_events),
            "confidence": _get_confidence(extracted_indices, merged_events),
            "sources": sources,
            "extraction_api_metadata": ext_meta,
            "reconciliation_api_metadata": recon_metadata,
            "validation_status": "confirmed",
            "validation_notes": match.get("notes", f"Matches CSV row {csv_row}."),
        }
        records.append(record)

    # Process missing_from_csv events (candidates for addition)
    for missing in recon_result.get("missing_from_csv", []):
        extracted_indices = missing.get("extracted_event_indices", [])
        sources = _build_sources(extracted_indices, merged_events, work_unit)
        ext_meta = _get_extraction_metadata(extracted_indices, merged_events, extraction_metadata)

        record = {
            "run_timestamp": run_timestamp,
            "country": work_unit.country,
            "date": missing.get("date", ""),
            "new_status": missing.get("new_status", ""),
            "event_description": missing.get("event_description", ""),
            "confidence": _get_confidence(extracted_indices, merged_events),
            "sources": sources,
            "extraction_api_metadata": ext_meta,
            "reconciliation_api_metadata": recon_metadata,
            "validation_status": "candidate_addition",
            "validation_notes": missing.get("notes", "Found in sources but absent from CSV."),
        }
        records.append(record)

    # Process unsupported_in_sources events
    for unsupported in recon_result.get("unsupported_in_sources", []):
        csv_row = unsupported.get("csv_row")
        csv_event = None
        for ev in work_unit.csv_events:
            if ev.row_index == csv_row:
                csv_event = ev
                break

        record = {
            "run_timestamp": run_timestamp,
            "country": work_unit.country,
            "csv_row": csv_row,
            "date": csv_event.date_str() if csv_event else "",
            "new_status": csv_event.status_change if csv_event else "",
            "event_description": "",
            "confidence": "",
            "sources": [],
            "extraction_api_metadata": None,
            "reconciliation_api_metadata": recon_metadata,
            "validation_status": "unsupported",
            "validation_notes": unsupported.get("notes", f"CSV row {csv_row} not found in sources."),
        }
        records.append(record)

    # Process discrepancies
    for disc in recon_result.get("discrepancies", []):
        csv_row = disc.get("csv_row")
        csv_event = None
        for ev in work_unit.csv_events:
            if ev.row_index == csv_row:
                csv_event = ev
                break

        extracted_indices = disc.get("extracted_event_indices", [])
        sources = _build_sources(extracted_indices, merged_events, work_unit)
        ext_meta = _get_extraction_metadata(extracted_indices, merged_events, extraction_metadata)

        record = {
            "run_timestamp": run_timestamp,
            "country": work_unit.country,
            "csv_row": csv_row,
            "date": csv_event.date_str() if csv_event else "",
            "new_status": csv_event.status_change if csv_event else "",
            "event_description": _get_event_description(extracted_indices, merged_events),
            "confidence": _get_confidence(extracted_indices, merged_events),
            "sources": sources,
            "extraction_api_metadata": ext_meta,
            "reconciliation_api_metadata": recon_metadata,
            "validation_status": "discrepancy",
            "validation_notes": (
                f"Field: {disc.get('field', '?')}. "
                f"CSV: {disc.get('csv_value', '?')}. "
                f"Extracted: {disc.get('extracted_value', '?')}. "
                f"Assessment: {disc.get('assessment', '?')}. "
                f"Reasoning: {disc.get('reasoning', '')}"
            ),
        }
        records.append(record)

    # Apply human decisions
    if decisions:
        resolved_records = []
        for record in records:
            status = record["validation_status"]
            if status == "confirmed":
                resolved_records.append(record)
                continue
            decision = None
            if status in ("discrepancy", "unsupported"):
                csv_row = record.get("csv_row")
                if csv_row is not None:
                    key = f"{work_unit.country}|{csv_row}"
                    decision = decisions.get(key)
            elif status == "candidate_addition":
                key = f"{work_unit.country}|addition|{record.get('date', '')}"
                decision = decisions.get(key)
            if decision:
                resolved_records.extend(_apply_decision(record, decision))
            else:
                resolved_records.append(record)
        records = resolved_records

    return records


def _build_sources(
    extracted_indices: list[int],
    merged_events: list[dict],
    work_unit: WorkUnit,
) -> list[dict]:
    """Build source citation dicts for the given extracted event indices."""
    sources = []
    for idx in extracted_indices:
        if idx < 0 or idx >= len(merged_events):
            continue
        event = merged_events[idx]
        source_type = event.get("source_type", "")

        # Get the numbered text for commit hash and file path
        if source_type == "rdcr" and work_unit.rdcr_text:
            repo_commit = work_unit.rdcr_text.repo_commit
            file_path = work_unit.rdcr_text.source_file
        elif source_type == "pocom" and work_unit.pocom_text:
            repo_commit = work_unit.pocom_text.repo_commit
            file_path = work_unit.pocom_text.source_file
        else:
            repo_commit = "unknown"
            file_path = "unknown"

        for ev in event.get("evidence", []):
            source = {
                "repo_commit": repo_commit,
                "file_path": file_path,
                "line_start": ev.get("line_start"),
                "line_end": ev.get("line_end"),
                "quote": ev.get("quote", ""),
            }
            sources.append(source)

    return sources


def _get_extraction_metadata(
    extracted_indices: list[int],
    merged_events: list[dict],
    extraction_metadata: dict,
) -> dict | None:
    """Get the extraction API metadata for the first matching event."""
    for idx in extracted_indices:
        if idx < 0 or idx >= len(merged_events):
            continue
        source_type = merged_events[idx].get("source_type", "")
        if source_type in extraction_metadata:
            return extraction_metadata[source_type]
    return None


def _get_event_description(extracted_indices: list[int], merged_events: list[dict]) -> str:
    """Get the event description from the first extracted event."""
    for idx in extracted_indices:
        if 0 <= idx < len(merged_events):
            return merged_events[idx].get("event_description", "")
    return ""


def _get_confidence(extracted_indices: list[int], merged_events: list[dict]) -> str:
    """Get the confidence from the first extracted event."""
    for idx in extracted_indices:
        if 0 <= idx < len(merged_events):
            return merged_events[idx].get("confidence", "")
    return ""


def run_assemble(
    config: PipelineConfig,
    run_timestamp: str,
    countries_filter: list[str] | None = None,
) -> None:
    """Assemble final output from all pipeline stages."""
    work_units = _load_work_units(config, countries_filter)

    # Load human decisions
    decisions_path = config.paths.manual_reconciliation
    decisions = _load_decisions(decisions_path)
    if decisions:
        print(f"  Loaded {len(decisions)} human decisions from {decisions_path}")

    final_dir = config.paths.output_dir / "final"
    final_dir.mkdir(parents=True, exist_ok=True)

    records_path = final_dir / "sourcing_records.jsonl"
    summary_path = final_dir / "summary.csv"

    all_records = []
    summary_rows = []

    print(f"Assembling final output...")

    for wu in work_units:
        records = assemble_country(wu, config, run_timestamp, decisions)
        all_records.extend(records)

        # Compute summary stats
        confirmed = sum(1 for r in records if r["validation_status"] == "confirmed")
        candidates = sum(1 for r in records if r["validation_status"] == "candidate_addition")
        unsupported = sum(1 for r in records if r["validation_status"] == "unsupported")
        discrepancies = sum(1 for r in records if r["validation_status"] == "discrepancy")

        if records:
            summary_rows.append({
                "country": wu.country,
                "csv_events": len(wu.csv_events),
                "confirmed": confirmed,
                "candidate_additions": candidates,
                "unsupported": unsupported,
                "discrepancies": discrepancies,
            })

    # Write JSONL
    with open(records_path, "w") as f:
        for record in all_records:
            f.write(json.dumps(record, default=str) + "\n")

    # Write summary CSV
    if summary_rows:
        with open(summary_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=["country", "csv_events", "confirmed", "candidate_additions", "unsupported", "discrepancies"])
            writer.writeheader()
            writer.writerows(summary_rows)

    print(f"  Total sourcing records: {len(all_records)}")
    print(f"  Countries with output: {len(summary_rows)}")
    total_confirmed = sum(r["confirmed"] for r in summary_rows)
    total_candidates = sum(r["candidate_additions"] for r in summary_rows)
    total_unsupported = sum(r["unsupported"] for r in summary_rows)
    total_discrepancies = sum(r["discrepancies"] for r in summary_rows)
    print(f"  Confirmed: {total_confirmed}")
    print(f"  Candidate additions: {total_candidates}")
    print(f"  Unsupported: {total_unsupported}")
    print(f"  Discrepancies: {total_discrepancies}")
    print(f"  Output: {records_path}")
    print(f"  Summary: {summary_path}")
