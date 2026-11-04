# OBD-II Analyzer

[English](README.md) · **Русский**

Анализатор данных бортовой диагностики (OBD-II). Предназначен для работы с файлами диагностики, экспортированными из программы CarScaner в формате CSV #2.

Читает CSV-логи, вычисляет метрики по режимам работы двигателя и генерирует отчёты в форматах CSV, PNG, HTML (Plotly) и PDF. При обработке нескольких логов автоматически строит сравнительный отчёт.

## Графический интерфейс

GUI запускается без указания пути до CSV: `python analyze_obd.py` (или напрямую `python gui.py`).

Элементы окна:

- **Папка с CSV-логами** — откуда читать сырые логи
- **Папка отчётов** — куда складывать результаты (пусто = рядом с исходными CSV)
- **Форматы отчётов** — чекбоксы CSV / PNG / HTML / PDF / GeoJSON / XLS (в сводной)
- **Переформировать все отчёты** — полный прогон по всем исходным CSV
- **Сформировать новые отчёты** — пропускать CSV, для которых в папке отчётов уже есть `*_metrics.csv`
- **Сформировать сводную** — сравнительный отчёт по `*_metrics.csv` в папке отчётов

В GUI недостающие пакеты предлагаются к установке (с точной pip-командой) и
ставятся только после согласия пользователя. В CLI (запуск с путём) автоустановки
нет — печатается команда установки; формат отчёта с отсутствующим пакетом
пропускается с сообщением, остальные форматы формируются как обычно.

## Генерируемые файлы

Для каждого входного `{name}.csv`:

**CSV:**
- `{name}_metrics.csv` — сводные метрики по режимам
- `{name}_joker.csv` — события заглохов двигателя
- `{name}_profile.csv` — профиль скорости (параметры по бинам 5 км/ч)
- `{name}_knock_groups.csv` — группы детонации
- `{name}_knock_timeline.csv` — хронология детонации
- `{name}_misfire_timeline.csv` — хронология пропусков зажигания

**PNG (11 графиков):**
- Таймлайн RPM/Speed/Temp, heatmap детонации, гистограммы LTFT/STFT
- Матрица корреляций, коррекции топлива, кислородные датчики
- Температурные профили, нагрузка двигателя, анализ MAF
- Пропуски зажигания, сводный дашборд

**HTML:** 
- `{name}_report.html` — единый интерактивный отчёт с табами
- `{name}_X.html` — отдельные страницы с каждым графиком

**PDF:** `{name}_report.pdf` — отчёт с метриками и PNG-иллюстрациями

**GEOJSON:** `{name}.geojson` — геокодированный отчёт: отрезки маршрута с min/max/mean значениями + точки событий: заглохов (event_type: stall, красный кружок) и увеличения счётчика ошибок DTC (event_type: dtc_increase, оранжевый кружок)

**Сравнительный отчёт** (при обработке директории с двумя и более логами):
- `comparison_report.csv` — сводная таблица: строки = поездки, столбцы = ключевые метрики + режимы + статусы; формируется всегда
- `comparison_profiles.csv` — профили скорости: строки = скоростной бин + метрика, столбцы = поездки; формируется если есть `*_profile.csv`
- `comparison_report.html` — интерактивный HTML с вкладками: сводная таблица, тренды, детонация, режимы, heatmap статусов, профили скорости, тренды профилей
- `comparison_report.pdf` — PDF со сводной таблицей и графиками
- `comparison_report.xlsx` — Excel со сводной таблицей и листами: Тренды, Детонация, Режимы, Статусы
- `comparison_trends.png` — тренды ключевых параметров по поездкам (LTFT/STFT, T ОЖ, T впуска, RPM, нагрузка, скорость, впрыск, O2)
- `comparison_knock.png` — сравнение детонации по силе
- `comparison_modes.png` — распределение времени по режимам езды
- `comparison_heatmap.png` — heatmap статусов ключевых метрик

## Режимы работы двигателя

| Режим | Описание |
|---|---|
| `PRE_START` | Зажигание включено, двигатель не запущен (RPM = 0) |
| `WARMUP` | Прогрев (от запуска до начала движения) |
| `DRIVE_CITY` | Городской режим (0–60 км/ч) |
| `DRIVE_SUBURBAN` | Загородный режим (61–110 км/ч) |
| `DRIVE_HIGHWAY` | Трасса (110+ км/ч) |

## Статусы метрик

- ✅ **OK** — значение в норме
- ⚠️ **WARNING** — требует внимания
- ❌ **ERROR** — критическое отклонение
- ○ **NEUTRAL** — информационный параметр

## Запуск в терминале

```bash
# Один файл
python analyze_obd.py log_2026-01-27.csv

# С параметрами (бензин АИ-95, температура на улице -5)
python analyze_obd.py log_2026-01-27.csv -fuel АИ-95 -temp -5

# Все CSV в директории
python analyze_obd.py ./logs

# Текущая директория
python analyze_obd.py .

# Выборочная генерация отчётов (без csv таблицы и без pdf отчета)
python analyze_obd.py log.csv -nocsv -nopdf
python analyze_obd.py log.csv -nopng -nohtml
```

## Параметры командной строки

| Параметр | Описание | По умолчанию |
|---|---|---|
| `path` | Путь к CSV файлу или директории с логами | если не указан — GUI |
| `-fuel` | Тип топлива (АИ-92, АИ-95, АИ-98) | АИ-95 |
| `-temp` | Температура окружающей среды (°C) | автоопределение |
| `-lang` | Указать язык для отчетов | ru |
| `-nocsv` | Не создавать дополнительные CSV файлы | False |
| `-nopng` | Не создавать PNG графики | False |
| `-noplot` | Не создавать PLOT графики | False |
| `-nohtml` | Не создавать HTML отчёт | False |
| `-nopdf` | Не создавать PDF отчёт | False |
| `-nogeojson` | Не создавать геокодированный отчёт | False |
| `-nomap` | Не создавать вкладку с интерактивной картой в html отчёте | False |
| `-nocompare` | Не создавать сравнительный отчёт по поездкам (только при обработке директории) | False |
| `-noxls` | Не создавать Excel-отчёт сравнения поездок | False |
| `-continue` | Пропускать файлы с уже существующим `_metrics.csv`; не пересоздавать готовые PDF/HTML | False |

## Матрица поведения флагов

| Команда | CSV | PNG | HTML | PDF |
|---|---|---|---|---|
| ./ | metrics + доп. | встроены в HTML+PDF, удалены | единый с плотами | с графиками |
| ./ -nopng | metrics + доп. | нет | единый с плотами | без графиков |
| ./ -noplot | metrics + доп. | встроены в HTML+PDF, удалены | единый с PNG | с графиками |
| ./ -nohtml | metrics + доп. | встроены в PDF, сохранены | отдельные HTML x3 | с графиками |
| ./ -nopdf | metrics + доп. | встроены в HTML, сохранены | единый с плотами | нет |
| ./ -nopng -noplot | metrics + доп. | нет | единый (только таблицы) | без графиков |
| ./ -nopng -nohtml | metrics + доп. | нет | отдельные HTML x3 | без графиков |
| ./ -nopng -noplot -nohtml | metrics + доп. | нет | нет | без графиков |
| ./ -nocsv | только metrics | встроены в HTML+PDF, удалены | единый с плотами | с графиками |

## Запуск в Docker

```bash
# Сборка образа (из корня проекта)
docker build -f docker/Dockerfile -t obd-analyzer .
# или запустить скрипт:  docker\build.bat  (Windows) /  bash docker/build.sh  (Linux/macOS)

# Анализ одного файла (данные монтируются через volume)
docker run --rm -v "C:\logs:/data" obd-analyzer /data/log.csv -lang ru

# Анализ директории
docker run --rm -v "C:\logs:/data" obd-analyzer /data -lang en

# С флагами
docker run --rm -v "C:\logs:/data" obd-analyzer /data -nopdf -noxls -lang ru
```

Результаты сохраняются рядом с исходными CSV внутри смонтированного volume.

## Структура проекта

```
analyze_obd/
├── analyze_obd.py           Оркестратор: загрузка CSV, метрики, запуск отчётов
├── analyze_obd.json         Маппинг колонок исходного CSV
├── core_obd.py              Ядро: константы, утилиты, функции статусов
├── core_obd.json            Ядро: пороговые значения констант
├── gui.py                   Графический интерфейс (tkinter, запуск без аргументов)
├── deps.py                  Зависимости: проверка и установка по согласию (для GUI)
├── translation.py           Модуль локализации (t(), set_language())
│
├── lang/                    Файлы переводов
│   ├── ru.json                  Перевод: русский
│   ├── en.json                  Перевод: английский
│   └── de.json                  Перевод: немецкий
│
├── build/                Генераторы отчётов и визуализаций
│   ├── build_csv.py             CSV-отчёты: джокер-события, профиль скорости, группы детонации
│   ├── build_png.py             PNG-графики: таймлайн, heatmap, гистограммы, корреляции, дашборд
│   ├── build_html.py            HTML-отчёт: интерактивные графики Plotly, таблицы, табы
│   ├── build_html.j2            HTML-отчёт: Jinja2-шаблон страницы
│   ├── build_html.js            HTML-отчёт: JS-логика для встраивания
│   ├── build_html.css           HTML-отчёт: стили
│   ├── build_plotly.py          Plotly-графики: таймлайн, heatmap, гистограммы, 3D
│   ├── build_plotly.js          Plotly-графики: JS-обёртка для встраивания
│   ├── build_pdf.py             PDF-отчёт: метрики, карточки, таблицы, PNG-иллюстрации
│   ├── build_map.py             Интерактивная карта: маршрут и параметры в HTML
│   ├── build_map.j2             Карта: Jinja2-шаблон панели карты
│   ├── build_map.js             Карта: JS-логика для встраивания
│   └── build_geojson.py         GeoJSON: сегменты маршрута с min/max/mean значениями
│
├── plugins/                 Аналитические плагины
│   ├── check_catalyst.py        Анализ катализатора и качества топлива
│   ├── check_coolant.py         Анализ прогрева, термостата и вентилятора
│   └── check_knock.py           Анализ детонации и пропусков зажигания
│
├── compare/                 Сравнение нескольких поездок
│   ├── compare_core.py          Загрузка *_metrics.csv, сводные DataFrame
│   ├── compare_png.py           PNG-графики: тренды, детонация, режимы, heatmap статусов
│   ├── compare_plotly.py        Plotly-графики для HTML-отчёта сравнения (интерактивные)
│   ├── compare_html.py          HTML-отчёт сравнения с вкладками
│   ├── compare_html.j2          HTML-отчёт сравнения: Jinja2-шаблон страницы
│   ├── compare_html.css         Стили HTML-отчёта сравнения
│   ├── compare_html.js          JS-логика HTML-отчёта сравнения
│   ├── compare_profiles.py      Профили скорости: загрузка *_profile.csv, HTML-вкладки, CSV-экспорт
│   ├── compare_pdf.py           PDF-отчёт сравнения
│   ├── compare_xls.py           Excel-отчёт сравнения (.xlsx)
│   └── compare_csv.py           CSV-отчёт сравнения (всегда)
│
├── tests/                   Юнит-тесты
│   ├── test_column_mapping.py   Тесты маппинга колонок и find_column
│   ├── test_knock_grouping.py   Тесты группировки и классификации детонации
│   ├── test_statuses.py         Тесты расчёта статусов параметров (параметризованные)
│   ├── test_compare_core.py     Тесты модуля сравнения поездок (compare_core)
│   ├── test_core_obd_json.py    Тесты конфига core_obd.json: ключи, типы, инварианты min < max
│   ├── test_render.py           Тесты модулей генерации: build_html, build_png, build_csv
│   ├── test_compare_reports.py  Тесты compare_plotly, compare_pdf и HTML-валидности
│   └── README.md                Инструкция по запуску тестов
│
├── docker/                  Docker — сборка и запуск
│   ├── Dockerfile               Образ Python 3.12-slim, непривилегированный пользователь obd
│   ├── requirements.txt         Зависимости Python для Docker-образа
│   ├── build.sh                 Скрипт сборки (Linux/macOS)
│   └── build.bat                Скрипт сборки (Windows)
│
├── setup.cfg                Конфиг isort / flake8 / mypy
└── .pre-commit-config.yaml  Pre-commit хуки: black, isort, flake8, mypy
```

## Зависимости

### Runtime (`docker/requirements.txt`)

| Пакет | Версия | Назначение |
|---|---|---|
| `pandas` | >=2.0 | Обработка CSV и DataFrame |
| `numpy` | >=1.24 | Числовые вычисления |
| `matplotlib` | >=3.7 | PNG-графики |
| `Pillow` | >=10.0 | Обработка изображений (используется matplotlib) |
| `requests` | >=2.28 | Автоопределение температуры через Open-Meteo API |
| `jinja2` | >=3.1 | HTML-шаблоны (`build_html.j2`, `compare_html.j2`) |
| `plotly` | >=5.18 | **Опционально** — интерактивные Plotly-графики в HTML |
| `reportlab` | >=4.0 | **Опционально** — PDF-отчёт |
| `openpyxl` | >=3.1 | **Опционально** — Excel-отчёт сравнения (.xlsx) |

```bash
pip install pandas numpy matplotlib Pillow requests jinja2
# Опциональные (полный набор отчётов):
pip install plotly reportlab openpyxl
```

### Dev-зависимости (только для разработки)

| Пакет | Назначение |
|---|---|
| `pytest` | Запуск юнит-тестов |
| `pytest-cov` | Отчёт покрытия (опционально) |
| `pre-commit` | Запуск хуков black / isort / flake8 / mypy перед коммитом |

```bash
pip install pytest pre-commit
pre-commit install   # установить git-хуки из .pre-commit-config.yaml
```

## История версий

Полная история изменений — в [CHANGELOG.ru.md](CHANGELOG.ru.md) (русский) и [CHANGELOG.md](CHANGELOG.md) (английский).

## Лицензия

MIT — см. [LICENSE](LICENSE).
