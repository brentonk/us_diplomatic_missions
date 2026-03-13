"""Stage 2: Independent LLM Extraction.

For each country, make one API call per available source file (rdcr and/or pocom)
using Sonnet to extract diplomatic status transition events.
"""

import asyncio
import json
from pathlib import Path

from .api_client import ApiClient
from .config import PipelineConfig
from .models import VALID_STATUSES, WorkUnit
from .text_utils import country_slug

# Tool schema for extraction
EXTRACTION_TOOL = {
    "name": "record_events",
    "description": "Record the diplomatic status transition events extracted from the source text.",
    "input_schema": {
        "type": "object",
        "properties": {
            "country": {"type": "string"},
            "source_file": {"type": "string"},
            "events": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "date": {
                            "type": "string",
                            "description": "ISO 8601 date or partial date (YYYY, YYYY-MM, or YYYY-MM-DD)",
                        },
                        "new_status": {
                            "type": "string",
                            "enum": VALID_STATUSES,
                            "description": "The highest level of U.S. diplomatic representation after the change",
                        },
                        "event_description": {
                            "type": "string",
                            "description": "Brief description of what happened",
                        },
                        "confidence": {
                            "type": "string",
                            "enum": ["high", "medium", "low"],
                        },
                        "evidence": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "line_start": {"type": "integer"},
                                    "line_end": {"type": "integer"},
                                    "quote": {"type": "string"},
                                },
                                "required": ["line_start", "line_end", "quote"],
                            },
                        },
                    },
                    "required": ["date", "new_status", "event_description", "confidence", "evidence"],
                },
            },
        },
        "required": ["country", "source_file", "events"],
    },
}


async def _extract_from_source(
    client: ApiClient,
    work_unit: WorkUnit,
    source_type: str,
    numbered_text: str,
    source_file: str,
    system_prompt: str,
    model: str,
    temperature: float,
    max_tokens: int,
    run_timestamp: str,
    output_dir: Path,
    skip_existing: bool = True,
) -> dict | None:
    """Extract events from a single source file for a country."""
    slug = country_slug(work_unit.country)
    output_path = output_dir / f"{slug}_{source_type}.json"

    if skip_existing and output_path.exists():
        with open(output_path) as f:
            existing = json.load(f)
        event_count = len(existing.get("result", {}).get("events", [])) if existing.get("result") else 0
        print(f"  {work_unit.country} ({source_type}): skipped (existing, {event_count} events)")
        return existing

    user_message = f"Country: {work_unit.country}\nSource: {source_file}\n\n{numbered_text}"

    messages = [{"role": "user", "content": user_message}]

    try:
        tool_result, metadata = await client.call_with_tools(
            model=model,
            system=system_prompt,
            messages=messages,
            tools=[EXTRACTION_TOOL],
            temperature=temperature,
            max_tokens=max_tokens,
        )

        output = {
            "run_timestamp": run_timestamp,
            "api_metadata": metadata.model_dump(),
            "result": tool_result,
        }

        with open(output_path, "w") as f:
            json.dump(output, f, indent=2)

        event_count = len(tool_result.get("events", [])) if tool_result else 0
        print(f"  {work_unit.country} ({source_type}): {event_count} events extracted")
        return output

    except Exception as e:
        print(f"  {work_unit.country} ({source_type}): FAILED - {e}")
        return None


async def _extract_country(
    client: ApiClient,
    work_unit: WorkUnit,
    system_prompt: str,
    config: PipelineConfig,
    run_timestamp: str,
    output_dir: Path,
    skip_existing: bool = True,
) -> list[dict | None]:
    """Extract events from all available sources for a country."""
    results = []

    if work_unit.rdcr_text:
        result = await _extract_from_source(
            client=client,
            work_unit=work_unit,
            source_type="rdcr",
            numbered_text=work_unit.rdcr_text.text,
            source_file=work_unit.rdcr_text.source_file,
            system_prompt=system_prompt,
            model=config.models.extraction,
            temperature=config.api.temperature,
            max_tokens=config.api.max_tokens_extraction,
            run_timestamp=run_timestamp,
            output_dir=output_dir,
            skip_existing=skip_existing,
        )
        results.append(result)

    if work_unit.pocom_text:
        result = await _extract_from_source(
            client=client,
            work_unit=work_unit,
            source_type="pocom",
            numbered_text=work_unit.pocom_text.text,
            source_file=work_unit.pocom_text.source_file,
            system_prompt=system_prompt,
            model=config.models.extraction,
            temperature=config.api.temperature,
            max_tokens=config.api.max_tokens_extraction,
            run_timestamp=run_timestamp,
            output_dir=output_dir,
            skip_existing=skip_existing,
        )
        results.append(result)

    return results


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
    """Print cost estimate for extraction calls."""
    total_input_tokens = 0
    total_calls = 0

    # Rough estimate: system prompt ~2000 tokens
    system_prompt_tokens = 2000

    for wu in work_units:
        if wu.rdcr_text:
            total_input_tokens += wu.token_estimates.get("rdcr", 0) + system_prompt_tokens
            total_calls += 1
        if wu.pocom_text:
            total_input_tokens += wu.token_estimates.get("pocom", 0) + system_prompt_tokens
            total_calls += 1

    # Estimate output at ~1000 tokens per call
    total_output_tokens = total_calls * 1000

    # Sonnet pricing (approximate): $3/M input, $15/M output
    input_cost = total_input_tokens / 1_000_000 * 3
    output_cost = total_output_tokens / 1_000_000 * 15
    total_cost = input_cost + output_cost

    print(f"Stage 2: Cost Estimate (Sonnet extraction)")
    print(f"  API calls: {total_calls}")
    print(f"  Estimated input tokens: {total_input_tokens:,}")
    print(f"  Estimated output tokens: {total_output_tokens:,}")
    print(f"  Estimated cost: ${total_cost:.2f} (input: ${input_cost:.2f}, output: ${output_cost:.2f})")


async def run_stage2_async(
    config: PipelineConfig,
    run_timestamp: str,
    countries_filter: list[str] | None = None,
    dry_run: bool = False,
) -> None:
    """Run Stage 2 extraction asynchronously."""
    work_units = _load_work_units(config, countries_filter)

    if dry_run:
        _estimate_cost(work_units, config)
        return

    # Load system prompt
    with open(config.paths.prompt_extract) as f:
        system_prompt = f.read()

    # Set up output directory
    output_dir = config.paths.output_dir / "extractions"
    output_dir.mkdir(parents=True, exist_ok=True)

    # Initialize API client
    client = ApiClient(
        log_dir=config.paths.log_dir,
        concurrency=config.api.concurrency_extraction,
    )

    # Track results for manifest
    successes = []
    failures = []

    print(f"Stage 2: Extracting events from {len(work_units)} countries...")

    skip_existing = config.api.skip_existing

    # Run all countries concurrently (bounded by semaphore)
    tasks = []
    for wu in work_units:
        task = _extract_country(
            client=client,
            work_unit=wu,
            system_prompt=system_prompt,
            config=config,
            run_timestamp=run_timestamp,
            output_dir=output_dir,
            skip_existing=skip_existing,
        )
        tasks.append((wu.country, task))

    for country, task in tasks:
        results = await task
        if any(r is not None for r in results):
            successes.append(country)
        else:
            failures.append(country)

    # Write manifest
    manifest_path = config.paths.output_dir / "manifest.json"
    manifest = {}
    if manifest_path.exists():
        with open(manifest_path) as f:
            manifest = json.load(f)
    manifest["stage2"] = {
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


def run_stage2(
    config: PipelineConfig,
    run_timestamp: str,
    countries_filter: list[str] | None = None,
    dry_run: bool = False,
) -> None:
    """Synchronous entry point for Stage 2."""
    asyncio.run(run_stage2_async(config, run_timestamp, countries_filter, dry_run))
