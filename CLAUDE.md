# US Diplomacy Extraction Pipeline

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
```

## Project structure

- `main.py` — CLI entry point (argparse subcommands)
- `transition_extraction/` — Pipeline package
  - `config.py` — Loads `input/extraction_config.yaml`, returns `PipelineConfig` dataclass
  - `models.py` — Dataclasses: `CsvEvent`, `CountryMapping`, `NumberedText`, `WorkUnit`, `ExtractedEvent`, `ApiMetadata`
  - `text_utils.py` — Shared utilities: `normalize_country_name`, `number_lines`, `fuzzy_match`, `country_slug`, `estimate_tokens`
  - `xml_parsers.py` — `parse_rdcr_tei()` (TEI XML) and `parse_pocom_missions()` (structured XML + role resolution)
  - `api_client.py` — `ApiClient` wrapping `anthropic.AsyncAnthropic` with retry, semaphore concurrency, JSONL logging
  - `stage0_resolve.py` — Maps CSV country names to repo filenames using normalization + aliases
  - `stage1_preprocess.py` — Parses CSV, converts XML to numbered-line text, writes per-country work units
  - `stage2_extract.py` — Async Sonnet extraction with tool use
  - `stage3_verify.py` — Fuzzy-matches extracted quotes against source text
  - `stage4_reconcile.py` — Async Opus reconciliation with tool use
  - `assemble.py` — Builds final sourcing records + summary CSV
- `input/` — Config, prompts, CSV data, aliases
  - `extraction_config.yaml` — Model strings, API params, thresholds, paths
  - `country_aliases.yaml` — CSV name → repo stem overrides (grows as edge cases surface)
  - `prompt_extract.txt` — System prompt for Stage 2
  - `prompt_reconcile.txt` — System prompt for Stage 4
  - `2024-01-16_transitions.csv` — Hand-coded transitions (590 rows)
- `instructions/extraction_pipeline.md` — Full pipeline specification
- `rdcr/`, `pocom/` — Git submodules (State Department sources)
- `output/` — All pipeline outputs (gitignored)
- `logs/` — API call logs (gitignored)

## Key conventions

- **Package manager**: `uv` (never `pip install` directly)
- **No Pydantic**: Plain dataclasses for all models
- **stdlib XML**: `xml.etree.ElementTree` only (no lxml)
- **TEI namespace**: `http://www.tei-c.org/ns/1.0` — must be handled in all `find`/`findall` calls in rdcr parsing
- **Async for API stages only**: Stages 2 and 4 use `asyncio` with semaphore. Python-only stages are synchronous.
- **Intermediate files**: Each stage writes JSON to `output/`. Enables resumability and inspection.
- **Shared `country_slug()`**: Use `from .text_utils import country_slug` — do not define local slug functions in individual modules.
- **LLM calls go through the Messages API** (`api_client.py`), never through Claude Code's own loop. This is a reproducibility requirement.
- **All API calls**: `temperature: 0`, tool use for structured output, full request/response logged to JSONL.

## Country resolution status

- 199/215 countries resolve in both repos
- 14 rdcr-only (historical entities: Austrian Empire, Baden, Bavaria, etc.)
- 2 genuinely unresolved (South Yemen, Zanzibar — no source files in either repo)
- When new aliases are needed, add to `input/country_aliases.yaml` and re-run stage0

## Cost estimates (full pipeline, all 213 countries)

- Stage 2 (Sonnet extraction): ~412 API calls, ~$10
- Stage 4 (Opus reconciliation): ~213 API calls, ~$52
