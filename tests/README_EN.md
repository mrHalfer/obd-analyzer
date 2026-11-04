# Unit Tests — OBD-II Analyser v9.4

## Test Files

| File | What it tests | Tests |
|---|---|---|
| `test_column_mapping.py` | Column mapping loader (`load_column_mapping`) and column search in a DataFrame (`find_column`) | 13 |
| `test_knock_grouping.py` | Knock event grouping and severity classification (`classify_knock_groups_with_remission`) | 11 |
| `test_statuses.py` | Parameter status calculations (`get_status`): LTFT, STFT, coolant temperature, knock counts. Parametrized via `@pytest.mark.parametrize` | 9 |
| `test_compare_core.py` | Trip comparison module (`compare/compare_core.py`): `parse_numeric`, `_extract_trip_id`, `resolve_val_stat`, `get_numeric_series`, `build_compare_rows`, `get_drive_mode_durations`, `get_status_matrix`, `STATUS_MAP` | 53 |
| `test_core_obd_json.py` | Validation of `core_obd.json`: required keys, numeric types, hex colors, min < max invariants | 12 |
| `test_render.py` | Report generation modules: `build_html` (HTML output, file creation), `build_png` (functions run without exceptions), `build_csv` (knock timeline CSV creation) | 25 |
| `test_compare_reports.py` | Comparison report modules: `compare_plotly` (`_trip_labels`, `generate_all_plotly_html`, all `_plot_*`), `compare_pdf` (`_stat_bg`, `_register_fonts`, `_build_one_chunk_table`, `create_compare_pdf`), HTML validity (`report.html` and `comparison_report.html`) | 22 |
| **Total** | | **145** |

> Parametrized tests expand to more actual test cases at runtime.

## Running Tests

### All tests
```bash
cd c:\Scripts\obd
python -m pytest tests/ -v
```

### Single file
```bash
python -m pytest tests/test_statuses.py -v
```

### With coverage report (requires pytest-cov)
```bash
python -m pytest tests/ -v --cov=. --cov-report=term-missing
```

## Dependencies

Tests require **pytest** (not in the standard library):
```bash
python -m pip install pytest
```

Optional, for coverage reports:
```bash
python -m pip install pytest-cov
```

## Notes

- Tests read `core_obd.json` for real threshold values — changing the config may affect expected results.
- `test_knock_grouping.py` requires `plugins/check_knock.py` and its dependencies.
- `test_compare_core.py` requires `compare/compare_core.py` and `core_obd.json`.
- `test_core_obd_json.py` validates `core_obd.json` directly — if thresholds change, some min < max invariants may need revisiting.
- `test_render.py` uses the built-in `tmp_path` fixture and creates temporary files; no real OBD log files are required.
- `test_compare_reports.py` creates temporary `*_metrics.csv` files via fixtures; PDF and Plotly tests are automatically skipped (`pytest.skip`) if `reportlab` / `plotly` are not installed. HTML validity is checked with the built-in `html.parser`.

## Test Coverage

### test_column_mapping.py (13 tests)

`TestLoadColumnMapping`:
- `test_returns_dict` — `load_column_mapping()` returns a `dict`
- `test_not_empty` — mapping contains at least one entry
- `test_values_are_lists` — all values are lists of candidate column names
- `test_required_keys_present` — RPM, SPEED keys are present
- `test_rpm_candidates_not_empty` — RPM candidate list is non-empty

`TestFindColumn`:
- `test_exact_match` — exact column name match
- `test_exact_match_priority_over_partial` — exact match takes priority over partial
- `test_partial_match_case_insensitive` — case-insensitive partial match
- `test_multiple_candidates_first_wins` — first matching candidate is returned
- `test_returns_none_when_not_found` — returns `None` when no match found
- `test_empty_dataframe` — returns `None` for empty DataFrame
- `test_partial_match_returns_first_found` — returns first partial match in iteration order
- `test_lat_lon_typical` — typical GPS column names (Latitude, Longitude)

### test_knock_grouping.py (11 tests)

`TestKnockGrouping`:
- `test_empty_dataframe` — empty input returns empty list
- `test_no_knock_events` — zero-retard rows produce no groups
- `test_single_weak_event` — single event at KNOCK_WEAK_MAX boundary → `weak`
- `test_single_medium_event` — event at KNOCK_MEDIUM_MAX boundary → `medium`
- `test_single_strong_event` — event at KNOCK_STRONG_MIN boundary → `strong`
- `test_groups_split_by_gap` — events separated by large gap produce two groups
- `test_groups_merged_within_gap` — events within gap merge into one group
- `test_result_has_required_fields` — result dict contains all required keys
- `test_remission_reduces_strong_to_medium` — remission downgrades severity at low RPM/speed
- `test_max_retard_correct` — `max_retard` field equals the maximum retard value
- `test_severity_boundary_weak_medium` — boundary between weak and medium severity

### test_statuses.py (9 test functions)

- `test_ltft_status` — LTFT value → expected status (parametrized)
- `test_ltft_pre_start_and_nan_neutral` — PRE_START / NaN → NEUTRAL (parametrized)
- `test_stft_status` — STFT value → expected status (parametrized)
- `test_coolant_temp_status` — coolant temperature → expected status set (parametrized)
- `test_pre_start_always_neutral` — PRE_START regime always returns NEUTRAL (parametrized)
- `test_nan_always_neutral` — NaN always returns NEUTRAL (parametrized)
- `test_unknown_param_neutral` — unknown parameter code → NEUTRAL
- `test_knock_count_status` — knock count → expected status set (parametrized)
- `test_status_values_are_valid` — all returned values are one of the four valid statuses (parametrized)

### test_compare_core.py (53 tests)

`TestParseNumeric` (14): plain float, percent suffix, degree-C suffix, negative, integer string, zero, "n/a" string, empty string, text only, int input, float input, NaN input, embedded number, positive sign.

`TestExtractTripId` (6): date only, date+time with dash, date+time with T separator, no date returns stem, different prefix, date at start.

`TestResolveValStat` (6): direct code found, fallback chain primary missing, fallback chain second candidate, code missing returns empty, multiple trips independent, fallback per trip.

`TestGetNumericSeries` (4): returns float series, NaN for missing, NaN for text value, multiple trips.

`TestBuildCompareRows` (6): empty df returns empty list, row has required keys, all-empty metric skipped, trip_vals contains all trips, label is string, long value truncated.

`TestGetDriveModeDurations` (4): returns DataFrame with mode columns, numeric values extracted, missing columns are NaN, index matches trip IDs.

`TestGetStatusMatrix` (7): empty df returns empty, numeric mapping, OK maps to 1, WARNING maps to 2, ERROR maps to 3, all-empty stats returns empty, matrix shape.

`TestStatusMap` (6): OK is 1, WARNING is 2, ERROR is 3, NEUTRAL is 0, empty is -1, all values in range.

### test_core_obd_json.py (12 tests)

- `test_numeric_key_present` — each expected numeric key exists in the config (parametrized)
- `test_color_key_present` — each expected color key exists (parametrized)
- `test_numeric_key_is_number` — numeric keys hold `int` or `float` values (parametrized)
- `test_color_key_is_hex_string` — color keys hold valid hex color strings (parametrized)
- `test_min_less_than_max` — all min/max pairs satisfy min < max (parametrized)
- `test_ltft_percentiles_in_0_1_range` — LTFT percentile thresholds are in [0, 1]
- `test_stft_percentiles_in_0_1_range` — STFT percentile thresholds are in [0, 1]
- `test_o2_thresholds_in_sensor_range` — O2 thresholds are within valid sensor voltage range
- `test_cat_aging_index_in_0_1` — catalyst aging index is in [0, 1]
- `test_log_dt_positive` — LOG_DT is a positive number
- `test_rpm_thresholds_ordering` — RPM thresholds are in ascending order
- `test_geojson_distance_positive` — GeoJSON distance threshold is positive

### test_render.py (25 tests)

`TestBuildSummaryCard` (4): contains title, contains rows, returns div element, empty rows handled.

`TestBuildSummaryPanel` (3): missing metrics file returns HTML, valid metrics returns non-empty HTML, corrupted file returns HTML.

`TestCreateReportHtml` (3): creates HTML file, HTML file is not empty, `no_html` flag skips file creation.

`TestBuildPng` (12): `plot_time_series`, `plot_time_series` with missing columns, `plot_knock_heatmap`, `plot_ltft_stft_hist`, `plot_fuel_correction_timeline`, `plot_o2_sensors_timeline`, `plot_temperature_profiles`, `plot_engine_load_profile`, `plot_maf_analysis`, `plot_misfire_analysis`, `create_summary_dashboard`, `plot_correlation_matrix` — all run without exceptions.

`TestBuildCsv` (3): `save_knock_timeline` without KNOCK_RETARD column (silent return), with knock events (file created), knock CSV contains expected columns.

### test_compare_reports.py (22 tests)

`TestTripLabels` (4): short IDs unchanged, long IDs truncated to date, empty list, mixed IDs.

`TestGenerateAllPlotlyHtml` (4): empty df returns empty dict, returns dict, keys are known chart names, values are non-empty HTML strings.

Standalone (2): `test_plot_functions_return_str_or_none` — each `_plot_*` function returns `str` or `None` (parametrized); `test_plot_functions_empty_df_return_none` — empty DataFrame input returns `None` (parametrized).

`TestStatBg` (2): returns a color for any status input, OK and ERROR colors differ.

Standalone PDF (4): `test_register_fonts_returns_two_strings`, `test_build_one_chunk_table_returns_table`, `test_create_compare_pdf_creates_file_or_none`, `test_create_compare_pdf_empty_df_returns_none`.

`TestHtmlValidity` (6): `report.html` is parseable, contains basic HTML structure (`<html>`, `<head>`, `<body>`), no unclosed `<script>`, no unclosed `<style>`; `comparison_report.html` is parseable, contains basic HTML structure.
