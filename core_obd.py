#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Ядро анализа OBD-II данных для Lada Granta FL 2022 (ВАЗ-11182 1.6л).

Содержит:
- Константы (статусы, пороги, временные параметры)
- Вспомогательные функции (парсинг времени, фильтрация, подсчёт событий)
- Функции анализа (детонация, пропуски, топливо, температура)
- Функции определения статусов и режимов работы
"""

import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
import requests

from translation import t

logger = logging.getLogger(__name__)

# Статусы
STATUS_OK = '✅'
STATUS_WARNING = '⚠️'
STATUS_ERROR = '❌'
STATUS_NEUTRAL = '○'

# Разделитель между блоками
SEPARATOR_LINE = '---SEPARATOR---'

# === Загрузка пороговых значений из core_obd.json ===
_THRESHOLDS_PATH = Path(__file__).with_name('core_obd.json')


def _load_thresholds() -> dict[str, float | str]:
    """Загружает пороговые значения из core_obd.json."""
    if not _THRESHOLDS_PATH.exists():
        raise FileNotFoundError(
            f'Не найден файл пороговых значений: {_THRESHOLDS_PATH}\n'
            f'Создайте core_obd.json рядом со скриптом.'
        )
    with open(_THRESHOLDS_PATH, 'r', encoding='utf-8') as f:
        data = json.load(f)
    result: dict[str, float | str] = {}
    for key, val in data.items():
        if key.startswith('_'):
            continue
        if not isinstance(val, (int, float, str)):
            raise ValueError(f'Значение {key}={val!r} в {_THRESHOLDS_PATH} должно быть числом или строкой')
        result[key] = val
    return result


_cfg = _load_thresholds()

# Период выборки логов (сек)
LOG_DT: float = _cfg['LOG_DT']

# Минимальные обороты двигателя для учета в статистике
MIN_RPM_THRESHOLD: float = _cfg['MIN_RPM_THRESHOLD']

# Минимальная длительность устойчивого движения для определения конца прогрева (сек)
MIN_MOVEMENT_DURATION_SEC: float = _cfg['MIN_MOVEMENT_DURATION_SEC']

# Порог RPM для определения заглохшего двигателя
STALLED_RPM_THRESHOLD: float = _cfg['STALLED_RPM_THRESHOLD']

# Максимальная длительность серии RPM < STALLED_RPM_THRESHOLD для признания заглохом (сек)
MAX_STALLED_DURATION_SEC: float = _cfg['MAX_STALLED_DURATION_SEC']

# Максимальный интервал между событиями заглохшего двигателя в одной группе (сек)
MAX_STALLED_GROUP_GAP_SEC: float = _cfg['MAX_STALLED_GROUP_GAP_SEC']

# Максимальный интервал между событиями детонации в одной группе (сек)
MAX_KNOCK_GROUP_GAP_SEC: float = _cfg['MAX_KNOCK_GROUP_GAP_SEC']

# Перцентили для фильтрации выбросов
LTFT_PERCENTILE_LOW: float = _cfg['LTFT_PERCENTILE_LOW']
LTFT_PERCENTILE_HIGH: float = _cfg['LTFT_PERCENTILE_HIGH']
SHORT_TERM_PERCENTILE_LOW: float = _cfg['SHORT_TERM_PERCENTILE_LOW']
SHORT_TERM_PERCENTILE_HIGH: float = _cfg['SHORT_TERM_PERCENTILE_HIGH']

# === Классификация детонации по силе отскока (°) ===
KNOCK_WEAK_MAX: float = _cfg['KNOCK_WEAK_MAX']          # слабая:  1 .. WEAK_MAX
KNOCK_MEDIUM_MAX: float = _cfg['KNOCK_MEDIUM_MAX']      # средняя: WEAK_MAX+1 .. MEDIUM_MAX
KNOCK_STRONG_MIN: float = _cfg['KNOCK_STRONG_MIN']      # сильная: STRONG_MIN+

# === Пороги анализа детонаций по количеству групп ===
KNOCK_WEAK_INTERVAL_MIN: float = _cfg['KNOCK_WEAK_INTERVAL_MIN']        # интервал для слабых (мин)
KNOCK_MEDIUM_INTERVAL_MIN: float = _cfg['KNOCK_MEDIUM_INTERVAL_MIN']    # интервал для средних (мин)
KNOCK_WEAK_THRESHOLD_GOOD: float = _cfg['KNOCK_WEAK_THRESHOLD_GOOD']    # групп на интервал — норма
KNOCK_WEAK_THRESHOLD_BAD: float = _cfg['KNOCK_WEAK_THRESHOLD_BAD']      # групп на интервал — плохо
KNOCK_MEDIUM_THRESHOLD_GOOD: float = _cfg['KNOCK_MEDIUM_THRESHOLD_GOOD']  # групп на интервал — норма
KNOCK_MEDIUM_THRESHOLD_BAD: float = _cfg['KNOCK_MEDIUM_THRESHOLD_BAD']    # групп на интервал — плохо
KNOCK_STRONG_THRESHOLD_ATTENTION: float = _cfg['KNOCK_STRONG_THRESHOLD_ATTENTION']  # за поездку — внимание
KNOCK_STRONG_THRESHOLD_BAD: float = _cfg['KNOCK_STRONG_THRESHOLD_BAD']              # за поездку — плохо

# === Пороги анализа величины отскока детонации ===
KNOCK_RETARD_TOLERANCE: float = _cfg['KNOCK_RETARD_TOLERANCE']          # допуск вокруг KNOCK_STRONG_MIN
KNOCK_RETARD_MEAN_DIVISOR: float = _cfg['KNOCK_RETARD_MEAN_DIVISOR']    # делитель для порогов MEAN

# === Параметры снисходительности для слабых детонаций ===
KNOCK_MAX_RPM_REMISSION: float = _cfg['KNOCK_MAX_RPM_REMISSION']        # максимальные обороты для снисходительности
KNOCK_MAX_SPEED_REMISSION: float = _cfg['KNOCK_MAX_SPEED_REMISSION']    # максимальная скорость для снисходительности
KNOCK_MAX_RETARD_REMISSION: float = _cfg['KNOCK_MAX_RETARD_REMISSION']  # максимальный угол отскока для снисходительности
KNOCK_DURATION_REMISSION: float = _cfg['KNOCK_DURATION_REMISSION']      # максимальная длительность для снисходительности (сек)

# === Референсные линии на графиках топливных коррекций ===
CHART_FUEL_OK_LINE: float = _cfg['CHART_FUEL_OK_LINE']
CHART_FUEL_WARN_LINE: float = _cfg['CHART_FUEL_WARN_LINE']

# === Пороги топливных коррекций ===
LTFT_OK_MIN: float = _cfg['LTFT_OK_MIN']
LTFT_OK_MAX: float = _cfg['LTFT_OK_MAX']
LTFT_WARNING_MIN: float = _cfg['LTFT_WARNING_MIN']
LTFT_WARNING_MAX: float = _cfg['LTFT_WARNING_MAX']

STFT_OK_MIN: float = _cfg['STFT_OK_MIN']
STFT_OK_MAX: float = _cfg['STFT_OK_MAX']
STFT_WARNING_MIN: float = _cfg['STFT_WARNING_MIN']
STFT_WARNING_MAX: float = _cfg['STFT_WARNING_MAX']

# === Пороги температуры охлаждающей жидкости (ОЖ) ===
COOLANT_TEMP_NORMAL_MIN: float = _cfg['COOLANT_TEMP_NORMAL_MIN']
COOLANT_TEMP_NORMAL_MAX: float = _cfg['COOLANT_TEMP_NORMAL_MAX']
COOLANT_TEMP_WARNING_MIN: float = _cfg['COOLANT_TEMP_WARNING_MIN']
COOLANT_TEMP_WARNING_MAX: float = _cfg['COOLANT_TEMP_WARNING_MAX']
COOLANT_TEMP_MAX_MIN: float = _cfg['COOLANT_TEMP_MAX_MIN']    # мин. ожидаемый максимум за поездку (ниже → не прогрелся)
COOLANT_TEMP_MAX_ERROR: float = _cfg['COOLANT_TEMP_MAX_ERROR'] # если макс. за поездку превысил → перегрев

# === Пороги O2 датчика (напряжение) ===
O2_RICH_THRESHOLD: float = _cfg['O2_RICH_THRESHOLD']
O2_LEAN_THRESHOLD: float = _cfg['O2_LEAN_THRESHOLD']
O2_NORMAL_MIN: float = _cfg['O2_NORMAL_MIN']
O2_NORMAL_MAX: float = _cfg['O2_NORMAL_MAX']
O2_CROSSING_MIN_COOLANT_TEMP: float = _cfg['O2_CROSSING_MIN_COOLANT_TEMP']
O2_DK2_NORM_MIN: float = _cfg['O2_DK2_NORM_MIN']
O2_DK2_NORM_MAX: float = _cfg['O2_DK2_NORM_MAX']

# === Пороги для пропусков зажигания и детонации ===
KNOCK_COUNT_WARNING: float = _cfg['KNOCK_COUNT_WARNING']
KNOCK_INTENSITY_WARNING: float = _cfg['KNOCK_INTENSITY_WARNING']

# === Пороги для заглохов ===
STALLED_COUNT_WARMUP_WARNING: float = _cfg['STALLED_COUNT_WARMUP_WARNING']
STALLED_COUNT_OTHER_WARNING: float = _cfg['STALLED_COUNT_OTHER_WARNING']

# === Пороги: пропуски зажигания / впрыск / MAF / дроссель ===
MISFIRE_WARNING: float = _cfg['MISFIRE_WARNING']                # пропусков за поездку
INJECTION_TIME_WARNING: float = _cfg['INJECTION_TIME_WARNING']  # мс
INJECTION_TIME_ERROR: float = _cfg['INJECTION_TIME_ERROR']      # мс
MAF_MIN_ERROR: float = _cfg['MAF_MIN_ERROR']                    # г/сек
MAF_MIN_WARNING: float = _cfg['MAF_MIN_WARNING']                # г/сек
MAF_MAX_WARNING: float = _cfg['MAF_MAX_WARNING']                # г/сек
THROTTLE_MIN_WARNING: float = _cfg['THROTTLE_MIN_WARNING']      # % (при движении)
THROTTLE_MAX_MIN: float = _cfg['THROTTLE_MAX_MIN']              # % мин. ожидаемый максимум за поездку
THROTTLE_MAX_HIGH: float = _cfg['THROTTLE_MAX_HIGH']            # % если максимум выше → поездка с высокой нагрузкой

# === Анализ катализатора: условия отбора окон ДК1/ДК2 ===
CAT_MIN_WINDOWS: int = int(_cfg['CAT_MIN_WINDOWS'])         # мин. кол-во окон для диагноза
CAT_WINDOW_SIZE: int = int(_cfg['CAT_WINDOW_SIZE'])         # сэмплов в скользящем окне
CAT_MIN_STD1: float = _cfg['CAT_MIN_STD1']                  # мин. СКО сигнала ДК1 (В); ниже — окно неинформативно
CAT_COOLANT_MIN: float = _cfg['CAT_COOLANT_MIN']            # °C
CAT_RPM_MIN: float = _cfg['CAT_RPM_MIN']                    # об/мин
CAT_SPEED_MIN: float = _cfg['CAT_SPEED_MIN']                # км/ч
CAT_MAF_MIN: float = _cfg['CAT_MAF_MIN']                    # г/сек; ниже — холостой ход или отсечка топлива
CAT_MAF_MAX_STD: float = _cfg['CAT_MAF_MAX_STD']            # г/сек; выше — переходный режим, окно исключается

# === Анализ катализатора: оценка состояния ===
CAT_AGING_BAD_VALUE: float = _cfg['CAT_AGING_BAD_VALUE']    # направление индекса: 1 = «мёртв при →1»
CAT_AGING_WARN: float = _cfg['CAT_AGING_WARN']              # порог индекса (0–1)
CAT_AGING_ERR: float = _cfg['CAT_AGING_ERR']                # порог индекса (0–1)

# Медиана ниже PHYSICAL_GOOD_MAX → кат живой, пороги из перцентилей выборки
CAT_PHYSICAL_GOOD_MAX_RATIO: float = _cfg['CAT_PHYSICAL_GOOD_MAX_RATIO']
CAT_PHYSICAL_GOOD_MAX_CORR: float = _cfg['CAT_PHYSICAL_GOOD_MAX_CORR']
# Жёсткие пороги (медиана выше PHYSICAL_GOOD_MAX): ниже GOOD = OK | выше WARN = WARN | выше обоих = ERR
CAT_HARD_GOOD_RATIO: float = _cfg['CAT_HARD_GOOD_RATIO']
CAT_HARD_GOOD_CORR: float = _cfg['CAT_HARD_GOOD_CORR']
CAT_HARD_WARN_RATIO: float = _cfg['CAT_HARD_WARN_RATIO']
CAT_HARD_WARN_CORR: float = _cfg['CAT_HARD_WARN_CORR']
# Пороги СКО ДК2 для режима «только ДК2» (широкополосный ДК1)
CAT_DK2_GOOD_STD: float = _cfg['CAT_DK2_GOOD_STD']         # СКО ниже → окно GOOD
CAT_DK2_WARN_STD: float = _cfg['CAT_DK2_WARN_STD']         # СКО выше → окно BAD

# === Пороги анализа системы охлаждения ===
COOLANT_FAN_ON_TEMP: float = _cfg['COOLANT_FAN_ON_TEMP']
COOLANT_FAN_OFF_TEMP: float = _cfg['COOLANT_FAN_OFF_TEMP']
COOLANT_FAN_SPEED_THRESHOLD: float = _cfg['COOLANT_FAN_SPEED_THRESHOLD']
COOLANT_WARMUP_MIN_TEMP: float = _cfg['COOLANT_WARMUP_MIN_TEMP']
COOLANT_WARMUP_TARGET_TEMP: float = _cfg['COOLANT_WARMUP_TARGET_TEMP']
COOLANT_WARMUP_MIN_RATE_GOOD: float = _cfg['COOLANT_WARMUP_MIN_RATE_GOOD']  # °C/сек
COOLANT_WARMUP_MIN_RATE_WARN: float = _cfg['COOLANT_WARMUP_MIN_RATE_WARN']  # °C/сек
COOLANT_WARMUP_MAX_TIME_MIN: float = _cfg['COOLANT_WARMUP_MAX_TIME_MIN']
COOLANT_WARMUP_COLD_START_MAX_TEMP: float = _cfg['COOLANT_WARMUP_COLD_START_MAX_TEMP']
COOLANT_WARMUP_MIN_DURATION_MIN: float = _cfg['COOLANT_WARMUP_MIN_DURATION_MIN']
COOLANT_THERMOSTAT_OPEN_TEMP: float = _cfg['COOLANT_THERMOSTAT_OPEN_TEMP']
COOLANT_THERMOSTAT_MIN_ANALYSIS_SEC: float = _cfg['COOLANT_THERMOSTAT_MIN_ANALYSIS_SEC']
COOLANT_THERMOSTAT_WINDOW_SEC: float = _cfg['COOLANT_THERMOSTAT_WINDOW_SEC']
COOLANT_THERMOSTAT_STABLE_TEMP_MIN: float = _cfg['COOLANT_THERMOSTAT_STABLE_TEMP_MIN']
COOLANT_THERMOSTAT_STABLE_TEMP_MAX: float = _cfg['COOLANT_THERMOSTAT_STABLE_TEMP_MAX']
COOLANT_THERMOSTAT_CHECK_SPEED_MIN: float = _cfg['COOLANT_THERMOSTAT_CHECK_SPEED_MIN']
COOLANT_THERMOSTAT_COOLING_RATE_MIN: float = _cfg['COOLANT_THERMOSTAT_COOLING_RATE_MIN']  # °C/сек
COOLANT_OVERHEAT_WARNING_TEMP: float = _cfg['COOLANT_OVERHEAT_WARNING_TEMP']
COOLANT_OVERHEAT_ERROR_TEMP: float = _cfg['COOLANT_OVERHEAT_ERROR_TEMP']
COOLANT_OVERHEAT_MIN_DURATION_SEC: float = _cfg['COOLANT_OVERHEAT_MIN_DURATION_SEC']

# === Параметры генерации GeoJSON маршрута ===
# Расстояние (м) для объединения почти идентичных GPS-точек (стоянка, светофор)
GEOJSON_DUPLICATE_DIST: float = _cfg['GEOJSON_DUPLICATE_DIST']
# Минимальное расстояние между итоговыми точками маршрута (м)
GEOJSON_MIN_DISTANCE: float = _cfg['GEOJSON_MIN_DISTANCE']
# Минимально допустимый внутренний угол в вершине N2 (°); ниже — GPS-выброс
GEOJSON_MAX_TURN_ANGLE: float = _cfg['GEOJSON_MAX_TURN_ANGLE']

# === Цветовые схемы статусов ===
# Фоновые цвета ячеек (PNG heatmap, Plotly, XLS, PDF)
STATUS_COLOR_NO_DATA: str = str(_cfg['STATUS_COLOR_NO_DATA'])
STATUS_COLOR_NEUTRAL: str = str(_cfg['STATUS_COLOR_NEUTRAL'])
STATUS_COLOR_OK:      str = str(_cfg['STATUS_COLOR_OK'])
STATUS_COLOR_WARNING: str = str(_cfg['STATUS_COLOR_WARNING'])
STATUS_COLOR_ERROR:   str = str(_cfg['STATUS_COLOR_ERROR'])
# Цвета текста статусов (HTML CSS, XLS)
STATUS_TEXT_OK:      str = str(_cfg['STATUS_TEXT_OK'])
STATUS_TEXT_WARNING: str = str(_cfg['STATUS_TEXT_WARNING'])
STATUS_TEXT_ERROR:   str = str(_cfg['STATUS_TEXT_ERROR'])
STATUS_TEXT_NEUTRAL: str = str(_cfg['STATUS_TEXT_NEUTRAL'])

# PLOTLY доступность (флаг импортируется в HTML-модуле)
try:
    __import__('plotly')
    PLOTLY_AVAILABLE = True
except ImportError:
    PLOTLY_AVAILABLE = False


# ============================================================================
# === Загрузка маппинга колонок ===
# ============================================================================

COLUMN_MAPPING_PATH = Path(__file__).with_name('analyze_obd.json')
def load_column_mapping() -> dict[str, list[str]]:
    """Загружает маппинг колонок из analyze_obd.json.

    Returns:
        Словарь {целевое_имя: [варианты_исходных_колонок]} или {} при ошибке.
    """
    if not COLUMN_MAPPING_PATH.exists():
        logger.warning(t('console.column_mapping_missing', path=COLUMN_MAPPING_PATH))
        return {}
    try:
        with open(COLUMN_MAPPING_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        logger.error(t('console.column_mapping_error', path=COLUMN_MAPPING_PATH, e=e))
        return {}
    mapping = {k: v for k, v in data.items() if isinstance(v, list)}
    logger.info(t('console.column_mapping_loaded', path=COLUMN_MAPPING_PATH))
    return mapping

# ============================================================================
# Утилиты для работы с метриками
# ============================================================================

def get_metric_val(metrics_df: pd.DataFrame, code: str, default: str = 'N/A') -> str:
    """Извлекает значение метрики по коду из DataFrame.

    Args:
        metrics_df: DataFrame с колонками CODE, VAL, STAT.
        code: Код метрики для поиска.
        default: Значение по умолчанию, если метрика не найдена.

    Returns:
        Строковое значение метрики или default.
    """
    if code in metrics_df['CODE'].values:
        return str(metrics_df.loc[metrics_df['CODE'] == code, 'VAL'].iloc[0])
    return default


def get_metric_stat(metrics_df: pd.DataFrame, code: str, default: str = STATUS_NEUTRAL, as_text: bool = False) -> str:
    """Извлекает статус метрики по коду из DataFrame.

    Args:
        metrics_df: DataFrame с колонками CODE, VAL, STAT.
        code: Код метрики для поиска.
        default: Значение по умолчанию, если метрика не найдена.
        as_text: Если True, конвертирует эмодзи в текст (OK/WARN/ERR).

    Returns:
        Статус метрики (эмодзи или текст) или default.
    """
    if code in metrics_df['CODE'].values:
        stat = str(metrics_df.loc[metrics_df['CODE'] == code, 'STAT'].iloc[0])
    else:
        stat = default

    if as_text:
        stat_map = {'✅': 'OK', '⚠️': 'WARN', '❌': 'ERR', '○': ''}
        return stat_map.get(stat, stat)
    return stat


def get_time_axis_minutes(df: pd.DataFrame) -> np.ndarray:
    """Генерирует временную ось в минутах для графиков.

    Args:
        df: DataFrame с данными.

    Returns:
        Массив времени в минутах от начала записи.
    """
    return np.arange(len(df)) * LOG_DT / 60.0


# ============================================================================
# Вспомогательные функции парсинга и фильтрации
# ============================================================================

def group_events_by_time(time_sec: pd.Series, max_gap_sec: float) -> list[tuple[int, int]]:
    """Группирует последовательные события по временной близости.

    Args:
        time_sec: Series с временем в секундах (индексация 0..N-1).
        max_gap_sec: Максимальный разрыв между событиями в одной группе.

    Returns:
        Список кортежей (start_idx, end_idx) для каждой группы.
    """
    if len(time_sec) == 0:
        return []
    arr = time_sec.values
    breaks = np.where(np.diff(arr) > max_gap_sec)[0] + 1
    starts = np.concatenate([[0], breaks])
    ends = np.concatenate([breaks - 1, [len(arr) - 1]])
    return list(zip(starts.tolist(), ends.tolist()))

def _parse_time_to_seconds(time_str: str) -> Optional[float]:
    """Преобразует строку времени HH:MM:SS.fff в секунды от начала дня.

    Args:
        time_str: Строка времени 'HH:MM:SS.fff'. Миллисекунды опциональны.

    Returns:
        Секунды от начала дня или None при ошибке парсинга.
    """
    for fmt in ('%H:%M:%S.%f', '%H:%M:%S'):
        try:
            dt = datetime.strptime(time_str, fmt)
            return dt.hour * 3600 + dt.minute * 60 + dt.second + dt.microsecond / 1_000_000
        except ValueError:
            continue
    return None


def parse_time_to_seconds_vectorized(series: pd.Series) -> pd.Series:
    """Векторизованное преобразование времени HH:MM:SS.fff в секунды для pandas Series.

    Args:
        series: Series со строками времени. Может содержать NaN.

    Returns:
        Series с секундами от начала дня. NaN для невалидных записей.
    """
    def _parse(t: object) -> float:
        if pd.isna(t):
            return np.nan
        try:
            parts = str(t).split(':')
            hours = int(parts[0])
            minutes = int(parts[1])
            sec_parts = parts[2].split('.')
            seconds = int(sec_parts[0])
            milliseconds = int(sec_parts[1]) if len(sec_parts) > 1 else 0
            return hours * 3600 + minutes * 60 + seconds + milliseconds / 1000.0
        except (ValueError, IndexError, AttributeError):
            return np.nan
    return series.apply(_parse)


def filter_warmup_startup(df: pd.DataFrame) -> pd.DataFrame:
    """Фильтрует начальную фазу запуска двигателя с низкими оборотами.

    Удаляет записи из начала WARMUP с RPM < MIN_RPM_THRESHOLD,
    чтобы предотвратить ложную детекцию заглохов при запуске.

    Args:
        df: DataFrame с колонками 'REGIME', 'RPM', 'TIME'.

    Returns:
        Отфильтрованный DataFrame. Если колонки отсутствуют — исходный без изменений.
    """
    if 'REGIME' not in df.columns or 'RPM' not in df.columns or 'TIME' not in df.columns:
        return df

    df_copy = df.copy()

    # Находим первую запись WARMUP
    warmup_mask = df_copy['REGIME'] == 'WARMUP'
    if not warmup_mask.any():
        return df_copy

    first_warmup_idx = df_copy[warmup_mask].index[0]

    # Ищем первое появление RPM >= MIN_RPM_THRESHOLD в WARMUP
    warmup_section = df_copy.loc[first_warmup_idx:]
    stable_rpm_mask = (warmup_section['REGIME'] == 'WARMUP') & (warmup_section['RPM'] >= MIN_RPM_THRESHOLD)

    if not stable_rpm_mask.any():
        return df_copy

    # Индекс первого стабильного RPM в WARMUP
    first_stable_idx = warmup_section[stable_rpm_mask].index[0]

    # Исключаем все записи WARMUP до первого стабильного RPM
    return df_copy.loc[first_stable_idx:]


def _validate_stalled_group(
    group_start: int,
    group_end: int,
    joker_events: pd.DataFrame,
    df_filtered: pd.DataFrame,
) -> bool:
    """Проверяет, является ли группа заглохов допустимым кратковременным эпизодом.

    Возвращает False, если длительность группы превышает MAX_STALLED_DURATION_SEC
    или если после группы нет восстановления RPM (конец поездки/заглушение).
    """
    group_start_time = joker_events.loc[group_start, 'TIME_SEC']
    group_end_time = joker_events.loc[group_end, 'TIME_SEC']
    group_duration = group_end_time - group_start_time

    if group_duration >= MAX_STALLED_DURATION_SEC:
        return False

    max_original_idx = joker_events.loc[group_end, 'original_index']
    has_recovery = (df_filtered.loc[max_original_idx + 1:, 'RPM'] >= STALLED_RPM_THRESHOLD).any()

    if not has_recovery:
        return False

    return True


def filter_stalled_events(df: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """Фильтрует события заглохов (RPM < STALLED_RPM_THRESHOLD).

    Группирует события по времени (разрыв <= MAX_STALLED_GROUP_GAP_SEC),
    исключает намеренные остановки (длительность >= MAX_STALLED_DURATION_SEC),
    режим PRE_START, и заглушение двигателя в конце поездки.

    Args:
        df: DataFrame с колонками 'REGIME', 'RPM', 'TIME'.

    Returns:
        Кортеж (filtered_df, valid_groups_count):
        - filtered_df: DataFrame с валидными событиями заглохов
        - valid_groups_count: Количество валидных групп заглохов
    """
    empty_result = (pd.DataFrame(), 0)

    if 'RPM' not in df.columns or 'TIME' not in df.columns or 'REGIME' not in df.columns:
        return empty_result

    # Фильтруем начальный запуск WARMUP
    df_filtered = filter_warmup_startup(df)

    # Находим джокер события (RPM < STALLED_RPM_THRESHOLD, исключая PRE_START)
    joker_mask = (df_filtered['REGIME'] != 'PRE_START') & (df_filtered['RPM'] < STALLED_RPM_THRESHOLD)
    joker_events = df_filtered[joker_mask].copy()

    if len(joker_events) == 0:
        return empty_result

    # Парсим время
    joker_events['TIME_SEC'] = parse_time_to_seconds_vectorized(joker_events['TIME'])
    joker_events = joker_events.dropna(subset=['TIME_SEC'])

    if len(joker_events) == 0:
        return empty_result

    # Сбрасываем индекс для группировки, но сохраняем исходный
    joker_events = joker_events.reset_index().rename(columns={'index': 'original_index'})

    # Группируем события
    groups = group_events_by_time(joker_events['TIME_SEC'], MAX_STALLED_GROUP_GAP_SEC)

    # Фильтруем группы: исключаем намеренные остановки и заглушения в конце поездки
    valid_indices: list[int] = []
    valid_groups_count = 0

    for group_start, group_end in groups:
        if not _validate_stalled_group(group_start, group_end, joker_events, df_filtered):
            continue

        # Группа валидна
        valid_indices.extend(range(group_start, group_end + 1))
        valid_groups_count += 1

    if len(valid_indices) == 0:
        return empty_result

    filtered_events = joker_events.iloc[valid_indices].copy()
    return filtered_events, valid_groups_count


def count_stalled_event_groups(df: pd.DataFrame) -> int:
    """Подсчитывает количество групп заглохших событий двигателя.

    Группирует события RPM < STALLED_RPM_THRESHOLD по времени
    (разрыв <= MAX_STALLED_GROUP_GAP_SEC), исключает намеренные остановки
    (длительность >= MAX_STALLED_DURATION_SEC), режим PRE_START, и заглушение
    двигателя в конце поездки (нет последующих записей с положительным RPM).

    Args:
        df: DataFrame с колонками 'REGIME', 'RPM', 'TIME'.

    Returns:
        Количество кратковременных эпизодов заглоха. 0 при отсутствии данных.
    """
    _, count = filter_stalled_events(df)
    return count


# ============================================================================
# Функции определения режимов работы двигателя
# ============================================================================

def detect_engine_start(df: pd.DataFrame) -> int:
    """Определяет момент запуска двигателя по первому появлению RPM > 0.

    Args:
        df: DataFrame с колонкой 'RPM'.

    Returns:
        Индекс первой записи с RPM > 0. 0 если нет колонки, len(df) если RPM всегда <= 0.
    """
    if 'RPM' not in df.columns:
        return 0

    rpm_positive = df['RPM'] > 0

    if rpm_positive.any():
        first_rpm_idx = rpm_positive.idxmax()
        return first_rpm_idx
    else:
        return len(df)


def detect_warmup_end(df: pd.DataFrame) -> int:
    """Определяет окончание прогрева по началу устойчивого движения (SPEED > 0, >= 1 сек).

    Args:
        df: DataFrame с колонкой 'SPEED'.

    Returns:
        Индекс начала движения. len(df) если нет колонки или автомобиль не двигался.
    """
    if 'SPEED' not in df.columns:
        return len(df)

    min_records = int(MIN_MOVEMENT_DURATION_SEC / LOG_DT)
    speed_pos = (df['SPEED'] > 0).astype(int)
    complete = speed_pos.rolling(min_records).sum() == min_records
    if not complete.any():
        return len(df)
    end_pos = int(complete.to_numpy().argmax())
    return end_pos - min_records + 1


# ============================================================================
# Функции работы с температурой
# ============================================================================

def _get_temperature_from_api(date_str: str, latitude: float = 55.7558,
                            longitude: float = 37.6173, timeout: int = 10) -> Optional[int]:
    """Получает среднюю температуру воздуха за день через Open-Meteo Archive API.

    Args:
        date_str: Дата в формате 'YYYY-MM-DD'.
        latitude: Широта (по умолчанию Москва).
        longitude: Долгота (по умолчанию Москва).
        timeout: Таймаут HTTP запроса в секундах.

    Returns:
        Округлённая средняя температура (°C) или None при ошибке.
    """
    try:
        url = "https://archive-api.open-meteo.com/v1/archive"
        params = {
            "latitude": latitude,
            "longitude": longitude,
            "start_date": date_str,
            "end_date": date_str,
            "daily": "temperature_2m_mean",
            "timezone": "auto"
        }

        response = requests.get(url, params=params, timeout=timeout)
        response.raise_for_status()
        data = response.json()

        if 'daily' in data and 'temperature_2m_mean' in data['daily']:
            temp = data['daily']['temperature_2m_mean'][0]
            if temp is not None:
                logger.debug(t('console.api_temp_received', temp=temp))
                return round(temp)

        return None

    except requests.exceptions.Timeout:
        logger.warning(t('console.api_timeout'))
        return None
    except requests.exceptions.RequestException as e:
        logger.error(t('console.api_error', e=e))
        return None
    except (KeyError, IndexError, ValueError) as e:
        logger.error(t('console.api_data_error', e=e))
        return None


_COORD_RE = re.compile(r'^-?\d{1,3}\.\d{4,}$')
_TIME_RE   = re.compile(r'\d{1,2}:\d{2}:\d{2}')


def find_gps_columns(df: pd.DataFrame) -> tuple[Optional[str], Optional[str]]:
    """Определяет колонки широты и долготы.

    Сначала ищет по имени (содержит 'lat'/'lon' без учёта регистра).
    Fallback: последние 2 колонки — проверяет имя + формат данных (≥4 знаков после точки).

    Returns:
        (lat_col, lon_col) — имена колонок или None.
    """
    def _is_coord(series: pd.Series) -> bool:
        sample = series.replace(0, pd.NA).dropna().head(20)
        if len(sample) < 3:
            return False
        return sample.astype(str).str.match(_COORD_RE).mean() >= 0.5

    cols = list(df.columns)
    cols_lower = {c: str(c).lower() for c in cols}

    lat_col = next((c for c in cols if 'lat' in cols_lower[c] and _is_coord(df[c])), None)
    lon_col = next((c for c in cols if 'lon' in cols_lower[c] and _is_coord(df[c])), None)

    # Fallback: последние 2 колонки
    if (lat_col is None or lon_col is None) and len(cols) >= 2:
        for c in cols[-2:]:
            cl = cols_lower[c]
            if lat_col is None and 'lat' in cl and _is_coord(df[c]):
                lat_col = c
            if lon_col is None and 'lon' in cl and _is_coord(df[c]):
                lon_col = c

    return lat_col, lon_col


def looks_like_time(series: pd.Series) -> bool:
    """Проверяет, содержит ли серия значения формата HH:MM:SS."""
    sample = series.dropna().head(20)
    if sample.empty:
        return False
    return bool(sample.astype(str).str.contains(_TIME_RE).any())


def auto_detect_temperature(df: pd.DataFrame, date_str: Optional[str] = None,
                           latitude: float = 55.7558, longitude: float = 37.6173) -> int:
    """Автоматически определяет температуру окружающей среды.

    Стратегия: 1) API Open-Meteo, 2) fallback по минимуму COOLANT_TEMP / INTAKE_TEMP.

    Args:
        df: DataFrame с 'COOLANT_TEMP' и/или 'INTAKE_TEMP'.
        date_str: Дата 'YYYY-MM-DD' для API. None — только датчики.
        latitude: Широта (по умолчанию Москва).
        longitude: Долгота (по умолчанию Москва).

    Returns:
        Округлённая температура (°C). 0 если не удалось определить.
    """
    # Попытка извлечь координаты из лога
    lat_col, lon_col = find_gps_columns(df)
    if lat_col and lon_col:
        lat_vals = df[lat_col].replace(0, pd.NA).dropna()
        lon_vals = df[lon_col].replace(0, pd.NA).dropna()
        if len(lat_vals) > 0 and len(lon_vals) > 0:
            latitude = float(lat_vals.mean())
            longitude = float(lon_vals.mean())

    # Попытка получить температуру из API
    if date_str:
        api_temp = _get_temperature_from_api(date_str, latitude, longitude)
        if api_temp is not None:
            return api_temp
        logger.warning(t('console.api_unavailable'))

    # Fallback: расчет по датчикам
    temps = []

    if 'COOLANT_TEMP' in df.columns:
        coolant_min = df['COOLANT_TEMP'].min()
        if not pd.isna(coolant_min):
            temps.append(coolant_min)

    if 'INTAKE_TEMP' in df.columns:
        intake_min = df['INTAKE_TEMP'].min()
        if not pd.isna(intake_min):
            temps.append(intake_min)

    if temps:
        detected_temp = min(temps)
        logger.info(t('console.sensor_temp_detected', temp=detected_temp))
        return round(detected_temp)
    else:
        logger.warning(t('console.sensor_temp_failed'))
        return 0


# ============================================================================
# Функции определения статусов параметров
# ============================================================================

# Словарь правил оценки статусов параметров.
# Типы: 'range' (OK/WARNING диапазоны), 'upper' (превышение порога),
#        'lower' (занижение порога), 'neutral' (всегда NEUTRAL).
_STATUS_RULES: dict[str, dict] = {
    'LTFT':               {'type': 'range', 'ok': (LTFT_OK_MIN, LTFT_OK_MAX), 'warning': (LTFT_WARNING_MIN, LTFT_WARNING_MAX)},
    'STFT':               {'type': 'range', 'ok': (STFT_OK_MIN, STFT_OK_MAX), 'warning': (STFT_WARNING_MIN, STFT_WARNING_MAX)},
    'TEMP_COOLANT_Mean':  {'type': 'range', 'ok': (COOLANT_TEMP_NORMAL_MIN, COOLANT_TEMP_NORMAL_MAX),
                           'warning': (COOLANT_TEMP_WARNING_MIN, COOLANT_TEMP_WARNING_MAX), 'skip_regimes': ('WARMUP',)},
    'TEMP_COOLANT_Max':   {'type': 'custom', 'skip_regimes': ('WARMUP',)},
    'RPM':                {'type': 'neutral'},
    'KNOCK_COUNT':        {'type': 'upper', 'zero_ok': True, 'warning': KNOCK_COUNT_WARNING},
    'KNOCK_INTENSITY':    {'type': 'upper', 'zero_ok': True, 'warning': KNOCK_INTENSITY_WARNING},
    'MISFIRE':            {'type': 'upper', 'zero_ok': True, 'warning': MISFIRE_WARNING},
    'STALLED':            {'type': 'custom'},
    'INJECTION_TIME_Max': {'type': 'upper', 'warning': INJECTION_TIME_WARNING, 'error': INJECTION_TIME_ERROR},
    'MAF_Min':            {'type': 'lower', 'error': MAF_MIN_ERROR, 'warning': MAF_MIN_WARNING},
    'MAF_Max':            {'type': 'lower', 'warning': MAF_MAX_WARNING, 'skip_regimes': ('WARMUP',)},
    'THROTTLE_Min':       {'type': 'upper', 'warning': THROTTLE_MIN_WARNING},
    'THROTTLE_Max':       {'type': 'custom', 'skip_regimes': ('WARMUP',)},
    'ACCEL':              {'type': 'neutral'},
}

# Порядок поиска ключей в _STATUS_RULES (от более специфичных к общим).
_STATUS_RULE_KEYS: list[str] = sorted(_STATUS_RULES.keys(), key=len, reverse=True)


def _evaluate_rule(rule: dict, value: float) -> str:
    """Вычисляет статус по правилу из _STATUS_RULES."""
    rtype = rule['type']

    if rtype == 'neutral':
        return STATUS_NEUTRAL

    if rtype == 'range':
        ok_lo, ok_hi = rule['ok']
        if ok_lo <= value <= ok_hi:
            return STATUS_OK
        warn_lo, warn_hi = rule['warning']
        if warn_lo <= value <= warn_hi:
            return STATUS_WARNING
        return STATUS_ERROR

    if rtype == 'upper':
        if rule.get('zero_ok') and value == 0:
            return STATUS_OK
        error_thr = rule.get('error')
        if error_thr is not None and value > error_thr:
            return STATUS_ERROR
        if value > rule['warning']:
            return STATUS_WARNING if error_thr is not None else STATUS_ERROR
        return STATUS_OK if error_thr is not None or rule.get('zero_ok') else STATUS_OK

    if rtype == 'lower':
        error_thr = rule.get('error')
        if error_thr is not None and value < error_thr:
            return STATUS_ERROR
        if value < rule['warning']:
            return STATUS_WARNING
        return STATUS_OK

    return STATUS_NEUTRAL


def _custom_status_coolant_max(value: float) -> str:
    """Статус максимальной температуры ОЖ: норм диапазон → OK, слишком низкий → WARN, перегрев → ERR."""
    if value < COOLANT_TEMP_MAX_MIN:
        return STATUS_WARNING
    if value >= COOLANT_TEMP_MAX_ERROR:
        return STATUS_ERROR
    return STATUS_OK


def _custom_status_stalled(value: float, regime: str) -> str:
    """Статус числа заглохов: 0 → OK, мало → WARN (порог зависит от режима), много → ERR."""
    threshold = STALLED_COUNT_WARMUP_WARNING if regime == 'WARMUP' else STALLED_COUNT_OTHER_WARNING
    if value == 0:
        return STATUS_OK
    return STATUS_WARNING if value <= threshold else STATUS_ERROR


def _custom_status_throttle_max(value: float) -> str:
    """Статус максимального положения дросселя: вне рабочего диапазона → NEUTRAL, иначе → OK."""
    if value < THROTTLE_MAX_MIN or value >= THROTTLE_MAX_HIGH:
        return STATUS_NEUTRAL
    return STATUS_OK


_CUSTOM_STATUS_HANDLERS = {
    'TEMP_COOLANT_Max': lambda value, _: _custom_status_coolant_max(value),
    'STALLED':          lambda value, regime: _custom_status_stalled(value, regime),
    'THROTTLE_Max':     lambda value, _: _custom_status_throttle_max(value),
}


def get_status(param: str, value: float, regime: str = 'ALL') -> str:
    """Определяет статус параметра (OK/WARNING/ERROR/NEUTRAL) по его значению и режиму.

    Args:
        param: Название параметра ('LTFT', 'TEMP_COOLANT_Mean', 'KNOCK_COUNT' и т.д.).
        value: Значение параметра.
        regime: Режим работы двигателя. По умолчанию 'ALL'.

    Returns:
        Один из STATUS_OK / STATUS_WARNING / STATUS_ERROR / STATUS_NEUTRAL.
    """
    if regime == 'PRE_START' or pd.isna(value):
        return STATUS_NEUTRAL

    # Поиск подходящего правила (ключ должен входить в param)
    for key in _STATUS_RULE_KEYS:
        if key in param:
            rule = _STATUS_RULES[key]
            if regime in rule.get('skip_regimes', ()):
                return STATUS_NEUTRAL
            if rule['type'] != 'custom':
                return _evaluate_rule(rule, value)
            handler = _CUSTOM_STATUS_HANDLERS.get(key)
            if handler:
                return handler(value, regime)

    return STATUS_NEUTRAL


# ============================================================================
# Функции построения метрик
# ============================================================================

def build_percentile_metrics(
    regime_code: str, regime_desc: str, values: pd.Series,
    metric_code: str, metric_label: str, unit: str,
    fmt: str = '.2f',
    p_low: float = SHORT_TERM_PERCENTILE_LOW,
    p_high: float = SHORT_TERM_PERCENTILE_HIGH,
    zero_skip_percentile: bool = False,
    status_param: str | None = None,
) -> list[dict]:
    """Строит метрики Mean/Min(перцентиль)/Max(перцентиль) для числового ряда.

    Args:
        regime_code: Код режима ('ALL', 'DRIVE_CITY' и т.д.).
        regime_desc: Описание режима для пользователя.
        values: Series значений (уже без NaN).
        metric_code: Код метрики для CODE поля ('LTFT', 'MAF' и т.д.).
        metric_label: Человекочитаемое название для DESC поля.
        unit: Единица измерения.
        fmt: Формат числа (по умолчанию '.2f').
        p_low: Нижний перцентиль (по умолчанию 2.5%).
        p_high: Верхний перцентиль (по умолчанию 97.5%).
        zero_skip_percentile: Если True и raw min/max == 0, использовать 0.0 вместо перцентиля.
        status_param: Имя параметра для get_status(). None → STATUS_NEUTRAL для Min/Max.

    Returns:
        Список словарей метрик (Mean, Min, Max). Пустой если values пуст.
    """
    if len(values) == 0:
        return []

    result: list[dict] = []

    # Mean
    mean_val = values.mean()
    mean_status = get_status(status_param, mean_val, regime_code) if status_param else STATUS_NEUTRAL
    result.append({
        'CODE': f'{regime_code}_{metric_code}_Mean',
        'DESC': f'{regime_desc}: {metric_label} {t("stat.mean")} ({unit})',
        'VAL': f'{mean_val:{fmt}}',
        'STAT': mean_status,
    })

    # Min (перцентиль)
    raw_min = values.min()
    raw_max = values.max()
    p_low_pct = p_low * 100
    p_high_pct = p_high * 100

    if zero_skip_percentile and raw_min == 0:
        val_min = 0.0
    else:
        val_min = values.quantile(p_low)

    if zero_skip_percentile and raw_max == 0:
        val_max = 0.0
    else:
        val_max = values.quantile(p_high)

    min_status = get_status(f'{status_param}_Min', val_min, regime_code) if status_param else STATUS_NEUTRAL
    max_status = get_status(f'{status_param}_Max', val_max, regime_code) if status_param else STATUS_NEUTRAL

    p_low_label = f'{int(p_low_pct)}' if p_low_pct == int(p_low_pct) else f'{p_low_pct:.1f}'
    p_high_label = f'{int(p_high_pct)}' if p_high_pct == int(p_high_pct) else f'{p_high_pct:.1f}'

    result.append({
        'CODE': f'{regime_code}_{metric_code}_Min',
        'DESC': f'{regime_desc}: {metric_label} {p_low_label}% {t("stat.percentile")} ({unit})',
        'VAL': f'{val_min:{fmt}}',
        'STAT': min_status,
    })
    result.append({
        'CODE': f'{regime_code}_{metric_code}_Max',
        'DESC': f'{regime_desc}: {metric_label} {p_high_label}% {t("stat.percentile")} ({unit})',
        'VAL': f'{val_max:{fmt}}',
        'STAT': max_status,
    })

    return result


def build_stat_metrics(
    regime_code: str, regime_desc: str, values: pd.Series,
    metric_code: str, metric_label: str, unit: str,
    fmt: str = '.1f',
    stats: tuple[str, ...] = ('mean', 'min', 'max'),
    status_param: str | None = None,
    status_stats: tuple[str, ...] = (),
) -> list[dict]:
    """Строит метрики Mean/Min/Max (без перцентилей) для числового ряда.

    Args:
        regime_code: Код режима.
        regime_desc: Описание режима.
        values: Series значений (уже без NaN).
        metric_code: Код метрики для CODE поля.
        metric_label: Человекочитаемое название.
        unit: Единица измерения.
        fmt: Формат числа (по умолчанию '.1f').
        stats: Какие статистики включать ('mean', 'min', 'max').
        status_param: Базовое имя параметра для get_status(). None → NEUTRAL.
        status_stats: Для каких stats вызывать get_status (например ('mean', 'max')).

    Returns:
        Список словарей метрик. Пустой если values пуст.
    """
    if len(values) == 0:
        return []

    result: list[dict] = []
    stat_codes = {'mean': 'Mean', 'min': 'Min', 'max': 'Max'}
    stat_funcs = {'mean': values.mean, 'min': values.min, 'max': values.max}

    for stat in stats:
        label_code = stat_codes[stat]
        val = stat_funcs[stat]()
        if stat in status_stats and status_param:
            status = get_status(f'{status_param}_{label_code}', val, regime_code)
        else:
            status = STATUS_NEUTRAL
        result.append({
            'CODE': f'{regime_code}_{metric_code}_{label_code}',
            'DESC': f'{regime_desc}: {metric_label} {t(f"stat.{stat}")} ({unit})',
            'VAL': f'{val:{fmt}}',
            'STAT': status,
        })

    return result


# ---------------------------------------------------------------------------
# Брендинг EL-MODS OBD
# ---------------------------------------------------------------------------

def brand_svg() -> str:
    """Возвращает inline SVG-логотип EL-MODS OBD для HTML-отчётов."""
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 210 44"'
        ' width="210" height="44" role="img" aria-label="EL-MODS OBD">'
        '<rect x="0" y="5" width="5" height="34" rx="2.5" fill="#1976d2"/>'
        '<circle cx="13" cy="16" r="2.5" fill="#90caf9"/>'
        '<circle cx="13" cy="24" r="2.5" fill="#90caf9"/>'
        '<circle cx="13" cy="32" r="2.5" fill="#64b5f6" opacity="0.7"/>'
        '<text x="22" y="31"'
        ' font-family="\'Segoe UI\',\'Helvetica Neue\',Arial,sans-serif"'
        ' font-size="22" font-weight="700">'
        '<tspan fill="#1a237e" letter-spacing="1.5">EL-MODS</tspan>'
        '<tspan fill="#90a4ae" font-size="18" font-weight="300"> \u00b7 </tspan>'
        '<tspan fill="#1976d2" letter-spacing="2">OBD</tspan>'
        '</text>'
        '<line x1="22" y1="38" x2="207" y2="38" stroke="#bbdefb" stroke-width="1.5"/>'
        '</svg>'
    )


#: Ширина логотипа для PDF-таблиц (pt)
BRAND_LOGO_W: float = 170

try:
    from reportlab.lib import colors as _rl_colors
    from reportlab.pdfbase import pdfmetrics as _rl_pdfmetrics
    from reportlab.platypus import Flowable as _Flowable

    class _LogoFlowable(_Flowable):
        """Брендинг EL-MODS OBD — вставляется в правую ячейку заголовка PDF."""
        _W: float = BRAND_LOGO_W
        _H: float = 26

        def __init__(self) -> None:
            super().__init__()
            self.width  = self._W
            self.height = self._H

        def draw(self) -> None:
            c = self.canv
            c.saveState()
            c.setFillColor(_rl_colors.HexColor('#1976d2'))
            c.roundRect(0, 2, 4, 22, 2, fill=1, stroke=0)
            c.setFillColor(_rl_colors.HexColor('#90caf9'))
            for dot_y in (19, 12, 5):
                c.circle(11, dot_y, 1.7, fill=1, stroke=0)
            c.setFillColor(_rl_colors.HexColor('#1a237e'))
            c.setFont('Helvetica-Bold', 15)
            c.drawString(20, 7, 'EL-MODS')
            w1 = _rl_pdfmetrics.stringWidth('EL-MODS', 'Helvetica-Bold', 15)
            sep = ' \u00b7 '
            c.setFillColor(_rl_colors.HexColor('#90a4ae'))
            c.setFont('Helvetica', 12)
            c.drawString(20 + w1, 8, sep)
            sep_w = _rl_pdfmetrics.stringWidth(sep, 'Helvetica', 12)
            c.setFillColor(_rl_colors.HexColor('#1976d2'))
            c.setFont('Helvetica-Bold', 15)
            c.drawString(20 + w1 + sep_w, 7, 'OBD')
            c.setStrokeColor(_rl_colors.HexColor('#bbdefb'))
            c.setLineWidth(1)
            c.line(20, 2, self._W - 2, 2)
            c.restoreState()

    def brand_logo_flowable() -> _Flowable:
        """Возвращает экземпляр логотипа EL-MODS OBD для PDF-отчётов."""
        return _LogoFlowable()

except ImportError:
    def brand_logo_flowable() -> None:  # type: ignore[misc]
        """Заглушка: reportlab недоступен."""
        return None
