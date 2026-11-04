#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Модуль генерации интерактивных Plotly-графиков для анализа OBD-II данных.

Содержит:
- 14 функций построения графиков (2D и 3D)
- Вспомогательные функции (downsample, finalize)
- Построитель всех графиков для отчёта
- Сохранение отдельных HTML-страниц с плотами
"""

import logging
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

import sys as _sys
from pathlib import Path as _Path
_root = _Path(__file__).parent.parent
for _d in [str(_root), str(_root / 'build'), str(_root / 'plugins')]:
    if _d not in _sys.path:
        _sys.path.insert(0, _d)

from core_obd import (
    LOG_DT,
    PLOTLY_AVAILABLE,
    get_time_axis_minutes,
)
from translation import t

logger = logging.getLogger(__name__)

if PLOTLY_AVAILABLE:
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots

# Множитель лимита записей для плотов (1 = обычный, 3 = отдельные HTML-страницы)
_POINTS_MULTIPLIER: int = 1

# ---------------------------------------------------------------------------
# Вспомогательные функции
# ---------------------------------------------------------------------------

def _get_adaptive_step(df: pd.DataFrame, max_points: int | None = None) -> int:
    """Вычисляет адаптивный шаг прореживания на основе длительности поездки.

    Целевая частота дискретизации:
    - < 30 мин: 3 записи/сек
    - 30-90 мин: 2 записи/сек
    - > 90 мин: 1 запись/сек

    Финальная частота умножается на _POINTS_MULTIPLIER (3x для отдельных HTML-файлов).

    Args:
        df: DataFrame для прореживания.
        max_points: Опциональный максимальный лимит точек (для 3D-графиков).

    Returns:
        Шаг прореживания (step для df.iloc[::step]).
    """
    if len(df) == 0:
        return 1

    # Вычисляем длительность поездки в минутах
    duration_min = len(df) * LOG_DT / 60.0

    # Определяем целевую частоту (записей в секунду)
    if duration_min < 30:
        target_freq = 3
    elif duration_min < 90:
        target_freq = 2
    else:
        target_freq = 1

    # Увеличиваем частоту для отдельных HTML-файлов
    target_freq *= _POINTS_MULTIPLIER

    # Исходная частота записей в секунду (зависит от LOG_DT)
    original_freq = 1.0 / LOG_DT

    # Вычисляем шаг прореживания
    step = max(1, int(round(original_freq / target_freq)))

    # Если задан максимальный лимит точек — выбираем больший шаг
    if max_points is not None:
        step_for_limit = max(1, len(df) // max_points)
        step = max(step, step_for_limit)

    return step


def _downsample(df: pd.DataFrame) -> pd.DataFrame:
    """Адаптивно прореживает DataFrame в зависимости от длительности поездки.

    Целевая частота дискретизации:
    - < 30 мин: 3 записи/сек
    - 30-90 мин: 2 записи/сек
    - > 90 мин: 1 запись/сек
    """
    step = _get_adaptive_step(df)
    return df.iloc[::step]


# JS контекстного меню «Показать на карте» для графиков, встроенных в iframe единого отчёта.
# Сам-проверяет: window === window.parent → standalone-файл, меню не активируется.
# Проверяет наличие вкладки Карта через postMessage-зондирование родительского окна.
_SCRIPT_DIR = Path(__file__).parent
with open(_SCRIPT_DIR / 'build_plotly.js', encoding='utf-8') as _f:
    _IFRAME_CTX_MENU_JS = '<script>' + _f.read() + '</script>'


def _finalize_chart(fig: Any, return_html: bool, output_dir: Path, base_name: str, suffix: str, label: str,
                    map_nav: bool = False) -> str | None:
    """Финализирует Plotly-график: возвращает HTML или сохраняет в файл.

    map_nav=True — инжектирует JS контекстного меню «Показать на карте» (только для графиков с временной осью X).
    """
    if return_html:
        html_str = fig.to_html(full_html=True)
        if map_nav:
            html_str = html_str.replace('</body>', _IFRAME_CTX_MENU_JS + '</body>', 1)
        return html_str
    out_path = output_dir / f'{base_name}_{suffix}.html'
    fig.write_html(str(out_path), include_plotlyjs=True)
    logger.info(t('console.plotly_saved', label=label, path=out_path))
    return None

# ---------------------------------------------------------------------------
# Интерактивные графики Plotly
# ---------------------------------------------------------------------------
def _plotly_synchronized_timeline(df_clean: pd.DataFrame, output_dir: Path, base_name: str, return_html: bool = False) -> str | None:
    """Синхронизированный таймлайн: RPM, SPEED, MAF, O2 датчики, топливные коррекции, температуры."""
    required = ['RPM', 'SPEED']
    if not all(col in df_clean.columns for col in required):
        return None

    df_sampled = _downsample(df_clean)
    # Ось X: реальное время суток если доступно, иначе — минуты с начала
    use_dtick = False
    if 'TIME' in df_sampled.columns and df_sampled['TIME'].notna().any():
        try:
            metrics_csv = output_dir / f'{base_name}_metrics.csv'
            mdf = pd.read_csv(metrics_csv)
            run_date = mdf.loc[mdf['CODE'] == 'RUN_DATE', 'VAL'].iloc[0]
            date_str = str(run_date) + ' '
        except (pd.errors.ParserError, UnicodeDecodeError, OSError, IndexError, KeyError):
            date_str = ''
        x = pd.to_datetime(date_str + df_sampled['TIME'].astype(str).str[:8], errors='coerce')
        x_label = t('common.time_of_day')
    else:
        x = df_sampled.index.values * LOG_DT / 60.0
        x_label = t('common.time_min')
        use_dtick = True

    # Синхронизированный таймлайн с общей шкалой X и зумированием по ней
    subplot_titles = (
        t('plotly.timeline.row1'), t('plotly.timeline.row2'), t('plotly.timeline.row3'),
        t('plotly.timeline.row4'), t('plotly.timeline.row5'), t('plotly.timeline.row6'),
    )
    fig = make_subplots(rows=6, cols=1, shared_xaxes=True,
                       subplot_titles=subplot_titles,
                       vertical_spacing=0.02)

    # Row 1: Обороты (RPM)
    fig.add_trace(go.Scatter(x=x, y=df_sampled['RPM'], name='RPM',
                            line=dict(color='#1f77b4', width=2)), row=1, col=1)

    # Row 2: Скорость (SPEED)
    fig.add_trace(go.Scatter(x=x, y=df_sampled['SPEED'], name='Speed',
                            line=dict(color='#2ca02c', width=2)), row=2, col=1)

    # Row 3: Расход воздуха (MAF)
    if 'MAF' in df_sampled.columns:
        fig.add_trace(go.Scatter(x=x, y=df_sampled['MAF'], name='MAF',
                                line=dict(color='#9467bd', width=2)), row=3, col=1)

    # Row 4: Датчики кислорода (O2 Sensors) — на одном графике с нормами
    if 'O2_B1S1' in df_sampled.columns:
        fig.add_trace(go.Scatter(x=x, y=df_sampled['O2_B1S1'], name=t('plotly.timeline.dk1'),
                                line=dict(color='#ff7f0e', width=1)), row=4, col=1)
    if 'O2_B1S2' in df_sampled.columns:
        fig.add_trace(go.Scatter(x=x, y=df_sampled['O2_B1S2'], name=t('plotly.timeline.dk2'),
                                line=dict(color='#1f77b4', width=2)), row=4, col=1)
    if 'O2_B1S1' in df_sampled.columns or 'O2_B1S2' in df_sampled.columns:
        fig.add_hline(y=0.65, line_dash='dash', line_color='green', row=4, col=1)
        fig.add_hline(y=0.85, line_dash='dash', line_color='green', row=4, col=1,
                      annotation_text=t('plotly.timeline.dk2_norm'))
        fig.update_yaxes(range=[0, 1], row=4, col=1)

    # Row 5: Коррекции топлива (STFT и LTFT на одном графике с нормами)
    has_ltft = ('LTFT_PERCENT' in df_sampled.columns) or ('LTFT' in df_sampled.columns)
    has_stft = 'STFT_PERCENT' in df_sampled.columns
    if has_stft:
        fig.add_trace(go.Scatter(x=x, y=df_sampled['STFT_PERCENT'], name='STFT',
                                line=dict(color="#ff7f0e", width=2)), row=5, col=1)
    if has_ltft:
        ltft_data = df_sampled['LTFT_PERCENT'] if 'LTFT_PERCENT' in df_sampled.columns else (df_sampled['LTFT'] - 1) * 100
        fig.add_trace(go.Scatter(x=x, y=ltft_data, name='LTFT',
                                line=dict(color="#1f77b4", width=2)), row=5, col=1)
    if has_stft or has_ltft:
        fig.add_hline(y=12, line_dash='dash', line_color='#d62728', row=5, col=1)
        fig.add_hline(y=-12, line_dash='dash', line_color='#d62728', row=5, col=1)
        fig.add_hline(y=6, line_dash='dot', line_color="#ff7f0e", row=5, col=1,
                      annotation_text=t('plotly.timeline.lean'))
        fig.add_hline(y=-6, line_dash='dot', line_color="#ff7f0e", row=5, col=1,
                      annotation_text=t('plotly.timeline.rich'))
        fig.update_yaxes(range=[-20, 20], row=5, col=1)

    # Row 6: Температурный профиль (COOLANT и INTAKE на одном графике)
    if 'COOLANT_TEMP' in df_sampled.columns:
        fig.add_trace(go.Scatter(x=x, y=df_sampled['COOLANT_TEMP'], name=t('plotly.timeline.coolant'),
                                line=dict(color='#d62728', width=2)), row=6, col=1)
        fig.add_hline(y=90, line_dash='dash', line_color='green', row=6, col=1,
                      annotation_text=t('plotly.timeline.coolant_norm'))
        fig.add_hline(y=105, line_dash='dash', line_color='red', row=6, col=1,
                      annotation_text=t('plotly.timeline.coolant_max'))
    if 'INTAKE_TEMP' in df_sampled.columns:
        fig.add_trace(go.Scatter(x=x, y=df_sampled['INTAKE_TEMP'], name=t('plotly.timeline.intake'),
                                line=dict(color="#1f77b4", width=2)), row=6, col=1)

    # Глобальные настройки оформления
    fig.update_layout(
        title=t('plotly.timeline.title'),
        height=1400,
        showlegend=True,
        legend=dict(orientation='h', yanchor='bottom', y=-0.1, xanchor='center', x=0.5)
    )

    # Подписи осей X для всех рядов
    fig.update_xaxes(title_text=x_label, row=6, col=1)
    if use_dtick:
        fig.update_xaxes(dtick=1)

    return _finalize_chart(fig, return_html, output_dir, base_name,
                          'viz_synchronized_timeline_plotly',
                          t('plotly.chart_labels.timeline'), map_nav=True)


def _plotly_knock_heatmap(df_clean: pd.DataFrame, output_dir: Path, base_name: str, return_html: bool = False) -> str | None:
    """Интерактивная heatmap детонации RPM vs ENGINE_LOAD."""
    if 'KNOCK_RETARD' not in df_clean.columns or 'RPM' not in df_clean.columns or 'ENGINE_LOAD' not in df_clean.columns:
        return None

    kdf = df_clean[(df_clean['KNOCK_RETARD'] > 1) & df_clean['RPM'].notna() & df_clean['ENGINE_LOAD'].notna()].copy()
    if kdf.empty:
        return None
    rpm_max = max(4000, int(np.nanmax(kdf['RPM']) + 200))
    rpm_bins = np.arange(0, rpm_max + 1, 250)
    load_bins = np.arange(0, 101, 5)
    hist, xedges, yedges = np.histogram2d(kdf['RPM'], kdf['ENGINE_LOAD'], bins=[rpm_bins, load_bins])
    fig = go.Figure(data=go.Heatmap(
        z=hist.T, x=xedges[:-1], y=yedges[:-1], colorscale='Inferno',
        colorbar=dict(title=t('plotly.knock_heatmap.colorbar')),
    ))
    fig.update_layout(
        title=t('plotly.knock_heatmap.title'),
        xaxis_title='RPM',
        yaxis_title=t('plotly.knock_heatmap.y_axis'),
        height=700,
    )
    return _finalize_chart(fig, return_html, output_dir, base_name,
                           'viz_knock_heatmap_plotly', t('plotly.chart_labels.knock_heatmap'))


def _plotly_ltft_stft_hist(df_clean: pd.DataFrame, output_dir: Path, base_name: str, return_html: bool = False) -> str | None:
    """Интерактивные гистограммы LTFT/STFT."""
    has_ltft = ('LTFT_PERCENT' in df_clean.columns) or ('LTFT' in df_clean.columns)
    has_stft = 'STFT_PERCENT' in df_clean.columns
    if not (has_ltft or has_stft):
        return None

    df_sampled = _downsample(df_clean)
    fig = go.Figure()
    if has_ltft:
        if 'LTFT_PERCENT' in df_sampled.columns:
            ltft = df_sampled['LTFT_PERCENT'].dropna()
        else:
            ltft_raw = df_sampled['LTFT'].dropna()
            ltft = (ltft_raw - 1.0) * 100.0 if not ltft_raw.empty else pd.Series(dtype=float)
        if not ltft.empty:
            fig.add_trace(go.Histogram(x=ltft, name='LTFT (%)', opacity=0.6, nbinsx=40))
    if has_stft:
        stft = df_sampled['STFT_PERCENT'].dropna()
        if not stft.empty:
            fig.add_trace(go.Histogram(x=stft, name='STFT (%)', opacity=0.6, nbinsx=40))
    fig.update_layout(
        title=t('plotly.ltft_stft_hist.title'),
        xaxis_title=t('plotly.ltft_stft_hist.x_axis'),
        barmode='overlay',
        height=400,
    )
    return _finalize_chart(fig, return_html, output_dir, base_name,
                           'viz_ltft_stft_hist_plotly', t('plotly.chart_labels.ltft_stft'))


def _plotly_correlation_matrix(df_clean: pd.DataFrame, output_dir: Path, base_name: str, return_html: bool = False) -> str | None:
    """Интерактивная матрица корреляций ключевых параметров."""
    params = ['RPM', 'SPEED', 'ENGINE_LOAD', 'MAF', 'THROTTLE_POS', 'COOLANT_TEMP']
    available = [p for p in params if p in df_clean.columns]
    if len(available) < 3:
        return None

    corr = df_clean[available].corr()
    fig = go.Figure(data=go.Heatmap(
        z=corr.values, x=available, y=available, colorscale='RdBu', zmin=-1, zmax=1,
        colorbar=dict(title=t('plotly.corr_matrix.colorbar')),
    ))
    fig.update_layout(title=t('plotly.corr_matrix.title'), height=700)
    return _finalize_chart(fig, return_html, output_dir, base_name,
                           'viz_corr_matrix_plotly', t('plotly.chart_labels.corr_matrix'))


def _plotly_engine_load(df_clean: pd.DataFrame, output_dir: Path, base_name: str, return_html: bool = False) -> str | None:
    """Интерактивный 4-панельный анализ нагрузки двигателя."""
    if 'ENGINE_LOAD' not in df_clean.columns or 'RPM' not in df_clean.columns:
        return None

    df_sampled = _downsample(df_clean)
    subplot_titles = (
        t('plotly.engine_load.subplot1'), t('plotly.engine_load.subplot2'),
        t('plotly.engine_load.subplot3'), t('plotly.engine_load.subplot4'),
    )
    fig = make_subplots(rows=2, cols=2, subplot_titles=subplot_titles)
    mk = dict(size=4, opacity=0.6)
    if 'COOLANT_TEMP' in df_sampled.columns:
        mk['color'] = df_sampled['COOLANT_TEMP']
        mk['colorscale'] = 'Viridis'
    fig.add_trace(go.Scatter(x=df_sampled['RPM'], y=df_sampled['ENGINE_LOAD'],
                             mode='markers', marker=mk, name=''), row=1, col=1)
    load_data = df_sampled['ENGINE_LOAD'].dropna()
    fig.add_trace(go.Histogram(x=load_data, nbinsx=50, name=t('plotly.engine_load.hist_name')), row=1, col=2)
    if 'REGIME' in df_sampled.columns:
        regimes = df_sampled['REGIME'].unique()
        means = [df_sampled[df_sampled['REGIME'] == r]['ENGINE_LOAD'].mean() for r in regimes]
        fig.add_trace(go.Bar(x=list(regimes), y=means, name=t('plotly.engine_load.bar_name')), row=2, col=1)
        regime_data = [df_sampled[df_sampled['REGIME'] == r]['ENGINE_LOAD'].dropna().values for r in regimes if len(df_sampled[df_sampled['REGIME'] == r]) > 10]
        regime_labels = [r for r in regimes if len(df_sampled[df_sampled['REGIME'] == r]) > 10]
        if regime_data:
            for lab, data in zip(regime_labels, regime_data):
                fig.add_trace(go.Box(y=data, name=lab), row=2, col=2)
    fig.update_layout(title=t('plotly.engine_load.title'), height=700, showlegend=False)
    fig.update_xaxes(title_text='RPM', row=1, col=1)
    fig.update_xaxes(title_text=t('plotly.engine_load.x_axis_load'), row=1, col=2)
    return _finalize_chart(fig, return_html, output_dir, base_name,
                           'viz_engine_load_plotly', t('plotly.chart_labels.engine_load'))


def _plotly_maf_analysis(df_clean: pd.DataFrame, output_dir: Path, base_name: str, return_html: bool = False) -> str | None:
    """Интерактивный 6-панельный анализ MAF."""
    if 'MAF' not in df_clean.columns:
        return None

    df_sampled = _downsample(df_clean)
    x = get_time_axis_minutes(df_sampled)
    maf = df_sampled['MAF'].dropna()
    subplot_titles = (
        t('plotly.maf.subplot1'), t('plotly.maf.subplot2'),
        t('plotly.maf.subplot3'), t('plotly.maf.subplot4'),
        t('plotly.maf.subplot5'), t('plotly.maf.subplot6'),
    )
    fig = make_subplots(rows=3, cols=2, subplot_titles=subplot_titles)
    fig.add_trace(go.Scatter(x=x[:len(maf)], y=maf.values, line=dict(color='purple', width=1)), row=1, col=1)
    fig.add_trace(go.Histogram(x=df_sampled['MAF'].dropna(), nbinsx=50), row=1, col=2)
    if 'RPM' in df_sampled.columns:
        fig.add_trace(go.Scatter(x=df_sampled['RPM'], y=df_sampled['MAF'], mode='markers', marker=dict(size=3, opacity=0.5)), row=2, col=1)
    if 'THROTTLE_POS' in df_sampled.columns:
        fig.add_trace(go.Scatter(x=df_sampled['THROTTLE_POS'], y=df_sampled['MAF'], mode='markers', marker=dict(size=3, opacity=0.5)), row=2, col=2)
    if 'REGIME' in df_sampled.columns:
        regimes = [r for r in df_sampled['REGIME'].unique() if len(df_sampled[df_sampled['REGIME'] == r]['MAF'].dropna()) > 10]
        for r in regimes:
            fig.add_trace(go.Box(y=df_sampled[df_sampled['REGIME'] == r]['MAF'].dropna().values, name=r), row=3, col=1)
    if 'ENGINE_LOAD' in df_sampled.columns:
        fig.add_trace(go.Scatter(x=df_sampled['ENGINE_LOAD'], y=df_sampled['MAF'], mode='markers', marker=dict(size=3, opacity=0.5)), row=3, col=2)
    fig.update_layout(title=t('plotly.maf.title'), height=700, showlegend=False)
    return _finalize_chart(fig, return_html, output_dir, base_name,
                           'viz_maf_analysis_plotly', t('plotly.chart_labels.maf'))


def _plotly_misfire_analysis(df_clean: pd.DataFrame, output_dir: Path, base_name: str, return_html: bool = False) -> str | None:
    """Интерактивный 4-панельный анализ пропусков зажигания."""
    misfire_cols = [c for c in ['MISFIRE_CYL1', 'MISFIRE_CYL2', 'MISFIRE_CYL3', 'MISFIRE_CYL4'] if c in df_clean.columns]
    if not misfire_cols or sum(df_clean[c].fillna(0).sum() for c in misfire_cols) == 0:
        return None

    df_sampled = _downsample(df_clean)
    x = get_time_axis_minutes(df_sampled)
    cyl_prefix = t('plotly.misfire.cyl_prefix')
    subplot_titles = (
        t('plotly.misfire.subplot1'), t('plotly.misfire.subplot2'),
        t('plotly.misfire.subplot3'), t('plotly.misfire.subplot4'),
    )
    fig = make_subplots(rows=2, cols=2, subplot_titles=subplot_titles)
    cyl_nums = [int(c.replace('MISFIRE_CYL', '')) for c in misfire_cols]
    counts = [df_sampled[c].fillna(0).sum() for c in misfire_cols]
    fig.add_trace(go.Bar(x=cyl_nums, y=counts, text=counts, textposition='auto'), row=1, col=1)
    for col in misfire_cols:
        m = df_sampled[col].fillna(0) > 0
        if m.any():
            fig.add_trace(go.Scatter(x=x[m], y=df_sampled.loc[m, col], mode='markers',
                                     name=f"{cyl_prefix}{col.replace('MISFIRE_CYL', '')}",
                                     marker=dict(size=6)), row=1, col=2)
    if 'RPM' in df_sampled.columns and 'ENGINE_LOAD' in df_sampled.columns:
        for col in misfire_cols:
            m = df_sampled[col].fillna(0) > 0
            if m.any():
                fig.add_trace(go.Scatter(x=df_sampled.loc[m, 'RPM'], y=df_sampled.loc[m, 'ENGINE_LOAD'],
                                         mode='markers',
                                         name=col.replace('MISFIRE_CYL', cyl_prefix),
                                         marker=dict(size=8)), row=2, col=1)
    if 'REGIME' in df_sampled.columns:
        regime_totals = {r: sum(df_sampled.loc[df_sampled['REGIME'] == r, c].fillna(0).sum() for c in misfire_cols) for r in df_sampled['REGIME'].unique()}
        fig.add_trace(go.Bar(x=list(regime_totals.keys()), y=list(regime_totals.values())), row=2, col=2)
    fig.update_layout(title=t('plotly.misfire.title'), height=620)
    return _finalize_chart(fig, return_html, output_dir, base_name,
                           'viz_misfire_analysis_plotly', t('plotly.chart_labels.misfire'))


def _plotly_dashboard(df_clean: pd.DataFrame, output_dir: Path, base_name: str, return_html: bool = False) -> str | None:
    """Интерактивный сводный дашборд с 9 панелями."""
    df_sampled = _downsample(df_clean)
    specs = [[{}, {}, {}], [{}, {}, {}], [{}, {}, {'type': 'domain'}]]
    subplot_titles = (
        t('plotly.dashboard.subplot1'), t('plotly.dashboard.subplot2'), t('plotly.dashboard.subplot3'),
        t('plotly.dashboard.subplot4'), t('plotly.dashboard.subplot5'), t('plotly.dashboard.subplot6'),
        t('plotly.dashboard.subplot7'), t('plotly.dashboard.subplot8'), t('plotly.dashboard.subplot9'),
    )
    fig = make_subplots(rows=3, cols=3, specs=specs, subplot_titles=subplot_titles)
    if 'RPM' in df_sampled.columns:
        fig.add_trace(go.Histogram(x=df_sampled['RPM'].dropna(), nbinsx=50, name='RPM'), row=1, col=1)
    if 'COOLANT_TEMP' in df_sampled.columns:
        fig.add_trace(go.Histogram(x=df_sampled['COOLANT_TEMP'].dropna(), nbinsx=30,
                                   name=t('plotly.timeline.coolant')), row=1, col=2)
        fig.add_vline(x=90, line_dash='dash', line_color='green', row=1, col=2)
        fig.add_vline(x=105, line_dash='dash', line_color='red', row=1, col=2)
    if 'ENGINE_LOAD' in df_sampled.columns:
        fig.add_trace(go.Histogram(x=df_sampled['ENGINE_LOAD'].dropna(), nbinsx=40,
                                   name=t('plotly.engine_load.hist_name')), row=1, col=3)
    if 'LTFT_PERCENT' in df_sampled.columns or 'LTFT' in df_sampled.columns:
        ltft = df_sampled['LTFT_PERCENT'] if 'LTFT_PERCENT' in df_sampled.columns else (df_sampled['LTFT'] - 1) * 100
        fig.add_trace(go.Histogram(x=ltft.dropna(), nbinsx=40), row=2, col=1)
        fig.add_vline(x=0, line_dash='dash', row=2, col=1)
        fig.add_vline(x=10, line_dash='dot', row=2, col=1)
        fig.add_vline(x=-10, line_dash='dot', row=2, col=1)
    if 'STFT_PERCENT' in df_sampled.columns:
        fig.add_trace(go.Histogram(x=df_sampled['STFT_PERCENT'].dropna(), nbinsx=40), row=2, col=2)
        fig.add_vline(x=0, line_dash='dash', row=2, col=2)
        fig.add_vline(x=15, line_dash='dot', row=2, col=2)
        fig.add_vline(x=-15, line_dash='dot', row=2, col=2)
    if 'MAF' in df_sampled.columns:
        fig.add_trace(go.Histogram(x=df_sampled['MAF'].dropna(), nbinsx=40), row=2, col=3)
    if 'INJECTION_TIME' in df_sampled.columns:
        fig.add_trace(go.Histogram(x=df_sampled['INJECTION_TIME'].dropna(), nbinsx=40), row=3, col=1)
    if 'THROTTLE_POS' in df_sampled.columns:
        fig.add_trace(go.Histogram(x=df_sampled['THROTTLE_POS'].dropna(), nbinsx=40), row=3, col=2)
    if 'REGIME' in df_sampled.columns:
        regime_counts = df_sampled['REGIME'].value_counts()
        fig.add_trace(go.Pie(labels=regime_counts.index, values=regime_counts.values, hole=0.4), row=3, col=3)
    fig.update_layout(title=t('plotly.dashboard.title', base_name=base_name), height=800, showlegend=False)
    return _finalize_chart(fig, return_html, output_dir, base_name,
                           'viz_dashboard_plotly', t('plotly.chart_labels.dashboard'))


def _plotly_3d_engine_map(df: pd.DataFrame, output_dir: Path, base_name: str, return_html: bool = False) -> str | None:
    """3D-карта работы двигателя: облако точек RPM x Нагрузка x Температура."""
    required = ['RPM', 'ENGINE_LOAD', 'COOLANT_TEMP']
    if not all(col in df.columns for col in required):
        return None

    step = _get_adaptive_step(df, max_points=5000 * _POINTS_MULTIPLIER)
    df_sampled = df.iloc[::step].copy()
    df_sampled = df_sampled.dropna(subset=required)
    if len(df_sampled) == 0:
        return None

    if 'KNOCK_RETARD' in df_sampled.columns:
        knock_data = df_sampled['KNOCK_RETARD'].fillna(0)
        color = knock_data
        colorscale = 'Hot'
        colorbar_title = t('plotly.3d_engine_map.colorbar_knock')
        size = np.clip(knock_data * 2 + 3, 3, 15)
    else:
        color = df_sampled['COOLANT_TEMP']
        colorscale = 'Viridis'
        colorbar_title = t('plotly.3d_engine_map.colorbar_temp')
        size = 5

    has_time = 'TIME' in df_sampled.columns
    t_labels = df_sampled['TIME'].where(df_sampled['TIME'].notna(), '').astype(str).str[:8].tolist() if has_time else [''] * len(df_sampled)
    knock_available = 'KNOCK_RETARD' in df_sampled.columns
    knock_vals = df_sampled['KNOCK_RETARD'].tolist() if knock_available else [0] * len(df_sampled)

    _hrpm = t('plotly.3d_engine_map.hover_rpm')
    _hload = t('plotly.3d_engine_map.hover_load')
    _htemp = t('plotly.3d_engine_map.hover_temp')
    _hknock = t('plotly.3d_engine_map.hover_knock')

    fig = go.Figure(data=[go.Scatter3d(
        x=df_sampled['RPM'],
        y=df_sampled['ENGINE_LOAD'],
        z=df_sampled['COOLANT_TEMP'],
        mode='markers',
        marker=dict(size=size, color=color, colorscale=colorscale, showscale=True,
                    colorbar=dict(title=colorbar_title), opacity=0.7, line=dict(width=0)),
        customdata=t_labels,
        text=[f'{ts + "<br>" if ts else ""}{_hrpm}: {r}<br>{_hload}: {l}%<br>{_htemp}: {temp}°C' +
              (f'<br>{_hknock}: {k}°' if knock_available else '')
              for ts, r, l, temp, k in zip(t_labels, df_sampled['RPM'], df_sampled['ENGINE_LOAD'],
                                           df_sampled['COOLANT_TEMP'], knock_vals)],
        hovertemplate='%{text}<extra></extra>'
    )])

    fig.update_layout(
        title=t('plotly.3d_engine_map.title'),
        scene=dict(
            xaxis_title=t('plotly.3d_engine_map.x_axis'),
            yaxis_title=t('plotly.3d_engine_map.y_axis'),
            zaxis_title=t('plotly.3d_engine_map.z_axis'),
            camera=dict(eye=dict(x=1.5, y=1.5, z=1.3)),
        ),
        height=680, showlegend=False,
    )
    return _finalize_chart(fig, return_html, output_dir, base_name,
                           'viz_3d_engine_map', t('plotly.chart_labels.3d_engine_map'), map_nav=True)


def _plotly_3d_trajectory(df: pd.DataFrame, output_dir: Path, base_name: str, return_html: bool = False) -> str | None:
    """3D-траектория работы двигателя во времени."""
    required = ['RPM', 'ENGINE_LOAD', 'COOLANT_TEMP']
    if not all(col in df.columns for col in required):
        return None

    step = _get_adaptive_step(df, max_points=1000 * _POINTS_MULTIPLIER)
    df_sampled = df.iloc[::step].copy()
    df_sampled = df_sampled.dropna(subset=required)
    if len(df_sampled) == 0:
        return None

    if 'KNOCK_RETARD' in df_sampled.columns:
        color_data = df_sampled['KNOCK_RETARD'].fillna(0)
        colorscale = 'Hot'
        colorbar_title = t('plotly.3d_trajectory.colorbar_knock')
    else:
        color_data = df_sampled['COOLANT_TEMP']
        colorscale = 'Thermal'
        colorbar_title = t('plotly.3d_trajectory.colorbar_temp')

    has_time = 'TIME' in df_sampled.columns
    t_labels = df_sampled['TIME'].where(df_sampled['TIME'].notna(), '').astype(str).str[:8].tolist() if has_time else [''] * len(df_sampled)
    time_min = df_sampled.index.to_numpy() * LOG_DT / 60.0

    _hrpm = t('plotly.3d_trajectory.hover_rpm')
    _hload = t('plotly.3d_trajectory.hover_load')
    _htemp = t('plotly.3d_trajectory.hover_temp')

    fig = go.Figure(data=[go.Scatter3d(
        x=df_sampled['RPM'], y=df_sampled['ENGINE_LOAD'], z=time_min,
        mode='lines+markers',
        line=dict(color=color_data, colorscale=colorscale, width=4, showscale=True,
                  colorbar=dict(title=colorbar_title)),
        marker=dict(size=3, color=color_data, colorscale=colorscale),
        customdata=t_labels,
        text=[f'{ts + "<br>" if ts else ""}{_hrpm}: {r}<br>{_hload}: {l}%<br>{_htemp}: {temp}°C'
              for ts, r, l, temp in zip(t_labels, df_sampled['RPM'],
                                        df_sampled['ENGINE_LOAD'], df_sampled['COOLANT_TEMP'])],
        hovertemplate='%{text}<extra></extra>'
    )])

    fig.update_layout(
        title=t('plotly.3d_trajectory.title'),
        scene=dict(
            xaxis_title=t('plotly.3d_trajectory.x_axis'),
            yaxis_title=t('plotly.3d_trajectory.y_axis'),
            zaxis_title=t('plotly.3d_trajectory.z_axis'),
            camera=dict(eye=dict(x=1.5, y=-1.5, z=1.2)),
        ),
        height=680, showlegend=False,
    )
    return _finalize_chart(fig, return_html, output_dir, base_name,
                           'viz_3d_trajectory', t('plotly.chart_labels.3d_trajectory'), map_nav=True)


def _plotly_3d_knock_volume(df: pd.DataFrame, output_dir: Path, base_name: str, return_html: bool = False) -> str | None:
    """3D-объёмная карта детонации: RPM x Нагрузка x Величина отскока УОЗ."""
    required = ['RPM', 'ENGINE_LOAD', 'KNOCK_RETARD']
    if not all(col in df.columns for col in required):
        return None

    df_knock = df[df['KNOCK_RETARD'] > 1].copy()
    if len(df_knock) == 0:
        return None

    step = _get_adaptive_step(df_knock, max_points=3000 * _POINTS_MULTIPLIER)
    df_sampled = df_knock.iloc[::step]

    has_time = 'TIME' in df_sampled.columns
    t_labels = df_sampled['TIME'].where(df_sampled['TIME'].notna(), '').astype(str).str[:8].tolist() if has_time else [''] * len(df_sampled)

    _hrpm = t('plotly.3d_knock.hover_rpm')
    _hload = t('plotly.3d_knock.hover_load')
    _hknock = t('plotly.3d_knock.hover_knock')

    fig = go.Figure(data=[go.Scatter3d(
        x=df_sampled['RPM'], y=df_sampled['ENGINE_LOAD'], z=df_sampled['KNOCK_RETARD'],
        mode='markers',
        marker=dict(size=df_sampled['KNOCK_RETARD'] * 1.5 + 3, color=df_sampled['KNOCK_RETARD'],
                    colorscale='Hot', showscale=True,
                    colorbar=dict(title=t('plotly.3d_knock.colorbar')),
                    opacity=0.8, line=dict(width=0)),
        customdata=t_labels,
        text=[f'{ts + "<br>" if ts else ""}{_hrpm}: {r}<br>{_hload}: {l}%<br>{_hknock}: {k}°'
              for ts, r, l, k in zip(t_labels, df_sampled['RPM'],
                                     df_sampled['ENGINE_LOAD'], df_sampled['KNOCK_RETARD'])],
        hovertemplate='%{text}<extra></extra>'
    )])

    fig.update_layout(
        title=t('plotly.3d_knock.title'),
        scene=dict(
            xaxis_title=t('plotly.3d_knock.x_axis'),
            yaxis_title=t('plotly.3d_knock.y_axis'),
            zaxis_title=t('plotly.3d_knock.z_axis'),
            camera=dict(eye=dict(x=1.5, y=1.5, z=1.3)),
        ),
        height=680, showlegend=False,
    )
    return _finalize_chart(fig, return_html, output_dir, base_name,
                           'viz_3d_knock', t('plotly.chart_labels.3d_knock'), map_nav=True)


# ---------------------------------------------------------------------------
# Порядок и заголовки графиков для отчёта
# ---------------------------------------------------------------------------
def _get_chart_builders() -> list[tuple[str, Any]]:
    """Возвращает список пар (заголовок, функция-построитель) для всех графиков.

    Заголовки вычисляются в момент вызова, после установки языка через set_language().
    """
    return [
        (t('plotly.chart_labels.dashboard'),    _plotly_dashboard),
        (t('plotly.chart_labels.timeline'),     _plotly_synchronized_timeline),
        (t('plotly.chart_labels.knock_heatmap'), _plotly_knock_heatmap),
        (t('plotly.chart_labels.ltft_stft'),    _plotly_ltft_stft_hist),
        (t('plotly.chart_labels.corr_matrix'),  _plotly_correlation_matrix),
        (t('plotly.chart_labels.engine_load'),  _plotly_engine_load),
        (t('plotly.chart_labels.maf'),          _plotly_maf_analysis),
        (t('plotly.chart_labels.misfire'),      _plotly_misfire_analysis),
        (t('plotly.chart_labels.3d_engine_map'), _plotly_3d_engine_map),
        (t('plotly.chart_labels.3d_trajectory'), _plotly_3d_trajectory),
        (t('plotly.chart_labels.3d_knock'),     _plotly_3d_knock_volume),
    ]


def build_plotly_html_charts(df_clean: pd.DataFrame, output_dir: Path, base_name: str) -> list[tuple[str, str]]:
    """Строит все Plotly-графики в режиме iframe и возвращает их HTML-код.

    Обходит _get_chart_builders(), вызывая каждый построитель с return_html=True.
    Графики, вернувшие None (нет данных / ошибка), пропускаются без исключения.

    Args:
        df_clean: Очищенный DataFrame с OBD-данными.
        output_dir: Директория файла (нужна некоторым графикам для чтения _metrics.csv).
        base_name: Базовое имя файла без расширения.

    Returns:
        Список пар (заголовок, HTML-строка). Пустой список если Plotly недоступен.
    """
    if not PLOTLY_AVAILABLE:
        return []
    result = []
    for title, fn in _get_chart_builders():
        try:
            html_str = fn(df_clean, output_dir, base_name, return_html=True)
            if html_str:
                result.append((title, html_str))
        except (ValueError, KeyError, TypeError):
            pass
    return result


def save_separate_plot_files(df_clean: pd.DataFrame, output_dir: Path, base_name: str) -> None:
    """Сохраняет каждый Plotly-график в отдельный HTML-файл с увеличенным лимитом записей (x3).

    Временно устанавливает _POINTS_MULTIPLIER=3 для более детальной прорисовки,
    затем сбрасывает его в 1 через finally (даже при исключении).

    Args:
        df_clean: Очищенный DataFrame с OBD-данными.
        output_dir: Директория для сохранения файлов.
        base_name: Базовое имя файла без расширения (используется как префикс).
    """
    global _POINTS_MULTIPLIER
    _POINTS_MULTIPLIER = 3
    try:
        count = 0
        for _, fn in _get_chart_builders():
            try:
                fn(df_clean, output_dir, base_name, return_html=False)
                count += 1
            except (ValueError, KeyError, TypeError):
                pass
        if count > 0:
            logger.info(t('console.plotly_html_count', count=count, multiplier=_POINTS_MULTIPLIER))
    finally:
        _POINTS_MULTIPLIER = 1
