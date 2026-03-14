# State system definitions

The data is matched to two widely used state system membership datasets, each defining which political entities count as sovereign states and when.

## Correlates of War (COW)

The Correlates of War project's state system membership list (2024 version). COW defines system membership beginning in 1816, with most entries starting in the 19th or 20th century. Each state is identified by a three-letter abbreviation (e.g., `AFG`) and a numeric code (e.g., `700`).

Source: Correlates of War Project, "State System Membership List, v2024," <https://correlatesofwar.org/data-sets/state-system-membership/>.

## Gleditsch-Ward (GW)

The Gleditsch-Ward state system membership list, as revised and extended by Gleditsch and Ward (1999). GW uses similar conventions to COW but differs in its criteria for statehood, resulting in different membership dates and country lists. Each state is identified by a two- to five-letter abbreviation and a numeric code.

Source: Kristian Skrede Gleditsch and Michael D. Ward, "Interstate System Membership: A Revised List of the Independent States since 1816," *International Interactions* 25, no. 4 (1999): 393--413.

## Gleditsch-Ward with microstates (GWM)

The GW list supplemented with micro and island states that are not included in the standard GW data. Uses the same coding system as GW.

## USDOS name mapping

State system codes are mapped to U.S. Department of State country names using a hand-maintained mapping file. Some codes have date-bounded entries where the USDOS name changes over time (e.g., COW code `YUG` maps to "Kingdom of Serbia/Yugoslavia" before 1992 and "Serbia" after). When the USDOS name changes within a state system membership interval, the range data is split at the boundary so that each row has a unique `country_name_usdos` value.
