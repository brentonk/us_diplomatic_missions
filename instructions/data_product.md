# US diplomatic missions: Data product

The goal of this project is to host public data on the status of USA diplomatic missions abroad, matched (separately) to both the Correlates of War and the Gleditsch-Ward state system data.


## Data creation

In this stage of the project, you will create scripts in the `data_assembly/` subdirectory. `transition_extraction/` can be consulted for information on how the USDOS-identified transitions data was created, but it should be left untouched unless you notice critical errors in the logic of the code there.

You will work with three definitions of the state system.

- Correlates of War
- Gleditsch-Ward without microstates
- Gleditsch-Ward with microstates

For each of these state system definitions, you will create four datasets in CSV format.

All output CSV filenames include the version from `pyproject.toml` (e.g., `mission_status_range_cow_v0.1.csv`). The version must be read from `pyproject.toml` at generation time, not hardcoded. Output files are written to `data/v[VERSION]/` (e.g., `data/v0.1/mission_status_range_cow_v0.1.csv`).

Note: GW and GWM datasets share the same coding system (abbreviations, numeric codes, and country names), so column names use `_gw` in both. They differ only in which states are included: GWM adds microstates.

### Input files

- **Assembled transitions:** `output/final/assembled_transitions.csv` --- the confirmed diplomatic status changes, produced by `python main.py assemble`. Same column format as the hand-coded input (`state_dept_name`, `status_change`, `year`, `month`, `day`).
- **USDOS name mapping:** `input/state_system_codes.yaml` --- maps state system codes to USDOS country names. Some codes have date-bounded entries (e.g., YUG maps to "Kingdom of Serbia/Yugoslavia" before 1992-05-21 and "Serbia" after). This file drives the `country_name_usdos` column and determines where intervals must be split.
- **COW state list:** `input/cow_statelist2024.csv` --- system membership intervals for the Correlates of War definition.
- **GW state list:** `input/ksgmdw.txt` --- system membership intervals for Gleditsch-Ward (tab-separated).
- **GW microstates supplement:** `input/microstates.txt` --- additional micro/island states for the GWM definition.

The existing `data_assembly/` code provides infrastructure that can be extended:

- `state_codes.py` has `StateCodeResolver`, which loads the raw state system data and the YAML mapping.
- `panel.py` has `build_panel()`, which builds interval-level panels for a quick diagnostic. It reads from the raw input transitions CSV and uses different column names. The core logic (splitting intervals at transition dates and USDOS name-change boundaries, carrying status across gaps) is similar to what is needed for the data product. Once the data product scripts are complete, evaluate whether `panel.py` and its associated diagnostic (`diagnostics.py`) have become redundant.

### 1. Mission level status ranges: `mission_status_range_[cow|gw|gwm]_v[VERSION].csv`

The most compact, human-readable version of the data. The unit of observation is the **country--date range**, akin to the input state system membership data. Each row is a separate diplomatic status.

The dataset should contain the following columns:

- `country_abbrev_[cow|gw]`: Country name abbreviation in the corresponding system.
- `country_code_[cow|gw]`: Country code in the corresponding system.
- `country_name_[cow|gw]`: Country name in the corresponding system.
- `country_name_usdos`: Country name in US Department of State records.
  - Should be unique to each row---split rows in cases where the mapping changes.
  - Leave empty if no match in US Department of State records.
- `date_start`: Starting date for the date range, in YYYY-MM-DD format.
- `date_end`: Ending date for the date range, in YYYY-MM-DD format.
- `us_mission_status`: Highest level of US diplomatic mission in the recipient country during the time range.

Every non-USA country in the underlying system data should be included, even if it has no match in US Department of State records. In cases of no match, the diplomatic mission status should be recorded as "None" throughout the range.

At system (re)entry dates, check the corresponding transition event data for the most recent status on the same day or earlier. If there is a match, use that as the initial status. If no match, set initial status to "None."

**Partition principle:** For each country, the date ranges should form a proper partition of the date ranges in the state system membership data. In other words, there should be no overlap between the date ranges in any pair of rows corresponding to the same country, and the collection of rows should exactly cover the set of dates of state system membership.

If a transition entry does not have the precise day, use the earliest day available. This means YYYY entries will be mapped to YYYY-01-01, and YYYY-MM entries will be mapped to YYYY-MM-01.

#### Simple example --- Haiti in COW

```
HAI,41,Haiti,Haiti,1859-01-01,1862-09-30,None
HAI,41,Haiti,Haiti,1862-10-01,1915-07-28,Legation
HAI,41,Haiti,Haiti,1934-08-15,1943-03-22,Legation
HAI,41,Haiti,Haiti,1943-03-23,1963-05-14,Embassy
HAI,41,Haiti,Haiti,1963-05-15,1964-01-15,None
HAI,41,Haiti,Haiti,1964-01-16,2024-12-31,Embassy
```

#### Complex example --- Yugoslavia/Serbia in COW

Yugoslavia (YUG, code 345) illustrates several complications: the USDOS name mapping changes over time (Kingdom of Serbia/Yugoslavia before 1992-05-21, Serbia after), there is a WWII gap in system membership, and the code eventually transitions to SRB.

The assembled transitions contain the following confirmed events:

- Kingdom of Serbia/Yugoslavia: Legation (1882-11-10), Embassy (1942-09-29)
- Serbia: Embassy (1992-05-21), None (1999-03-23), Embassy (2001-05-01)

COW system membership spans three intervals: YUG 1878-07-13 to 1941-04-20, YUG 1944-10-20 to 2006-06-03, and SRB 2006-06-03 to 2024-12-31.

```
YUG,345,Yugoslavia,Kingdom of Serbia/Yugoslavia,1878-07-13,1882-11-09,None
YUG,345,Yugoslavia,Kingdom of Serbia/Yugoslavia,1882-11-10,1941-04-20,Legation
YUG,345,Yugoslavia,Kingdom of Serbia/Yugoslavia,1944-10-20,1992-05-20,Embassy
YUG,345,Yugoslavia,Serbia,1992-05-21,1999-03-22,Embassy
YUG,345,Yugoslavia,Serbia,1999-03-23,2001-04-30,None
YUG,345,Yugoslavia,Serbia,2001-05-01,2006-06-03,Embassy
SRB,345,Serbia,Serbia,2006-06-03,2024-12-31,Embassy
```

Key features demonstrated:

- **USDOS name split:** Row 3 to row 4 splits at the 1992-05-21 mapping boundary, changing `country_name_usdos` from "Kingdom of Serbia/Yugoslavia" to "Serbia" within the same system code.
- **Status carry-over across a gap:** The Embassy transition on 1942-09-29 falls during the WWII gap in system membership. At re-entry (1944-10-20), the most recent status is carried forward.
- **Diplomatic suspension:** The 1999 Kosovo War interruption sets status to None, restored in 2001.
- **Code succession:** YUG ends and SRB begins on 2006-06-03, sharing numeric code 345 but with different abbreviations and system names.

### 2. Daily mission status: `mission_status_daily_[cow|gw|gwm]_v[VERSION].csv`

The "long" version of the data. This should be generated algorithmically from the date range data and contain the following columns.

- `country_abbrev_[cow|gw]`: Country name abbreviation in the corresponding system.
- `country_code_[cow|gw]`: Country code in the corresponding system.
- `country_name_[cow|gw]`: Country name in the corresponding system.
- `country_name_usdos`: Country name in US Department of State records. Leave empty if no match.
- `date`: Day in YYYY-MM-DD format.
- `us_mission_status`: Highest level of US diplomatic mission in the recipient country on the given day.

### 3. Monthly mission status: `mission_status_monthly_[cow|gw|gwm]_v[VERSION].csv`

Aggregated from the daily data. The unit of observation is **country-code--month**: one row per state system code per month. Aggregation is over all days in the month for a given code, regardless of USDOS name changes within the month.

- `country_abbrev_[cow|gw]`: Country name abbreviation in the corresponding system.
- `country_code_[cow|gw]`: Country code in the corresponding system.
- `country_name_[cow|gw]`: Country name in the corresponding system.
- `country_name_usdos`: Country name in US Department of State records. If the USDOS name changes within the month, concatenate all applicable names (separated by ` / `). Leave empty if no match.
- `month`: Month in YYYY-MM format.
- `us_mission_min`: Minimum diplomatic status across all days in the month.
- `us_mission_max`: Maximum diplomatic status across all days in the month.
- `us_mission_median`: Median diplomatic status across all days in the month.
- `us_mission_mode`: Modal diplomatic status across all days in the month.

### 4. Yearly mission status: `mission_status_yearly_[cow|gw|gwm]_v[VERSION].csv`

Aggregated from the daily data. The unit of observation is **country-code--year**: one row per state system code per year. Aggregation is over all days in the year for a given code, regardless of USDOS name changes within the year.

- `country_abbrev_[cow|gw]`: Country name abbreviation in the corresponding system.
- `country_code_[cow|gw]`: Country code in the corresponding system.
- `country_name_[cow|gw]`: Country name in the corresponding system.
- `country_name_usdos`: Country name in US Department of State records. If the USDOS name changes within the year, concatenate all applicable names (separated by ` / `). Leave empty if no match.
- `year`: Year in YYYY format.
- `us_mission_min`: Minimum diplomatic status across all days in the year.
- `us_mission_max`: Maximum diplomatic status across all days in the year.
- `us_mission_median`: Median diplomatic status across all days in the year.
- `us_mission_mode`: Modal diplomatic status across all days in the year.

### Status ordering for aggregation

Diplomatic statuses are ordered from greatest (Embassy) to least (None), per `README.md`:

1. Embassy (max)
2. Ambassador Nonresident
3. Legation
4. Envoy Nonresident
5. Consulate
6. Consul Nonresident
7. Liaison
8. Interests
9. None (min)

All `us_mission_*` columns in every dataset must contain one of these nine strings exactly. Intermediate code may use numeric ranks internally, but output values must be character strings. Ties in the median or mode (unlikely to occur) should be broken in favor of the greater status.

### Codebook: `CODEBOOK_us_mission_status_v[VERSION].md` and `CODEBOOK_us_mission_status_v[VERSION].pdf`

A codebook should be written in Markdown and exported to PDF via pandoc. The codebook should include the following:

1. Brief overview of the data project
2. Brief listing of data products
3. Clear explanation of the diplomatic statuses tracked, the coding rules for transitions, and the sources consulted
4. Clear explanation of the row structure and column definitions for each data product
   - These can be collapsed as appropriate (e.g., we don't need nearly-redundant versions of the gw daily and gwm daily datasets, for example)
5. (for versions after 0.1) Running change log

It is fine if there are multiple source files that go into the codebook creation, but they must be assembled or compiled into a single Markdown file at the end.


## Versioning

The canonical version lives in `pyproject.toml` (currently 0.1, the initial pre-release). After the initial release, any code change that produces different output data requires a version bump before release: minor for small corrections, major for things like new state system data versions. Each release gets a GitHub tag (e.g., `v0.1`). Data from prior releases must never be deleted or overwritten --- this project is intended for scientific research and published results must remain reproducible from their tagged release.


## Website

The data product will be distributed via a GitHub Pages website. Source code for the website should live in `web/`, with static output placed in `_site/`. A GitHub workflow should be set up to publish the site on push.

Most components of the website should be procedurally generated from the codebase, not hard-coded. I am comfortable with Quarto-based websites (e.g., I have used it for course websites, see `brentonk/qps1` and `brentonk/mfpa`), but open to other frameworks. Whatever works best.

### Data and codebook download

The most important part of the website is a page to download the data and codebook. This page should be organized in reverse chronological order, with the most recent release in its own section at the top, and then (once version > 0.1) a second archive section at the bottom with older releases.

After version 0.1, the top listing should have the change log for the most recent release since the last release, and the archive listings should also contain their relevant change logs.

Links should be provided to download each individual file, as well as `us_mission_status_v[VERSION].zip` and `us_mission_status_v[VERSION].tar.gz` archives containing all 14 files (12 data products + 2 codebook files). The archives should have a "flat" organization with no nested directories. The website should link directly to raw files in the `data/v[VERSION]/` directory on GitHub rather than copying files into `_site/`, if feasible.

### Data explorer

I would also like to include a data explorer section containing basic information about each country included in the data.

I envision the data explorer growing over time, but for now let's keep it simple. There should be a list of country names (COW by default, with dropdown letting user switch to GW). Click on a name and it takes you to a page that shows you a timeline of diplomatic status, corresponding to the date range data but presented legibly.
