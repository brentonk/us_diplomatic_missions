# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/), and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- `us_mission_start` and `us_mission_end` columns in the monthly and yearly datasets, giving the status on the first and last observed day of each period.
- Polars example for daily expansion in the codebook, alongside the existing pandas example.

### Changed

- Clarified data explorer subtitle and welcome text to specify that it shows the highest status of US permanent diplomatic representation.
- Replaced pandas and numpy with polars in the pipeline (Stage 0/1 CSV reading, daily expansion, monthly/yearly aggregation). Output data is unchanged.
- Bumped version to 0.2 (new monthly/yearly columns change the output data).

## [0.1] - 2026-03-10

Initial public release.
