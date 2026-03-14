# US Diplomatic Missions Extraction Pipeline

## Pre-commit checklist

Before every commit, re-read this file and update it with any relevant new information (new conventions, gotchas, resolved issues, etc.).

## Project overview

Validates hand-coded U.S. diplomatic status transitions (590 rows, ~215 countries) against two State Department XML source repos (`rdcr` for narrative history, `pocom` for structured mission records). Uses Claude via the Anthropic Messages API for extraction and reconciliation, with deterministic Python for everything else.

## Running the pipeline

```bash
uv run python main.py stage0              # Country name resolution
uv run python main.py stage1              # Preprocessing (XML -> numbered text)
uv run python main.py stage2              # LLM extraction (Sonnet)
uv run python main.py stage3              # Quote verification
uv run python main.py stage4              # LLM reconciliation (Opus)
uv run python main.py assemble            # Final output assembly
uv run python main.py run-all             # All stages sequentially
uv run python main.py --dry-run stage2    # Cost estimate without API calls
uv run python main.py --countries "Afghanistan,Andorra" run-all  # Filter countries
uv run python main.py build-panel --system cow   # Build COW interval panel
uv run python main.py build-panel --system gw    # Build GW interval panel
```

## Project structure

- `main.py` — CLI entry point (argparse subcommands)
- `transition_extraction/` — Pipeline package
  - `config.py` — Loads `input/extraction_config.yaml`, returns `PipelineConfig` dataclass
  - `models.py` — Pydantic models: `CsvEvent`, `CountryMapping`, `NumberedText`, `WorkUnit`, `ExtractedEvent`, `ApiMetadata`
  - `text_utils.py` — Shared utilities: `normalize_country_name`, `number_lines`, `fuzzy_match`, `country_slug`, `estimate_tokens`
  - `xml_parsers.py` — `parse_rdcr_tei()` (TEI XML) and `parse_pocom_missions()` (structured XML + role resolution)
  - `api_client.py` — `ApiClient` wrapping `anthropic.AsyncAnthropic` with retry, semaphore concurrency, JSONL logging
  - `stage0_resolve.py` — Maps CSV country names to repo filenames using normalization + aliases
  - `stage1_preprocess.py` — Parses CSV, converts XML to numbered-line text, writes per-country work units
  - `stage2_extract.py` — Async Sonnet extraction with tool use
  - `stage3_verify.py` — Fuzzy-matches extracted quotes against source text
  - `stage4_reconcile.py` — Async Opus reconciliation with tool use
  - `assemble.py` — Builds final sourcing records + summary CSV
- `data_assembly/` — Panel data assembly package
  - `state_codes.py` — `StateCodeResolver`: loads raw state system data + code-keyed YAML mapping, resolves codes ↔ USDOS names. Validates date-range overlaps.
  - `panel.py` — `build_panel()`: builds interval-level panel datasets with merged US mission status
  - `diagnostics.py` — Compares generated panel against old `_mod` reference files
- `scripts/` — One-time utility scripts
  - `migrate_state_codes.py` — (historical) Extracted YAML mapping from old `_mod` CSV files
  - `convert_mapping_format.py` — Converted YAML from USDOS-name-keyed to code-keyed format
  - `verify_state_codes.py` — Round-trip verification of mapping against old data
- `input/` — Config, prompts, CSV data, aliases
  - `extraction_config.yaml` — Model strings, API params, thresholds, paths
  - `country_aliases.yaml` — CSV name → repo stem overrides (grows as edge cases surface)
  - `state_system_codes.yaml` — COW/GW code → USDOS name mapping (code-keyed, ~210 codes per system, with date-bounded entries for code reuse)
  - `cow_statelist2024.csv` — Raw COW state list (2024 version)
  - `ksgmdw.txt` — Raw Gleditsch-Ward state list (tab-separated)
  - `microstates.txt` — GW supplement for micro/island states not in `ksgmdw.txt`
  - `prompt_extract.txt` — System prompt for Stage 2
  - `prompt_reconcile.txt` — System prompt for Stage 4
  - `2024-01-16_transitions.csv` — Hand-coded transitions (590 rows)
- `instructions/extraction_pipeline.md` — Full pipeline specification
- `rdcr/`, `pocom/` — Git submodules (State Department sources)
- `output/` — All pipeline outputs (gitignored)
- `logs/` — API call logs (gitignored)

## Key conventions

- **Package manager**: `uv` (never `pip install` directly)
- **Pydantic models**: All models in `models.py` are Pydantic `BaseModel` subclasses. Use `.model_dump()` to serialize, `Model.model_validate(d)` to deserialize. `config.py` still uses plain dataclasses since it doesn't need serialization.
- **stdlib XML**: `xml.etree.ElementTree` only (no lxml)
- **TEI namespace**: `http://www.tei-c.org/ns/1.0` — must be handled in all `find`/`findall` calls in rdcr parsing
- **Async for API stages only**: Stages 2 and 4 use `asyncio` with semaphore. Python-only stages are synchronous.
- **Intermediate files**: Each stage writes JSON to `output/`. Enables resumability and inspection.
- **Skip existing**: Stages 2 and 4 skip API calls when output files already exist (`api.skip_existing: true` in config). Use `--force` CLI flag to override. This makes it safe to re-run the full pipeline without re-doing completed work.
- **Shared `country_slug()`**: Use `from .text_utils import country_slug` — do not define local slug functions in individual modules.
- **LLM calls go through the Messages API** (`api_client.py`), never through Claude Code's own loop. This is a reproducibility requirement.
- **All API calls**: `temperature: 0`, tool use for structured output, full request/response logged to JSONL.

## Country resolution status

- 200/215 countries resolve in both repos
- 14 rdcr-only (historical entities: Austrian Empire, Baden, Bavaria, etc.)
- 1 pocom-only (Zanzibar — uses Tanzania's chiefs of mission page)
- 0 unresolved
- North Yemen and South Yemen both map to `yemen.xml` in rdcr (shared source file)
- When new aliases are needed, add to `input/country_aliases.yaml` and re-run stage0

## Known extraction limitations (do not change now — preserving reproducibility)

The Stage 2 extraction prompt instructs the model to skip consulates not located in the capital (`prompt_extract.txt` line 31: "Consulates are only coded if located in the capital"). This correctly implements the README coding rule, but it causes the extraction to miss many early consular establishments that appear clearly in RDCR text — e.g., Morocco 1797 (Tangier, not the capital), Japan 1855 (Shimoda), Norway 1809, Panama 1823, Nassau 1853, etc. These show up as "unsupported" in reconciliation and are resolved via manual `keep` decisions with notes citing external records.

The root cause is that the extraction model applies the capital-only filter at extraction time rather than surfacing the event for the reconciliation stage to evaluate. If the extraction pipeline is revised in the future:
- Extract all consulate events regardless of location, tagging non-capital ones with a flag
- Let the reconciliation stage or manual review decide whether to keep or reject
- This would eliminate the largest category of spurious "unsupported" flags

Do not change the extraction logic now — the current manual reconciliation workflow has already corrected for these gaps and changing the pipeline would break reproducibility of existing results.

## Cost estimates (full pipeline, all 213 countries)

- Stage 2 (Sonnet extraction): ~412 API calls, ~$9
- Stage 4 (Opus reconciliation): ~213 API calls, ~$8
