#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Оркестратор анализа OBD-II данных для Lada Granta FL 2022 (ВАЗ-11182 1.6л).

Координирует загрузку CSV, маппинг колонок, вычисление метрик
и генерацию отчётов через модули csv/png/html/pdf.

Версия: 9.5 (2026-11-04)
История изменений — см. CHANGELOG.ru.md
"""

import argparse
import importlib
import logging
import sys
from pathlib import Path
from typing import Optional

# ============================================================================
# Режим запуска (схема auto-install взята из animatron.py)
# ============================================================================
# Без позиционного аргумента (файла/папки) скрипт запускает GUI: он сам
# предложит установить недостающие пакеты после согласия пользователя.
# В CLI-режиме (путь задан) зависимости только проверяются — в консоль
# печатается точная команда установки, ничего не ставится автоматически.
from deps import MissingDependencyError, CORE_PACKAGES, pip_install_hint

_OPTS_WITH_VALUE = {'-fuel', '-temp', '-lang'}


def _has_input_argument(argv: list[str]) -> bool:
    """True, если в argv есть позиционный аргумент (путь к файлу/папке)."""
    i = 0
    while i < len(argv):
        tok = argv[i]
        if tok in _OPTS_WITH_VALUE:
            i += 2  # опция съедает своё значение
            continue
        if tok.startswith('-'):
            i += 1
            continue
        return True
    return False


if __name__ == '__main__' and '-h' not in sys.argv[1:] and '--help' not in sys.argv[1:] \
        and not _has_input_argument(sys.argv[1:]):
    from gui import run_gui
    sys.exit(run_gui())

if __name__ == '__main__':
    # CLI: ядерные зависимости только проверяем (установку делает пользователь)
    for _pkg in CORE_PACKAGES:
        try:
            importlib.import_module(_pkg)
        except ImportError:
            sys.stderr.write(
                f'Не найден пакет {_pkg} — без него анализ не работает.\n'
                f'Установите командой:\n    {pip_install_hint(_pkg)}\n'
            )
            sys.exit(1)

import pandas as pd

# --- Пути к подпапкам проекта (build/, plugins/, compare/) ---
_PROJECT_ROOT = Path(__file__).parent
for _subdir in ('build', 'plugins', 'compare'):
    _p = str(_PROJECT_ROOT / _subdir)
    if _p not in sys.path:
        sys.path.insert(0, _p)

# --- Настройка консольного обработчика ДО импорта модулей ---
# Это перехватывает INFO-сообщения, возникающие при загрузке конфигов на уровне модуля
_root_logger = logging.getLogger()
_root_logger.setLevel(logging.DEBUG)
_console_handler = logging.StreamHandler()
_console_handler.setLevel(logging.INFO)
_console_handler.setFormatter(logging.Formatter('%(message)s'))
_root_logger.addHandler(_console_handler)

# Импорты модулей формирования отчётов
from build_csv import (
    save_joker_events,
    create_speed_profile,
    save_knock_groups,
    save_knock_timeline,
    save_misfire_timeline,
)

# build_png требует matplotlib — опциональную зависимость формата PNG:
# при её отсутствии модуль не импортируется, а генерация PNG будет пропущена
# с сообщением и pip-командой (см. _generate_png_charts)
_png_missing: Optional[MissingDependencyError] = None
try:
    import build_png as _build_png
except MissingDependencyError as _png_e:
    _build_png = None
    _png_missing = _png_e

from build_html import (
    create_report_html,
)

from build_pdf import (
    create_pdf_report,
)

# Импорт из ядра: только то, что реально используется в оркестраторе
from core_obd import (
    STATUS_OK, STATUS_WARNING, STATUS_ERROR, STATUS_NEUTRAL,
    SEPARATOR_LINE,
    LOG_DT,
    _THRESHOLDS_PATH,
    MIN_RPM_THRESHOLD,
    STALLED_RPM_THRESHOLD,
    MAX_STALLED_DURATION_SEC,
    LTFT_PERCENTILE_LOW, LTFT_PERCENTILE_HIGH,
    # Функции
    parse_time_to_seconds_vectorized,
    filter_warmup_startup,
    count_stalled_event_groups,
    get_status,
    build_percentile_metrics,
    build_stat_metrics,
    detect_engine_start,
    detect_warmup_end,
    auto_detect_temperature,
    load_column_mapping,
    looks_like_time,
)

# Импорты из модулей анализа конкретных аспектов (детонация, пропуски, топливо, катализатор, охлаждение)
from check_knock import analyze_knock, analyze_misfires
from check_catalyst import analyze_catalyst, analyze_fuel_quality
from check_coolant import analyze_coolant_system
from build_geojson import generate_geojson
from translation import t, set_language

from compare_core     import load_trips
from compare_csv      import create_compare_csv

# compare_png требует matplotlib — тот же порядок, что и с build_png выше
_cmp_png_missing: Optional[MissingDependencyError] = None
try:
    from compare_png import generate_all_plots
except MissingDependencyError as _cmp_e:
    generate_all_plots = None
    _cmp_png_missing = _cmp_e

from compare_html     import create_compare_html
from compare_pdf      import create_compare_pdf
from compare_xls      import create_compare_xls
from compare_profiles import load_profiles, build_profiles_csv

logger = logging.getLogger(__name__)

# ============================================================================
# Функция анализа данных (оркестрация)
# ============================================================================

def validate_input_file(file_path: str) -> bool:
    """Проверяет корректность входного файла перед обработкой.

    Проверки:
    1. Размер файла не превышает 150 МБ
    2. Файл является валидным CSV (можно прочитать заголовок)
    3. В заголовке есть базовые обязательные колонки (TIME или RPM)

    Args:
        file_path: Путь к файлу для проверки.

    Returns:
        True если файл валиден, False если найдены проблемы.
    """
    file_path_obj = Path(file_path)

    # Проверка 1: Файл существует
    if not file_path_obj.exists():
        logger.error(t('console.file_not_found', path=file_path))
        return False

    # Проверка 2: Размер файла <= 150 МБ
    MAX_FILE_SIZE_MB = 150
    file_size_bytes = file_path_obj.stat().st_size
    file_size_mb = file_size_bytes / (1024 * 1024)

    if file_size_mb > MAX_FILE_SIZE_MB:
        logger.warning(t('console.file_too_large', size_mb=file_size_mb, max_mb=MAX_FILE_SIZE_MB))
        logger.info(t('console.file_too_large_hint1'))
        logger.info(t('console.file_too_large_hint2'))
        return False

    # Проверка 3: Файл является валидным CSV
    try:
        # Пытаемся прочитать только заголовок (первые 5 строк для проверки структуры)
        df_sample = pd.read_csv(file_path, nrows=5, encoding='utf-8-sig')
    except UnicodeDecodeError:
        try:
            # Пробуем другую кодировку
            df_sample = pd.read_csv(file_path, nrows=5, encoding='cp1251')
        except (pd.errors.ParserError, UnicodeDecodeError, OSError) as e:
            logger.error(t('console.csv_read_error', e=e))
            logger.info(t('console.csv_read_hint_text'))
            return False
    except (pd.errors.ParserError, OSError) as e:
        logger.error(t('console.csv_read_error', e=e))
        logger.info(t('console.csv_read_hint_comma'))
        return False

    # Проверка 4: В файле есть колонки
    if df_sample.empty or len(df_sample.columns) == 0:
        logger.warning(t('console.file_empty'))
        return False

    # Проверка наличия обязательных колонок будет выполнена после fuzzy-маппинга
    # в функции _load_and_map_columns()
    return True


_CSV_INJECTION_PREFIXES = ('=', '+', '-', '@', '|', '%')


def _warn_csv_injection(df: pd.DataFrame, file_path: str) -> None:
    """Проверяет строковые ячейки CSV на признаки формульной инъекции.

    OBD-CSV содержит только числа и единицы измерения, поэтому ячейки,
    начинающиеся с =, +, -, @, | или %, подозрительны. pandas их не исполняет,
    однако при экспорте в Excel они могут выполниться. Функция только логирует
    предупреждение — данные не изменяются.

    Args:
        df: Загруженный DataFrame.
        file_path: Путь к файлу (для сообщения в лог).
    """
    suspicious: list[str] = []
    for col in df.select_dtypes(include="object").columns:
        mask = df[col].astype(str).str.startswith(_CSV_INJECTION_PREFIXES)
        if mask.any():
            suspicious.append(col)
    if suspicious:
        logger.warning(
            "Файл %s содержит ячейки с возможной формульной инъекцией "
            "в колонках: %s. При экспорте в Excel используйте защищённый режим.",
            file_path,
            ", ".join(suspicious),
        )


# Узкополосные O2-датчики (напряжение): при матчинге исключаем широкополосные колонки
_O2_NARROWBAND_TARGETS = frozenset({
    'O2_B1S1', 'O2_B1S2', 'O2_B1S3', 'O2_B1S4',
    'O2_B2S1', 'O2_B2S2', 'O2_B2S3', 'O2_B2S4',
})


def _is_wideband_col(col: str, col_lower: str) -> bool:
    """True если колонка относится к широкополосному O2-датчику."""
    return (
        'шир' in col_lower          # широкополосный
        or 'wide' in col_lower      # wideband
        or 'мА' in col              # миллиамперы (Кириллица, регистрозависимо)
        or 'mA' in col              # milliamps   (латиница, регистрозависимо)
    )


def _load_and_map_columns(file_path: str) -> Optional[pd.DataFrame]:
    """Загружает CSV и выполняет fuzzy-маппинг колонок по JSON-конфигу.

    Args:
        file_path: Путь к CSV файлу с OBD-II данными.

    Returns:
        DataFrame с замапленными колонками или None при ошибке.
    """
    try:
        df = pd.read_csv(file_path)
    except (pd.errors.ParserError, UnicodeDecodeError, OSError) as e:
        logger.error(t('console.file_read_error', e=e))
        return None

    if df.empty:
        logger.warning(t('console.file_data_empty'))
        return None

    _warn_csv_injection(df, file_path)

    df_clean = df.copy()

    fuzzy_column_mapping = load_column_mapping()
    if not fuzzy_column_mapping:
        return None

    # Работаем только с исходными колонками (до добавления наших TARGET-столбцов),
    # чтобы избежать KeyError при обращении к cols_lower по новым именам
    original_columns = list(df_clean.columns)
    used_source_columns = set()
    cols_lower = {col: col.lower() if isinstance(col, str) else str(col).lower() for col in original_columns}

    # Первая колонка считается временем если похожа на HH:MM:SS
    first_col = original_columns[0]
    if looks_like_time(df_clean[first_col]):
        df_clean['TIME'] = df_clean[first_col]
        used_source_columns.add(first_col)
        df_clean.attrs['source_TIME'] = first_col

    for target_col, patterns in fuzzy_column_mapping.items():
        found_col = None
        for pattern in patterns:
            pattern_lower = pattern.lower()
            # Ищем первый столбец, содержащий указанный фрагмент, только среди исходных колонок
            candidates = [
                col for col in original_columns
                if col not in used_source_columns and pattern_lower in cols_lower.get(col, str(col).lower())
            ]
            # Для узкополосных O2-датчиков исключаем широкополосные колонки
            if target_col in _O2_NARROWBAND_TARGETS:
                candidates = [
                    c for c in candidates
                    if not _is_wideband_col(c, cols_lower.get(c, c.lower()))
                ]
            if candidates:
                # Для RPM избегаем "x1000" если есть выбор
                if target_col == 'RPM':
                    exact_rpm = [c for c in candidates if 'x1000' not in c]
                    if exact_rpm:
                        found_col = exact_rpm[0]
                    else:
                        found_col = candidates[0]
                else:
                    found_col = candidates[0]
                break

        if found_col is not None:
            df_clean[target_col] = df_clean[found_col]
            used_source_columns.add(found_col)
            df_clean.attrs[f'source_{target_col}'] = found_col

    # Логирование распознанных колонок
    logger.info(t('console.columns_recognized', found=len(used_source_columns), total=len(original_columns)))
    for target, patterns in fuzzy_column_mapping.items():
        if target in df_clean.columns:
            for pattern in patterns:
                pattern_lower = pattern.lower()
                # Поиск исходной колонки, которая реально была использована
                for col in original_columns:
                    if pattern_lower in str(col).lower() and col in used_source_columns:
                        logger.debug(t('console.column_mapped', target=target, col=col))
                        break
                break

    # Forward-fill замапленных OBD-колонок для логов с round-robin опросом.
    # В таких логах каждая строка содержит данные одного PID — остальные NaN.
    # ffill превращает разреженные строки в полные снимки последних известных значений.
    # Для стандартных логов (где каждая строка уже полная) — эффект нулевой.
    obd_cols = [col for col in fuzzy_column_mapping if col in df_clean.columns and col != 'TIME']
    if obd_cols:
        df_clean[obd_cols] = df_clean[obd_cols].ffill()

    # Проверка обязательных колонок после маппинга
    if 'TIME' not in df_clean.columns:
        logger.error(t('console.columns_mandatory_missing'))
        logger.info(t('console.columns_mandatory_hint1'))
        logger.info(t('console.columns_mandatory_hint2', cols=[col for col in df_clean.columns if col in fuzzy_column_mapping]))
        return None

    # Предупреждение о рекомендуемых колонках
    recommended_columns = ['RPM', 'SPEED']
    missing_recommended = [col for col in recommended_columns if col not in df_clean.columns]
    if missing_recommended:
        logger.warning(t('console.columns_recommended_missing', cols=missing_recommended))
        logger.info(t('console.columns_recommended_hint'))

    return df_clean


def _filter_time_duplicates(df_clean: pd.DataFrame) -> pd.DataFrame:
    """Удаляет дубликаты по колонке TIME и вычисляет TIME_SEC."""
    if 'TIME' not in df_clean.columns:
        return df_clean
    try:
        df_clean['TIME_DT'] = pd.to_datetime(df_clean['TIME'], format='%H:%M:%S.%f', errors='coerce')
        df_clean['TIME_DIFF'] = df_clean['TIME_DT'].diff().dt.total_seconds()

        valid_time_mask = (df_clean['TIME_DIFF'].isna()) | (df_clean['TIME_DIFF'] >= 0.1)
        rows_before = len(df_clean)
        df_clean = df_clean[valid_time_mask].reset_index(drop=True)
        rows_removed = rows_before - len(df_clean)
        if rows_removed > 0:
            logger.debug(t('console.duplicates_removed_time', n=rows_removed))

        # TIME_SEC считаем один раз векторизованно
        df_clean['TIME_SEC'] = parse_time_to_seconds_vectorized(df_clean['TIME'])

        # Временные служебные колонки больше не нужны
        df_clean = df_clean.drop(columns=['TIME_DT', 'TIME_DIFF'])
    except (ValueError, KeyError, AttributeError) as e:
        logger.warning(t('console.duplicates_filter_error', e=e))
    return df_clean


def _convert_fuel_distance_columns(df_clean: pd.DataFrame) -> pd.DataFrame:
    """Создаёт LTFT_PERCENT/STFT_PERCENT из LTFT/STFT и вычисляет дельту дистанции.

    Если исходная колонка содержит «%» в названии — значения уже в процентах, копируем как есть.
    Иначе применяем авто-детект: abs().max() ≤ 2.0 → мультипликатор (0.98 → -2%), иначе — тоже %.
    """
    for src_col, pct_col in [('LTFT', 'LTFT_PERCENT'), ('STFT', 'STFT_PERCENT')]:
        if src_col not in df_clean.columns:
            continue
        source_col_name = df_clean.attrs.get(f'source_{src_col}', '')
        if '%' in str(source_col_name):
            # Исходная колонка уже в процентах (заголовок содержит %)
            df_clean[pct_col] = df_clean[src_col]
        else:
            # Неизвестный формат — авто-детект по диапазону значений
            vals = df_clean[src_col].dropna()
            if len(vals) > 0 and vals.abs().max() <= 2.0:
                df_clean[pct_col] = (df_clean[src_col] - 1) * 100
            else:
                df_clean[pct_col] = df_clean[src_col]
    if 'DISTANCE' in df_clean.columns:
        df_clean['DISTANCE_DELTA'] = df_clean['DISTANCE'].diff()
        df_clean.loc[0, 'DISTANCE_DELTA'] = 0
        df_clean.loc[df_clean['DISTANCE_DELTA'] < 0, 'DISTANCE_DELTA'] = 0
        df_clean.loc[df_clean['DISTANCE_DELTA'] > 5, 'DISTANCE_DELTA'] = 0
    return df_clean


def _assign_drive_regimes(df_clean: pd.DataFrame, engine_start_idx: int, warmup_end_idx: int) -> pd.DataFrame:
    """Присваивает каждой строке режим работы двигателя (PRE_START, WARMUP, DRIVE_*)."""
    df_clean['REGIME'] = 'UNKNOWN'
    if engine_start_idx > 0:
        df_clean.loc[:engine_start_idx - 1, 'REGIME'] = 'PRE_START'
        logger.info(t('console.prestart_detected', n=engine_start_idx, sec=engine_start_idx * LOG_DT))
    if warmup_end_idx > engine_start_idx:
        df_clean.loc[engine_start_idx:warmup_end_idx - 1, 'REGIME'] = 'WARMUP'
    if 'SPEED' in df_clean.columns:
        after_warmup = df_clean.index >= warmup_end_idx
        df_clean.loc[after_warmup & (df_clean['SPEED'] >= 0)   & (df_clean['SPEED'] <= 60),  'REGIME'] = 'DRIVE_CITY'
        df_clean.loc[after_warmup & (df_clean['SPEED'] > 60)   & (df_clean['SPEED'] <= 110), 'REGIME'] = 'DRIVE_SUBURBAN'
        df_clean.loc[after_warmup & (df_clean['SPEED'] > 110),                                'REGIME'] = 'DRIVE_HIGHWAY'
    return df_clean


def _clean_and_prepare_data(
    df_clean: pd.DataFrame,
    file_path: str,
    temp_outside: Optional[float],
) -> Optional[tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, float, float]]:
    """Очищает данные, определяет температуру, категоризирует режимы.

    Args:
        df_clean: DataFrame после маппинга колонок.
        file_path: Путь к CSV файлу (для извлечения даты).
        temp_outside: Температура снаружи (°C). None — автоопределение.

    Returns:
        (df_clean, df_full, df_full_filtered, temp_outside, all_drive_duration_min)
        или None при ошибке.
    """
    if temp_outside is None:
        # Извлекаем дату из имени файла (формат: YYYY-MM-DD_...)
        date_str = None
        try:
            filename = Path(file_path).stem
            if len(filename) >= 10:
                date_str = filename[:10]  # YYYY-MM-DD
        except (ValueError, IndexError):
            pass
        temp_outside = auto_detect_temperature(df_clean, date_str=date_str)

    # Фильтрация пустых строк
    key_params = ['RPM', 'SPEED', 'COOLANT_TEMP', 'ENGINE_LOAD', 'MAF']
    available_key_params = [p for p in key_params if p in df_clean.columns]
    if available_key_params:
        valid_mask = df_clean[available_key_params].notna().any(axis=1)
        rows_before = len(df_clean)
        df_clean = df_clean[valid_mask].reset_index(drop=True)
        rows_removed = rows_before - len(df_clean)
        if rows_removed > 0:
            logger.debug(t('console.empty_rows_removed', n=rows_removed))

    if len(df_clean) == 0:
        logger.warning(t('console.no_data_after_filter'))
        return None

    df_clean = _filter_time_duplicates(df_clean)

    if len(df_clean) == 0:
        logger.warning(t('console.no_data_after_filter'))
        return None

    df_clean = _convert_fuel_distance_columns(df_clean)
    df_clean = _assign_drive_regimes(df_clean, detect_engine_start(df_clean), detect_warmup_end(df_clean))

    # df_full — полные данные БЕЗ фильтрации низких RPM (для подсчёта заглохших)
    df_full = df_clean.copy()
    # Отфильтрованная версия df_full для подсчёта заглохших (без секции первого запуска WARMUP)
    df_full_filtered = filter_warmup_startup(df_full)

    if 'RPM' in df_clean.columns:
        low_rpm_mask = (df_clean['REGIME'] != 'PRE_START') & (df_clean['RPM'] < MIN_RPM_THRESHOLD)
        rows_before = len(df_clean)
        df_clean = df_clean[~low_rpm_mask].reset_index(drop=True)
        rows_removed = rows_before - len(df_clean)
        if rows_removed > 0:
            logger.debug(t('console.joker_excluded', rpm=MIN_RPM_THRESHOLD, n=rows_removed))
            logger.debug(t('console.joker_excluded_hint'))

    # ALL_DRIVE_DURATION в минутах (для оценки детонации)
    all_drive_mask = df_clean['REGIME'].isin(['DRIVE_CITY', 'DRIVE_SUBURBAN', 'DRIVE_HIGHWAY'])
    all_drive_duration_min = 0
    if 'REGIME' in df_clean.columns and all_drive_mask.any():
        all_drive_duration_min = len(df_clean[all_drive_mask]) * LOG_DT / 60

    return df_clean, df_full, df_full_filtered, temp_outside, all_drive_duration_min


def _build_header_metrics(
    df_clean: pd.DataFrame,
    file_path: str,
    fuel_type: str,
    temp_outside: float,
) -> list[dict]:
    """Строит метрики заголовка поездки (RUN_*)."""
    base_filename = Path(file_path).stem
    start_time   = df_clean['TIME'].iloc[0]  if 'TIME' in df_clean.columns else ''
    end_time     = df_clean['TIME'].iloc[-1] if 'TIME' in df_clean.columns else ''
    duration_sec = len(df_clean) * LOG_DT
    return [
        {'CODE': 'RUN_FUEL_TYPE',    'DESC': t('metric_descs.fuel_type'),    'VAL': fuel_type,                'STAT': STATUS_NEUTRAL},
        {'CODE': 'RUN_TEMP_OUTSIDE', 'DESC': t('metric_descs.temp_outside'), 'VAL': temp_outside,             'STAT': STATUS_NEUTRAL},
        {'CODE': 'RUN_DATE',         'DESC': t('metric_descs.run_date'),     'VAL': base_filename[:10],       'STAT': STATUS_NEUTRAL},
        {'CODE': 'RUN_TIME_START',   'DESC': t('metric_descs.time_start'),   'VAL': start_time,               'STAT': STATUS_NEUTRAL},
        {'CODE': 'RUN_TIME_END',     'DESC': t('metric_descs.time_end'),     'VAL': end_time,                 'STAT': STATUS_NEUTRAL},
        {'CODE': 'RUN_DURATION',     'DESC': t('metric_descs.duration_min'), 'VAL': f'{duration_sec/60:.1f}', 'STAT': STATUS_NEUTRAL},
    ]


def _build_coolant_metrics(
    regime_code: str,
    regime_desc: str,
    regime_df: pd.DataFrame,
    status_stats: tuple[str, ...],
) -> list[dict]:
    """Метрики температуры ОЖ для одного режима."""
    if 'COOLANT_TEMP' not in regime_df.columns:
        return []
    vals = regime_df['COOLANT_TEMP'].dropna()
    if vals.empty:
        return []
    return build_stat_metrics(regime_code, regime_desc, vals,
        'TEMP_COOLANT', t('metric_labels.coolant_temp'), t('units.celsius'),
        status_param='TEMP_COOLANT', status_stats=status_stats)


def _build_fuel_trim_metrics(
    regime_code: str,
    regime_desc: str,
    regime_df: pd.DataFrame,
) -> list[dict]:
    """Метрики топливных коррекций LTFT и STFT для одного режима."""
    metrics: list[dict] = []
    if 'LTFT_PERCENT' in regime_df.columns:
        vals = regime_df['LTFT_PERCENT'].dropna()
        if not vals.empty:
            metrics += build_percentile_metrics(regime_code, regime_desc, vals,
                'LTFT', t('metric_labels.ltft'), t('units.percent'),
                p_low=LTFT_PERCENTILE_LOW, p_high=LTFT_PERCENTILE_HIGH,
                zero_skip_percentile=True, status_param='LTFT')
    if 'STFT_PERCENT' in regime_df.columns:
        vals = regime_df['STFT_PERCENT'].dropna()
        if not vals.empty:
            metrics += build_percentile_metrics(regime_code, regime_desc, vals,
                'STFT', t('metric_labels.stft'), t('units.percent'),
                zero_skip_percentile=True, status_param='STFT')
    return metrics


def _build_drive_sensor_metrics(
    regime_code: str,
    regime_desc: str,
    regime_df: pd.DataFrame,
) -> list[dict]:
    """Метрики датчиков потока: O2, MAF, время впрыска, дроссель."""
    metrics: list[dict] = []
    if 'O2_B1S1' in regime_df.columns:
        metrics += build_percentile_metrics(regime_code, regime_desc,
            regime_df['O2_B1S1'].dropna(), 'O2_B1S1', t('metric_labels.o2_sensor1'), t('units.volts'), fmt='.3f')
    if 'O2_B1S2' in regime_df.columns:
        metrics += build_percentile_metrics(regime_code, regime_desc,
            regime_df['O2_B1S2'].dropna(), 'O2_B1S2', t('metric_labels.o2_sensor2'), t('units.volts'), fmt='.3f')
    if 'MAF' in regime_df.columns:
        metrics += build_percentile_metrics(regime_code, regime_desc,
            regime_df['MAF'].dropna(), 'MAF', t('metric_labels.maf'), t('units.grams_per_sec'), status_param='MAF')
    if 'INJECTION_TIME' in regime_df.columns:
        metrics += build_percentile_metrics(regime_code, regime_desc,
            regime_df['INJECTION_TIME'].dropna(), 'INJECTION_TIME', t('metric_labels.injection_time'), t('units.ms'),
            status_param='INJECTION_TIME')
    if 'THROTTLE_POS' in regime_df.columns:
        metrics += build_percentile_metrics(regime_code, regime_desc,
            regime_df['THROTTLE_POS'].dropna(), 'THROTTLE', t('metric_labels.throttle'), t('units.percent'),
            fmt='.1f', status_param='THROTTLE')
    return metrics


def _build_base_params(
    regime_code: str,
    regime_desc: str,
    regime_df: pd.DataFrame,
) -> list[dict]:
    """Общие параметры для всех режимов: RPM, скорость, нагрузка, угол опережения, газ, температура впуска."""
    metrics: list[dict] = []
    if 'RPM' in regime_df.columns:
        metrics += build_stat_metrics(regime_code, regime_desc,
            regime_df['RPM'].dropna(), 'RPM', t('metric_labels.rpm'), t('units.rpm'), fmt='.0f',
            status_param='RPM', status_stats=('mean',))
    if regime_code != 'WARMUP' and 'SPEED' in regime_df.columns:
        metrics += build_stat_metrics(regime_code, regime_desc,
            regime_df['SPEED'].dropna(), 'SPEED', t('metric_labels.speed'), t('units.km_h'), stats=('mean', 'max'))
    if 'ENGINE_LOAD' in regime_df.columns:
        metrics += build_stat_metrics(regime_code, regime_desc,
            regime_df['ENGINE_LOAD'].dropna(), 'LOAD', t('metric_labels.load'), t('units.percent'), stats=('mean',))
    if 'SPARK_ADVANCE' in regime_df.columns:
        metrics += build_stat_metrics(regime_code, regime_desc,
            regime_df['SPARK_ADVANCE'].dropna(), 'SPARK', t('metric_labels.spark'), t('units.degrees'), stats=('mean',))
    if 'ACCEL_POS' in regime_df.columns:
        metrics += build_stat_metrics(regime_code, regime_desc,
            regime_df['ACCEL_POS'].dropna(), 'ACCEL', t('metric_labels.accel'), t('units.percent'),
            status_param='ACCEL', status_stats=('mean', 'min', 'max'))
    if 'INTAKE_TEMP' in regime_df.columns:
        metrics += build_stat_metrics(regime_code, regime_desc,
            regime_df['INTAKE_TEMP'].dropna(), 'INTAKE_TEMP', t('metric_labels.intake_temp'), t('units.celsius'))
    return metrics


def _build_single_regime_metrics(
    regime_code: str,
    regime_desc: str,
    regime_df: pd.DataFrame,
    regime_df_full: pd.DataFrame,
    df_clean: pd.DataFrame,
) -> list[dict]:
    """Строит метрики для одного режима работы двигателя."""
    metrics: list[dict] = [
        {'CODE': f'{regime_code}_COUNT',    'DESC': f'{regime_desc}: {t("metric_descs.count_records")}',  'VAL': len(regime_df),                    'STAT': STATUS_NEUTRAL},
        {'CODE': f'{regime_code}_DURATION', 'DESC': f'{regime_desc}: {t("metric_descs.duration_min")}',   'VAL': f'{len(regime_df)*LOG_DT/60:.1f}', 'STAT': STATUS_NEUTRAL},
    ]

    # PRE_START: только COUNT, DURATION и минимальная температура впуска
    if regime_code == 'PRE_START':
        if 'INTAKE_TEMP' in regime_df.columns:
            vals = regime_df['INTAKE_TEMP'].dropna()
            if not vals.empty:
                metrics.append({'CODE': f'{regime_code}_INTAKE_TEMP_Min', 'DESC': f'{regime_desc}: {t("metric_descs.intake_temp_min")}', 'VAL': f'{vals.min():.1f}', 'STAT': STATUS_NEUTRAL})
        return metrics

    stalled_count = count_stalled_event_groups(regime_df_full)
    metrics.append({'CODE': f'{regime_code}_STALLED_COUNT', 'DESC': f'{regime_desc}: {t("metric_descs.stalled_count", rpm=int(STALLED_RPM_THRESHOLD), sec=int(MAX_STALLED_DURATION_SEC))}', 'VAL': int(stalled_count), 'STAT': get_status('STALLED', stalled_count, regime_code)})

    if regime_code != 'WARMUP' and 'DISTANCE_DELTA' in regime_df.columns:
        metrics.append({'CODE': f'{regime_code}_DISTANCE', 'DESC': f'{regime_desc}: {t("metric_descs.distance_km")}', 'VAL': f'{regime_df["DISTANCE_DELTA"].sum():.2f}', 'STAT': STATUS_NEUTRAL})

    # ALL: Т ОЖ (только max) + топливные коррекции (фолбэк при отсутствии ALL_DRIVE)
    if regime_code == 'ALL':
        metrics += _build_coolant_metrics(regime_code, regime_desc, regime_df, status_stats=('max',))
        metrics += _build_fuel_trim_metrics(regime_code, regime_desc, regime_df)
        all_driving_df = df_clean[~df_clean['REGIME'].isin(['WARMUP', 'PRE_START'])]
        if 'FUEL_CONSUMPTION' in all_driving_df.columns:
            metrics += build_stat_metrics(regime_code, regime_desc,
                all_driving_df['FUEL_CONSUMPTION'].dropna(), 'FUEL', t('metric_labels.fuel'), t('units.l_100km'), stats=('mean',))

    # ALL_DRIVE / DRIVE_* / WARMUP: полный набор датчиков
    if regime_code in ['ALL_DRIVE', 'DRIVE_CITY', 'DRIVE_SUBURBAN', 'DRIVE_HIGHWAY', 'WARMUP']:
        metrics += _build_coolant_metrics(regime_code, regime_desc, regime_df, status_stats=('mean', 'max'))
        metrics += _build_fuel_trim_metrics(regime_code, regime_desc, regime_df)
        metrics += _build_drive_sensor_metrics(regime_code, regime_desc, regime_df)
        if regime_code == 'ALL_DRIVE' and 'FUEL_CONSUMPTION' in regime_df.columns:
            metrics += build_stat_metrics(regime_code, regime_desc,
                regime_df['FUEL_CONSUMPTION'].dropna(), 'FUEL', t('metric_labels.fuel'), t('units.l_100km'), stats=('mean',))

    metrics += _build_base_params(regime_code, regime_desc, regime_df)
    return metrics


def _build_analysis_sections(
    knock_analysis: list[dict],
    misfire_analysis: list[dict],
    fuel_quality_analysis: list[dict],
    catalyst_analysis: list[dict],
    coolant_analysis: list[dict],
) -> list[dict]:
    """Строит секции аналитических модулей: детонация, пропуски, топливо, катализатор, охлаждение."""
    metrics: list[dict] = []

    metrics.append({'CODE': SEPARATOR_LINE, 'DESC': t('sections.knock'), 'VAL': '', 'STAT': ''})
    metrics.extend(knock_analysis)

    metrics.append({'CODE': SEPARATOR_LINE, 'DESC': t('sections.misfire'), 'VAL': '', 'STAT': ''})
    metrics.extend(misfire_analysis)

    if fuel_quality_analysis:
        metrics.append({'CODE': SEPARATOR_LINE, 'DESC': t('sections.fuel_quality'), 'VAL': '', 'STAT': ''})
        metrics.extend(fuel_quality_analysis)

    if catalyst_analysis:
        metrics.append({'CODE': SEPARATOR_LINE, 'DESC': t('sections.catalyst'), 'VAL': '', 'STAT': ''})
        metrics.extend(catalyst_analysis)

    if coolant_analysis:
        metrics.append({'CODE': SEPARATOR_LINE, 'DESC': t('sections.coolant_system'), 'VAL': '', 'STAT': ''})
        metrics.extend(coolant_analysis)

    return metrics


def _build_regime_metrics(
    df_clean: pd.DataFrame,
    df_full_filtered: pd.DataFrame,
    file_path: str,
    fuel_type: str,
    temp_outside: float,
    all_drive_duration_min: float,
    knock_analysis: list[dict],
    misfire_analysis: list[dict],
    fuel_quality_analysis: list[dict],
    catalyst_analysis: list[dict],
    coolant_analysis: list[dict],
) -> list[dict]:
    """Строит полный список метрик: заголовок, по режимам, детонация, пропуски, топливо, катализатор, охлаждение."""
    metrics = _build_header_metrics(df_clean, file_path, fuel_type, temp_outside)
    metrics.append({'CODE': SEPARATOR_LINE, 'DESC': t('sections.general'), 'VAL': '', 'STAT': ''})

    regimes = [
        ('ALL', t('regimes.ALL'), df_clean, df_full_filtered),
        ('ALL_DRIVE', t('regimes.ALL_DRIVE'),
         df_clean[df_clean['REGIME'].isin(['DRIVE_CITY', 'DRIVE_SUBURBAN', 'DRIVE_HIGHWAY'])],
         df_full_filtered[df_full_filtered['REGIME'].isin(['DRIVE_CITY', 'DRIVE_SUBURBAN', 'DRIVE_HIGHWAY'])]),
        ('PRE_START', t('regimes.PRE_START'),
         df_clean[df_clean['REGIME'] == 'PRE_START'],
         df_full_filtered[df_full_filtered['REGIME'] == 'PRE_START']),
        ('WARMUP', t('regimes.WARMUP'),
         df_clean[df_clean['REGIME'] == 'WARMUP'],
         df_full_filtered[df_full_filtered['REGIME'] == 'WARMUP']),
        ('DRIVE_CITY', t('regimes.DRIVE_CITY'),
         df_clean[df_clean['REGIME'] == 'DRIVE_CITY'],
         df_full_filtered[df_full_filtered['REGIME'] == 'DRIVE_CITY']),
        ('DRIVE_SUBURBAN', t('regimes.DRIVE_SUBURBAN'),
         df_clean[df_clean['REGIME'] == 'DRIVE_SUBURBAN'],
         df_full_filtered[df_full_filtered['REGIME'] == 'DRIVE_SUBURBAN']),
        ('DRIVE_HIGHWAY', t('regimes.DRIVE_HIGHWAY'),
         df_clean[df_clean['REGIME'] == 'DRIVE_HIGHWAY'],
         df_full_filtered[df_full_filtered['REGIME'] == 'DRIVE_HIGHWAY']),
    ]

    for idx, (regime_code, regime_desc, regime_df, regime_df_full) in enumerate(regimes):
        if len(regime_df) == 0:
            continue
        if idx > 0:
            metrics.append({'CODE': SEPARATOR_LINE, 'DESC': regime_desc, 'VAL': '', 'STAT': ''})
        metrics += _build_single_regime_metrics(regime_code, regime_desc, regime_df, regime_df_full, df_clean)

    metrics += _build_analysis_sections(
        knock_analysis, misfire_analysis, fuel_quality_analysis, catalyst_analysis, coolant_analysis,
    )
    return metrics


def _run_analysis_modules(
    df_clean: pd.DataFrame,
    df_full_filtered: pd.DataFrame,
    temp_outside: Optional[float],
    all_drive_duration_min: float,
) -> tuple:
    """Запускает все аналитические модули и возвращает их результаты в виде кортежа."""
    knock_analysis = analyze_knock(df_clean, all_drive_duration_min)
    misfire_analysis = analyze_misfires(df_clean)
    fuel_quality_analysis = analyze_fuel_quality(df_clean)
    catalyst_analysis = analyze_catalyst(df_clean)
    coolant_analysis = analyze_coolant_system(df_clean, temp_outside)
    return knock_analysis, misfire_analysis, fuel_quality_analysis, catalyst_analysis, coolant_analysis


def analyze_data(
    file_path: str,
    fuel_type: str = 'АИ-95',
    temp_outside: Optional[float] = None,
) -> tuple[list[dict], pd.DataFrame, list[dict], pd.DataFrame] | tuple[None, None, None, None]:
    """Основная функция анализа OBD-II данных из CSV файла.

    Загрузка CSV, fuzzy-маппинг колонок, очистка данных, автоопределение
    температуры, категоризация режимов (PRE_START/WARMUP/DRIVE_*),
    вычисление метрик, анализ детонации/пропусков/топлива.

    Args:
        file_path: Путь к CSV файлу с OBD-II данными.
        fuel_type: Тип топлива (по умолчанию 'АИ-95').
        temp_outside: Температура снаружи (°C). None — автоопределение.

    Returns:
        (metrics, df_clean, knock_analysis, df_full) или (None, None, None, None).
    """
    # Валидация входного файла
    if not validate_input_file(file_path):
        return None, None, None, None

    df_clean = _load_and_map_columns(file_path)
    if df_clean is None:
        return None, None, None, None

    prep_result = _clean_and_prepare_data(df_clean, file_path, temp_outside)
    if prep_result is None:
        return None, None, None, None

    df_clean, df_full, df_full_filtered, temp_outside, all_drive_duration_min = prep_result

    knock_analysis, misfire_analysis, fuel_quality_analysis, catalyst_analysis, coolant_analysis = \
        _run_analysis_modules(df_clean, df_full_filtered, temp_outside, all_drive_duration_min)

    metrics = _build_regime_metrics(
        df_clean, df_full_filtered, file_path, fuel_type, temp_outside,
        all_drive_duration_min, knock_analysis, misfire_analysis,
        fuel_quality_analysis, catalyst_analysis, coolant_analysis,
    )

    return metrics, df_clean, knock_analysis, df_full


def _cleanup_temp_pngs(output_dir: Path, base_filename: str) -> None:
    """Удаляет временные PNG файлы после встраивания в PDF."""
    pattern = f'{base_filename}_viz_*.png'
    png_files = list(output_dir.glob(pattern))
    if png_files:
        for f in png_files:
            f.unlink()
        logger.info(t('console.png_temp_removed', n=len(png_files)))


def _print_processing_stats(metrics_df: pd.DataFrame, df_clean: pd.DataFrame) -> None:
    """Выводит сводную статистику по итогам обработки файла."""
    ok_count   = len(metrics_df[metrics_df['STAT'] == STATUS_OK])
    warn_count = len(metrics_df[metrics_df['STAT'] == STATUS_WARNING])
    err_count  = len(metrics_df[metrics_df['STAT'] == STATUS_ERROR])
    logger.info(t('console.regime_stats_header'))
    for regime in ['PRE_START', 'WARMUP', 'DRIVE_CITY', 'DRIVE_SUBURBAN', 'DRIVE_HIGHWAY']:
        regime_df = df_clean[df_clean['REGIME'] == regime]
        count = len(regime_df)
        if count == 0:
            continue
        duration_min = count * LOG_DT / 60
        if 'DISTANCE_DELTA' in regime_df.columns:
            distance_km = regime_df['DISTANCE_DELTA'].sum()
            logger.info(t('console.regime_stats_with_km', regime=regime, count=count, min=duration_min, km=distance_km))
        else:
            logger.info(t('console.regime_stats_no_km', regime=regime, count=count, min=duration_min))
    logger.info(t('console.status_ok_count', n=ok_count))
    logger.info(t('console.status_warn_count', n=warn_count))
    logger.info(t('console.status_error_count', n=err_count))


def _log_format_skipped(fmt: str, exc: Optional[BaseException]) -> None:
    """Логирует пропуск формата из-за отсутствующего пакета (с pip-командой)."""
    pkg = getattr(exc, 'package', None) or getattr(exc, 'name', None) or 'неизвестен'
    detail = t('console.dep_missing_pkg', pkg=pkg, cmd=pip_install_hint(pkg))
    logger.error(t('console.format_skipped', fmt=fmt, detail=detail))


def _generate_csv_reports(
    df_full: pd.DataFrame,
    df_clean: pd.DataFrame,
    output_dir: Path,
    base_filename: str,
) -> None:
    """Формирует все дополнительные CSV файлы: джокер, профиль скорости, группы и хронологию детонации, пропуски."""
    save_joker_events(df_full, output_dir, base_filename)
    create_speed_profile(df_clean, output_dir, base_filename)
    kg_result = save_knock_groups(df_clean, output_dir, base_filename)
    if kg_result is not None:
        kdf_groups, group_map = kg_result
        save_knock_timeline(df_clean, output_dir, base_filename, kdf=kdf_groups, group_map=group_map)
    else:
        save_knock_timeline(df_clean, output_dir, base_filename)
    save_misfire_timeline(df_clean, output_dir, base_filename)


def _generate_png_charts(df_clean: pd.DataFrame, output_dir: Path, base_filename: str) -> None:
    """Генерирует все PNG графики через модуль build_png; ошибки логирует без прерывания."""
    if _build_png is None:
        _log_format_skipped('PNG', _png_missing)
        return
    try:
        _build_png.plot_time_series(df_clean, output_dir, base_filename)
        _build_png.plot_knock_heatmap(df_clean, output_dir, base_filename)
        _build_png.plot_ltft_stft_hist(df_clean, output_dir, base_filename)
        _build_png.plot_correlation_matrix(df_clean, output_dir, base_filename)
        _build_png.plot_fuel_correction_timeline(df_clean, output_dir, base_filename)
        _build_png.plot_o2_sensors_timeline(df_clean, output_dir, base_filename)
        _build_png.plot_temperature_profiles(df_clean, output_dir, base_filename)
        _build_png.plot_engine_load_profile(df_clean, output_dir, base_filename)
        _build_png.plot_maf_analysis(df_clean, output_dir, base_filename)
        _build_png.plot_misfire_analysis(df_clean, output_dir, base_filename)
        _build_png.create_summary_dashboard(df_clean, output_dir, base_filename)
    except (ValueError, RuntimeError, OSError) as viz_e:
        logger.error(t('console.viz_error', e=viz_e), exc_info=True)


def _generate_geojson(file_path: str, output_dir: Optional[Path] = None) -> Optional[Path]:
    """Генерирует GeoJSON маршрута; возвращает путь к файлу или None при ошибке."""
    try:
        out = Path(output_dir) / f'{Path(file_path).stem}.geojson' if output_dir else None
        return generate_geojson(file_path, output_geojson=out)
    except (OSError, ValueError) as geo_e:
        logger.error(t('console.geojson_create_error', e=geo_e), exc_info=True)
        return None


def _generate_html_report(
    output_dir: Path,
    base_filename: str,
    no_html: bool,
    no_plot: bool,
    no_csv: bool,
    no_png: bool,
    df_clean: pd.DataFrame,
    geojson_path: Optional[Path],
) -> None:
    """Создаёт HTML отчёт или отдельные Plotly-страницы; пропускает, если оба флага no_html и no_plot."""
    if no_html and no_plot:
        return
    try:
        map_geojson = geojson_path if geojson_path is not None else None
        create_report_html(output_dir, base_filename, no_plot=no_plot, no_html=no_html,
                           no_csv=no_csv, no_png=no_png, df_clean=df_clean,
                           geojson_path=map_geojson)
    except (ModuleNotFoundError, MissingDependencyError) as dep_e:
        _log_format_skipped('HTML', dep_e)
    except (OSError, RuntimeError) as report_e:
        logger.error(t('console.html_report_error', e=report_e), exc_info=True)


def _generate_pdf_report(output_dir: Path, base_filename: str, no_pdf: bool, no_png: bool) -> None:
    """Создаёт PDF отчёт; пропускает при no_pdf=True."""
    if no_pdf:
        return
    try:
        create_pdf_report(output_dir, base_filename, no_png=no_png)
    except (ModuleNotFoundError, MissingDependencyError) as dep_e:
        _log_format_skipped('PDF', dep_e)
    except (OSError, RuntimeError) as pdf_e:
        logger.error(t('console.pdf_report_error', e=pdf_e), exc_info=True)


def _run_compare(
    directory: Path,
    no_png: bool = False,
    no_html: bool = False,
    no_pdf: bool = False,
    no_xls: bool = False,
) -> None:
    """Строит сравнительный отчёт по всем *_metrics.csv в директории."""
    logger.info('\n' + '='*60)
    logger.info(t('console.compare_start'))
    try:
        vals_df, stats_df = load_trips(directory)
        if vals_df.empty or len(vals_df) < 2:
            logger.info(t('console.compare_skip_few'))
            return

        # CSV генерируется всегда (аналогично _metrics.csv)
        create_compare_csv(directory, vals_df, stats_df)
        profiles = load_profiles(directory)
        build_profiles_csv(directory, profiles)

        png_paths: dict[str, Path] = {}
        if not no_png:
            if generate_all_plots is None:
                _log_format_skipped('PNG (сравнение)', _cmp_png_missing)
            else:
                png_paths = generate_all_plots(vals_df, stats_df, directory)

        if not no_html:
            try:
                create_compare_html(directory, vals_df, stats_df, png_paths)
            except (ModuleNotFoundError, MissingDependencyError) as dep_e:
                _log_format_skipped('HTML (сравнение)', dep_e)

        if not no_pdf:
            try:
                create_compare_pdf(directory, vals_df, stats_df, png_paths)
            except (ModuleNotFoundError, MissingDependencyError) as dep_e:
                _log_format_skipped('PDF (сравнение)', dep_e)

        if not no_xls:
            try:
                create_compare_xls(directory, vals_df, stats_df)
            except (ModuleNotFoundError, MissingDependencyError) as dep_e:
                _log_format_skipped('XLS (сравнение)', dep_e)

        # PNG встроены в HTML/PDF как base64 — временные файлы больше не нужны.
        # Удаляем их, если хотя бы один отчёт был сформирован (иначе они единственный вывод).
        if png_paths and not (no_html and no_pdf):
            removed = 0
            for p in png_paths.values():
                try:
                    p.unlink()
                    removed += 1
                except OSError:
                    pass
            if removed:
                logger.info(t('console.compare_png_removed', n=removed))

        logger.info(t('console.compare_done', n=len(vals_df)))
    except (OSError, ValueError, RuntimeError) as cmp_e:
        logger.error(f'Ошибка сравнения поездок: {cmp_e}', exc_info=True)


def process_file(
    file_path: str | Path,
    fuel_type: str = 'АИ-95',
    temp_outside: Optional[float] = None,
    no_csv: bool = False,
    no_png: bool = False,
    no_plot: bool = False,
    no_html: bool = False,
    no_pdf: bool = False,
    no_geojson: bool = False,
    no_map: bool = False,
    do_continue: bool = False,
    output_dir: Optional[str | Path] = None,
) -> bool:
    """Обрабатывает один CSV файл: анализ данных + генерация отчётов (CSV/PNG/HTML/PDF/GeoJSON).

    Args:
        file_path: Путь к CSV файлу с OBD-II данными.
        fuel_type: Тип топлива (по умолчанию 'АИ-95').
        temp_outside: Температура снаружи (°C). None — автоопределение.
        no_csv: Не создавать дополнительные CSV файлы (профиль, джокер, детонация, пропуски). Метрики создаются всегда.
        no_png: Не создавать PNG графики.
        no_plot: Не генерировать интерактивные Plotly-графики (HTML отчёт будет использовать PNG).
        no_html: Не создавать единый HTML отчёт (вместо него — отдельные HTML-страницы с плотами, лимит записей x3).
        no_pdf: Не создавать PDF отчёт.
        no_geojson: Не создавать GeoJSON файл с маршрутом.
        no_map: Не создавать вкладку «Карта» в HTML отчёте.
        do_continue: Пропускать уже обработанные файлы (есть _metrics.csv).
        output_dir: Папка для результатов. None — рядом с исходным CSV (как в CLI).

    Returns:
        True при успехе, False при ошибке.
    """
    file_path = Path(file_path)
    if not file_path.exists():
        logger.error(t('console.file_not_found', path=file_path))
        return False

    # Папка результатов: по умолчанию рядом с исходным CSV; в GUI — отдельная
    output_dir = Path(output_dir) if output_dir else file_path.parent
    output_dir.mkdir(parents=True, exist_ok=True)

    # --- Режим -continue: пропуск уже обработанных файлов ---
    if do_continue:
        _out_dir  = output_dir
        _base     = file_path.stem
        _metrics  = _out_dir / f'{_base}_metrics.csv'
        if _metrics.exists():
            logger.info(t('console.continue_skipped', name=file_path.name))
            return True
        # Метрик нет — запускаем анализ, но пропускаем уже готовые отчёты
        _pdf_done  = (_out_dir / f'{_base}_report.pdf').exists()
        _html_done = (_out_dir / f'{_base}_report.html').exists()
        if _pdf_done and _html_done:
            no_png = True
        if _pdf_done:
            no_pdf = True
        if _html_done:
            no_html = True

    # Лог-файл рядом с результатами: {имя_файла}.log, перезаписывается при каждом запуске
    _log_path = output_dir / f'{file_path.stem}.log'
    _fh = logging.FileHandler(_log_path, encoding='utf-8', mode='w')
    _fh.setLevel(logging.DEBUG)
    _fh.setFormatter(logging.Formatter('%(asctime)s %(levelname)-8s %(name)s: %(message)s', datefmt='%H:%M:%S'))
    _root_logger.addHandler(_fh)

    logger.info('\n' + '='*60)
    logger.info(t('console.analysis_header', name=file_path.name))
    logger.info(t('console.fuel_type', fuel_type=fuel_type))
    if temp_outside is not None:
        logger.info(t('console.outside_temp', temp=temp_outside))
    try:
        result = analyze_data(file_path, fuel_type, temp_outside)
        if result[0] is None:
            return False

        metrics, df_clean, knock_analysis, df_full = result
        metrics_df = pd.DataFrame(metrics)
        base_filename = file_path.stem

        # Метрики сохраняются всегда (нужны для PDF и HTML отчётов)
        metrics_file = output_dir / f'{base_filename}_metrics.csv'
        metrics_df.to_csv(metrics_file, index=False, encoding='utf-8-sig')
        logger.info(t('console.metrics_saved', path=metrics_file))

        # Дополнительные CSV файлы (профиль, джокер, детонация, пропуски)
        if not no_csv:
            _generate_csv_reports(df_full, df_clean, output_dir, base_filename)

        # Сохранение графиков в PNG файлы
        if not no_png:
            _generate_png_charts(df_clean, output_dir, base_filename)

        # Генерация GeoJSON маршрута (до HTML, чтобы встроить карту в отчёт)
        geojson_path = None
        if not no_geojson:
            geojson_path = _generate_geojson(file_path, output_dir)

        # Создание HTML отчёта / отдельных плотов
        map_geojson = geojson_path if not no_map else None
        _generate_html_report(output_dir, base_filename, no_html, no_plot, no_csv, no_png, df_clean, map_geojson)

        # Создание PDF отчёта
        _generate_pdf_report(output_dir, base_filename, no_pdf, no_png)

        # PNG встроены в HTML (base64) и в PDF — временные файлы больше не нужны.
        # Удаляем, если сформированы оба отчёта; иначе оставляем как единственный вывод.
        if not no_png and not no_pdf and not no_html:
            _cleanup_temp_pngs(output_dir, base_filename)

        _print_processing_stats(metrics_df, df_clean)
        return True
    except (OSError, ValueError, RuntimeError, pd.errors.ParserError) as e:
        logger.error(t('console.file_process_error', name=file_path.name, e=e), exc_info=True)
        return False
    finally:
        _root_logger.removeHandler(_fh)
        _fh.close()


def find_csv_files(directory: str | Path) -> list[Path]:
    """Находит исходные CSV файлы с OBD-II данными, исключая файлы отчётов.

    Args:
        directory: Путь к директории для сканирования.

    Returns:
        Отсортированный список Path исходных CSV файлов.
    """
    dir_path = Path(directory)
    if not dir_path.exists():
        logger.error(t('console.dir_not_found', path=directory))
        return []

    if not dir_path.is_dir():
        logger.error(t('console.not_a_dir', path=directory))
        return []

    csv_files = []
    for file_path in dir_path.glob('*.csv'):
        if any(suffix in file_path.name for suffix in ['_metrics', '_profile', '_knock', '_misfire', '_joker', '_report']):
            continue
        csv_files.append(file_path)

    return sorted(csv_files)


def main() -> None:
    """Точка входа: парсинг аргументов CLI и запуск обработки файла/директории."""
    parser = argparse.ArgumentParser(
        description='Скрипт анализа OBD-II данных для Lada Granta FL 2022',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Примеры (порядок аргументов произвольный):
  python analyze_obd.py log_2026-01-27.csv
  python analyze_obd.py log_2026-01-27.csv -fuel АИ-95 -temp -5
  python analyze_obd.py -fuel АИ-92 -temp 10 log_2026-01-27.csv -nopng -nopdf
  python analyze_obd.py . -nocsv -fuel АИ-95 -temp -7
  python analyze_obd.py log_2026-01-27.csv -noplot -nopdf
  python analyze_obd.py log_2026-01-27.csv -nohtml
        '''
    )
    parser.add_argument('path', nargs='?', default=None,
                        help='Файл .csv или директория с логами (без аргументов запускается GUI)')
    parser.add_argument('-fuel', default='АИ-95', metavar='XX', help='Тип топлива (по умолчанию: АИ-95)')
    parser.add_argument('-temp', type=float, default=None, metavar='XXX', help='Температура снаружи (°C)')
    parser.add_argument('-lang', default='ru', metavar='CODE', help='Язык отчёта (ru, en; по умолчанию: ru)')
    parser.add_argument('-nocsv', action='store_true', help='Не формировать CSV файлы (метрики, профиль, джокер, детонация, пропуски)')
    parser.add_argument('-nopng', action='store_true', help='Не формировать PNG графики')
    parser.add_argument('-noplot', action='store_true', help='Не формировать интерактивные Plotly-графики (использовать PNG)')
    parser.add_argument('-nohtml', action='store_true', help='Не формировать единый HTML отчёт (вместо него — отдельные HTML-страницы с плотами, лимит записей x3)')
    parser.add_argument('-nopdf', action='store_true', help='Не формировать PDF отчёт')
    parser.add_argument('-nogeojson', action='store_true', help='Не формировать GeoJSON файл с маршрутом')
    parser.add_argument('-nomap', action='store_true', help='Не создавать вкладку «Карта» в HTML отчёте')
    parser.add_argument('-nocompare', action='store_true', help='Не формировать сравнительный отчёт по поездкам (только при обработке директории)')
    parser.add_argument('-noxls', action='store_true', help='Не формировать Excel-отчёт сравнения поездок')
    parser.add_argument('-continue', action='store_true', dest='do_continue',
                        help='Пропускать файлы, для которых уже создан _metrics.csv; пропускать PDF/HTML если они уже существуют')
    parser.add_argument('-verbose', action='store_true', help='Подробный вывод в консоль и лог-файл (уровень DEBUG)')

    args = parser.parse_args()

    if args.path is None:
        # В обычном пути сюда не доходим: GUI запускается до импорта модулей
        parser.error('Не указан файл или папка (без аргументов запускается GUI)')

    # Переключить консоль на DEBUG если запрошен подробный вывод
    if args.verbose:
        _console_handler.setLevel(logging.DEBUG)

    set_language(args.lang)
    logger.info(t('console.thresholds_loaded', path=_THRESHOLDS_PATH))
    path_arg = args.path
    fuel_type = args.fuel
    temp_outside = args.temp
    no_csv = args.nocsv
    no_png = args.nopng
    no_plot = args.noplot
    no_html = args.nohtml
    no_pdf = args.nopdf
    no_geojson = args.nogeojson
    no_map = args.nomap
    no_compare  = args.nocompare
    no_xls      = args.noxls
    do_continue = args.do_continue

    path_obj = Path(path_arg)

    if path_obj.is_file():
        if path_obj.suffix.lower() != '.csv':
            logger.error(t('console.file_not_found', path=path_arg))
            sys.exit(1)

        if process_file(path_obj, fuel_type, temp_outside, no_csv=no_csv, no_png=no_png, no_plot=no_plot, no_html=no_html, no_pdf=no_pdf, no_geojson=no_geojson, no_map=no_map, do_continue=do_continue):
            logger.info(t('console.analysis_done'))
        else:
            sys.exit(1)

    elif path_obj.is_dir() or path_arg in ['.', './']:
        if path_arg in ['.', './']:
            directory = Path.cwd()
        else:
            directory = path_obj.resolve()

        logger.info(t('console.searching_csv', path=directory))
        csv_files = find_csv_files(directory)

        if len(csv_files) == 0:
            logger.warning(t('console.csv_not_found_in_dir'))
            sys.exit(1)

        logger.info(t('console.csv_files_found', n=len(csv_files)))

        success_count = 0
        for csv_file in csv_files:
            if process_file(csv_file, fuel_type, temp_outside, no_csv=no_csv, no_png=no_png, no_plot=no_plot, no_html=no_html, no_pdf=no_pdf, no_geojson=no_geojson, no_map=no_map, do_continue=do_continue):
                success_count += 1

        logger.info(f'\n{"="*60}')
        logger.info(t('console.batch_done', ok=success_count, total=len(csv_files)))
        logger.info(t('console.batch_errors', n=len(csv_files) - success_count))
        logger.info(f'{"="*60}')

        if not no_compare and success_count >= 2:
            _run_compare(directory, no_png=no_png, no_html=no_html, no_pdf=no_pdf, no_xls=no_xls)

    else:
        logger.error(t('console.path_not_found', path=path_arg))
        sys.exit(1)


if __name__ == '__main__':
    main()
