# Extraction of transitions in US diplomatic mission status

## Overview

This pipeline validates human-coded diplomatic events against primary sources and produces auditable sourcing records. For each country, it compares a CSV of hand-coded events against XML source files from the State Department, identifies discrepancies, and generates structured sourcing information tied to specific lines in the repo.


## Inputs

- `input/2024-01-16_transitions.csv`: Hand-coded diplomatic status changes. Columns: `state_dept_name`, `status_change`, `year`, `month`, `day`, `last_verified`, `notes`.
- `rdcr/articles/*.xml`: Primary source. TEI-encoded narrative prose from *A Guide to the United States' History of Recognition, Diplomatic, and Consular Relations, by Country, since 1776*. One file per country (e.g., `afghanistan.xml`). Each file contains paragraphs describing the full history of U.S. relations with that country.
- `pocom/missions-countries/*.xml`: Secondary source. Structured records from *Principal Officers & Chiefs of Mission*. One file per country. Each file lists chiefs of mission with role titles, appointment dates, credential presentation dates, and departure dates. Despite the structured XML format, these records contain inconsistencies, gaps, and edge cases that resist purely programmatic parsing — which is why they are sent through the LLM extraction pipeline rather than parsed directly.

Both `rdcr/` and `pocom/` are git submodules. Not every country appears in both repos: `rdcr` includes many historical entities (e.g., Austrian Empire, Baden, Hanseatic Republics) that have no `pocom` counterpart, and the filename conventions differ between the two repos.


## Design Principles

### Reproducibility requirements

All LLM-powered steps in this pipeline MUST go through the **Anthropic Messages API** directly (`api.anthropic.com/v1/messages`), not through Claude Code's own agentic loop. This is a research pipeline and every inference step must be fully specified and logged.

For every API call:

- **Pin the model version** using the full model string, never a bare alias.
  - Opus: `claude-opus-4-6`
  - Sonnet: `claude-sonnet-4-6`
  - Haiku: `claude-haiku-4-5-20251001`
- **Set `temperature: 0`** for all calls.
- **Use tool use / function calling** to enforce structured JSON output schemas. Do not rely on the model to produce well-formed JSON in free text.
- **Log the complete request and response** for every call — system prompt, messages, tool definitions, all parameters, and the full response body. Write these to a JSONL log file.
- **Embed run metadata in all stored JSON outputs**. Every JSON file the pipeline writes must include:
  - `run_timestamp`: ISO 8601 datetime (with timezone) recorded once at pipeline start and used consistently across all outputs from that run.
  - `api_metadata`: for any output derived from an API call, capture the response-level fields returned by the Messages API — at minimum `id` (the unique message ID), `model` (the resolved model version string, which may differ from the alias sent in the request), `usage` (`input_tokens`, `output_tokens`), and `stop_reason`. This is the primary mechanism for tracking which exact model version produced each result.
- **Version-control the prompts**. Each prompt template should live in its own file (e.g., `input/prompt_extract.txt`, `input/prompt_reconcile.txt`) so that changes are trackable in git.

### Deterministic verification

Anything that *can* be checked programmatically *should* be checked programmatically. The LLM is used for reading comprehension and judgment; string matching, line-number lookups, and data formatting are handled in Python.


## Pipeline Architecture

The pipeline has five stages. Stages 0, 1, and 3 are pure Python. Stages 2 and 4 use the Messages API.

### Stage 0: Country Name Resolution (Python, no LLM)

The mapping from country names in the CSV to filenames in the State Department source repos may not be straightforward. Country names change over time (Zaire → Congo, Burma → Myanmar, Swaziland → Eswatini), transliteration varies, filenames may use hyphens, underscores, or abbreviations, and some CSV entries may refer to entities that don't have a one-to-one match in the repo (e.g., historical entities that were later merged or split).

Build the mapping as follows:

1. List all country names (or identifiers) present in the CSV data (the `state_dept_name` column).
2. List all available XML files in each source repo separately: `rdcr/articles/*.xml` and `pocom/missions-countries/*.xml`. Extract the country identifier from each filename (the stem without extension, e.g., `afghanistan`).
3. For each source repo independently, attempt deterministic matching:
   - Normalize both sides: lowercase, strip diacritics, collapse whitespace, remove punctuation.
   - Try exact match on normalized strings.
   - Try known aliases from a hand-maintained lookup table (`input/country_aliases.yaml`). Seed this with common cases (e.g., `"Korea, South": "korea-south"`, `"Congo (Kinshasa)": "congo-democratic-republic"`). This file will grow as edge cases surface.
4. For any CSV country that has no match in **either** repo, flag it in a **resolution report** for manual review. Do not guess — an incorrect match is worse than a missing one. Countries that match in one repo but not the other are normal (see Inputs) and should proceed with whichever source is available.

Output: a mapping file (`output/country_mapping.json`) with one entry per CSV country, structured as:

```json
{
  "Afghanistan": {
    "rdcr": "rdcr/articles/afghanistan.xml",
    "pocom": "pocom/missions-countries/afghanistan.xml"
  },
  "Austrian Empire": {
    "rdcr": "rdcr/articles/austrian-empire.xml",
    "pocom": null
  }
}
```

Countries with at least one source proceed to the rest of the pipeline. Countries with no match in either repo are listed separately as unresolved.

**Important**: Review the resolution report before running the rest of the pipeline. Any unresolved countries need manual additions to `input/country_aliases.yaml`, after which Stage 0 can be re-run.

### Stage 1: Preprocessing (Python, no LLM)

For each country:

1. Read the CSV file and parse events into a list of structured records.
2. Read each available XML source file and produce a **numbered-line plain text** version. The two repos have different XML structures and need different preprocessing:
   - **rdcr** (TEI narrative): Strip XML tags, collapse inline elements (`<placeName>`, `<persName>`, `<date>`, etc.) to their text content, and preserve paragraph breaks. The result should read as continuous prose.
   - **pocom** (structured mission records): Render each chief-of-mission record as a readable line or short block, e.g., `"William H. Hornibrook, Envoy Extraordinary and Minister Plenipotentiary. Appointed: 1935-01-22. Credentials presented: 1935-05-04. Left post: 1936-03-16."` Preserve any free-text `<note>` fields. The goal is a format the model can read and cite line numbers from, not a faithful XML reproduction.
   - In both cases: prepend a line number to each line (e.g., `[42] The United States established diplomatic relations with...`) and record the mapping between line numbers and byte offsets in the original XML file.
3. Compute the current git commit hash of each source submodule (not the parent repo).
4. Record the file paths relative to the repo root.
5. Estimate token counts for each processed source file using the `anthropic` package's token counting endpoint or, if unavailable, a rough heuristic of 1 token per 4 characters. Flag any file exceeding 60K tokens for special handling.

Output: a per-country work unit containing the parsed CSV events, numbered source texts, and repo metadata.

### Stage 2: Independent Extraction (Messages API)

For each country, make one API call per available source file. Some countries will have both rdcr and pocom sources; others will have only one. Do **not** include the CSV in these calls. The goal is an independent reading.

Status transitions should be coded according to the scheme in `README.md`. Do not code recognition events or events related to the receiving country's diplomatic status in the USA. We are interested solely in changes in the highest level of USA diplomatic mission in the receiving country.

**System prompt** should specify:
- The researcher's event schema (what counts as a diplomatic status change — establish relations, break relations, suspend relations, resume relations, raise/lower legation to embassy, etc.).
- Instructions to extract every event matching the schema, with date, event type, and a brief description.
- Instructions to cite the evidence: return the line range from the numbered text and a **verbatim quote** (short — one or two sentences max) that supports the event.
- Instructions to flag any ambiguous or uncertain events with a confidence indicator.

**Use tool use** to define the output schema. The `new_status` field should be constrained to match the status categories defined in `README.md`. The `event_description` field is free text for the model to describe what happened.

```json
{
  "type": "object",
  "properties": {
    "country": { "type": "string" },
    "source_file": { "type": "string" },
    "events": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "date": { "type": "string", "description": "ISO 8601 date or partial date (YYYY, YYYY-MM, or YYYY-MM-DD)" },
          "new_status": {
            "type": "string",
            "enum": [
              "Embassy",
              "Ambassador Nonresident",
              "Legation",
              "Envoy Nonresident",
              "Consulate",
              "Consul Nonresident",
              "Liaison",
              "Interests",
              "None"
            ],
            "description": "The highest level of U.S. diplomatic representation after the change"
          },
          "event_description": { "type": "string", "description": "Brief description of what happened" },
          "confidence": { "type": "string", "enum": ["high", "medium", "low"] },
          "evidence": {
            "type": "array",
            "items": {
              "type": "object",
              "properties": {
                "line_start": { "type": "integer" },
                "line_end": { "type": "integer" },
                "quote": { "type": "string" }
              }
            }
          }
        }
      }
    }
  }
}
```

The tool-use schema above defines the structure the model returns. When writing the extraction result to disk, **wrap it** with the run metadata fields described in the reproducibility requirements:

```json
{
  "run_timestamp": "2026-03-13T14:22:07-05:00",
  "api_metadata": {
    "message_id": "msg_01XFDUDYJgAACzvnptvVoYEL",
    "model": "claude-sonnet-4-6-20260313",
    "usage": { "input_tokens": 3842, "output_tokens": 1205 },
    "stop_reason": "end_turn"
  },
  "result": { "...extraction output from tool use..." }
}
```

The `model` field here is the value returned by the API in the response, not the alias sent in the request — this is the authoritative record of which model version produced the output.

**Model:** Sonnet is the right choice here. This is a structured extraction task over relatively straightforward prose — it doesn't require the deeper reasoning of Opus, and Sonnet's speed and cost profile make it practical for running across many countries. It is also strong at following schemas precisely.

### Stage 3: Quote Verification (Python, no LLM)

Before reconciliation, verify every quote returned in Stage 2:

1. For each extracted event, retrieve the actual text at the claimed line range from the numbered source.
2. Do a fuzzy string match (e.g., `difflib.SequenceMatcher` or similar) between the claimed quote and the actual text at those lines.
3. Flag any quote with a match ratio below a threshold (suggest 0.85) as a **citation error**.
4. Events with citation errors should be included in the reconciliation but marked, so the reconciler knows the evidence may be unreliable.

This step is critical. It is the primary defense against hallucinated sourcing.

### Stage 4: Reconciliation (Messages API)

For each country, make one API call that includes:

- The events extracted in Stage 2 (from all available source files for that country, merged and deduplicated).
- The events from the human-coded CSV.
- Any citation-error flags from Stage 3.

**System prompt** should instruct the model to produce a reconciliation report:

- **Matches**: Events present in both the human CSV and the extracted set. Note any minor discrepancies in date or status.
- **Missing from CSV**: Events found in the sources but absent from the human coding. These are candidates for additions.
- **Unsupported in sources**: Events in the human CSV that could not be found in either source file. These may be errors in the CSV, or may reflect information from sources not included in this pipeline.
- **Discrepancies**: Events present in both but with conflicting dates, statuses, or descriptions.

For each item in the report, the model should reference the relevant extracted event(s) and/or CSV row(s).

**Use tool use** to enforce the output schema:

```json
{
  "type": "object",
  "properties": {
    "country": { "type": "string" },
    "matched": {
      "type": "array",
      "description": "Events present in both CSV and extracted set with consistent date and status",
      "items": {
        "type": "object",
        "properties": {
          "csv_row": { "type": "integer", "description": "1-indexed row number in the country's CSV events" },
          "extracted_event_indices": {
            "type": "array",
            "items": { "type": "integer" },
            "description": "Indices into the merged/deduplicated extraction events list"
          },
          "notes": { "type": "string", "description": "Any minor discrepancies or observations" }
        }
      }
    },
    "missing_from_csv": {
      "type": "array",
      "description": "Events found in sources but absent from CSV — candidates for addition",
      "items": {
        "type": "object",
        "properties": {
          "extracted_event_indices": {
            "type": "array",
            "items": { "type": "integer" }
          },
          "date": { "type": "string" },
          "new_status": { "type": "string" },
          "event_description": { "type": "string" },
          "notes": { "type": "string" }
        }
      }
    },
    "unsupported_in_sources": {
      "type": "array",
      "description": "CSV events not found in either source file",
      "items": {
        "type": "object",
        "properties": {
          "csv_row": { "type": "integer" },
          "notes": { "type": "string", "description": "Why the model believes this event is unsupported" }
        }
      }
    },
    "discrepancies": {
      "type": "array",
      "description": "Events present in both but with conflicting dates, statuses, or descriptions",
      "items": {
        "type": "object",
        "properties": {
          "csv_row": { "type": "integer" },
          "extracted_event_indices": {
            "type": "array",
            "items": { "type": "integer" }
          },
          "field": { "type": "string", "description": "Which field conflicts: date, new_status, or both" },
          "csv_value": { "type": "string" },
          "extracted_value": { "type": "string" },
          "assessment": { "type": "string", "enum": ["csv_likely_correct", "extracted_likely_correct", "ambiguous"] },
          "reasoning": { "type": "string" }
        }
      }
    }
  }
}
```

**Model:** Opus is warranted here because reconciliation requires judgment. The model must reason about whether two differently-described events are actually the same, whether date discrepancies reflect errors or ambiguity in the sources, and whether "missing" events are genuinely absent or just described differently. This is a harder cognitive task than extraction.

### Output Assembly (Python, no LLM)

For each event in the final validated set, produce a sourcing record:

```json
{
  "run_timestamp": "2026-03-13T14:22:07-05:00",
  "country": "Freedonia",
  "date": "1925-06-15",
  "new_status": "Legation",
  "event_description": "The United States established a legation in Freedonia.",
  "confidence": "high",
  "sources": [
    {
      "repo_commit": "abc123def456",
      "file_path": "rdcr/articles/freedonia.xml",
      "line_start": 42,
      "line_end": 44,
      "quote": "On June 15, 1925, the United States and Freedonia established formal diplomatic relations."
    }
  ],
  "extraction_api_metadata": {
    "message_id": "msg_01XFDUDYJgAACzvnptvVoYEL",
    "model": "claude-sonnet-4-6-20260313",
    "usage": { "input_tokens": 3842, "output_tokens": 1205 },
    "stop_reason": "end_turn"
  },
  "reconciliation_api_metadata": {
    "message_id": "msg_01ABCDEFghijklmnop",
    "model": "claude-opus-4-6-20260313",
    "usage": { "input_tokens": 8210, "output_tokens": 2407 },
    "stop_reason": "end_turn"
  },
  "validation_status": "confirmed",
  "validation_notes": "Matches CSV row 7. Date and status consistent."
}
```

Each final record carries `run_timestamp` (set once at pipeline start), plus the API response metadata from both the extraction and reconciliation calls that produced it. This makes it possible to trace any output record back to the exact model versions and API calls that generated it, without consulting the separate JSONL log.

Write the full results to a structured output file (JSON or JSONL, one record per event per country). Also write a summary CSV with one row per country showing counts of confirmed, added, flagged, and unsupported events.


## Configuration

Use a single `input/extraction_config.yaml` to pin all parameters:

```yaml
models:
  extraction: "claude-sonnet-4-6"
  reconciliation: "claude-opus-4-6"

api:
  temperature: 0
  max_tokens_extraction: 4096
  max_tokens_reconciliation: 8192

verification:
  quote_match_threshold: 0.85

paths:
  rdcr_articles: "./rdcr/articles"
  pocom_missions: "./pocom/missions-countries"
  transitions_csv: "./input/2024-01-16_transitions.csv"
  country_aliases: "./input/country_aliases.yaml"
  output_dir: "./output"
  log_dir: "./logs"
```

The `country_aliases.yaml` file maps CSV country names to source repo identifiers. Seed it with known mismatches and add to it as Stage 0 surfaces unresolved cases:

```yaml
# CSV name -> repo filename stem (without extension)
"Korea, South": "korea-south"
"Congo (Kinshasa)": "congo-democratic-republic"
"Burma": "burma"  # even if repo uses "myanmar", list both directions
"Myanmar": "burma"
"Eswatini": "swaziland"  # if repo still uses old name
```


## Error Handling and Retry

- Wrap all API calls in retry logic with exponential backoff for rate limits and transient failures.
- If an extraction call fails after retries, log the failure and skip that country, don't halt the full pipeline.
- Write a manifest of which countries succeeded and which failed so partial runs can be resumed.


## Notes on Chunking

If Stage 1 flags any source files as exceeding 60K tokens, those files need to be split. Split on paragraph or section boundaries in the original XML, with overlapping context (repeat the last 2–3 paragraphs of each chunk at the start of the next). After Stage 2, deduplicate extracted events across chunks by matching on date and event type before passing to Stage 4. This should be rare for State Department country pages — most will fit comfortably in a single call.


## Cost Estimation

Before running the full pipeline, do a dry run on 3–5 representative countries (pick one small, one medium, one with complex history) to measure actual token usage and API costs per country. Use those numbers to estimate the cost of the full run and decide whether any prompt optimization is needed.
