# Инструкции для ИИ-помощника (AGENTS.md проекта OBD-II Analyzer)

Проект: **анализатор логов OBD-II для Lada Granta FL 2022** (ВАЗ-11182 1.6л).
Python 3.10+ (в Docker — 3.12). Windows-ориентированный, кроссплатформенный.
Общаться с владельцем **по-русски**. Папка проекта: `C:\Scripts\obd\Python`.

## 1. Golden rules

1. **Не делать `git commit`/`push`/`tag` без просьбы.** Репозиторий: `https://github.com/mrHalfer/obd-analyzer`, ветка `main`, локальный git лежит в папке проекта. Владелец коммитит и сам через GitHub Desktop — перед своими git-действиями всегда `git pull`/`git status`, не работать поверх чужих незапушенных коммитов вслепую.
2. **Никаких личных данных, логов поездок, реальных CSV** в репозиторий. `__pycache__`/`.pytest_cache` — в `.gitignore`; **папка `build/` — ИСХОДНИКИ** (генераторы отчётов), её в `.gitignore` не вносить.
3. **Не менять лицензию**: MIT, копирайт `Denis Rakhmatullin (mrHalfer)` (файл `LICENSE`).
4. Тесты — арбитр: после любой правки ядра/генераторов гонять `py -3 -m pytest tests -q` (сейчас 436 тестов, все зелёные). Тесты под сломанный код не подгонять.
5. Не переформатировать чужой код, не менять отступы соседних строк; стиль — как у соседей (line-length 100, black/isort/flake8/mypy через `setup.cfg` и pre-commit).

## 2. Карта проекта

| Файл/папка | Что там |
|---|---|
| `analyze_obd.py` | Оркестратор: загрузка CSV, маппинг колонок, метрики, диспетчер отчётов, `_run_compare`, CLI `main()`. Версия — в докстринге (`Версия: X.Y (YYYY-MM-DD)`) |
| `analyze_obd.json` | Маппинг «целевая колонка → кандидаты имён» из CSV. **`TIME` здесь нет и быть не должно** — время всегда 1-я колонка CSV (см. §4) |
| `gui.py` | tkinter-GUI (см. §5; переключатель языка RU/EN, локальный `gui_config.json` не коммитить); `deps.py` — проверка pip-зависимостей и установка по согласию |
| `core_obd.py` + `core_obd.json` | Ядро: константы, пороги, статусы, утилиты (`looks_like_time`, `find_gps_columns`, `parse_time_to_seconds...`) |
| `translation.py` + `lang/{ru,en,de}.json` | Локализация `t('a.b.c', **params)`; поиск: текущий язык → ru-fallback → ключ |
| `build/` | Генераторы отчётов одного лога: `build_csv/png/html/pdf/plotly/map/geojson` (+ `.j2/.js/.css`) |
| `plugins/` | `check_knock`, `check_catalyst`, `check_coolant` — аналитические плагины |
| `compare/` | Сравнение поездок по `*_metrics.csv` в папке: `compare_core/png/html/pdf/xls/profiles/csv` |
| `tests/` | pytest, синтетические DataFrame (реальных CSV нет); `py -3 -m pytest tests -q` |
| `docker/` | Dockerfile (python 3.12-slim) + `requirements.txt` — runtime-зависимости |
| `README.md` / `README.ru.md` | en-оригинал (основной) / ru-версия |
| `CHANGELOG.md` (en) / `CHANGELOG.ru.md` (ru) | История версий, см. §3 |

Поток данных: `CSV → fuzzy-маппинг колонок → метрики по режимам (WARMUP/...) → отчёты (CSV/PNG/HTML/PDF/GeoJSON) → при ≥2 логов сравнение (*_metrics.csv → compare_*)`.

## 3. Обязательная синхронность языков (главное правило документации)

Любое пользовательское изменение требует **парных** правок:

- **Changelog**: новая версия — секция `### X.Y` в BOTH `CHANGELOG.md` (en) и `CHANGELOG.ru.md` (ru) (секции должны совпасть по составу — сейчас 9.5…2.0).
- **README**: `README.md` (en, основной) и `README.ru.md` (ru) — зеркальные правки, та же структура.
- **Сообщение в консоль/отчёт** — только через `t('console.…')`/соотв. секцию и добавить ключ в **все три** `lang/*.json` (ru/en/de). Русские литералы вне `t()` допустимы лишь в местах, где перевод недостижим (guard-блок запуска до импорта `translation`). Строки GUI-виджетов — через `t('gui.…')` (ключи во всех трёх файлах).
- **Версия**: правится в докстринге `analyze_obd.py` и в обеих changelog-секциях `### X.Y`.

## 4. Особенности анализа (неочевидное)

- **Время — всегда первая колонка CSV**, если она похожа на `HH:MM:SS` (`looks_like_time`, `analyze_obd.py`). Ключ `TIME` в маппинг `analyze_obd.json` НЕ добавлять (тест `test_column_mapping` это фиксирует).
- Отчёты пишутся рядом с исходным CSV; `process_file(..., output_dir=...)` — в отдельную папку (использует GUI). Лог `{stem}.log` — тоже в `output_dir`.
- GeoJSON: `generate_geojson(input_csv, output_geojson=...)` — путь вывода явно, иначе рядом с входом.
- Сравнение (`_run_compare`) читает `*_metrics.csv`/`*_profile.csv` **из переданной папки**; запускается автоматически при ≥2 успешно обработанных логов (GUI повторяет это правило).
- find_csv_files считает исходниками только CSV БЕЗ суффиксов `_metrics/_profile/_knock/_misfire/_joker/_report`.

## 5. Зависимости и GUI (схема из animatron.py)

- **Жёсткие**: numpy, pandas (`deps.CORE_PACKAGES`). **Форматные**: PNG→matplotlib, HTML→plotly+jinja2, PDF→reportlab, XLS→openpyxl (`deps.FORMAT_PACKAGES`).
- Политика: **CLI — никогда не устанавливать**, только печатать `deps.pip_install_hint()` (точное: `sys.executable -m pip install …`) и пропускать формат без падения всего анализа. **GUI — установка только после согласия** в диалоге.
- Режим выбирается в guard-блоке `analyze_obd.py` (самый верх, до тяжёлых импортов): нет позиционного аргумента и нет `-h/--help` → GUI. Guard НЕ должен срабатывать при импорте модуля `analyze_obd` из GUI (проверка `__name__ == '__main__'` — не убирать, иначе рекурсивный запуск GUI).
- Новая опциональная зависимость: добавить в `deps.FORMAT_PACKAGES`, импорт только через `deps.require(...)` (бросает `MissingDependencyError`, наследник `ModuleNotFoundError`), вызовы формат-генераторов обёрнуты в `except (ModuleNotFoundError, MissingDependencyError)` → `_log_format_skipped`.
- **matplotlib** больше нигде не импортировать на уровне модуля (см. `build_png.py`/`compare_png.py` — эталон).
- GUI-правила: диалоги и виджеты — ТОЛЬКО из потока окна (через `queue` + `threading.Event`, см. `ObdApp._ask`); работа в фоновом потоке; **после pip-установки перепроверять импорт** и `importlib.reload(analyze_obd)`, чтобы защищённые импорты (`_build_png`) подхватили новинки.
- Язык GUI: сохраняется в `gui_config.json` рядом с `gui.py` (уже в `.gitignore` — НЕ коммитить); нет конфига → `detect_system_language()` (русский UI → `ru`, иначе `en`). Переключение в окне: `ObdApp._on_language` → `save_language` + `set_language` + `_retranslate()` (перетекстичиваются виджеты, зарегистрированные `_reg`); язык отчётов = язык интерфейса (`ao.set_language(get_language())`). В `GUI_LANGS` только ru/en, новые ключи — в `gui.*` всех трёх `lang/*.json`.

## 6. Известные ловушки (уже наступали)

- reportlab падает `ValueError` на пустом списке строк `Table` — в `build_pdf._create_card` есть guard «нет данных», не убирать.
- `t()` использует `format_map` с `{именными}` плейсхолдерами; JSON-файлы языков — один ключ на строку, проверять `json.load` после правки.
- В PowerShell кириллица в `Select-String`/консоли — кракозябры (кодовая страница), файлы при этом целы: проверять содержимое python-скриптом, не глазами консоли.
- README/CHANGELOG/lang — **LF, UTF-8 без BOM**; при скриптовых правках сохранять концы строк источника.
- GUI-смоук: запуск `py gui.py` или `py analyze_obd.py` без аргументов открывает окно; проверка «прожил пару секунд» через `Start-Process -PassThru` + `Stop-Process` (это СВОЙ процесс).

## 7. Проверка перед коммитом/релизом

1. `py -3 -m pytest tests -q` — все зелёные (причину FAIL чинить, не глушить).
2. `py -3 -m py_compile` изменённых модулей; JSON (`analyze_obd.json`, `core_obd.json`, `lang/*.json`) — `json.load`.
3. Функциональная проба на синтетическом CSV (генератор-одноразовку — в `C:\Temp\opencode`, не в репозиторий): CLI-прогон и, если трогали GUI-путь, `process_file(..., output_dir=...)`.
4. Секции §3 выполнены (changelog×2, README×2, lang×3, версия).
5. Не коммитить сгенерированные отчёты (`*_metrics.csv`, `*_report.*`, `comparison_report.*`, `*.geojson`, `*.log`) — заодно сверять с `.dockerignore`.

## 8. Прочее

- Docker-образ: `docker build -f docker/Dockerfile -t obd-analyzer .`; зависимости — только из `docker/requirements.txt`.
- Тесты не имеют доступа к сети — новых сетевых вызовов в них быть не может.
- `pre-commit` (`trailing-whitespace`, `end-of-file-fixer`, black/isort/flake8/mypy) настроен `.pre-commit-config.yaml`; black/isort исключают `plugins/` и `compare/` — не «чинить» это без спроса.
