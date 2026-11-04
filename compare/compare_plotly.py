#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Интерактивные Plotly-графики для HTML-отчёта сравнения поездок OBD-II.

Функции:
- _plot_trends_plotly      — линейные тренды LTFT/STFT/T ОЖ по поездкам
- _plot_knock_bars_plotly  — столбчатая диаграмма детонации
- _plot_mode_durations_plotly — стековая диаграмма длительностей режимов
- _plot_status_heatmap_plotly — heatmap статусов

Каждая функция возвращает HTML-фрагмент <div> с встроенным Plotly-графиком
(без Plotly CDN — он добавляется один раз в compare_html.py).
"""

import json
import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd

_root = Path(__file__).parent.parent
for _d in [str(_root)]:
    if _d not in sys.path:
        sys.path.insert(0, _d)

from translation import t
from compare_core import (
    get_numeric_series,
    get_drive_mode_durations,
    get_status_matrix,
)
from core_obd import (
    STATUS_COLOR_NO_DATA, STATUS_COLOR_NEUTRAL,
    STATUS_COLOR_OK, STATUS_COLOR_WARNING, STATUS_COLOR_ERROR,
)

logger = logging.getLogger(__name__)

try:
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots
    PLOTLY_AVAILABLE = True
except ImportError:
    PLOTLY_AVAILABLE = False


# ---------------------------------------------------------------------------
# Вспомогательные функции
# ---------------------------------------------------------------------------

def _trip_labels(trip_ids: list[str]) -> list[str]:
    """Укорачивает trip_id до даты для меток осей."""
    return [tid.split(' ')[0] if len(tid) > 10 else tid for tid in trip_ids]


def _to_fig_json(fig: 'go.Figure') -> str:
    """Сериализует фигуру в JSON-спецификацию для lazy-инициализации через Plotly.newPlot."""
    spec = json.loads(fig.to_json())
    spec['config'] = {'responsive': True}
    return json.dumps(spec, ensure_ascii=False).replace('</', '<\\/')


_LAYOUT_DEFAULTS = dict(
    autosize=True,
    paper_bgcolor='#fff',
    plot_bgcolor='#fff',
    font=dict(family='Segoe UI, system-ui, sans-serif', size=12, color='#1a1a1a'),
    margin=dict(l=60, r=20, t=50, b=60),
)


# ---------------------------------------------------------------------------
# Тренды
# ---------------------------------------------------------------------------

def _plot_trends_plotly(vals_df: pd.DataFrame, stats_df: pd.DataFrame) -> str | None:
    """Линейные тренды ключевых параметров по поездкам.

    Подграфики сгруппированы по смыслу (порядок как в синхро-таймлайне):
    RPM → Speed → Load → O2 → Injection → LTFT/STFT → Coolant → Intake.
    Параметры одной группы объединены на одном подграфике (несколько линий).
    """
    if not PLOTLY_AVAILABLE or vals_df.empty:
        return None

    trip_ids = list(vals_df.index)
    xlabels = _trip_labels(trip_ids)

    def _s(code: str) -> np.ndarray:
        return get_numeric_series(vals_df, stats_df, code).values

    # Определения подграфиков: (заголовок, [(values, label, color), ...], ref_type)
    # ref_type: 'fuel' | 'coolant' | None
    subplot_defs = [
        (t('compare.trends.rpm_label'),
            [(_s('RPM_MEAN'),             t('compare.trends.rpm_label'),            '#0277BD')],
            None),
        (t('compare.trends.speed_label'),
            [(_s('SPEED_MEAN'),           t('compare.trends.speed_label'),          '#00838F')],
            None),
        (t('compare.trends.load_label'),
            [(_s('LOAD_MEAN'),            t('compare.trends.load_label'),           '#558B2F')],
            None),
        (t('compare.trends.o2_rich_label') + ' / ' + t('compare.trends.o2_lean_label'),
            [(_s('O2_RICH_TIME'),         t('compare.trends.o2_rich_label'),        '#D32F2F'),
             (_s('O2_LEAN_TIME'),         t('compare.trends.o2_lean_label'),        '#1565C0')],
            None),
        (t('compare.trends.injection_time_label'),
            [(_s('INJECTION_TIME_MEAN'),  t('compare.trends.injection_time_label'), '#6D4C41')],
            None),
        (t('compare.trends.ltft_label') + ' / ' + t('compare.trends.stft_label'),
            [(_s('LTFT_MEAN'),            t('compare.trends.ltft_label'),           '#1976D2'),
             (_s('STFT_MEAN'),            t('compare.trends.stft_label'),           '#F57C00')],
            'fuel'),
        (t('compare.trends.coolant_label') + ' / ' + t('compare.trends.coolant_mean_label'),
            [(_s('ALL_TEMP_COOLANT_Max'), t('compare.trends.coolant_label'),        '#C62828'),
             (_s('COOLANT_MEAN'),         t('compare.trends.coolant_mean_label'),   '#EF9A9A')],
            'coolant'),
        (t('compare.trends.intake_temp_label'),
            [(_s('INTAKE_TEMP_MEAN'),     t('compare.trends.intake_temp_label'),    '#7E57C2')],
            None),
    ]

    # Оставляем только подграфики, где есть хоть одна серия с данными
    active = [
        (title, series, ref) for title, series, ref in subplot_defs
        if any(not np.all(np.isnan(v)) for v, _, _ in series)
    ]
    if not active:
        return None

    n = len(active)
    fig = make_subplots(
        rows=n, cols=1, shared_xaxes=True,
        subplot_titles=[title for title, _, _ in active],
        vertical_spacing=max(0.02, min(0.06, 0.5 / n)),
    )

    for row_i, (_, series, ref_type) in enumerate(active, start=1):
        multi = len([s for s in series if not np.all(np.isnan(s[0]))]) > 1
        for vals, label, color in series:
            mask = ~np.isnan(vals)
            if not mask.any():
                continue
            x_visible = [xlabels[i] for i, m in enumerate(mask) if m]
            y_visible = [float(vals[i]) for i, m in enumerate(mask) if m]
            fig.add_trace(
                go.Scatter(
                    x=x_visible, y=y_visible,
                    mode='lines+markers',
                    line=dict(color=color, width=2),
                    marker=dict(size=8, color=color),
                    name=label,
                    showlegend=multi,
                    legendgroup=f'row{row_i}',
                ),
                row=row_i, col=1,
            )
        if ref_type == 'fuel':
            fig.add_hline(y=0,   line_dash='dot',  line_color='#9e9e9e', line_width=1, row=row_i, col=1)
            fig.add_hline(y= 6,  line_dash='dot',  line_color='#FF7043', line_width=1, row=row_i, col=1)
            fig.add_hline(y=-6,  line_dash='dot',  line_color='#FF7043', line_width=1, row=row_i, col=1)
            fig.add_hline(y= 12, line_dash='dash', line_color='#B71C1C', line_width=1, row=row_i, col=1)
            fig.add_hline(y=-12, line_dash='dash', line_color='#B71C1C', line_width=1, row=row_i, col=1)
        elif ref_type == 'coolant':
            fig.add_hline(y=90,  line_dash='dash', line_color='#4CAF50', line_width=1, row=row_i, col=1,
                          annotation_text=t('compare.trends.norm'))
            fig.add_hline(y=105, line_dash='dash', line_color='#B71C1C', line_width=1, row=row_i, col=1,
                          annotation_text=t('compare.trends.max'))

    fig.update_layout(
        height=240 * n,
        title_text=t('compare.trends.title'),
        title_x=0.5,
        showlegend=True,
        legend=dict(orientation='h', yanchor='bottom', y=1.01, xanchor='right', x=1),
        **_LAYOUT_DEFAULTS,
    )
    fig.update_yaxes(gridcolor='#e0e0e0')
    # Принудительно категориальная ось X — иначе Plotly пытается распарсить
    # строки вида '2026-02-18' как даты и молча пропускает '2026-02-18_2' и т.п.
    fig.update_xaxes(type='category', tickangle=-30)

    return _to_fig_json(fig)


# ---------------------------------------------------------------------------
# Детонация
# ---------------------------------------------------------------------------

def _plot_knock_bars_plotly(vals_df: pd.DataFrame, stats_df: pd.DataFrame) -> str | None:
    """Сгруппированная столбчатая диаграмма детонации по поездкам."""
    if not PLOTLY_AVAILABLE or vals_df.empty:
        return None

    trip_ids = list(vals_df.index)
    xlabels = _trip_labels(trip_ids)

    weak   = np.nan_to_num(get_numeric_series(vals_df, stats_df, 'KNOCK_WEAK_COUNT').values,   nan=0.0)
    medium = np.nan_to_num(get_numeric_series(vals_df, stats_df, 'KNOCK_MEDIUM_COUNT').values, nan=0.0)
    strong = np.nan_to_num(get_numeric_series(vals_df, stats_df, 'KNOCK_STRONG_COUNT').values, nan=0.0)

    if np.all(weak == 0) and np.all(medium == 0) and np.all(strong == 0):
        return None

    fig = go.Figure()
    fig.add_trace(go.Bar(x=xlabels, y=weak,   name=t('compare.knock.weak'),   marker_color='#FFC107'))
    fig.add_trace(go.Bar(x=xlabels, y=medium, name=t('compare.knock.medium'), marker_color='#FF7043'))
    fig.add_trace(go.Bar(x=xlabels, y=strong, name=t('compare.knock.strong'), marker_color='#B71C1C'))

    fig.update_layout(
        barmode='group',
        title_text=t('compare.knock.title'),
        title_x=0.5,
        xaxis=dict(type='category', tickangle=-30),
        yaxis=dict(title=t('compare.knock.y_axis'), gridcolor='#e0e0e0'),
        legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='right', x=1),
        height=380,
        **_LAYOUT_DEFAULTS,
    )
    return _to_fig_json(fig)


# ---------------------------------------------------------------------------
# Режимы езды
# ---------------------------------------------------------------------------

def _plot_mode_durations_plotly(vals_df: pd.DataFrame) -> str | None:
    """Стековая диаграмма длительностей режимов езды по поездкам."""
    if not PLOTLY_AVAILABLE or vals_df.empty:
        return None

    durations_df = get_drive_mode_durations(vals_df)
    if durations_df.isna().all().all():
        return None

    durations_df = durations_df.fillna(0.0)
    xlabels = _trip_labels(list(durations_df.index))
    colors = ['#4CAF50', '#2196F3', '#FF9800', '#9C27B0']

    fig = go.Figure()
    for col, color in zip(durations_df.columns, colors):
        fig.add_trace(go.Bar(
            x=xlabels,
            y=durations_df[col].values,
            name=col,
            marker_color=color,
        ))

    fig.update_layout(
        barmode='stack',
        title_text=t('compare.modes.title'),
        title_x=0.5,
        xaxis=dict(type='category', tickangle=-30),
        yaxis=dict(title=t('compare.modes.y_axis'), gridcolor='#e0e0e0'),
        legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='right', x=1),
        height=380,
        **_LAYOUT_DEFAULTS,
    )
    return _to_fig_json(fig)


# ---------------------------------------------------------------------------
# Heatmap статусов
# ---------------------------------------------------------------------------

_STATUS_COLORSCALE = [
    [0.00, STATUS_COLOR_NO_DATA],   # -1 → нет данных
    [0.25, STATUS_COLOR_NEUTRAL],   # 0 → нейтральный
    [0.50, STATUS_COLOR_OK],        # 1 → OK
    [0.75, STATUS_COLOR_WARNING],   # 2 → WARNING
    [1.00, STATUS_COLOR_ERROR],     # 3 → ERROR
]

_STATUS_TEXT = {-1: '', 0: '○', 1: 'ok', 2: '!!', 3: 'err'}


def _plot_status_heatmap_plotly(vals_df: pd.DataFrame, stats_df: pd.DataFrame) -> str | None:
    """Heatmap статусов ключевых метрик: строки=метрики, столбцы=поездки."""
    if not PLOTLY_AVAILABLE or vals_df.empty:
        return None

    matrix_df, labels = get_status_matrix(vals_df, stats_df)
    if matrix_df.empty:
        return None

    trip_ids = list(matrix_df.columns)
    xlabels = _trip_labels(trip_ids)

    z = matrix_df.values.tolist()
    text = [[_STATUS_TEXT.get(int(v), '') for v in row] for row in z]

    # Нормализуем значения -1..3 в диапазон 0..1 для colorscale
    z_norm = [[(v + 1) / 4 for v in row] for row in z]

    _heatmap_kwargs = dict(
        z=z_norm,
        x=xlabels,
        y=labels,
        text=text,
        colorscale=_STATUS_COLORSCALE,
        showscale=False,
        zmin=0, zmax=1,
        hovertemplate='%{y}<br>%{x}<extra></extra>',
        xgap=2, ygap=2,
    )
    try:
        heatmap = go.Heatmap(texttemplate='%{text}', **_heatmap_kwargs)
    except (ValueError, TypeError):
        # texttemplate not supported in older Plotly versions
        heatmap = go.Heatmap(**_heatmap_kwargs)
    fig = go.Figure(data=heatmap)

    n_metrics = len(labels)
    cell_h = max(28, min(50, 500 // n_metrics))
    fig_height = max(250, n_metrics * cell_h + 120)

    fig.update_layout(
        title_text=t('compare.heatmap.title'),
        title_x=0.5,
        xaxis=dict(type='category', tickangle=-30),
        yaxis=dict(autorange='reversed'),
        height=fig_height,
        **_LAYOUT_DEFAULTS,
    )

    # Легенда цветов (аннотации)
    legend_items = [
        ('#C8E6C9', t('compare.heatmap.ok')),
        ('#FFE0B2', t('compare.heatmap.warning')),
        ('#FFCDD2', t('compare.heatmap.error')),
        ('#CFD8DC', t('compare.heatmap.neutral')),
        ('#FFFFFF', t('compare.heatmap.no_data')),
    ]
    annotations = []
    x_pos = 0.0
    for color, name in legend_items:
        annotations.append(dict(
            x=x_pos, y=-0.1,
            xref='paper', yref='paper',
            text=f'<span style="background:{color};padding:2px 6px;border:1px solid #ccc;border-radius:3px;">&nbsp;</span> {name}',
            showarrow=False,
            font=dict(size=11),
            xanchor='left',
        ))
        x_pos += 0.2
    fig.update_layout(annotations=annotations)

    return _to_fig_json(fig)


# ---------------------------------------------------------------------------
# Генерация всех графиков
# ---------------------------------------------------------------------------

def generate_all_plotly_html(
    vals_df: pd.DataFrame,
    stats_df: pd.DataFrame,
) -> dict[str, str]:
    """Генерирует все Plotly-графики, возвращает словарь {name: html_div}.

    Имена соответствуют ключам в png_paths: 'trends', 'knock', 'modes', 'heatmap'.
    """
    if not PLOTLY_AVAILABLE:
        logger.debug('compare_plotly: plotly не установлен, пропуск')
        return {}

    results: dict[str, str] = {}

    for name, fn, args in [
        ('trends',  _plot_trends_plotly,          (vals_df, stats_df)),
        ('knock',   _plot_knock_bars_plotly,       (vals_df, stats_df)),
        ('modes',   _plot_mode_durations_plotly,   (vals_df,)),
        ('heatmap', _plot_status_heatmap_plotly,   (vals_df, stats_df)),
    ]:
        try:
            html_div = fn(*args)  # type: ignore[operator]
            if html_div:
                results[name] = html_div
        except (ValueError, KeyError, TypeError) as e:
            logger.error(f'Ошибка compare Plotly [{name}]: {e}', exc_info=True)

    return results
