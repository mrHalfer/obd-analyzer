#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Модуль экспорта сравнительных данных поездок OBD-II в Excel.

Создаёт .xlsx файл с листами:
- Сводка     — сводная таблица метрик по всем поездкам с цветовым кодированием
- Тренды     — числовые значения LTFT/STFT/T ОЖ по поездкам
- Детонация  — счётчики детонации по поездкам
- Режимы     — длительности режимов езды
- Статусы    — матрица статусов метрик
"""

import logging
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

_root = Path(__file__).parent.parent
for _d in [str(_root)]:
    if _d not in sys.path:
        sys.path.insert(0, _d)

from translation import t
from compare_core import (
    build_compare_rows,
    get_compare_label,
    get_numeric_series,
    get_drive_mode_durations,
    get_status_matrix,
)
from core_obd import (
    STATUS_COLOR_OK, STATUS_COLOR_WARNING, STATUS_COLOR_ERROR, STATUS_COLOR_NEUTRAL,
    STATUS_TEXT_OK, STATUS_TEXT_WARNING, STATUS_TEXT_ERROR, STATUS_TEXT_NEUTRAL,
)

logger = logging.getLogger(__name__)


def _hex_to_argb(hex_color: str) -> str:
    """Конвертирует #RRGGBB в ARGB-строку openpyxl (непрозрачный)."""
    return 'FF' + hex_color.lstrip('#').upper()


# ---------------------------------------------------------------------------
# Цвета для статусов (openpyxl fgColor — ARGB без '#')
# ---------------------------------------------------------------------------

_STAT_STYLE: dict[str, tuple[str, str]] = {
    '✅': (_hex_to_argb(STATUS_COLOR_OK),      _hex_to_argb(STATUS_TEXT_OK)),
    '⚠️': (_hex_to_argb(STATUS_COLOR_WARNING), _hex_to_argb(STATUS_TEXT_WARNING)),
    '❌': (_hex_to_argb(STATUS_COLOR_ERROR),   _hex_to_argb(STATUS_TEXT_ERROR)),
    '○':  (_hex_to_argb(STATUS_COLOR_NEUTRAL), _hex_to_argb(STATUS_TEXT_NEUTRAL)),
}
_HEADER_BG  = 'FFE8EAF6'
_HEADER_FG  = 'FF1A237E'

_INT_TO_STAT = {1: '✅', 2: '⚠️', 3: '❌', 0: '○', -1: ''}


# ---------------------------------------------------------------------------
# Стилизация ячеек
# ---------------------------------------------------------------------------

def _style_cell(cell: Any, stat: str, bold: bool = False) -> None:
    """Применяет заливку и цвет текста к ячейке по коду статуса."""
    try:
        from openpyxl.styles import PatternFill, Font, Alignment
        spec = _STAT_STYLE.get(str(stat).strip())
        if spec:
            bg_argb, fg_argb = spec
            cell.fill = PatternFill(fill_type='solid', fgColor=bg_argb)
            cell.font = Font(color=fg_argb, bold=bold)
        cell.alignment = Alignment(horizontal='center', vertical='center')
    except (ImportError, AttributeError, TypeError):
        pass


def _style_header_row(ws: Any, row_idx: int, n_cols: int) -> None:
    """Синяя шапка таблицы."""
    try:
        from openpyxl.styles import PatternFill, Font, Alignment
        for col in range(1, n_cols + 1):
            cell = ws.cell(row=row_idx, column=col)
            cell.fill = PatternFill(fill_type='solid', fgColor=_HEADER_BG)
            cell.font = Font(color=_HEADER_FG, bold=True)
            cell.alignment = Alignment(
                horizontal='left' if col == 1 else 'center',
                vertical='center',
            )
    except (ImportError, AttributeError, TypeError):
        pass


def _set_col_width(ws: Any, col_idx: int, width: float) -> None:
    """Устанавливает ширину столбца листа Excel (в символьных единицах openpyxl)."""
    try:
        from openpyxl.utils import get_column_letter
        ws.column_dimensions[get_column_letter(col_idx)].width = width
    except (ImportError, KeyError, AttributeError):
        pass


# ---------------------------------------------------------------------------
# Листы
# ---------------------------------------------------------------------------

def _write_summary(writer: Any, vals_df: pd.DataFrame, stats_df: pd.DataFrame, trip_ids: list) -> None:
    """Лист «Сводка»: метрики × поездки с цветовым кодированием."""
    rows_data = build_compare_rows(vals_df, stats_df)
    if not rows_data:
        return

    ws = writer.book.create_sheet(t('compare.xls.sheet_summary'))
    header = [t('compare.xls.col_param')] + [str(tid) for tid in trip_ids]
    for col, val in enumerate(header, 1):
        ws.cell(row=1, column=col, value=val)
    _style_header_row(ws, 1, len(header))

    for r_idx, row in enumerate(rows_data, start=2):
        ws.cell(row=r_idx, column=1, value=row['label'])
        try:
            from openpyxl.styles import Alignment
            ws.cell(row=r_idx, column=1).alignment = Alignment(horizontal='left', vertical='center')
        except (ImportError, AttributeError):
            pass
        for c_idx, tid in enumerate(trip_ids, start=2):
            val_str  = row['trip_vals'].get(tid, '')
            stat_str = row['trip_stats'].get(tid, '')
            display  = val_str if val_str not in ('', 'nan') else ''
            cell = ws.cell(row=r_idx, column=c_idx, value=display)
            _style_cell(cell, stat_str)

    # Ширина колонок
    max_label = max((len(r['label']) for r in rows_data), default=12)
    _set_col_width(ws, 1, max(max_label + 2, 18))
    max_trip = max((len(str(t)) for t in trip_ids), default=10)
    for c in range(2, len(trip_ids) + 2):
        _set_col_width(ws, c, max(max_trip + 4, 16))


def _write_numeric_sheet(
    writer: Any,
    vals_df: pd.DataFrame,
    stats_df: pd.DataFrame,
    trip_ids: list,
    sheet_name: str,
    metrics: list[tuple[str, str]],
) -> None:
    """Вспомогательная: поездки × числовые метрики."""
    data: dict[str, pd.Series] = {}
    for code, label in metrics:
        s = get_numeric_series(vals_df, stats_df, code)
        if not s.isna().all():
            data[label] = s
    if not data:
        return

    ws = writer.book.create_sheet(sheet_name)
    col_names = list(data.keys())
    header = [t('compare.xls.col_trip')] + col_names
    for col, val in enumerate(header, 1):
        ws.cell(row=1, column=col, value=val)
    _style_header_row(ws, 1, len(header))

    for r_idx, tid in enumerate(trip_ids, start=2):
        ws.cell(row=r_idx, column=1, value=str(tid))
        try:
            from openpyxl.styles import Alignment
            ws.cell(row=r_idx, column=1).alignment = Alignment(horizontal='left', vertical='center')
        except (ImportError, AttributeError):
            pass
        for c_idx, col_name in enumerate(col_names, start=2):
            val = data[col_name].get(tid, np.nan)
            if pd.notna(val):
                cell = ws.cell(row=r_idx, column=c_idx, value=round(float(val), 2))
                try:
                    from openpyxl.styles import Alignment
                    cell.alignment = Alignment(horizontal='center', vertical='center')
                except (ImportError, AttributeError):
                    pass

    max_trip = max((len(str(t)) for t in trip_ids), default=10)
    _set_col_width(ws, 1, max(max_trip + 2, 14))
    for c in range(2, len(col_names) + 2):
        _set_col_width(ws, c, 18)


def _write_modes(writer: Any, vals_df: pd.DataFrame, trip_ids: list) -> None:
    """Лист «Режимы»: длительности режимов езды по поездкам (мин)."""
    durations_df = get_drive_mode_durations(vals_df)
    if durations_df.isna().all().all():
        return

    ws = writer.book.create_sheet(t('compare.xls.sheet_modes'))
    header = [t('compare.xls.col_trip')] + list(durations_df.columns)
    for col, val in enumerate(header, 1):
        ws.cell(row=1, column=col, value=val)
    _style_header_row(ws, 1, len(header))

    for r_idx, tid in enumerate(trip_ids, start=2):
        ws.cell(row=r_idx, column=1, value=str(tid))
        try:
            from openpyxl.styles import Alignment
            ws.cell(row=r_idx, column=1).alignment = Alignment(horizontal='left', vertical='center')
        except (ImportError, AttributeError):
            pass
        for c_idx, col_name in enumerate(durations_df.columns, start=2):
            if tid in durations_df.index:
                val = durations_df.loc[tid, col_name]
                if pd.notna(val):
                    cell = ws.cell(row=r_idx, column=c_idx, value=round(float(val), 1))
                    try:
                        from openpyxl.styles import Alignment
                        cell.alignment = Alignment(horizontal='center', vertical='center')
                    except (ImportError, AttributeError):
                        pass

    max_trip = max((len(str(t)) for t in trip_ids), default=10)
    _set_col_width(ws, 1, max(max_trip + 2, 14))
    for c in range(2, len(durations_df.columns) + 2):
        _set_col_width(ws, c, 14)


def _write_statuses(writer: Any, vals_df: pd.DataFrame, stats_df: pd.DataFrame, trip_ids: list) -> None:
    """Лист «Статусы»: матрица статусов метрик × поездки."""
    matrix_df, labels = get_status_matrix(vals_df, stats_df)
    if matrix_df.empty:
        return

    ws = writer.book.create_sheet(t('compare.xls.sheet_statuses'))
    header = [t('compare.xls.col_metric')] + [str(tid) for tid in trip_ids]
    for col, val in enumerate(header, 1):
        ws.cell(row=1, column=col, value=val)
    _style_header_row(ws, 1, len(header))

    for r_idx, label in enumerate(labels, start=2):
        ws.cell(row=r_idx, column=1, value=label)
        try:
            from openpyxl.styles import Alignment
            ws.cell(row=r_idx, column=1).alignment = Alignment(horizontal='left', vertical='center')
        except (ImportError, AttributeError):
            pass
        for c_idx, tid in enumerate(trip_ids, start=2):
            if tid in matrix_df.columns:
                num_val = int(matrix_df.loc[label, tid])
                stat_emoji = _INT_TO_STAT.get(num_val, '')
                display = stat_emoji if stat_emoji else '—'
                cell = ws.cell(row=r_idx, column=c_idx, value=display)
                _style_cell(cell, stat_emoji)

    max_label = max((len(l) for l in labels), default=12)
    _set_col_width(ws, 1, max(max_label + 2, 20))
    max_trip = max((len(str(t)) for t in trip_ids), default=10)
    for c in range(2, len(trip_ids) + 2):
        _set_col_width(ws, c, max(max_trip + 4, 14))


# ---------------------------------------------------------------------------
# Публичная функция
# ---------------------------------------------------------------------------

def create_compare_xls(
    output_dir: Path,
    vals_df: pd.DataFrame,
    stats_df: pd.DataFrame,
) -> Path | None:
    """Генерирует Excel-отчёт сравнения поездок.

    Args:
        output_dir: Директория для сохранения файла.
        vals_df: DataFrame значений (индекс=trip_id, столбцы=CODE).
        stats_df: DataFrame статусов.

    Returns:
        Путь к .xlsx файлу или None при ошибке/недоступности openpyxl.
    """
    if vals_df.empty:
        logger.warning('compare_xls: нет данных для отчёта')
        return None

    try:
        import openpyxl  # noqa: F401
    except ImportError:
        logger.warning('compare_xls: openpyxl не установлен, Excel пропущен')
        return None

    trip_ids = list(vals_df.index)
    out_path = output_dir / 'comparison_report.xlsx'

    try:
        with pd.ExcelWriter(str(out_path), engine='openpyxl') as writer:
            # Удаляем пустой лист по умолчанию, созданный openpyxl
            for default_name in ('Sheet', 'Sheet1'):
                if default_name in writer.book.sheetnames:
                    del writer.book[default_name]

            _write_summary(writer, vals_df, stats_df, trip_ids)
            _write_numeric_sheet(
                writer, vals_df, stats_df, trip_ids, t('compare.xls.sheet_trends'),
                [
                    ('LTFT_MEAN',           get_compare_label('LTFT_MEAN')),
                    ('STFT_MEAN',           get_compare_label('STFT_MEAN')),
                    ('ALL_TEMP_COOLANT_Max', get_compare_label('ALL_TEMP_COOLANT_Max')),
                ],
            )
            _write_numeric_sheet(
                writer, vals_df, stats_df, trip_ids, t('compare.xls.sheet_knock'),
                [
                    ('KNOCK_TOTAL_COUNT',  get_compare_label('KNOCK_TOTAL_COUNT')),
                    ('KNOCK_WEAK_COUNT',   get_compare_label('KNOCK_WEAK_COUNT')),
                    ('KNOCK_MEDIUM_COUNT', get_compare_label('KNOCK_MEDIUM_COUNT')),
                    ('KNOCK_STRONG_COUNT', get_compare_label('KNOCK_STRONG_COUNT')),
                ],
            )
            _write_modes(writer, vals_df, trip_ids)
            _write_statuses(writer, vals_df, stats_df, trip_ids)

        logger.info(t('console.compare_xls_saved', path=out_path))
        return out_path

    except (OSError, ValueError) as e:
        logger.error(f'Ошибка создания Excel сравнения: {e}', exc_info=True)
        return None
