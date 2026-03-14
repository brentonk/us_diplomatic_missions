# Generating daily data

Daily-level datasets are not distributed due to their size (approximately 6--7 million rows per state system definition). They can be generated from the range datasets by expanding each date range into individual rows.

## Daily dataset columns

| Column | Description |
|--------|-------------|
| `country_abbrev_cow` / `country_abbrev_gw` | Country abbreviation. |
| `country_code_cow` / `country_code_gw` | Numeric country code. |
| `country_name_cow` / `country_name_gw` | Country name. |
| `country_name_usdos` | USDOS name. Empty if no match. |
| `date` | Date in YYYY-MM-DD format. |
| `us_mission_status` | Diplomatic status on that date. |

## R (tidyverse)

```r
library(tidyverse)

range_df <- read_csv("mission_status_range_cow_v{{VERSION}}.csv")

daily_df <- range_df |>
  mutate(date = map2(date_start, date_end, ~ seq(.x, .y, by = "day"))) |>
  unnest(date) |>
  select(-date_start, -date_end)
```

## Python (pandas)

```python
import pandas as pd

range_df = pd.read_csv("mission_status_range_cow_v{{VERSION}}.csv",
                        parse_dates=["date_start", "date_end"])

daily_rows = []
for _, row in range_df.iterrows():
    dates = pd.date_range(row["date_start"], row["date_end"], freq="D")
    for d in dates:
        daily_rows.append({**row.drop(["date_start", "date_end"]), "date": d})

daily_df = pd.DataFrame(daily_rows)
```

Replace `cow` with `gw` or `gwm` for other state system definitions. Daily data files are also available on request from the project maintainers.
