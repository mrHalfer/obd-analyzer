#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Модуль сравнительных PNG-графиков (matplotlib) для нескольких поездок OBD-II.

Функции:
- _plot_trends          — линейные тренды LTFT/STFT/T ОЖ по поездкам
- _plot_knock_bars      — столбчатая диаграмма детонации по силе
- _plot_mode_durations  — стековая диаграмма длительностей режимов
- _plot_status_heatmap  — heatmap статусов ключевых метрик
"""

import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd

_root = Path(__file__).parent.parent
for _d in [str(_root)]:
    if _d not in sys.path:
        sys.path.insert(0, _d)

# matplotlib — опциональная зависимость формата PNG: при отсутствии
# вместо голой ModuleNotFoundError бросаем MissingDependencyError с pip-командой
from deps import require
matplotlib = require('matplotlib', 'для PNG-графиков сравнения')
matplotlib.use('Agg')
import matplotlib.pyplot as plt

from translation import t
from compare_core import (
    get_numeric_series,
    get_drive_mode_durations,
    get_status_matrix,
)
from core_obd import (
    COOLANT_TEMP_MAX_MIN, COOLANT_TEMP_MAX_ERROR,
    CHART_FUEL_OK_LINE, CHART_FUEL_WARN_LINE,
    STATUS_COLOR_NO_DATA, STATUS_COLOR_NEUTRAL,
    STATUS_COLOR_OK, STATUS_COLOR_WARNING, STATUS_COLOR_ERROR,
)

logger = logging.getLogger(__name__)

_FIGSIZE_W = 11
_DPI = 150
_BAR_ALPHA = 0.85


def _trip_labels(trip_ids: list[str]) -> list[str]:
    """Укорачивает trip_id до даты (без времени) для меток осей."""
    return [tid.split(' ')[0] if len(tid) > 10 else tid for tid in trip_ids]


def _save(fig: plt.Figure, path: Path) -> None:
    """Сохраняет matplotlib-фигуру в PNG и закрывает её."""
    fig.tight_layout()
    fig.savefig(path, dpi=_DPI, bbox_inches='tight')
    plt.close(fig)
    logger.info(t('console.compare_png_saved', name=path.name))


# ---------------------------------------------------------------------------
# Тренды LTFT / STFT / T ОЖ
# ---------------------------------------------------------------------------

def _plot_trends(
    vals_df: pd.DataFrame,
    stats_df: pd.DataFrame,
    output_dir: Path,
) -> Path | None:
    """Линейные тренды ключевых параметров по поездкам."""
    if vals_df.empty:
        return None

    trip_ids = list(vals_df.index)
    x = np.arange(len(trip_ids))
    xlabels = _trip_labels(trip_ids)

    def _s(code: str) -> np.ndarray:
        return get_numeric_series(vals_df, stats_df, code).values

    # (group_label, [(vals, line_label, color), ...], ref_type)
    # ref_type: 'fuel' | 'coolant' | None
    subplot_defs = [
        (t('compare.trends.rpm_label'),
            [(_s('RPM_MEAN'), t('compare.trends.rpm_label'), '#0277BD')], None),
        (t('compare.trends.speed_label'),
            [(_s('SPEED_MEAN'), t('compare.trends.speed_label'), '#00838F')], None),
        (t('compare.trends.load_label'),
            [(_s('LOAD_MEAN'), t('compare.trends.load_label'), '#558B2F')], None),
        (t('compare.trends.o2_rich_label') + ' / ' + t('compare.trends.o2_lean_label'),
            [(_s('O2_RICH_TIME'),  t('compare.trends.o2_rich_label'),  '#D32F2F'),
             (_s('O2_LEAN_TIME'),  t('compare.trends.o2_lean_label'),  '#1565C0')], None),
        (t('compare.trends.injection_time_label'),
            [(_s('INJECTION_TIME_MEAN'), t('compare.trends.injection_time_label'), '#6D4C41')], None),
        (t('compare.trends.ltft_label') + ' / ' + t('compare.trends.stft_label'),
            [(_s('LTFT_MEAN'), t('compare.trends.ltft_label'), 'tab:blue'),
             (_s('STFT_MEAN'), t('compare.trends.stft_label'), 'tab:orange')], 'fuel'),
        (t('compare.trends.coolant_label') + ' / ' + t('compare.trends.coolant_mean_label'),
            [(_s('ALL_TEMP_COOLANT_Max'), t('compare.trends.coolant_label'),      'tab:red'),
             (_s('COOLANT_MEAN'),         t('compare.trends.coolant_mean_label'), '#E57373')], 'coolant'),
        (t('compare.trends.intake_temp_label'),
            [(_s('INTAKE_TEMP_MEAN'), t('compare.trends.intake_temp_label'), '#7E57C2')], None),
    ]
    # Убираем подграфики без данных (все серии пустые)
    active = [
        (grp_lbl, series, ref)
        for grp_lbl, series, ref in subplot_defs
        if any(not np.all(np.isnan(v)) for v, _, _ in series)
    ]
    if not active:
        return None

    n = len(active)
    fig, axes = plt.subplots(n, 1, figsize=(_FIGSIZE_W, 3.0 * n), sharex=True)
    if n == 1:
        axes = [axes]

    fig.suptitle(t('compare.trends.title'), fontsize=13, fontweight='bold', y=1.01)

    for ax, (grp_lbl, series, ref_type) in zip(axes, active):
        multi = sum(1 for v, _, _ in series if not np.all(np.isnan(v))) > 1
        for vals, line_lbl, color in series:
            mask = ~np.isnan(vals)
            if not mask.any():
                continue
            ax.plot(x[mask], vals[mask], marker='o', color=color, linewidth=2,
                    markersize=7, label=line_lbl)
        if ref_type == 'fuel':
            ax.axhline(0,                     color='gray',    linewidth=0.8, linestyle='--', alpha=0.6)
            ax.axhline( CHART_FUEL_OK_LINE,   color='#ff7f0e', linewidth=0.8, linestyle=':',  alpha=0.7)
            ax.axhline(-CHART_FUEL_OK_LINE,   color='#ff7f0e', linewidth=0.8, linestyle=':',  alpha=0.7)
            ax.axhline( CHART_FUEL_WARN_LINE, color='#d62728', linewidth=0.8, linestyle='--', alpha=0.7)
            ax.axhline(-CHART_FUEL_WARN_LINE, color='#d62728', linewidth=0.8, linestyle='--', alpha=0.7)
        elif ref_type == 'coolant':
            ax.axhline(COOLANT_TEMP_MAX_MIN,   color='green', linewidth=0.8, linestyle='--', alpha=0.6,
                       label=t('compare.trends.norm'))
            ax.axhline(COOLANT_TEMP_MAX_ERROR, color='red',   linewidth=0.8, linestyle='--', alpha=0.6,
                       label=t('compare.trends.max'))
        ax.set_ylabel(grp_lbl, fontsize=9)
        ax.grid(True, alpha=0.3)
        if multi or ref_type == 'coolant':
            ax.legend(loc='upper right', fontsize=8)

    axes[-1].set_xticks(x)
    axes[-1].set_xticklabels(xlabels, rotation=30, ha='right', fontsize=9)

    out_path = output_dir / 'comparison_trends.png'
    _save(fig, out_path)
    return out_path


# ---------------------------------------------------------------------------
# Столбчатая диаграмма детонации
# ---------------------------------------------------------------------------

def _plot_knock_bars(
    vals_df: pd.DataFrame,
    stats_df: pd.DataFrame,
    output_dir: Path,
) -> Path | None:
    """Столбчатая диаграмма: слабая / средняя / сильная детонация по поездкам."""
    if vals_df.empty:
        return None

    trip_ids = list(vals_df.index)
    x = np.arange(len(trip_ids))
    xlabels = _trip_labels(trip_ids)

    weak   = get_numeric_series(vals_df, stats_df, 'KNOCK_WEAK_COUNT').values
    medium = get_numeric_series(vals_df, stats_df, 'KNOCK_MEDIUM_COUNT').values
    strong = get_numeric_series(vals_df, stats_df, 'KNOCK_STRONG_COUNT').values

    # Нет данных — пропускаем
    if np.all(np.isnan(weak)) and np.all(np.isnan(medium)) and np.all(np.isnan(strong)):
        return None

    weak   = np.nan_to_num(weak,   nan=0.0)
    medium = np.nan_to_num(medium, nan=0.0)
    strong = np.nan_to_num(strong, nan=0.0)

    width = 0.25
    fig, ax = plt.subplots(figsize=(_FIGSIZE_W, 4.5))

    ax.bar(x - width, weak,   width, label=t('compare.knock.weak'),   color='#FFC107', alpha=_BAR_ALPHA)
    ax.bar(x,         medium, width, label=t('compare.knock.medium'), color='#FF7043', alpha=_BAR_ALPHA)
    ax.bar(x + width, strong, width, label=t('compare.knock.strong'), color='#B71C1C', alpha=_BAR_ALPHA)

    ax.set_title(t('compare.knock.title'), fontsize=13, fontweight='bold')
    ax.set_ylabel(t('compare.knock.y_axis'), fontsize=10)
    ax.set_xticks(x)
    ax.set_xticklabels(xlabels, rotation=30, ha='right', fontsize=9)
    ax.legend(fontsize=9)
    ax.grid(True, axis='y', alpha=0.3)
    ax.yaxis.set_major_locator(plt.MaxNLocator(integer=True))

    out_path = output_dir / 'comparison_knock.png'
    _save(fig, out_path)
    return out_path


# ---------------------------------------------------------------------------
# Стековая диаграмма длительностей режимов
# ---------------------------------------------------------------------------

def _plot_mode_durations(
    vals_df: pd.DataFrame,
    output_dir: Path,
) -> Path | None:
    """Стековая диаграмма: длительности режимов езды по поездкам."""
    if vals_df.empty:
        return None

    durations_df = get_drive_mode_durations(vals_df)
    # Пропускаем если нет данных ни по одному режиму
    if durations_df.isna().all().all():
        return None

    durations_df = durations_df.fillna(0.0)
    trip_ids = list(durations_df.index)
    xlabels  = _trip_labels(trip_ids)
    x = np.arange(len(trip_ids))

    colors = ['#4CAF50', '#2196F3', '#FF9800', '#9C27B0']  # Прогрев/Город/Пригород/Трасса

    fig, ax = plt.subplots(figsize=(_FIGSIZE_W, 4.5))

    bottom = np.zeros(len(trip_ids))
    for (col, color) in zip(durations_df.columns, colors):
        vals = durations_df[col].values
        ax.bar(x, vals, bottom=bottom, label=col, color=color, alpha=_BAR_ALPHA)
        bottom += vals

    ax.set_title(t('compare.modes.title'), fontsize=13, fontweight='bold')
    ax.set_ylabel(t('compare.modes.y_axis'), fontsize=10)
    ax.set_xticks(x)
    ax.set_xticklabels(xlabels, rotation=30, ha='right', fontsize=9)
    ax.legend(fontsize=9, loc='upper right')
    ax.grid(True, axis='y', alpha=0.3)

    out_path = output_dir / 'comparison_modes.png'
    _save(fig, out_path)
    return out_path


# ---------------------------------------------------------------------------
# Heatmap статусов
# ---------------------------------------------------------------------------

_STATUS_COLORS = {
    -1: STATUS_COLOR_NO_DATA,
     0: STATUS_COLOR_NEUTRAL,
     1: STATUS_COLOR_OK,
     2: STATUS_COLOR_WARNING,
     3: STATUS_COLOR_ERROR,
}

_STATUS_LABELS = {-1: '', 0: '○', 1: 'ok', 2: '!!', 3: 'err'}


def _plot_status_heatmap(
    vals_df: pd.DataFrame,
    stats_df: pd.DataFrame,
    output_dir: Path,
) -> Path | None:
    """Heatmap статусов ключевых метрик: строки=метрики, столбцы=поездки."""
    if vals_df.empty:
        return None

    matrix_df, labels = get_status_matrix(vals_df, stats_df)
    if matrix_df.empty:
        return None

    n_metrics = len(labels)
    n_trips   = len(vals_df)
    cell_h = max(0.5, min(0.9, 8.0 / n_metrics))
    cell_w = max(0.8, min(2.0, 12.0 / n_trips))
    fig_h = n_metrics * cell_h + 1.5
    fig_w = n_trips * cell_w + 3.5

    fig, ax = plt.subplots(figsize=(fig_w, fig_h))

    data = matrix_df.values  # shape: (n_metrics, n_trips)

    # Раскраска ячеек вручную
    for row_i, metric_label in enumerate(labels):
        for col_j, trip_id in enumerate(matrix_df.columns):
            val = int(data[row_i, col_j])
            color = _STATUS_COLORS.get(val, '#FFFFFF')
            ax.add_patch(plt.Rectangle((col_j, row_i), 1, 1, color=color))
            icon = _STATUS_LABELS.get(val, '')
            ax.text(col_j + 0.5, row_i + 0.5, icon,
                    ha='center', va='center', fontsize=10)

    ax.set_xlim(0, n_trips)
    ax.set_ylim(0, n_metrics)
    ax.set_xticks([i + 0.5 for i in range(n_trips)])
    ax.set_xticklabels(_trip_labels(list(matrix_df.columns)), rotation=35, ha='right', fontsize=9)
    ax.set_yticks([i + 0.5 for i in range(n_metrics)])
    ax.set_yticklabels(labels, fontsize=9)
    ax.invert_yaxis()

    # Сетка
    for i in range(n_metrics + 1):
        ax.axhline(i, color='#90A4AE', linewidth=0.5)
    for j in range(n_trips + 1):
        ax.axvline(j, color='#90A4AE', linewidth=0.5)

    ax.set_title(t('compare.heatmap.title'), fontsize=13, fontweight='bold', pad=12)

    # Легенда
    from matplotlib.patches import Patch
    legend_elements = [
        Patch(facecolor=_STATUS_COLORS[1],  label=t('compare.heatmap.ok')),
        Patch(facecolor=_STATUS_COLORS[2],  label=t('compare.heatmap.warning')),
        Patch(facecolor=_STATUS_COLORS[3],  label=t('compare.heatmap.error')),
        Patch(facecolor=_STATUS_COLORS[0],  label=t('compare.heatmap.neutral')),
        Patch(facecolor=_STATUS_COLORS[-1], label=t('compare.heatmap.no_data')),
    ]
    ax.legend(handles=legend_elements, loc='upper center', ncol=5,
              bbox_to_anchor=(0.5, -0.12), fontsize=8, framealpha=0.9)

    out_path = output_dir / 'comparison_heatmap.png'
    _save(fig, out_path)
    return out_path


# ---------------------------------------------------------------------------
# Генерация всех графиков
# ---------------------------------------------------------------------------

def generate_all_plots(
    vals_df: pd.DataFrame,
    stats_df: pd.DataFrame,
    output_dir: Path,
) -> dict[str, Path]:
    """Генерирует все сравнительные графики, возвращает словарь {name: path}."""
    paths: dict[str, Path] = {}

    try:
        p = _plot_trends(vals_df, stats_df, output_dir)
        if p:
            paths['trends'] = p
    except (ValueError, KeyError, TypeError) as e:
        logger.error(f'Ошибка _plot_trends: {e}', exc_info=True)

    try:
        p = _plot_knock_bars(vals_df, stats_df, output_dir)
        if p:
            paths['knock'] = p
    except (ValueError, KeyError, TypeError) as e:
        logger.error(f'Ошибка _plot_knock_bars: {e}', exc_info=True)

    try:
        p = _plot_mode_durations(vals_df, output_dir)
        if p:
            paths['modes'] = p
    except (ValueError, KeyError, TypeError) as e:
        logger.error(f'Ошибка _plot_mode_durations: {e}', exc_info=True)

    try:
        p = _plot_status_heatmap(vals_df, stats_df, output_dir)
        if p:
            paths['heatmap'] = p
    except (ValueError, KeyError, TypeError) as e:
        logger.error(f'Ошибка _plot_status_heatmap: {e}', exc_info=True)

    return paths
