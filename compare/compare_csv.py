#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Модуль экспорта сравнительных данных поездок OBD-II в CSV.

Генерирует comparison_report.csv — сводная таблица: строки = поездки,
столбцы = ключевые метрики (значения) + режимы езды + статусы.

Формируется всегда, независимо от флага -nocsv (как и _metrics.csv).
"""

import logging
import sys
from pathlib import Path

import pandas as pd

_root = Path(__file__).parent.parent
for _d in [str(_root)]:
    if _d not in sys.path:
        sys.path.insert(0, _d)

from translation import t
from compare_core import (
    COMPARE_METRICS,
    HEATMAP_METRIC_CODES,
    get_compare_label,
    get_drive_mode_label,
    parse_numeric,
    resolve_val_stat,
)

logger = logging.getLogger(__name__)

# Режимы езды исключая Прогрев — он уже есть в COMPARE_METRICS как WARMUP_DURATION
_EXTRA_MODE_CODES = ['DRIVE_CITY_DURATION', 'DRIVE_SUBURBAN_DURATION', 'DRIVE_HIGHWAY_DURATION']
_EXTRA_MODE_KEYS  = ['city_min', 'suburban_min', 'highway_min']


def create_compare_csv(
    output_dir: Path,
    vals_df: pd.DataFrame,
    stats_df: pd.DataFrame,
) -> Path | None:
    """Генерирует CSV-отчёт сравнения поездок.

    Строки — поездки, столбцы:
    - Значения всех ключевых метрик (COMPARE_METRICS)
    - Длительности режимов езды (Город / Пригород / Трасса)
    - Статусы метрик из HEATMAP_METRIC_CODES (суффикс «_статус»)

    Args:
        output_dir: Директория для сохранения файла.
        vals_df: DataFrame значений (индекс=trip_id, столбцы=CODE).
        stats_df: DataFrame статусов.

    Returns:
        Путь к CSV или None при ошибке.
    """
    if vals_df.empty:
        logger.warning('compare_csv: нет данных для отчёта')
        return None

    trip_ids = list(vals_df.index)

    col_trip = t('compare.csv.col_trip')
    status_suffix = t('compare.csv.status_suffix')

    rows = []
    for trip_id in trip_ids:
        row: dict[str, object] = {col_trip: trip_id}

        # Значения ключевых метрик
        for virtual_code, _label_key, _ in COMPARE_METRICS:
            label = get_compare_label(virtual_code)
            val_s, _ = resolve_val_stat(vals_df, stats_df, virtual_code)
            raw = val_s.get(trip_id, '')
            row[label] = raw if raw not in ('', 'nan') else ''

        # Длительности режимов езды (Город / Пригород / Трасса)
        for code, mode_key in zip(_EXTRA_MODE_CODES, _EXTRA_MODE_KEYS):
            col_label = get_drive_mode_label(mode_key)
            if code in vals_df.columns and trip_id in vals_df.index:
                num = parse_numeric(vals_df.loc[trip_id, code])
                row[col_label] = round(num, 1) if num == num else ''  # NaN check
            else:
                row[col_label] = ''

        # Статусы значимых метрик
        for virtual_code in HEATMAP_METRIC_CODES:
            label = get_compare_label(virtual_code)
            _, stat_s = resolve_val_stat(vals_df, stats_df, virtual_code)
            row[f'{label}{status_suffix}'] = stat_s.get(trip_id, '')

        rows.append(row)

    out_path = output_dir / 'comparison_report.csv'
    try:
        df = pd.DataFrame(rows)
        df.to_csv(str(out_path), index=False, encoding='utf-8-sig')
        logger.info(t('console.compare_csv_saved', path=out_path))
        return out_path
    except OSError as e:
        logger.error(f'Ошибка создания CSV сравнения: {e}', exc_info=True)
        return None
