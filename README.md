# U.S. Diplomatic Exchange Data

## Transitions data

### Overview

The data records the date and nature of substantial changes in the highest level of U.S. diplomatic representation in foreign capitals. The primary source is the Office of the Historian, U.S. Department of State, *A Guide to the United States' History of Recognition, Diplomatic, and Consular Relations, by Country, since 1776* (available in machine-readable XML at <https://github.com/HistoryAtState/rdcr>). Ambiguities in the primary source are resolved by consulting *Principal Officers & Chiefs of Mission* (<https://github.com/HistoryAtState/pocom>).

### Diplomatic status categories

Each transition records the highest level of U.S. diplomatic representation after the change. The categories, ordered from greatest to least, are:

1. **Embassy**: Permanent diplomatic mission headed by an ambassador.
2. **Ambassador Nonresident**: Nonresident ambassadorial relations --- ambassadors accredited to the country but not resident there.
3. **Legation**: Permanent diplomatic mission of lower status than an embassy, typically headed by an Envoy Extraordinary and Minister Plenipotentiary. Largely phased out after World War II.
4. **Envoy Nonresident**: Nonresident envoy relations --- envoys or ministers accredited to the country but not resident there.
5. **Consulate**: Consular office in the capital city. Only coded if located in the capital.
6. **Consul Nonresident**: Nonresident consular relations.
7. **Liaison**: Liaison office or informal diplomatic presence (e.g., "Office of the U.S. Representative," "Diplomatic Agent").
8. **Interests**: Interests section --- diplomats of one state working under the flag of a second on the territory of a third, used to maintain communication when formal relations are broken.
9. **None**: No formal diplomatic representation.

### Date coding rules

- When the records specify the date an embassy, legation, or consulate general opened, that date is used.
- If no specific opening date is provided, the date of presentation of credentials by the first chief of mission is used.
- For elevations of existing relations (e.g., legation to embassy), the date of formal elevation is used, even if there is a lag before the new ambassador presents credentials.
- For newly established relations, the date of credential presentation by the first envoy/ambassador is used.
- When State Department records are ambiguous about exact dates, as much information as possible is recorded and the remaining date components are left missing.

### Coding conventions

- **Missions** (e.g., to France and Prussia in the 1700s) are coded as legations.
- **"Office of the U.S. Representative"** (e.g., Marshall Islands) and **"Diplomatic Agent"** (e.g., Morocco) are coded as liaison offices.
- **Nonresident charges d'affaires** and **nonresident ministers** are coded at the level of the mission they represent: Envoy Nonresident if serving at the envoy level, Ambassador Nonresident if serving at the ambassadorial level. When the rank of the initial appointee is ambiguous (e.g., a charge d'affaires), the level of subsequent chiefs of mission is used to determine the appropriate category.
- **Consulates** are only coded if located in the capital. If an embassy/legation exists but the chief of mission is not permanently stationed there, it is still coded as embassy/legation (e.g., Samoa). If there is a representative but no mention of a permanent mission, it is coded as nonresident.
- **Governments in exile** during WWII: "embassy near the government" is treated as an open embassy.

### China and Taiwan

Under the One-China Policy, the State Department does not treat Taiwan as a separate entity from mainland China. Historical U.S. diplomatic relations with Taiwan are recorded within the State Department's China page. In this dataset, they are coded separately under `state_dept_name = "Taiwan"` to avoid confusion when merging with state system membership data (both COW and Gleditsch-Ward list Taiwan as a separate member).

Key coding decisions:

- The establishment of the People's Republic of China (1949-10-01) is coded as the date of the break in relations with China (`None`).
- Taiwan's embassy is coded as beginning on 1949-12-08, its date of system entry in both the COW and Gleditsch-Ward datasets, even though the U.S. embassy in Taipei did not physically open until 1949-12-19. This is because the U.S. embassy in mainland China had been moved repeatedly throughout 1949 to remain near the Nationalist government, and using the system entry date ensures consistency with the treatment of European governments in exile during WWII.
- The break in relations with Taiwan is coded as 1979-01-01 (U.S. recognition of the PRC).

### Country identification

Country names in `state_dept_name` follow the State Department's naming conventions. When merging with external datasets (Correlates of War, Gleditsch & Ward), a mapping is required because names often differ between sources.
