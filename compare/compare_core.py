#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Ядро модуля сравнения поездок OBD-II.

Загружает *_metrics.csv из директории, строит сводные DataFrame,
предоставляет утилиты для извлечения числовых значений и fallback-разрешения.
"""

import re
import sys
import logging
from pathlib import Path

import pandas as pd
import numpy as np

_root = Path(__file__).parent.parent
for _d in [str(_root)]:
    if _d not in sys.path:
        sys.path.insert(0, _d)

from translation import t

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Ключевые метрики для сравнения
# ---------------------------------------------------------------------------

# (virtual_code, label_key, fallback_codes | None)
# label_key — ключ в compare.metrics.* для перевода
COMPARE_METRICS: list[tuple[str, str, list[str] | None]] = [
    # ── Поездка ──────────────────────────────────────────────────────────────
    ('RUN_DURATION',              'duration',              None),
    ('ALL_DRIVE_DISTANCE',        'distance',              None),
    # ── Режим езды ───────────────────────────────────────────────────────────
    ('RPM_MEAN',                  'rpm_mean',              ['ALL_DRIVE_RPM_Mean',            'ALL_RPM_Mean']),
    ('SPEED_MEAN',                'speed_mean',            ['ALL_DRIVE_SPEED_Mean',          'ALL_SPEED_Mean']),
    ('LOAD_MEAN',                 'load_mean',             ['ALL_DRIVE_LOAD_Mean',           'ALL_LOAD_Mean']),
    # ── Температуры ──────────────────────────────────────────────────────────
    ('COOLANT_MEAN',              'coolant_mean',          ['ALL_DRIVE_TEMP_COOLANT_Mean',   'ALL_TEMP_COOLANT_Mean']),
    ('ALL_TEMP_COOLANT_Max',      'coolant_max',           None),
    ('INTAKE_TEMP_MEAN',          'intake_temp_mean',      ['ALL_DRIVE_INTAKE_TEMP_Mean',    'ALL_INTAKE_TEMP_Mean']),
    ('WARMUP_DURATION',           'warmup',                None),
    # ── Топливо ──────────────────────────────────────────────────────────────
    ('LTFT_MEAN',                 'ltft_mean',             ['ALL_DRIVE_LTFT_Mean',           'ALL_LTFT_Mean']),
    ('STFT_MEAN',                 'stft_mean',             ['ALL_DRIVE_STFT_Mean',           'ALL_STFT_Mean']),
    ('STFT_MIN',                  'stft_min',              ['ALL_DRIVE_STFT_Min',            'ALL_STFT_Min']),
    ('STFT_MAX',                  'stft_max',              ['ALL_DRIVE_STFT_Max',            'ALL_STFT_Max']),
    ('ALL_DRIVE_FUEL_Mean',       'fuel_mean',             None),
    ('INJECTION_TIME_MEAN',       'injection_time_mean',   ['ALL_DRIVE_INJECTION_TIME_Mean', 'ALL_INJECTION_TIME_Mean']),
    # ── Воздух / MAF ─────────────────────────────────────────────────────────
    ('MAF_MEAN',                  'maf_mean',              ['ALL_DRIVE_MAF_Mean',            'ALL_MAF_Mean']),
    ('MAF_MIN',                   'maf_min',               ['ALL_DRIVE_MAF_Min',             'ALL_MAF_Min']),
    ('MAF_MAX',                   'maf_max',               ['ALL_DRIVE_MAF_Max',             'ALL_MAF_Max']),
    # ── O2 / Лямбда ──────────────────────────────────────────────────────────
    ('O2_RICH_TIME',              'o2_rich_time',          None),
    ('O2_LEAN_TIME',              'o2_lean_time',          None),
    ('O2_CROSSING_RATE',          'o2_crossing_rate',      None),
    # ── Детонация / заглохи ───────────────────────────────────────────────────
    ('KNOCK_TOTAL_COUNT',         'knock_total',           None),
    ('KNOCK_WEAK_COUNT',          'knock_weak',            None),
    ('KNOCK_MEDIUM_COUNT',        'knock_medium',          None),
    ('KNOCK_STRONG_COUNT',        'knock_strong',          None),
    ('ALL_STALLED_COUNT',         'stalls',                None),
    # ── Катализатор ──────────────────────────────────────────────────────────
    ('CAT_O2_STATE',              'catalyst',              None),
]

# Коды режимов для диаграммы длительностей
DRIVE_MODE_CODES = ['WARMUP_DURATION', 'DRIVE_CITY_DURATION', 'DRIVE_SUBURBAN_DURATION', 'DRIVE_HIGHWAY_DURATION']
_DRIVE_MODE_KEYS = ['warmup', 'city', 'suburban', 'highway']


def get_compare_label(virtual_code: str) -> str:
    """Возвращает переведённую метку для virtual_code."""
    for vc, label_key, _ in COMPARE_METRICS:
        if vc == virtual_code:
            return t(f'compare.metrics.{label_key}')
    return virtual_code


def get_drive_mode_label(mode_key: str) -> str:
    """Возвращает переведённую метку режима езды."""
    return t(f'compare.drive_modes.{mode_key}')

# Коды для heatmap статусов (только метрики с значимым статусом)
HEATMAP_METRIC_CODES = [
    'LTFT_MEAN', 'STFT_MEAN',
    'ALL_TEMP_COOLANT_Max',
    'KNOCK_TOTAL_COUNT', 'KNOCK_WEAK_COUNT', 'KNOCK_MEDIUM_COUNT', 'KNOCK_STRONG_COUNT',
    'ALL_STALLED_COUNT',
    'CAT_O2_STATE',
]

STATUS_MAP = {'✅': 1, '⚠️': 2, '❌': 3, '○': 0, '': -1}


# ---------------------------------------------------------------------------
# Утилиты
# ---------------------------------------------------------------------------

def _extract_trip_id(metrics_path: Path) -> str:
    """Извлекает идентификатор поездки из имени файла *_metrics.csv.

    Пример: log_2026-01-27_metrics.csv -> '2026-01-27'
    """
    name = re.sub(r'_metrics$', '', metrics_path.stem)
    m = re.search(r'(\d{4}-\d{2}-\d{2})(?:[_T](\d{2}[-:]\d{2}))?', name)
    if m:
        date_part = m.group(1)
        time_part = m.group(2)
        if time_part:
            return f'{date_part} {time_part.replace("-", ":")}'
        return date_part
    return name


def parse_numeric(val_str: object) -> float:
    """Извлекает число из строки-значения метрики.

    '2.1 %' -> 2.1, '85 °C' -> 85.0, 'N/A' -> NaN
    """
    try:
        m = re.search(r'[-+]?\d+\.?\d*', str(val_str))
        if m:
            return float(m.group(0))
    except (ValueError, TypeError):
        pass
    return float('nan')


# ---------------------------------------------------------------------------
# Загрузка данных
# ---------------------------------------------------------------------------

def load_trips(directory: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Загружает все *_metrics.csv из директории.

    Returns:
        (vals_df, stats_df): DataFrame индексированные по trip_id,
        колонки — коды метрик CODE, значения — VAL / STAT.
        Возвращает пустые DataFrame если нет подходящих файлов.
    """
    metrics_files = sorted(directory.glob('*_metrics.csv'))
    val_rows: dict[str, dict[str, str]] = {}
    stat_rows: dict[str, dict[str, str]] = {}

    for mf in metrics_files:
        trip_id = _extract_trip_id(mf)
        # Обработка дублей trip_id
        if trip_id in val_rows:
            suffix = 2
            while f'{trip_id}_{suffix}' in val_rows:
                suffix += 1
            trip_id = f'{trip_id}_{suffix}'

        df = None
        for enc in ('utf-8-sig', 'cp1251'):
            try:
                df = pd.read_csv(mf, encoding=enc)
                break
            except (pd.errors.ParserError, UnicodeDecodeError, OSError):
                continue

        if df is None or df.empty or 'CODE' not in df.columns:
            logger.warning(f'Пропущен файл сравнения: {mf.name}')
            continue
        if 'VAL' not in df.columns or 'STAT' not in df.columns:
            logger.warning(f'Нет обязательных колонок VAL/STAT в {mf.name}')
            continue

        # Пропускаем строки-разделители
        df = df[df['CODE'] != '---SEPARATOR---']
        val_rows[trip_id] = df.set_index('CODE')['VAL'].astype(str).to_dict()
        stat_rows[trip_id] = df.set_index('CODE')['STAT'].astype(str).to_dict()

    if not val_rows:
        return pd.DataFrame(), pd.DataFrame()

    vals_df  = pd.DataFrame.from_dict(val_rows, orient='index')
    stats_df = pd.DataFrame.from_dict(stat_rows, orient='index')
    return vals_df, stats_df


# ---------------------------------------------------------------------------
# Разрешение метрик (fallback-цепочки)
# ---------------------------------------------------------------------------

def _get_fallback(virtual_code: str) -> list[str]:
    """Возвращает список реальных кодов для virtual_code."""
    for vc, _label, fallbacks in COMPARE_METRICS:
        if vc == virtual_code:
            return fallbacks if fallbacks else [virtual_code]
    return [virtual_code]


def resolve_val_stat(
    vals_df: pd.DataFrame,
    stats_df: pd.DataFrame,
    virtual_code: str,
) -> tuple[pd.Series, pd.Series]:
    """Разрешает виртуальный/реальный код в серии значений и статусов.

    Для каждой поездки берёт первый доступный код из fallback-цепочки.

    Returns:
        (val_series, stat_series) с индексом = trip_id
    """
    chains = _get_fallback(virtual_code)

    val_result  = pd.Series('', index=vals_df.index, dtype=str)
    stat_result = pd.Series('', index=vals_df.index, dtype=str)

    for code in chains:
        if code in vals_df.columns:
            mask = val_result == ''
            val_result[mask]  = vals_df[code][mask].fillna('')
            if code in stats_df.columns:
                stat_result[mask] = stats_df[code][mask].fillna('')

    return val_result, stat_result


def get_numeric_series(
    vals_df: pd.DataFrame,
    stats_df: pd.DataFrame,
    virtual_code: str,
) -> pd.Series:
    """Возвращает числовые значения метрики (float) для всех поездок."""
    val_s, _ = resolve_val_stat(vals_df, stats_df, virtual_code)
    return val_s.map(parse_numeric)


# ---------------------------------------------------------------------------
# Построение сводной таблицы
# ---------------------------------------------------------------------------

_MAX_CELL_LEN = 22  # Максимальная длина текстового значения в ячейке таблицы


def _truncate(val: str, max_len: int = _MAX_CELL_LEN) -> str:
    """Обрезает длинную строку до max_len символов с суффиксом '…'."""
    v = str(val).strip()
    if len(v) > max_len:
        return v[:max_len - 1] + '…'
    return v


def build_compare_rows(
    vals_df: pd.DataFrame,
    stats_df: pd.DataFrame,
) -> list[dict]:
    """Строит список строк для сводной таблицы сравнения.

    Каждая строка: {'code', 'label', 'trip_vals': {trip_id: val_str},
                    'trip_stats': {trip_id: stat_str}}
    Пропускает метрики, для которых нет данных ни в одной поездке.
    """
    if vals_df.empty:
        return []

    rows = []
    trip_ids = list(vals_df.index)

    for virtual_code, _label_key, _ in COMPARE_METRICS:
        val_s, stat_s = resolve_val_stat(vals_df, stats_df, virtual_code)
        # Пропускаем если везде пусто
        if val_s.eq('').all() or val_s.eq('nan').all():
            continue
        rows.append({
            'code':       virtual_code,
            'label':      get_compare_label(virtual_code),
            'trip_vals':  {tid: _truncate(val_s.get(tid, ''))  for tid in trip_ids},
            'trip_stats': {tid: stat_s.get(tid, '') for tid in trip_ids},
        })
    return rows


def get_drive_mode_durations(vals_df: pd.DataFrame) -> pd.DataFrame:
    """DataFrame длительностей по режимам езды (строки=поездки, колонки=режимы)."""
    result = pd.DataFrame(index=vals_df.index)
    for code, mode_key in zip(DRIVE_MODE_CODES, _DRIVE_MODE_KEYS):
        label = get_drive_mode_label(mode_key)
        if code in vals_df.columns:
            result[label] = vals_df[code].map(parse_numeric)
        else:
            result[label] = np.nan
    return result


def get_status_matrix(
    vals_df: pd.DataFrame,
    stats_df: pd.DataFrame,
) -> tuple[pd.DataFrame, list[str]]:
    """Строит числовую матрицу статусов для heatmap.

    Returns:
        (matrix_df, labels) где matrix_df содержит числа STATUS_MAP,
        labels — подписи строк (метрик).
    """
    labels = []
    rows = []
    for virtual_code in HEATMAP_METRIC_CODES:
        _val_s, stat_s = resolve_val_stat(vals_df, stats_df, virtual_code)
        # Пропускаем если нет данных
        if stat_s.eq('').all():
            continue
        label = get_compare_label(virtual_code)
        labels.append(label)
        rows.append(stat_s.map(lambda s: STATUS_MAP.get(str(s).strip(), -1)))

    if not rows:
        return pd.DataFrame(), []

    matrix_df = pd.DataFrame(rows, index=labels, columns=vals_df.index)
    return matrix_df, labels
