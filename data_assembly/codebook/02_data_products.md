# Data products

The data is provided in three temporal resolutions, each matched to three state system definitions, for a total of nine CSV files. All filenames include the version number (currently v{{VERSION}}).

## State system definitions

- **COW** (Correlates of War): The standard COW state system membership list (2024 version). Files use the suffix `_cow`.
- **GW** (Gleditsch-Ward): The Gleditsch-Ward state system membership list, excluding microstates. Files use the suffix `_gw`.
- **GWM** (Gleditsch-Ward with microstates): The Gleditsch-Ward list supplemented with micro and island states. Files use the suffix `_gwm`. GW and GWM share the same coding system (abbreviations, numeric codes, and country names); they differ only in which states are included.

## Distributed files

### Range datasets (one row per country--date range)

- `mission_status_range_cow_v{{VERSION}}.csv`
- `mission_status_range_gw_v{{VERSION}}.csv`
- `mission_status_range_gwm_v{{VERSION}}.csv`

### Monthly datasets (one row per country-code--month)

- `mission_status_monthly_cow_v{{VERSION}}.csv`
- `mission_status_monthly_gw_v{{VERSION}}.csv`
- `mission_status_monthly_gwm_v{{VERSION}}.csv`

### Yearly datasets (one row per country-code--year)

- `mission_status_yearly_cow_v{{VERSION}}.csv`
- `mission_status_yearly_gw_v{{VERSION}}.csv`
- `mission_status_yearly_gwm_v{{VERSION}}.csv`

### Daily datasets (not distributed)

Daily-level datasets (one row per country--day) are not distributed due to their size, but can be generated from the range data. See Section 6 for code to produce daily data from the range files.
