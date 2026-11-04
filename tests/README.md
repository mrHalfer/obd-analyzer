# Юнит-тесты OBD-II Analyser v9.4

## Структура

| Файл | Что тестирует | Тестов |
|---|---|---|
| `test_column_mapping.py` | Загрузка маппинга колонок (`load_column_mapping`) и поиск колонки в DataFrame (`find_column`) | 13 |
| `test_knock_grouping.py` | Группировка и классификация событий детонации (`classify_knock_groups_with_remission`) | 11 |
| `test_statuses.py` | Расчёт статусов параметров (`get_status`): LTFT, STFT, T ОЖ, детонация. Параметризованные тесты через `@pytest.mark.parametrize` | 9 |
| `test_compare_core.py` | Модуль сравнения поездок (`compare/compare_core.py`): `parse_numeric`, `_extract_trip_id`, `resolve_val_stat`, `get_numeric_series`, `build_compare_rows`, `get_drive_mode_durations`, `get_status_matrix`, `STATUS_MAP` | 53 |
| `test_core_obd_json.py` | Валидация `core_obd.json`: наличие всех ключей, числовые типы, hex-цвета, инварианты min < max | 12 |
| `test_render.py` | Модули генерации отчётов: `build_html` (HTML-вывод, создание файла), `build_png` (функции без исключений), `build_csv` (создание knock.csv) | 25 |
| `test_compare_reports.py` | Модули отчётов сравнения: `compare_plotly` (`_trip_labels`, `generate_all_plotly_html`, все `_plot_*`), `compare_pdf` (`_stat_bg`, `_register_fonts`, `_build_one_chunk_table`, `create_compare_pdf`), HTML-валидность (`report.html` и `comparison_report.html`) | 22 |
| **Итого** | | **145** |

> Параметризованные тесты (`@pytest.mark.parametrize`) при запуске разворачиваются в большее количество реальных тест-кейсов.

## Запуск

### Все тесты
```bash
cd c:\Scripts\obd
python -m pytest tests/ -v
```

### Один файл
```bash
python -m pytest tests/test_statuses.py -v
```

### С отчётом покрытия (если установлен pytest-cov)
```bash
python -m pytest tests/ -v --cov=. --cov-report=term-missing
```

## Зависимости

Тесты используют **pytest** (не входит в стандартную библиотеку):
```bash
python -m pip install pytest
```

Опционально для отчёта покрытия:
```bash
python -m pip install pytest-cov
```

## Замечания

- Тесты читают `core_obd.json` для получения реальных порогов — изменение конфига может изменить ожидаемые результаты.
- `test_knock_grouping.py` требует наличия `plugins/check_knock.py` и его зависимостей.
- `test_compare_core.py` требует наличия `compare/compare_core.py` и `core_obd.json`.
- `test_core_obd_json.py` проверяет `core_obd.json` напрямую — при изменении порогов некоторые инварианты (min < max) нужно пересмотреть.
- `test_render.py` использует фикстуры `tmp_path` (встроена в pytest) и создаёт временные файлы; не требует реальных OBD-логов.
- `test_compare_reports.py` создаёт временные `*_metrics.csv` через фикстуры; тесты PDF и Plotly автоматически пропускаются (`pytest.skip`) если `reportlab` / `plotly` не установлены. HTML-валидность проверяется встроенным `html.parser` без внешних зависимостей.
