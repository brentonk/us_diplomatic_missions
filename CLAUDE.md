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
uv run python main.py generate-data              # Generate all data product files + web sources
quarto render web                                # Build website locally
quarto preview web                               # Preview website locally
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
- `data_assembly/` — Data assembly and data product generation
  - `state_codes.py` — `StateCodeResolver`: loads raw state system data + code-keyed YAML mapping, resolves codes ↔ USDOS names. Supports COW, GW, and GWM (GW + microstates) systems.
  - `timeline.py` — Shared timeline logic: `build_status_timeline()`, `get_status_at()`, `collect_split_dates()`
  - `status.py` — Diplomatic status ordering (9 levels) and aggregation functions (min/max/median/mode)
  - `version.py` — Reads project version from `pyproject.toml`
  - `range_builder.py` — Builds interval-level range datasets (mission_status_range_*.csv)
  - `daily_builder.py` — Expands range data to daily rows (in-memory intermediate for aggregation)
  - `aggregator.py` — Monthly and yearly aggregation from daily data
  - `generate.py` — Orchestrator: generates all data product files (CSVs, codebook)
  - `codebook_builder.py` — Assembles codebook Markdown from fragments and renders PDF via pandoc
  - `codebook/` — Codebook source fragments (7 Markdown files assembled in order)
  - `generate_web.py` — Generates Quarto website source files (download page, explorer data)
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
- `instructions/` — Pipeline and data product specifications (gitignored, local reference only)
- `rdcr/`, `pocom/` — Git submodules (State Department sources)
- `output/` — All pipeline outputs (gitignored)
- `data/` — Versioned data products (committed, organized as `data/v{VERSION}/`): 9 CSVs, codebook (md + pdf)
- `web/` — Quarto website source (landing page, download page, data explorer)
- `.github/workflows/pages.yml` — GitHub Pages deployment on push to main
- `.github/workflows/release.yml` — Creates GitHub Release with data archives on version tag push
- `logs/` — API call logs (gitignored)

## Versioning

The canonical version is in `pyproject.toml`. The current pre-release version is 0.1.

- **Version bumps**: After the initial 0.1 release, any code change that produces different output data requires a version bump. Minor changes (e.g., typo fixes in mapping) get a minor bump; major changes (e.g., new state system data versions) get a major bump.
- **Release tags**: Each release should be tagged in GitHub (e.g., `v0.1`). Push a tag to trigger the release workflow, which creates a GitHub Release with data archives attached.
- **Data preservation**: This project is intended for scientific research. Data from prior releases must not be deleted or overwritten. Output datasets should be versioned alongside the code so that any published result can be reproduced from a tagged release.

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
