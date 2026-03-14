# U.S. Diplomatic Mission Status Data

Panel datasets recording the status of U.S. diplomatic missions abroad, from the earliest diplomatic contacts through 2024, matched to standard state system membership data used in international relations research.

**[Download the data](https://github.com/brentonk/us_diplomatic_missions/releases)** | **[Codebook](data/v0.1/CODEBOOK_us_mission_status_v0.1.md)** | **[Project website](https://brentonk.github.io/us_diplomatic_missions/)**

Maintained by Brenton Kenkel, Vanderbilt University (<brenton.kenkel@gmail.com>)

## Quick start

Download the data files from the [latest release](https://github.com/brentonk/us_diplomatic_missions/releases) or directly from [`data/v0.1/`](data/v0.1/).

Each state system definition (Correlates of War states, Gleditsch-Ward states, Gleditsch-Ward states + microstates) is available at three temporal resolutions:

| Resolution | Description | Example file |
|---|---|---|
| **Range** | One row per country--date range with constant status | `mission_status_range_cow_v0.1.csv` |
| **Monthly** | One row per country--month (min/max/median/mode) | `mission_status_monthly_cow_v0.1.csv` |
| **Yearly** | One row per country--year (min/max/median/mode) | `mission_status_yearly_cow_v0.1.csv` |

See the [codebook](data/v0.1/CODEBOOK_us_mission_status_v0.1.md) for variable definitions, coding rules, and special cases.

## Diplomatic status categories

Each observation records the highest level of U.S. diplomatic representation. The categories, ordered from greatest to least, are:

1. **Embassy**: Permanent diplomatic mission headed by an ambassador.
2. **Ambassador Nonresident**: Nonresident ambassadorial relations.
3. **Legation**: Permanent diplomatic mission of lower status than an embassy, typically headed by an Envoy Extraordinary and Minister Plenipotentiary. Largely phased out after WWII.
4. **Envoy Nonresident**: Nonresident envoy or minister relations.
5. **Consulate**: Consular office in the capital city. Only coded if located in the capital.
6. **Consul Nonresident**: Nonresident consular relations.
7. **Liaison**: Liaison office or informal diplomatic presence.
8. **Interests**: Interests section maintained under a protecting power.
9. **None**: No formal diplomatic representation.

## Sources

The primary source is the Office of the Historian, U.S. Department of State, [*A Guide to the United States' History of Recognition, Diplomatic, and Consular Relations, by Country, since 1776*](https://github.com/HistoryAtState/rdcr). Ambiguities are resolved by consulting [*Principal Officers & Chiefs of Mission*](https://github.com/HistoryAtState/pocom).

The extraction and validation pipeline uses Claude (Anthropic) via the Messages API to extract structured events from State Department XML sources and reconcile them against hand-coded transition data. All final coding decisions are made by the project maintainer.

## State system definitions

- **COW**: Correlates of War state system (2024 version).
- **GW**: Gleditsch-Ward state system, excluding microstates.
- **GWM**: Gleditsch-Ward state system, including microstates.

## Repository structure

```
us_diplomatic_missions/
├── data/
│   └── v0.1/                          # Versioned data products
│       ├── CODEBOOK_us_mission_status_v0.1.md
│       ├── CODEBOOK_us_mission_status_v0.1.pdf
│       ├── mission_status_range_{cow,gw,gwm}_v0.1.csv
│       ├── mission_status_monthly_{cow,gw,gwm}_v0.1.csv
│       └── mission_status_yearly_{cow,gw,gwm}_v0.1.csv
├── input/                              # Pipeline inputs
│   ├── 2024-01-16_transitions.csv      # Hand-coded diplomatic transitions (590 rows)
│   ├── extraction_config.yaml          # Pipeline configuration
│   ├── country_aliases.yaml            # CSV name → source repo filename overrides
│   ├── manual_reconciliation.yaml      # Human override decisions for reconciliation
│   ├── state_system_codes.yaml         # COW/GW code → USDOS name mapping
│   ├── cow_statelist2024.csv           # Raw COW state list
│   ├── ksgmdw.txt                      # Raw Gleditsch-Ward state list
│   ├── microstates.txt                 # GW microstate supplement
│   ├── prompt_extract.txt              # System prompt for LLM extraction (Stage 2)
│   └── prompt_reconcile.txt            # System prompt for LLM reconciliation (Stage 4)
├── output/
│   └── remote_api/                     # Non-deterministic LLM outputs (committed)
│       ├── extractions/                # Stage 2: per-country, per-source extraction results
│       └── reconciliations/            # Stage 4: per-country reconciliation results
├── transition_extraction/              # Extraction and validation pipeline
│   ├── api_client.py                   # Async Anthropic API client with retry
│   ├── assemble.py                     # Final output assembly from all stages
│   ├── audit_report.py                 # Interactive HTML audit interface
│   ├── config.py                       # Configuration loader
│   ├── models.py                       # Pydantic data models
│   ├── stage0_resolve.py               # Country name resolution
│   ├── stage1_preprocess.py            # XML → numbered text preprocessing
│   ├── stage2_extract.py               # LLM extraction (Sonnet)
│   ├── stage3_verify.py                # Quote verification
│   ├── stage4_reconcile.py             # LLM reconciliation (Opus)
│   ├── text_utils.py                   # Shared text utilities
│   └── xml_parsers.py                  # TEI and structured XML parsing
├── data_assembly/                      # Data product generation
│   ├── aggregator.py                   # Monthly/yearly aggregation
│   ├── codebook_builder.py             # Codebook assembly and PDF rendering
│   ├── codebook/                       # Codebook source fragments
│   ├── daily_builder.py                # Range → daily expansion
│   ├── generate.py                     # Orchestrator for all data products
│   ├── generate_web.py                 # Website source generation
│   ├── range_builder.py                # Interval-level range datasets
│   ├── state_codes.py                  # State system code resolver
│   ├── status.py                       # Diplomatic status ordering
│   ├── timeline.py                     # Status timeline logic
│   └── version.py                      # Version reader
├── web/                                # Quarto website source
├── rdcr/                               # Git submodule: State Dept narrative history
├── pocom/                              # Git submodule: State Dept mission records
├── .github/workflows/
│   ├── pages.yml                       # GitHub Pages deployment
│   └── release.yml                     # GitHub Release with data archives
├── main.py                             # CLI entry point
├── pyproject.toml
└── uv.lock
```

## Replication

All replication workflows require Python 3.12+ and [uv](https://docs.astral.sh/uv/).

```bash
git clone --recurse-submodules https://github.com/brentonk/us_diplomatic_missions.git
cd us_diplomatic_missions
uv sync
```

### Workflow 1: Regenerate data products from transitions

The simplest workflow. Regenerates the 9 CSV datasets, codebook, and website sources from the assembled transitions and state system inputs. No API calls required, but does require the git submodules for XML parsing (the assembly step reads from them).

```bash
uv run python main.py extraction0    # Resolve country names
uv run python main.py extraction1    # Parse XML → numbered text
uv run python main.py assemble       # Combine LLM outputs + manual decisions → transitions CSV
uv run python main.py generate-data  # Build data products from transitions CSV
```

The LLM extraction (Stage 2) and reconciliation (Stage 4) outputs are committed in `output/remote_api/`, so those stages can be skipped. The `assemble` step combines them with the manual decisions in `input/manual_reconciliation.yaml` to produce the transitions CSV, which `generate-data` then uses to build all data products in `data/v0.1/`.

### Workflow 2: Full pipeline replication

Reruns the entire pipeline from scratch, including the LLM API calls. This requires an Anthropic API key and costs approximately $17.

```bash
export ANTHROPIC_API_KEY="your-key-here"
uv run python main.py extraction-all # Extraction stages 0-4 + assembly
uv run python main.py generate-data  # Data products + website sources
```

Important caveats:

- **Non-deterministic**: LLM extraction and reconciliation produce slightly different outputs on each run, even at temperature 0. The committed outputs in `output/remote_api/` are the authoritative versions used to produce the released data.
- **Manual reconciliation**: The decisions in `input/manual_reconciliation.yaml` are keyed to specific extraction outputs. A fresh pipeline run will likely produce different extractions, requiring the manual reconciliation file to be revised.
- **Cost estimate**: Use `--dry-run` to preview API costs without making calls: `uv run python main.py --dry-run extraction2`. (My experience is that these overestimate actual costs, but YMMV.)
- **Country filter**: Test with a subset first: `uv run python main.py --countries "Afghanistan,Andorra" extraction-all`.
- **Audit interface**: After running the pipeline, generate the interactive audit report: `uv run python main.py audit`. This writes a self-contained HTML file to `output/local/final/audit_report.html` that you can open in a browser. It shows every discrepancy, candidate addition, and unsupported event by country, with the original CSV data alongside the LLM reconciliation output, so you can draft manual decisions for `input/manual_reconciliation.yaml`.

## Related datasets

Several existing datasets measure diplomatic representation in international relations.

**[COW Diplomatic Exchange](https://correlatesofwar.org/data-sets/diplomatic-exchange/)** (Bayer 2006).

**[Diplometrics Diplomatic Representation Database](https://korbel.du.edu/pardee/diplomatic-representation)** (Moyer et al 2023).

**[Measuring American Diplomacy](https://measuringdiplomacy.github.io/)** (Lindsey, Malis, and Thrall 2025).

Like the COW and Diplometrics data, this dataset focuses on the status of diplomatic missions. The geographical scope here is narrower, only examining missions sent by the U.S., but the resolution is finer than both (daily) and the scope is wider than Diplometrics (1776--present in raw transitions data, 1816--present in versions merged with state system data). The focus on the US is similar to the MAD project, but this collection focuses on mission status rather than individual appointees, and its temporal scope is wider.

## Coding conventions

For details on date coding rules, special cases (China/Taiwan, WWII governments in exile, nonresident representatives), and country identification, see the [codebook](data/v0.1/CODEBOOK_us_mission_status_v0.1.md).

## License

Code is released under the [MIT License](LICENSE). Data is released under [CC-BY 4.0](https://creativecommons.org/licenses/by/4.0/).

## Citation

If you use this data in academic work, please cite **working paper TBD**.
