# OBD-II Analyzer

**English** · [Русский](README.ru.md)

On-board diagnostics (OBD-II) data analyzer. Designed for diagnostic files exported from the CarScaner app in CSV #2 format.

Reads CSV logs, calculates metrics by engine operating mode, and generates reports in CSV, PNG, HTML (Plotly), and PDF formats. When processing multiple logs, automatically builds a cross-trip comparison report.

## Graphical Interface

The GUI starts when no CSV path is given: `python analyze_obd.py` (or directly `python gui.py`).

Window elements:

- **CSV log folder** — where raw logs are read from
- **Report folder** — where results are written (empty = next to the source CSVs)
- **Report formats** — checkboxes CSV / PNG / HTML / PDF / GeoJSON / XLS (comparison)
- **Rebuild all reports** — full run over every source CSV
- **Generate new reports** — skips CSVs that already have `*_metrics.csv` in the report folder
- **Generate comparison** — comparison report from the `*_metrics.csv` files in the report folder

In the GUI, missing packages are offered for installation (with the exact pip
command) and installed only after the user consents. In CLI mode (with a path)
there is no auto-install — the install command is printed instead; a report
format whose package is missing is skipped with a message while all other
formats are still generated.

## Generated Files

For each input `{name}.csv`:

**CSV:**
- `{name}_metrics.csv` — summary metrics by operating mode
- `{name}_joker.csv` — engine stall events
- `{name}_profile.csv` — speed profile (parameters in 5 km/h bins)
- `{name}_knock_groups.csv` — knock groups
- `{name}_knock_timeline.csv` — knock chronology
- `{name}_misfire_timeline.csv` — misfire chronology

**PNG (11 charts):**
- RPM/Speed/Temp timeline, knock heatmap, LTFT/STFT histograms
- Correlation matrix, fuel trims, oxygen sensors
- Temperature profiles, engine load, MAF analysis
- Misfires, summary dashboard

**HTML:**
- `{name}_report.html` — unified interactive report with tabs
- `{name}_X.html` — individual pages for each chart

**PDF:** `{name}_report.pdf` — report with metrics and PNG illustrations

**GEOJSON:** `{name}.geojson` — geocoded report: route segments with min/max/mean values + event points: stalls (event_type: stall, red circle) and DTC fault count increases (event_type: dtc_increase, orange circle)

**Comparison report** (generated automatically when processing a directory with two or more logs):
- `comparison_report.csv` — summary table: rows = trips, columns = key metrics + modes + statuses; always generated
- `comparison_profiles.csv` — speed profiles: rows = speed bin + metric, columns = trips; generated when `*_profile.csv` files are present
- `comparison_report.html` — interactive HTML with tabs: summary table, trends, knock, modes, status heatmap, speed profiles, profile trends
- `comparison_report.pdf` — PDF with summary table and charts
- `comparison_report.xlsx` — Excel with summary table and sheets: Trends, Knock, Modes, Statuses
- `comparison_trends.png` — key parameter trends across trips (LTFT/STFT, coolant T, intake T, RPM, load, speed, injection, O2)
- `comparison_knock.png` — knock comparison by severity
- `comparison_modes.png` — driving mode time distribution across trips
- `comparison_heatmap.png` — key metric status heatmap across trips

## Engine Operating Modes

| Mode | Description |
|---|---|
| `PRE_START` | Ignition on, engine not running (RPM = 0) |
| `WARMUP` | Warm-up (from engine start until movement begins) |
| `DRIVE_CITY` | City driving (0–60 km/h) |
| `DRIVE_SUBURBAN` | Suburban driving (61–110 km/h) |
| `DRIVE_HIGHWAY` | Highway driving (110+ km/h) |

## Metric Statuses

- ✅ **OK** — value within normal range
- ⚠️ **WARNING** — requires attention
- ❌ **ERROR** — critical deviation
- ○ **NEUTRAL** — informational parameter

## Running in the Terminal

```bash
# Single file
python analyze_obd.py log_2026-01-27.csv

# With parameters (95 octane gasoline, ambient temperature -5°C)
python analyze_obd.py log_2026-01-27.csv -fuel 95 -temp -5

# All CSV files in a directory
python analyze_obd.py ./logs

# Current directory
python analyze_obd.py .

# Selective report generation (no CSV tables, no PDF report)
python analyze_obd.py log.csv -nocsv -nopdf
python analyze_obd.py log.csv -nopng -nohtml
```

## Command-Line Parameters

| Parameter | Description | Default |
|---|---|---|
| `path` | Path to a CSV file or directory containing logs | GUI if omitted |
| `-fuel` | Fuel type (92, 95, 98 octane) | 95 |
| `-temp` | Ambient temperature (°C) | auto-detect |
| `-lang` | Report language | ru |
| `-nocsv` | Do not generate additional CSV files | False |
| `-nopng` | Do not generate PNG charts | False |
| `-noplot` | Do not generate PLOT charts | False |
| `-nohtml` | Do not generate HTML report | False |
| `-nopdf` | Do not generate PDF report | False |
| `-nogeojson` | Do not generate geocoded report | False |
| `-nomap` | Do not add interactive map tab to HTML report | False |
| `-nocompare` | Do not generate comparison report (directory mode only) | False |
| `-noxls` | Do not generate Excel comparison report | False |
| `-continue` | Skip files that already have `_metrics.csv`; do not regenerate existing PDF/HTML | False |

## Flag Behavior Matrix

| Command | CSV | PNG | HTML | PDF |
|---|---|---|---|---|
| ./ | metrics + extra | embedded in HTML+PDF, deleted | unified with plots | with charts |
| ./ -nopng | metrics + extra | none | unified with plots | without charts |
| ./ -noplot | metrics + extra | embedded in HTML+PDF, deleted | unified with PNG | with charts |
| ./ -nohtml | metrics + extra | embedded in PDF, saved | separate HTML x3 | with charts |
| ./ -nopdf | metrics + extra | embedded in HTML, saved | unified with plots | none |
| ./ -nopng -noplot | metrics + extra | none | unified (tables only) | without charts |
| ./ -nopng -nohtml | metrics + extra | none | separate HTML x3 | without charts |
| ./ -nopng -noplot -nohtml | metrics + extra | none | none | without charts |
| ./ -nocsv | metrics only | embedded in HTML+PDF, deleted | unified with plots | with charts |

## Running with Docker

```bash
# Build the image (from the project root)
docker build -f docker/Dockerfile -t obd-analyzer .
# or use the script:  docker\build.bat  (Windows) /  bash docker/build.sh  (Linux/macOS)

# Analyse a single file (data is mounted via a volume)
docker run --rm -v "/path/to/logs:/data" obd-analyzer /data/log.csv -lang en

# Analyse a directory
docker run --rm -v "/path/to/logs:/data" obd-analyzer /data -lang en

# With flags
docker run --rm -v "/path/to/logs:/data" obd-analyzer /data -nopdf -noxls -lang en
```

Results are written alongside the source CSV files inside the mounted volume.

## Project Structure

```
analyze_obd/
├── analyze_obd.py           Orchestrator: CSV loading, metrics, report generation
├── analyze_obd.json         Column mapping for the source CSV
├── core_obd.py              Core: constants, utilities, status functions
├── core_obd.json            Core: threshold values for constants
├── gui.py                   Graphical user interface (tkinter, launched with no arguments)
├── deps.py                  Dependency checker and consent-based installer (for the GUI)
├── translation.py           Localisation module (t(), set_language())
│
├── lang/                    Translation files
│   ├── ru.json                  Russian translations
│   ├── en.json                  English translations
│   └── de.json                  German translations
│
├── build/                Report and visualisation generators
│   ├── build_csv.py             CSV reports: joker events, speed profile, knock groups
│   ├── build_png.py             PNG charts: timeline, heatmap, histograms, correlations, dashboard
│   ├── build_html.py            HTML report: interactive Plotly charts, tables, tabs
│   ├── build_html.j2            HTML report: Jinja2 page template
│   ├── build_html.js            HTML report: JS logic for embedding
│   ├── build_html.css           HTML report: styles
│   ├── build_plotly.py          Plotly charts: timeline, heatmap, histograms, 3D
│   ├── build_plotly.js          Plotly charts: JS wrapper for embedding
│   ├── build_pdf.py             PDF report: metrics, cards, tables, PNG illustrations
│   ├── build_map.py             Interactive map: route and parameters in HTML
│   ├── build_map.j2             Map: Jinja2 panel template
│   ├── build_map.js             Map: JS logic for embedding
│   └── build_geojson.py         GeoJSON: route segments with min/max/mean values
│
├── plugins/                 Analytical plugins
│   ├── check_catalyst.py        Catalyst and fuel quality analysis
│   ├── check_coolant.py         Warm-up, thermostat and fan analysis
│   └── check_knock.py           Knock and misfire analysis
│
├── compare/                 Multi-trip comparison
│   ├── compare_core.py          Load *_metrics.csv files, build summary DataFrames
│   ├── compare_png.py           PNG charts: trends, knock, modes, status heatmap
│   ├── compare_plotly.py        Interactive Plotly charts for the HTML comparison report
│   ├── compare_html.py          HTML comparison report with tabs
│   ├── compare_html.j2          HTML comparison report: Jinja2 page template
│   ├── compare_html.css         Styles for the comparison HTML report
│   ├── compare_html.js          JS logic for the comparison HTML report
│   ├── compare_profiles.py      Speed profiles: load *_profile.csv, HTML tabs, CSV export
│   ├── compare_pdf.py           PDF comparison report
│   ├── compare_xls.py           Excel comparison report (.xlsx)
│   └── compare_csv.py           CSV comparison report (always generated)
│
├── tests/                   Unit tests
│   ├── test_column_mapping.py   Column mapping and find_column tests
│   ├── test_knock_grouping.py   Knock grouping and classification tests
│   ├── test_statuses.py         Parameter status tests (parametrized)
│   ├── test_compare_core.py     Multi-trip comparison module tests (compare_core)
│   ├── test_core_obd_json.py    core_obd.json validation: keys, types, min < max invariants
│   ├── test_render.py           Report generation tests: build_html, build_png, build_csv
│   ├── test_compare_reports.py  Comparison report tests: compare_plotly, compare_pdf, HTML validity
│   └── README.md                Test execution instructions
│
├── docker/                  Docker build files
│   ├── Dockerfile               Image: Python 3.12-slim, unprivileged obd user
│   ├── requirements.txt         Python dependencies for the Docker image
│   ├── build.sh                 Build script (Linux/macOS)
│   └── build.bat                Build script (Windows)
│
├── setup.cfg                isort / flake8 / mypy configuration
└── .pre-commit-config.yaml  Pre-commit hooks: black, isort, flake8, mypy
```

## Dependencies

### Runtime (`docker/requirements.txt`)

| Package | Version | Purpose |
|---|---|---|
| `pandas` | >=2.0 | CSV loading and DataFrame processing |
| `numpy` | >=1.24 | Numerical computations |
| `matplotlib` | >=3.7 | PNG charts |
| `Pillow` | >=10.0 | Image handling (used by matplotlib) |
| `requests` | >=2.28 | Automatic ambient temperature via Open-Meteo API |
| `jinja2` | >=3.1 | HTML templates (`build_html.j2`, `compare_html.j2`) |
| `plotly` | >=5.18 | **Optional** — interactive Plotly charts in HTML reports |
| `reportlab` | >=4.0 | **Optional** — PDF report |
| `openpyxl` | >=3.1 | **Optional** — Excel comparison report (.xlsx) |

```bash
pip install pandas numpy matplotlib Pillow requests jinja2
# Optional (full report set):
pip install plotly reportlab openpyxl
```

### Dev dependencies (development only)

| Package | Purpose |
|---|---|
| `pytest` | Run unit tests |
| `pytest-cov` | Coverage report (optional) |
| `pre-commit` | Run black / isort / flake8 / mypy hooks before commits |

```bash
pip install pytest pre-commit
pre-commit install   # install git hooks from .pre-commit-config.yaml
```

## Changelog

Full change history: [CHANGELOG.md](CHANGELOG.md) (English) and [CHANGELOG.ru.md](CHANGELOG.ru.md) (Russian).

## License

MIT — see [LICENSE](LICENSE).
