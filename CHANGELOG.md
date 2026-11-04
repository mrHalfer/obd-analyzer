# Changelog


### 9.6
- GUI: interface language switch (Русский/English) in the window; the choice is stored in `gui_config.json` next to the program (added to `.gitignore`) and reused on the next start
- First start auto-detects the language from the system UI locale (Russian → ru, anything else → en); report language follows the interface language
- All GUI texts moved to `lang/*.json` as `gui.*` keys (ru/en/de)

### 9.5
- GUI: running `python analyze_obd.py` with no arguments opens a window (tkinter): input/output folders, format checkboxes, "Rebuild all reports", "Generate new reports" and "Generate comparison" buttons; output goes to the in-window log pane
- Consent-based dependency auto-install in the GUI (packages are installed via pip and re-verified by import); in CLI the exact install command is printed instead and the affected report format is skipped without aborting the analysis
- New modules: `deps.py` (dependency check/install), `gui.py` (the interface)
- `process_file()` accepts `output_dir` — results can be written to a separate folder (CLI behaviour unchanged)
- Fix: PDF report crashed on logs where a summary card had no metrics at all (`_create_card` now substitutes a "no data" row)
- `test_column_mapping.py`: `TIME` removed from required mapping keys — time is always taken from the first CSV column and never goes through the mapping

### 9.4
- Excluded wideband O2 sensors from fuzzy mapping: added `_O2_NARROWBAND_TARGETS` and `_is_wideband_col()` to `analyze_obd.py` — when matching CSV columns to `O2_B1S1`–`O2_B2S4` parameters, columns containing "шир"/"wide" (wideband sensor) or "мА"/"mA" (current rather than voltage columns) are skipped
- Renamed: `O2_SENSOR1` → `O2_B1S1`, `O2_SENSOR2` → `O2_B1S2` across all modules (`analyze_obd.py`, `build_plotly.py`, `build_png.py`, `check_catalyst.py`, `tests/test_render.py`)
- Time column detection: added `looks_like_time()` to `core_obd.py` — the first CSV column is automatically treated as time when it matches the `HH:MM:SS` pattern; TIME removed from `analyze_obd.json`
- GPS column detection: added `find_gps_columns()` to `core_obd.py` — coordinate format validation (`^-?\d{1,3}\.\d{4,}$`) runs both when searching by name and in the last-two-columns fallback; used in `build_geojson.py` and `core_obd.py`
- Fixed `AttributeError: Can only use .str accessor with string values` in `build_plotly.py`: added `.astype(str)` before `.str[:8]` in 4 places
- `analyze_obd.json` column mapping: arrays sorted (Russian names first, longest to shortest, then English); sparse O2 and fuel-trim arrays filled in

### 9.3
- Branding refactoring: `brand_svg()`, `brand_logo_flowable()` and `BRAND_LOGO_W` moved to `core_obd.py`; local duplicates removed from `build/build_html.py`, `build/build_pdf.py`, `compare/compare_html.py`, `compare/compare_pdf.py`
- Compare HTML summary tables: first column is now sticky (`position: sticky; left: 0`) — remains visible during horizontal scroll
- Compare HTML: value cells in the summary table have a `title` tooltip showing the trip date and metric name
- Compare HTML: column show/hide by trip is now available for the speed profile table (badges with `scope="profiles"`, `data-col` on cells, `data-tscope` on the wrapper)
- Compare HTML: added a "Hide all / Show all" button next to the badges in all tables (summary and profiles); toggles all columns in its scope at once; button label reflects the current state
- Translations: added `compare.html.show_all` and `compare.html.hide_all` keys to `lang/ru.json`, `en.json`, `de.json`

### 9.2
- Branding: **EL-MODS OBD** logo added to all HTML and PDF reports — generated inline in Python with no external file dependency
- HTML (individual and comparison): logo placed in the top-right corner via a flex header (`justify-content: space-between`); on mobile (≤768px) it moves to the top (`order: -1`)
- PDF (individual and comparison): logo rendered via `_LogoFlowable` (ReportLab canvas primitives) placed in the right cell of a two-column header table; no new dependencies
- Compare PDF trends: new `_add_tall_png` function — detects each subplot's bounding rectangle by scanning for matplotlib spine border lines (dark horizontal bands); each subplot is cropped precisely at its borders with padding and packed onto pages without mid-subplot cuts; the suptitle is removed from the image

### 9.1
- Compare trends PNG + Plotly: removed per-point value labels (`ax.annotate` / `mode='text'`); LTFT and STFT combined into one subplot (two lines); coolant max and coolant mean combined; O2 rich and lean combined; subplot order aligned with the synchronized timeline: RPM → speed → load → O2 rich/lean → injection → LTFT/STFT → coolant T → intake T; 8 subplots instead of 11
- Compare HTML: fixed chart height snapping to 380 px on Plotly legend clicks — after chart initialisation the rendered height is pinned as inline `style.height`; `min-height: 380px` now serves only as a placeholder before load
- Fixed Pyright "Variable not allowed in type expression" — local type aliases `SubplotDef` / `SubplotGroup` removed from function bodies in `compare_plotly.py` and `compare_png.py`

### 9.0
- Refactoring: `render/` folder renamed to `build/`; all `sys.path` references updated in `analyze_obd.py`, all plugins, tests, and the `build/` modules themselves; `pyrightconfig.json` updated
- Compare: new module `compare/compare_profiles.py` — loads all `*_profile.csv` files from the working directory, collects speed bins from **all** trips (not just the first), builds a unified data structure via `_prepare_profile_data()`
- Compare: new **"Speed profiles"** tab — accordion by speed bin (0–5, 5–10, … km/h); each section contains a table of metric × trips; tab appears only when `*_profile.csv` files are found
- Compare: new **"Profile trends"** tab — accordion by speed bin; each section contains a Plotly chart with subplots (one per metric): X = trips, Y = value, grouped bars per trip; lazy initialisation on accordion open
- Compare: new output file `comparison_profiles.csv` — rows = speed bin + metric, columns = trips; always generated when `*_profile.csv` files exist
- Compare HTML JS: lazy loading for profile charts implemented via figure JSON spec (`<script type="application/json">`): `Plotly.newPlot()` is called in the parent document context on accordion open; `iframe srcdoc` approach removed (Plotly was not defined in the iframe context)
- Compare HTML: added CSP inline warning when opened with `?inline=true` (consistent with `build_html.py`); hidden by JS when the parameter is absent
- Compare: new metrics added to all formats (CSV, XLS, HTML, PDF): RPM avg, speed avg, engine load avg, coolant temp avg, intake temp avg, injection time avg, O2 rich time (%), O2 lean time (%)
- Compare: metrics in summary table and trends sorted into logical groups: trip → driving conditions → temperatures → fuel → air/MAF → O2/lambda → knock/stalls → catalyst
- Compare trends PNG + Plotly: new subplots for all new metrics (up to 11 series); `ref_type` controls reference lines (fuel ±6%/12%, coolant norms)
- Translations: added keys `compare.metrics` (28 entries), `compare.trends` (8 new labels), `compare.html.tab_profiles/tab_profile_trends`, `compare.profiles.*`, `console.compare_profiles_csv_saved` to `lang/ru.json`, `en.json`, `de.json`

### 8.9
- O2 crossings: `o2_crossing_rate` algorithm rewritten from `shift(1)` to a state machine with hysteresis (`check_catalyst.py`) — the previous approach missed nearly all transitions at LOG_DT=1s because it required a direct jump from <0.4V to >0.6V in a single step; intermediate values 0.4–0.6V are now ignored, only transitions between lean (≤0.4V) and rich (≥0.6V) states are counted; closed-loop filter: only rows where COOLANT_TEMP ≥ `O2_CROSSING_MIN_COOLANT_TEMP` (70°C); duration is computed as warm rows × `LOG_DT`, which correctly handles sparse logs
- Compare: 8 new metrics added to all formats (CSV, XLS, HTML, PDF): RPM avg, speed avg, engine load avg, coolant temp avg, intake temp avg, injection time avg, O2 rich time (%), O2 lean time (%)
- Compare: metrics in the summary table sorted into logical groups: trip → driving conditions → temperatures → fuel → air/MAF → O2/lambda → knock/stalls → catalyst
- Trends: new subplots added to `comparison_trends` (PNG + Plotly) for all new metrics; °C plots include norm/max reference lines, fuel trim plots include ±6%/±12% bands; up to 11 subplots, empty ones are skipped automatically
- Translations: all new keys added to `lang/ru.json`, `lang/en.json`, `lang/de.json` (sections `compare.metrics` and `compare.trends`)

### 8.8
- Map: DTC error increase markers — when the `ERROR_COUNT` column (mapped in `analyze_obd.json`) increases at a route point, an orange circle marker is shown with a popup (time, fault count, delta); works correctly with sparse logs (VAG and similar) where the error counter is not present in every row
- Map: `build_map.py` migrated to Jinja2 (`build_map.j2`); JS data passed via `window._OBD_MAP_DATA` object — HTML is now rendered by a template instead of string concatenation
- Map: stall and DTC popup titles moved to translations (`map.dtc_increase.*` in `lang/*.json`); "Time:" label in the stall popup is now localised
- Warmup assessment: warmup is only evaluated when initial temperature < 50°C AND duration > 2 min; otherwise status is NEUTRAL — report card shows the short label "Not assessed", metrics table shows the detailed reason (warm engine or too short)
- Refactoring: `_save_plot()` helper in `build_png.py` (`_PNG_DPI = 150` constant, 11 call sites); `get_time_axis_minutes()` made public in `core_obd.py` (6 uses in `build_png.py`, 2 in `build_plotly.py`); type annotations + docstring for `_collect_window_metrics` in `check_catalyst.py`; extracted `_insufficient_warm_points_metric()` and `_insufficient_windows_metric()`

### 8.7
- Type annotations in `build_geojson.py`: `_aggregate_group` return type narrowed to `dict[str, Any]`; duplicate `Path` import removed
- Code quality tooling: `setup.cfg` with `[isort]`, `[flake8]`, and `[mypy]` sections; `.pre-commit-config.yaml` with black / isort / flake8 / mypy hooks
- CSV injection guard: `_warn_csv_injection()` in `analyze_obd.py` logs a warning when cells starting with formula prefixes (`=`, `+`, `-`, `@`, `|`, `%`) are found in string columns
- Bilingual JSON comments: all `_comment_*` keys in `core_obd.json` and `analyze_obd.json` now have English `_comment_*_en` counterparts; `analyze_obd.json` parameters regrouped thematically
- Docker files moved to `docker/` subfolder: `docker/Dockerfile`, `docker/requirements.txt`, `docker/build.sh`, `docker/build.bat`; build command updated to `docker build -f docker/Dockerfile -t obd-analyzer .`
- Expanded test coverage (436 tests total):
  - `test_render.py` (25 tests): `build_html` — HTML content and file creation; `build_png` — 12 plot functions run without exceptions; `build_csv` — `_knock_timeline.csv` created correctly
  - `test_core_obd_json.py` (~250 tests): 100+ key presence checks, numeric types, hex color format, 15 `min < max` invariants, percentile and range assertions
  - `test_statuses.py` refactored: class-based tests replaced with `@pytest.mark.parametrize` — 25+ parametrized combinations
  - `test_compare_reports.py` (33 tests): `compare_plotly` — trip labels, all `_plot_*` functions; `compare_pdf` — `_stat_bg`, font registration, `_build_one_chunk_table`, `create_compare_pdf`; HTML validity via built-in `html.parser`

### 8.6
- Status color schemes centralised in `core_obd.json`: `STATUS_COLOR_*` and `STATUS_TEXT_*` constants serve as the single source of truth for PNG heatmap, Plotly, PDF, XLS, and HTML CSS
- HTML generators migrated to Jinja2: `build_html.py` and `compare_html.py` now render `build_html.j2` / `compare_html.j2` templates instead of string concatenation
- Test coverage expanded: added `test_compare_core.py` (53 tests for `compare/compare_core.py`: `parse_numeric`, `_extract_trip_id`, `resolve_val_stat`, `get_numeric_series`, `build_compare_rows`, `get_drive_mode_durations`, `get_status_matrix`, `STATUS_MAP`)

### 8.5
- Full localization support in comparison reports: metric names, tab labels, headings, and Excel sheet names are now translated (ru/en/de)
- Docker: added `docker/Dockerfile`, `docker/requirements.txt`, `docker/build.sh`, `docker/build.bat`
- Exception handling refactored: all `except Exception` replaced with specific types (`OSError`, `ValueError`, `KeyError`, `TypeError`, `pd.errors.ParserError`, `UnicodeDecodeError`, `RuntimeError`, etc.) across all 16 Python modules
- Chart reference line constants moved to `core_obd.json`: `CHART_FUEL_OK_LINE` (±6%), `CHART_FUEL_WARN_LINE` (±12%) for LTFT/STFT charts; `O2_DK2_NORM_MIN`/`O2_DK2_NORM_MAX` (0.65–0.85V) for the downstream O2 sensor

### 8.4
- Plotly charts in the HTML comparison report now correctly fill the full container width and do not overflow on mobile devices
- PDF comparison report: when comparing many trips, the table is automatically split across multiple pages (max 7 columns per table)
- Refactoring: all internal functions made private (`_` prefix); removed unused imports; pathlib used consistently

### 8.3
- Map: stall event points on the route — GeoJSON Point features with `event_type: "stall"`; rendered on the map as red circle markers with a popup (time, RPM)
- Comparison: interactive Plotly charts in the HTML comparison report (trends, knock, modes, status heatmap); falls back to PNG when plotly is unavailable
- Comparison: `compare_plots.py` renamed to `compare_png.py`
- Tests: `tests/` folder with 45 unit tests covering column mapping, knock grouping, and status calculations

### 8.2
- Project structure refactored: files renamed across all modules
  - `lang/analyze_obd_lang.py` → `translation.py` (root)
  - `lang/analyze_obd_lang_*.json` → `lang/{code}.json`
  - `analyze_obd_core.*` → `core_obd.*`
  - `plugins/analyze_obd_check_*.py` → `plugins/check_*.py`
  - `render/analyze_obd_*.py/js/css` → `build/build_*.py/js/css`

### 8.1
- CSV comparison report (`comparison_report.csv`): rows = trips, columns = key metrics + modes + statuses; always generated (like _metrics.csv)
- Excel export of comparison data (`comparison_report.xlsx`): sheets Summary, Trends, Knock, Modes, Statuses with status color coding
- Added `-noxls` flag to disable Excel report
- Trip badges in the HTML comparison report are now clickable: click to hide/show the corresponding column in the table

### 8.0
- New multi-trip comparison module (compare/): trends, knock, modes, status heatmap
- Comparison report generated automatically when processing a directory with ≥2 logs
- Added `-nocompare` flag to disable comparison
- Added `-continue` flag — skip already-processed files (existing _metrics.csv), do not regenerate existing PDF/HTML
- Saving PNG graphs in an HTML report as base64 data instead of a file link

### 7.5
- Project structure refactored: lang/, build/, plugins/
- Fixed incorrect LTFT/STFT coefficient interpretation when the source column header explicitly marks values as %

### 7.4
- Improved column mapping
- Approximate catalyst assessment using a single O2 sensor (downstream only)
- Auto-detection of LTFT/STFT format (percentage vs. multiplier coefficient)
- Improved report display when data is insufficient for certain categories
- Fixed card parameter evaluation for warmup-only logs (no driving modes)

### 7.3
- Code improvements – long functions split, partial refactoring
- Processing logs created instead of simple console output
- JS modules extracted into separate files
- German language added (-lang de)

### 7.2
- Multi-language report support (English translation added -lang en)

### 7.1
- Context menu for navigating from interactive charts to the map

### 7.0
- New module that adds an interactive map tab to the HTML report
- Further refactoring for code consistency and end-to-end report logic

### 6.5
- New geojson generation module for displaying log segments with min/max/mean values

### 6.4
- New cooling system assessment module — warm-up, overheating, thermostat and fan analysis

### 6.3
- Fixed PDF report generation error when insufficient data is available for catalyst analysis

### 6.2
- Improved modular project structure — analytical functions extracted into separate modules

### 6.1
- Improved catalyst analysis using oxygen sensors — MAF readings added
- Stricter data filtering for catalyst analysis to avoid false readings
- Due to stricter filtering, catalyst analysis now requires a higher-quality load log

### 6.0
- Improved knock severity assessment mechanism with remission parameters — if knock meets 3 of 4 remission criteria, its severity is downgraded
- Engine shutdown at end of trip no longer counted as a stall event
- Code refactoring, elimination of report inconsistencies
- Improved HTML and PDF report appearance

### 5.5
- Extended catalyst assessment — using O2 sensor 1 (upstream) and O2 sensor 2 (downstream) readings

### 5.4
- Added catalyst assessment based on ECU readings
- Expanded PDF report

### 5.3
- Revised knock count statuses
  - Trip duration and knock group counts are determined per class
  - Weak knocks (KNOCK_WEAK_COUNT): ≤1 group per 5 min — OK; 2–3 groups per 5 min — WARNING; >3 groups per 5 min — ERROR
  - Medium knocks (KNOCK_MEDIUM_COUNT): ≤1 group per 10 min — OK; 2 groups per 10 min — WARNING; >2 groups per 10 min — ERROR
  - Strong knocks (KNOCK_STRONG_COUNT): 0 groups for the whole trip — OK; 1 group — WARNING; >1 group — ERROR
  - KNOCK_TOTAL_COUNT status uses the worst of the above statuses
- All constants moved to a separate JSON file
- HTML report and plot-building modules separated
- `-noplot` and `-nohtml` arguments separated

### 5.2
- Improved `analyze_data()` and `core.get_status()` code
- Improved HTML report mobile responsiveness

### 5.1
- Type hints added to all modules and functions
- Unused imports and constants cleaned up
- Redundant docstrings reduced
- README with project and parameter descriptions

### 5.0
- Modular architecture (core + CSV/PNG/HTML/PDF modules)
- New PDF report with codes, descriptions, values, and statuses

### 4.9
- 3D engine visualization (RPM, LOAD, TEMP) with knock color coding

### 4.8
- Automatic ambient temperature detection via Open-Meteo API using log date

### 4.7
- Improved summary: weak/medium knock with status icons
- Smart icons for stall events and misfires

### 4.6
- Fixed tab switching in HTML report when opened in `?inline=true` mode
- Warning displayed in chart tabs when HTML is opened with `?inline=true`

### 4.5
- Lazy loading for interactive Plotly charts

### 4.4
- Interactive chart optimization
- Tabs separated: charts, tables, dashboard, matrices, timeline, analytics
- Summary tab added, mobile adaptation improved

### 4.3
- Improved Plotly charts, merged into a single HTML file

### 4.2
- Unified HTML report (CSV tables + Plotly/PNG charts)

### 4.1
- Fixed interactive dashboard creation

### 4.0
- Interactive Plotly charts (HTML)

### 3.5
- Percentiles for LTFT/STFT/MAF/INJECTION/THROTTLE with smart handling of 0.0 values

### 3.4
- Added `-nocsv`, `-nopng`, `-fuel`, `-temp` arguments

### 3.3
- Extended visualization: fuel trims, O2 sensors, temperatures, engine load, MAF, misfires, dashboard

### 3.2
- Fuel mixture quality statistics

### 3.1
- O2 sensor statistics, correlation matrix

### 3.0
- Parameter visualization, knock map, JSON column mapping
- ALL_DRIVE section for driving parameters (WARMUP excluded)
- Fixed false stall detection on ignition off

### 2.5
- Automatic engine start detection (RPM > 0)
- Joker events (stalls) exported to a separate CSV
- ALL_STALLED_COUNT as a sum across all modes
- Knock grouping (WEAK/MEDIUM/STRONG_COUNT)

### 2.0
- CODE/DESC/VAL/STAT format, OK/WARNING/ERROR statuses
- Knock, misfire, fuel mixture, and temperature analysis
- CarScaner CSV#2 log processing
