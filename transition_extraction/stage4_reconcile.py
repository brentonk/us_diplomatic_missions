"""Stage 4: LLM Reconciliation.

For each country, compare extracted events against CSV events using Opus
to produce a reconciliation report.
"""

import asyncio
import json
from pathlib import Path

from .api_client import ApiClient
from .config import PipelineConfig
from .models import WorkUnit
from .text_utils import country_slug

# Tool schema for reconciliation
RECONCILIATION_TOOL = {
    "name": "reconciliation_report",
    "description": "Record the reconciliation report comparing CSV events against extracted events.",
    "input_schema": {
        "type": "object",
        "properties": {
            "country": {"type": "string"},
            "matched": {
                "type": "array",
                "description": "Events present in both CSV and extracted set with consistent date and status",
                "items": {
                    "type": "object",
                    "properties": {
                        "csv_row": {
                            "type": "integer",
                            "description": "1-indexed row number in the country's CSV events",
                        },
                        "extracted_event_indices": {
                            "type": "array",
                            "items": {"type": "integer"},
                            "description": "Indices into the merged/deduplicated extraction events list",
                        },
                        "notes": {
                            "type": "string",
                            "description": "Any minor discrepancies or observations",
                        },
                    },
                    "required": ["csv_row", "extracted_event_indices", "notes"],
                },
            },
            "missing_from_csv": {
                "type": "array",
                "description": "Events found in sources but absent from CSV — candidates for addition",
                "items": {
                    "type": "object",
                    "properties": {
                        "extracted_event_indices": {
                            "type": "array",
                            "items": {"type": "integer"},
                        },
                        "date": {"type": "string"},
                        "new_status": {"type": "string"},
                        "event_description": {"type": "string"},
                        "notes": {"type": "string"},
                    },
                    "required": ["extracted_event_indices", "date", "new_status", "event_description", "notes"],
                },
            },
            "unsupported_in_sources": {
                "type": "array",
                "description": "CSV events not found in either source file",
                "items": {
                    "type": "object",
                    "properties": {
                        "csv_row": {"type": "integer"},
                        "notes": {
                            "type": "string",
                            "description": "Why the model believes this event is unsupported",
                        },
                    },
                    "required": ["csv_row", "notes"],
                },
            },
            "discrepancies": {
                "type": "array",
                "description": "Events present in both but with conflicting dates, statuses, or descriptions",
                "items": {
                    "type": "object",
                    "properties": {
                        "csv_row": {"type": "integer"},
                        "extracted_event_indices": {
                            "type": "array",
                            "items": {"type": "integer"},
                        },
                        "field": {
                            "type": "string",
                            "description": "Which field conflicts: date, new_status, or both",
                        },
                        "csv_value": {"type": "string"},
                        "extracted_value": {"type": "string"},
                        "assessment": {
                            "type": "string",
                            "enum": ["csv_likely_correct", "extracted_likely_correct", "ambiguous"],
                        },
                        "reasoning": {"type": "string"},
                    },
                    "required": ["csv_row", "extracted_event_indices", "field", "csv_value", "extracted_value", "assessment", "reasoning"],
                },
            },
        },
        "required": ["country", "matched", "missing_from_csv", "unsupported_in_sources", "discrepancies"],
    },
}


def _merge_extractions(slug: str, extractions_dir: Path, verifications_dir: Path) -> list[dict]:
    """Load and merge extracted events from all sources for a country.

    Returns a list of event dicts with source_type and citation verification info.
    Events are deduplicated by (date, new_status).
    """
    merged = []
    seen = set()

    # Load verification data if available
    verification_data = {}
    verif_path = verifications_dir / f"{slug}.json"
    if verif_path.exists():
        with open(verif_path) as f:
            vdata = json.load(f)
        for detail in vdata.get("details", []):
            key = (detail["source_type"], detail["event_index"])
            if key not in verification_data:
                verification_data[key] = []
            verification_data[key].append(detail)

    for source_type in ["rdcr", "pocom"]:
        extraction_path = extractions_dir / f"{slug}_{source_type}.json"
        if not extraction_path.exists():
            continue

        with open(extraction_path) as f:
            data = json.load(f)

        result = data.get("result")
        if result is None:
            continue

        for event_idx, event in enumerate(result.get("events", [])):
            dedup_key = (event.get("date", ""), event.get("new_status", ""))
            if dedup_key in seen:
                continue
            seen.add(dedup_key)

            # Check for citation errors
            verif_details = verification_data.get((source_type, event_idx), [])
            has_citation_error = any(d.get("is_error", False) for d in verif_details)

            merged_event = {
                **event,
                "source_type": source_type,
                "original_index": event_idx,
                "has_citation_error": has_citation_error,
            }
            merged.append(merged_event)

    return merged


def _build_reconciliation_message(
    work_unit: WorkUnit,
    merged_events: list[dict],
) -> str:
    """Build the user message for the reconciliation API call."""
    parts = [f"Country: {work_unit.country}\n"]

    # CSV events
    parts.append("## CSV Events (hand-coded)")
    for event in work_unit.csv_events:
        parts.append(f"Row {event.row_index}: {event.date_str()} — {event.status_change}")
        if event.notes:
            parts.append(f"  Notes: {event.notes}")
    parts.append("")

    # Extracted events
    parts.append("## Extracted Events (from source texts)")
    for idx, event in enumerate(merged_events):
        citation_flag = " [CITATION ERROR]" if event.get("has_citation_error") else ""
        parts.append(
            f"Event {idx}: {event.get('date', '?')} — {event.get('new_status', '?')} "
            f"(confidence: {event.get('confidence', '?')}, source: {event.get('source_type', '?')}){citation_flag}"
        )
        parts.append(f"  Description: {event.get('event_description', '')}")
        for ev in event.get("evidence", []):
            parts.append(f"  Evidence: lines {ev.get('line_start', '?')}-{ev.get('line_end', '?')}: \"{ev.get('quote', '')}\"")
    parts.append("")

    return "\n".join(parts)


async def _reconcile_country(
    client: ApiClient,
    work_unit: WorkUnit,
    system_prompt: str,
    config: PipelineConfig,
    run_timestamp: str,
    extractions_dir: Path,
    verifications_dir: Path,
    output_dir: Path,
) -> dict | None:
    """Reconcile extracted events against CSV for a single country."""
    slug = country_slug(work_unit.country)

    # Merge and deduplicate extracted events
    merged_events = _merge_extractions(slug, extractions_dir, verifications_dir)

    if not merged_events and not work_unit.csv_events:
        return None

    # Build message
    user_message = _build_reconciliation_message(work_unit, merged_events)
    messages = [{"role": "user", "content": user_message}]

    try:
        tool_result, metadata = await client.call_with_tools(
            model=config.models.reconciliation,
            system=system_prompt,
            messages=messages,
            tools=[RECONCILIATION_TOOL],
            temperature=config.api.temperature,
            max_tokens=config.api.max_tokens_reconciliation,
        )

        output = {
            "run_timestamp": run_timestamp,
            "api_metadata": metadata.model_dump(),
            "merged_events": merged_events,
            "result": tool_result,
        }

        output_path = output_dir / f"{slug}.json"
        with open(output_path, "w") as f:
            json.dump(output, f, indent=2)

        if tool_result:
            matched = len(tool_result.get("matched", []))
            missing = len(tool_result.get("missing_from_csv", []))
            unsupported = len(tool_result.get("unsupported_in_sources", []))
            discrepancies = len(tool_result.get("discrepancies", []))
            print(f"  {work_unit.country}: {matched} matched, {missing} missing, {unsupported} unsupported, {discrepancies} discrepancies")

        return output

    except Exception as e:
        print(f"  {work_unit.country}: FAILED - {e}")
        return None


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


def _estimate_cost(work_units: list[WorkUnit], config: PipelineConfig) -> None:
    """Print cost estimate for reconciliation calls."""
    total_calls = len(work_units)
    # Rough: ~2000 tokens system prompt + ~500 tokens per CSV event + ~500 per extracted event
    avg_csv_events = sum(len(wu.csv_events) for wu in work_units) / max(total_calls, 1)
    est_input_per_call = 2000 + int(avg_csv_events * 500) + int(avg_csv_events * 2 * 500)
    total_input = est_input_per_call * total_calls
    total_output = total_calls * 2000

    # Opus pricing (approximate): $15/M input, $75/M output
    input_cost = total_input / 1_000_000 * 15
    output_cost = total_output / 1_000_000 * 75
    total_cost = input_cost + output_cost

    print(f"Stage 4: Cost Estimate (Opus reconciliation)")
    print(f"  API calls: {total_calls}")
    print(f"  Estimated input tokens: {total_input:,}")
    print(f"  Estimated output tokens: {total_output:,}")
    print(f"  Estimated cost: ${total_cost:.2f} (input: ${input_cost:.2f}, output: ${output_cost:.2f})")


async def run_stage4_async(
    config: PipelineConfig,
    run_timestamp: str,
    countries_filter: list[str] | None = None,
    dry_run: bool = False,
) -> None:
    """Run Stage 4 reconciliation asynchronously."""
    work_units = _load_work_units(config, countries_filter)

    if dry_run:
        _estimate_cost(work_units, config)
        return

    # Load system prompt
    with open(config.paths.prompt_reconcile) as f:
        system_prompt = f.read()

    # Set up directories
    extractions_dir = config.paths.output_dir / "extractions"
    verifications_dir = config.paths.output_dir / "verifications"
    output_dir = config.paths.output_dir / "reconciliations"
    output_dir.mkdir(parents=True, exist_ok=True)

    # Initialize API client
    client = ApiClient(
        log_dir=config.paths.log_dir,
        concurrency=config.api.concurrency_reconciliation,
    )

    successes = []
    failures = []

    print(f"Stage 4: Reconciling {len(work_units)} countries...")

    tasks = []
    for wu in work_units:
        task = _reconcile_country(
            client=client,
            work_unit=wu,
            system_prompt=system_prompt,
            config=config,
            run_timestamp=run_timestamp,
            extractions_dir=extractions_dir,
            verifications_dir=verifications_dir,
            output_dir=output_dir,
        )
        tasks.append((wu.country, task))

    for country, task in tasks:
        result = await task
        if result is not None:
            successes.append(country)
        else:
            failures.append(country)

    # Update manifest
    manifest_path = config.paths.output_dir / "manifest.json"
    manifest = {}
    if manifest_path.exists():
        with open(manifest_path) as f:
            manifest = json.load(f)
    manifest["stage4"] = {
        "run_timestamp": run_timestamp,
        "successes": successes,
        "failures": failures,
    }
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)

    print(f"\n  Successes: {len(successes)}")
    print(f"  Failures: {len(failures)}")
    if failures:
        print(f"  Failed countries: {', '.join(failures)}")


def run_stage4(
    config: PipelineConfig,
    run_timestamp: str,
    countries_filter: list[str] | None = None,
    dry_run: bool = False,
) -> None:
    """Synchronous entry point for Stage 4."""
    asyncio.run(run_stage4_async(config, run_timestamp, countries_filter, dry_run))
