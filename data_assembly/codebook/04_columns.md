# Column definitions

## Range datasets

The unit of observation is the **country--date range**. Each row represents a period during which a country's diplomatic status was constant.

| Column | Description |
|--------|-------------|
| `country_abbrev_cow` / `country_abbrev_gw` | Country abbreviation in the state system (e.g., `AFG`, `HAI`). |
| `country_code_cow` / `country_code_gw` | Numeric country code in the state system (e.g., `700`, `41`). |
| `country_name_cow` / `country_name_gw` | Country name in the state system (e.g., `Afghanistan`, `Haiti`). |
| `country_name_usdos` | Country name in U.S. Department of State records. Empty if no match exists. Rows are split when the USDOS name mapping changes over time. |
| `date_start` | Start date of the range (YYYY-MM-DD). |
| `date_end` | End date of the range (YYYY-MM-DD), inclusive. |
| `us_mission_status` | Diplomatic status during this range. One of the nine status strings listed in Section 3. |

For each country, the date ranges form a proper partition of the state system membership dates: no gaps, no overlaps, and complete coverage. Status carries forward across gaps in system membership (e.g., a country that exits and re-enters the system retains its most recent status at re-entry, if a transition occurred during the gap).

GW and GWM datasets use the `_gw` column suffix and share the same coding system. They differ only in which states are included.

## Monthly datasets

The unit of observation is **country-code--month**. Aggregation is over all days in the month for a given state system code.

| Column | Description |
|--------|-------------|
| `country_abbrev_cow` / `country_abbrev_gw` | Country abbreviation. |
| `country_code_cow` / `country_code_gw` | Numeric country code. |
| `country_name_cow` / `country_name_gw` | Country name. |
| `country_name_usdos` | USDOS name(s). If the name changes within the month, all applicable names are concatenated with ` / `. Empty if no match. |
| `month` | Month in YYYY-MM format. |
| `us_mission_min` | Least diplomatic status observed on any day in the month. |
| `us_mission_max` | Greatest diplomatic status observed on any day in the month. |
| `us_mission_median` | Median diplomatic status across all days in the month. |
| `us_mission_mode` | Most frequent diplomatic status across all days in the month. |

Status comparisons use the ordering in Section 3 (Embassy is the greatest, None is the least). Ties in the median or mode are broken in favor of the greater status.

## Yearly datasets

The unit of observation is **country-code--year**. Structure is identical to the monthly datasets, with `year` (YYYY format) replacing `month`.
