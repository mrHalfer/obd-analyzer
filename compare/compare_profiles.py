#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Загрузка и отображение профилей скорости для HTML-отчёта сравнения поездок OBD-II.

Две вкладки:
- «Профили»        — аккордеон с таблицей: бины × поездки по каждой метрике.
- «Тренды профилей» — аккордеон с Plotly-графиками (бины на X, параметры в подграфиках).
"""

import html as html_module
import json
import logging
import re
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

logger = logging.getLogger(__name__)

try:
    import plotly.graph_objects as go
    _PLOTLY_AVAILABLE = True
except ImportError:
    _PLOTLY_AVAILABLE = False


# ---------------------------------------------------------------------------
# Загрузка файлов
# ---------------------------------------------------------------------------

def _extract_trip_id(profile_path: Path) -> str:
    """Извлекает trip_id из имени файла *_profile.csv."""
    name = re.sub(r'_profile$', '', profile_path.stem)
    m = re.search(r'(\d{4}-\d{2}-\d{2})(?:[_T](\d{2}[-:]\d{2}))?', name)
    if m:
        date_part = m.group(1)
        time_part = m.group(2)
        if time_part:
            return f'{date_part} {time_part.replace("-", ":")}'
        return date_part
    return name


def load_profiles(directory: Path) -> dict[str, pd.DataFrame]:
    """Загружает все *_profile.csv из директории.

    Returns:
        Словарь {trip_id: DataFrame}, отсортированный по trip_id.
        Пустой словарь, если файлы не найдены.
    """
    result: dict[str, pd.DataFrame] = {}
    for pf in sorted(directory.glob('*_profile.csv')):
        trip_id = _extract_trip_id(pf)
        df = None
        for enc in ('utf-8-sig', 'cp1251'):
            try:
                df = pd.read_csv(pf, encoding=enc)
                break
            except (pd.errors.ParserError, UnicodeDecodeError, OSError):
                continue
        if df is None or df.empty:
            continue
        # Дедупликация trip_id
        if trip_id in result:
            suffix = 2
            while f'{trip_id}_{suffix}' in result:
                suffix += 1
            trip_id = f'{trip_id}_{suffix}'
        result[trip_id] = df
        logger.debug(f'Загружен профиль скорости: {pf.name} → {trip_id}')
    return result


# ---------------------------------------------------------------------------
# Вспомогательные утилиты
# ---------------------------------------------------------------------------

def _speed_bin_label(row: pd.Series, col0: str, col1: str) -> str:
    """Формирует метку скоростного бина вида '10–15'."""
    try:
        lo = int(float(row[col0]))
        hi = int(float(row[col1]))
        return f'{lo}–{hi}'
    except (ValueError, TypeError):
        return str(row[col0])


def _fmt(val: Any, decimals: int = 1) -> str:
    """Форматирует число с заданной точностью или возвращает '—' для NaN."""
    try:
        f = float(val)
        if np.isnan(f):
            return '—'
        return f'{f:.{decimals}f}'
    except (ValueError, TypeError):
        return '—'


# ---------------------------------------------------------------------------
# Общий сбор данных из всех профилей
# ---------------------------------------------------------------------------

def _prepare_profile_data(
    profiles: dict[str, pd.DataFrame],
) -> tuple[list[str], list[str], list[str], dict[str, dict[str, dict[str, str]]]] | None:
    """Собирает метрики, бины и данные из ВСЕХ профилей.

    Бины собираются из каждой поездки, чтобы учесть разные диапазоны скоростей.

    Returns:
        (metric_cols, bins_order, trip_ids, data) или None если нет данных.
        data[bin_label][trip_id][metric_col] = formatted_value
    """
    if not profiles:
        return None

    # Список метрик — берём из первого профиля с достаточным кол-вом колонок
    metric_cols: list[str] = []
    for df in profiles.values():
        if len(df.columns) >= 3:
            metric_cols = list(df.columns)[2:]
            break
    if not metric_cols:
        return None

    # Бины — собираем ИЗ ВСЕХ поездок
    bins_min: dict[str, float] = {}
    for df in profiles.values():
        if df.empty or len(df.columns) < 2:
            continue
        cols = list(df.columns)
        for _, row in df.iterrows():
            label = _speed_bin_label(row, cols[0], cols[1])
            if label not in bins_min:
                try:
                    bins_min[label] = float(row[cols[0]])
                except (ValueError, TypeError):
                    bins_min[label] = 0.0

    if not bins_min:
        return None

    bins_order = sorted(bins_min.keys(), key=lambda lbl: bins_min[lbl])
    trip_ids = list(profiles.keys())

    # data[bin_label][trip_id][metric_col] = fmt_value
    data: dict[str, dict[str, dict[str, str]]] = {b: {} for b in bins_order}
    for trip_id, df in profiles.items():
        if df.empty or len(df.columns) < 2:
            continue
        cols = list(df.columns)
        for _, row in df.iterrows():
            label = _speed_bin_label(row, cols[0], cols[1])
            if label not in data:
                continue
            data[label][trip_id] = {
                c: _fmt(row[c]) if c in df.columns else '—'
                for c in metric_cols
            }

    return metric_cols, bins_order, trip_ids, data


# ---------------------------------------------------------------------------
# Вкладка «Профили» — один аккордеон-раздел на скоростной бин
# ---------------------------------------------------------------------------

def build_profiles_table_html(profiles: dict[str, pd.DataFrame]) -> str:
    """Строит аккордеон: один раздел на скоростной бин.

    В каждом разделе — таблица вида:
        Метрика | Поездка1 | Поездка2 | ...
    с одной строкой на каждую метрику профиля.
    """
    prepared = _prepare_profile_data(profiles)
    if prepared is None:
        return f'<p class="no-data-msg">{html_module.escape(t("compare.profiles.no_data"))}</p>'

    metric_cols, bins_order, trip_ids, data = prepared

    metric_col_label = html_module.escape(t('compare.profiles.metric_col'))
    th_trips = ''.join(
        f'<th data-col="{i}">{html_module.escape(str(tid))}</th>'
        for i, tid in enumerate(trip_ids)
    )
    thead = f'<thead><tr><th class="metric-col">{metric_col_label}</th>{th_trips}</tr></thead>'

    parts: list[str] = []
    for i, bin_label in enumerate(bins_order):
        bin_data = data[bin_label]
        tbody_rows: list[str] = []
        for metric in metric_cols:
            tds = ''.join(
                f'<td data-col="{ci}">{bin_data.get(tid, {}).get(metric, "—")}</td>'
                for ci, tid in enumerate(trip_ids)
            )
            tbody_rows.append(
                f'<tr><td class="metric-name">{html_module.escape(str(metric))}</td>{tds}</tr>'
            )
        tbody = '<tbody>' + ''.join(tbody_rows) + '</tbody>'
        table = (
            '<div class="compare-table-wrap" data-tscope="profiles">'
            f'<table class="compare-table profile-table">{thead}{tbody}</table>'
            '</div>'
        )
        open_attr = ' open' if i == 0 else ''
        speed_label = html_module.escape(f'{bin_label} {t("compare.profiles.speed_unit")}')
        parts.append(
            f'<details class="accordion-item"{open_attr}>'
            f'<summary>{speed_label}</summary>'
            f'<div class="accordion-body">{table}</div>'
            '</details>'
        )

    if not parts:
        return f'<p class="no-data-msg">{html_module.escape(t("compare.profiles.no_data"))}</p>'
    return '\n'.join(parts)


# ---------------------------------------------------------------------------
# Вкладка «Тренды профилей» — один аккордеон-раздел на скоростной бин
# ---------------------------------------------------------------------------

_TRIP_COLORS = [
    '#1976D2', '#F57C00', '#2E7D32', '#C62828',
    '#7B1FA2', '#00838F', '#558B2F', '#6D4C41',
    '#0288D1', '#AD1457', '#37474F', '#F9A825',
]

try:
    from plotly.subplots import make_subplots as _make_subplots
except ImportError:
    _make_subplots = None  # type: ignore[assignment]


def _build_bin_chart_plotly(
    bin_label: str,
    metric_cols: list[str],
    bin_data: dict[str, dict[str, str]],
    trip_ids: list[str],
    chart_id: str,
) -> tuple[str, int] | None:
    """Plotly-фигура для одного скоростного бина.

    Возвращает HTML-фрагмент: placeholder-div + <script type="application/json">
    со спецификацией фигуры. Инициализация — через JS в родительском документе
    (Plotly.newPlot вызывается на div в родительском DOM, без iframe).

    Returns:
        (html_fragment, height) или None если нет данных.
    """
    if not _PLOTLY_AVAILABLE or _make_subplots is None:
        return None

    active_metrics = [
        m for m in metric_cols
        if any(
            bin_data.get(tid, {}).get(m, '—') not in ('—', '')
            for tid in trip_ids
        )
    ]
    if not active_metrics:
        return None

    n = len(active_metrics)
    fig = _make_subplots(
        rows=n, cols=1,
        shared_xaxes=True,
        subplot_titles=active_metrics,
        vertical_spacing=max(0.02, min(0.06, 0.5 / n)),
    )

    xlabels = [tid.split(' ')[0] if len(tid) > 10 else tid for tid in trip_ids]

    for row_i, metric in enumerate(active_metrics, start=1):
        for col_j, (tid, xlabel) in enumerate(zip(trip_ids, xlabels)):
            raw = bin_data.get(tid, {}).get(metric, '—')
            try:
                y_val = float(raw) if raw not in ('—', '') else None
            except (ValueError, TypeError):
                y_val = None

            color = _TRIP_COLORS[col_j % len(_TRIP_COLORS)]
            fig.add_trace(
                go.Bar(
                    x=[xlabel],
                    y=[y_val if y_val is not None else 0],
                    name=tid,
                    marker_color=color,
                    opacity=0.85,
                    showlegend=(row_i == 1),
                    legendgroup=tid,
                    text=[f'{y_val:.1f}' if y_val is not None else ''],
                    textposition='outside',
                ),
                row=row_i, col=1,
            )

    height = max(280, 220 * n)
    fig.update_layout(
        autosize=True,
        paper_bgcolor='#fff',
        plot_bgcolor='#fff',
        font=dict(family='Segoe UI, system-ui, sans-serif', size=11),
        margin=dict(l=60, r=20, t=60, b=50),
        height=height,
        barmode='group',
        legend=dict(orientation='h', yanchor='bottom', y=1.01, xanchor='right', x=1),
        showlegend=True,
        title_text=bin_label,
        title_x=0.5,
    )
    fig.update_xaxes(type='category', gridcolor='#e0e0e0')
    fig.update_yaxes(gridcolor='#e0e0e0')

    # Сериализуем в JSON; экранируем </script> чтобы не сломать тег.
    fig_json = json.loads(fig.to_json())
    fig_json['config'] = {'responsive': True}
    spec = json.dumps(fig_json, ensure_ascii=False).replace('</', '<\\/')

    html_fragment = (
        f'<div id="{chart_id}" class="lazy-chart" style="height:{height}px"></div>'
        f'<script type="application/json" id="{chart_id}-spec">{spec}</script>'
    )
    return html_fragment, height


def _build_bin_table_fallback(
    metric_cols: list[str],
    bin_data: dict[str, dict[str, str]],
    trip_ids: list[str],
) -> str:
    """Fallback без Plotly: таблица метрик × поездок для одного бина."""
    metric_col_label = html_module.escape(t('compare.profiles.metric_col'))
    th_trips = ''.join(f'<th>{html_module.escape(tid)}</th>' for tid in trip_ids)
    header = f'<tr><th class="metric-col">{metric_col_label}</th>{th_trips}</tr>'
    rows = []
    for metric in metric_cols:
        tds = ''.join(
            f'<td>{bin_data.get(tid, {}).get(metric, "—")}</td>' for tid in trip_ids
        )
        rows.append(f'<tr><td class="metric-name">{html_module.escape(str(metric))}</td>{tds}</tr>')
    return (
        '<div class="compare-table-wrap">'
        f'<table class="compare-table profile-table">'
        f'<thead>{header}</thead><tbody>{"".join(rows)}</tbody></table></div>'
    )


def build_profile_trends_html(
    profiles: dict[str, pd.DataFrame],
    plotly_available: bool = True,
) -> str:
    """Аккордеон по скоростным бинам с lazy-загрузкой iframe.

    Каждый раздел = один бин (e.g. '30–35 км/ч').
    Внутри — iframe с data-src (загружается при открытии аккордеона).
    iframe содержит полный HTML-документ, Plotly берётся из родительского окна.
    Fallback без Plotly: таблица.
    """
    prepared = _prepare_profile_data(profiles)
    if prepared is None:
        return f'<p class="no-data-msg">{html_module.escape(t("compare.profiles.no_data"))}</p>'

    metric_cols, bins_order, trip_ids, data = prepared

    parts: list[str] = []
    for i, bin_label in enumerate(bins_order):
        bin_data = data[bin_label]
        if not bin_data:
            continue

        if _PLOTLY_AVAILABLE and plotly_available:
            chart_id = f'pchart-{i}'
            result = _build_bin_chart_plotly(bin_label, metric_cols, bin_data, trip_ids, chart_id)
            if result is None:
                continue
            chart_fragment, chart_h = result
            chart_content = f'<div class="chart-wrap" style="min-height:{chart_h}px">{chart_fragment}</div>'
        else:
            chart_content = _build_bin_table_fallback(metric_cols, bin_data, trip_ids)

        open_attr = ' open' if i == 0 else ''
        speed_label = html_module.escape(f'{bin_label} {t("compare.profiles.speed_unit")}')
        parts.append(
            f'<details class="accordion-item"{open_attr}>'
            f'<summary>{speed_label}</summary>'
            f'<div class="accordion-body">{chart_content}</div>'
            '</details>'
        )

    if not parts:
        return f'<p class="no-data-msg">{html_module.escape(t("compare.profiles.no_data"))}</p>'
    return '\n'.join(parts)


# ---------------------------------------------------------------------------
# CSV-экспорт профилей: строки = скоростной_бин / метрика, столбцы = поездки
# ---------------------------------------------------------------------------

def build_profiles_csv(
    output_dir: Path,
    profiles: dict[str, pd.DataFrame],
) -> Path | None:
    """Генерирует comparison_profiles.csv.

    Структура:
      - Столбец 1: скоростной бин (e.g. «0–5»)
      - Столбец 2: название метрики
      - Столбцы 3+: значения по каждой поездке (trip_id = дата)

    Args:
        output_dir: Директория для сохранения файла.
        profiles:   Словарь {trip_id: DataFrame}, результат load_profiles().

    Returns:
        Путь к CSV-файлу или None при ошибке / отсутствии данных.
    """
    prepared = _prepare_profile_data(profiles)
    if prepared is None:
        return None

    metric_cols, bins_order, trip_ids, data = prepared

    speed_bin_col = t('compare.profiles.speed_col')
    metric_col_hdr = t('compare.profiles.metric_col')

    rows: list[dict[str, object]] = []
    for bin_label in bins_order:
        bin_data = data[bin_label]
        for metric in metric_cols:
            row: dict[str, object] = {
                speed_bin_col: bin_label,
                metric_col_hdr: metric,
            }
            for tid in trip_ids:
                val = bin_data.get(tid, {}).get(metric, '')
                row[tid] = val if val not in ('—', '') else ''
            rows.append(row)

    out_path = output_dir / 'comparison_profiles.csv'
    try:
        pd.DataFrame(rows).to_csv(str(out_path), index=False, encoding='utf-8-sig')
        logger.info(t('console.compare_profiles_csv_saved', path=out_path))
        return out_path
    except OSError as e:
        logger.error(f'Ошибка создания CSV профилей: {e}', exc_info=True)
        return None
