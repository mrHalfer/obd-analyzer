#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Модуль формирования HTML-отчёта для анализа OBD-II данных.

Содержит:
- Конвертеры CSV -> HTML таблицы
- Генератор единого HTML-отчёта с табами
- CSS стили отчёта
"""

import html as html_module
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

import sys as _sys
from pathlib import Path as _Path
_root = _Path(__file__).parent.parent
for _d in [str(_root), str(_root / 'build'), str(_root / 'plugins')]:
    if _d not in _sys.path:
        _sys.path.insert(0, _d)

from core_obd import (
    STATUS_OK, STATUS_WARNING, STATUS_ERROR, STATUS_NEUTRAL,
    PLOTLY_AVAILABLE,
    get_status,
    get_metric_val,
    get_metric_stat,
)

from translation import t, get_language

logger = logging.getLogger(__name__)

from build_plotly import (
    build_plotly_html_charts,
    save_separate_plot_files,
)
from build_map import build_map_panel

_SCRIPT_DIR = Path(__file__).parent

# ---------------------------------------------------------------------------
# Jinja2 — шаблонизатор HTML-отчёта
# ---------------------------------------------------------------------------

try:
    from jinja2 import Environment, FileSystemLoader
    _jinja_env = Environment(
        loader=FileSystemLoader(str(_SCRIPT_DIR)),
        autoescape=False,
        keep_trailing_newline=True,
    )
    _jinja_env.globals['t'] = t
except ImportError:
    _jinja_env = None  # type: ignore[assignment]
    logger.warning('jinja2 не установлен — HTML-отчёт недоступен. Установите: pip install jinja2')

# ---------------------------------------------------------------------------
# CSS стили и вспомогательные функции для HTML-отчёта
# ---------------------------------------------------------------------------

_REPORT_CSS = (_SCRIPT_DIR / 'build_html.css').read_text(encoding='utf-8')

from core_obd import brand_svg as _brand_svg

_MAX_TABLE_ROWS = 500
_PAGE_SIZE = 20


def _metrics_csv_to_accordion_html(csv_path: Path | str) -> str:
    """Конвертирует CSV метрик в HTML-аккордеон с секциями по режимам."""
    if not csv_path.is_file():
        return ''
    try:
        df = pd.read_csv(csv_path, encoding='utf-8-sig')
    except (pd.errors.ParserError, UnicodeDecodeError, OSError):
        return ''
    if df.empty or 'CODE' not in df.columns:
        return ''
    code_col = 'CODE'
    desc_col = 'DESC' if 'DESC' in df.columns else (df.columns[1] if len(df.columns) > 1 else None)
    sep = '---SEPARATOR---'
    chunks = []
    current_name = t('sections.trip_info')
    current_rows = []
    for _, row in df.iterrows():
        if str(row.get(code_col, '')).strip() == sep:
            if current_rows:
                chunks.append((current_name, pd.DataFrame(current_rows)))
            current_name = str(row.get(desc_col, '')).strip() or t('common.unknown')
            current_rows = []
        else:
            current_rows.append(row)
    if current_rows:
        chunks.append((current_name, pd.DataFrame(current_rows)))
    if not chunks:
        return ''
    html_parts = []
    for i, (name, block_df) in enumerate(chunks):
        open_attr = ' open' if i == 0 else ''
        html_rows = ['<thead><tr>' + ''.join(f'<th>{html_module.escape(str(c))}</th>' for c in block_df.columns) + '</tr></thead>', '<tbody>']
        for _, row in block_df.iterrows():
            cells = []
            for c in block_df.columns:
                v = row[c]
                v = '' if pd.isna(v) else str(v)
                cls = ''
                if c == 'STAT' and v:
                    if '✅' in v or 'OK' in v: cls = ' class="stat-ok"'
                    elif '⚠' in v or 'WARNING' in v: cls = ' class="stat-warn"'
                    elif '❌' in v or 'ERROR' in v: cls = ' class="stat-err"'
                cells.append(f'<td{cls}>{html_module.escape(v)}</td>')
            html_rows.append('<tr>' + ''.join(cells) + '</tr>')
        html_rows.append('</tbody>')
        table_html = '<table>' + '\n'.join(html_rows) + '</table>'
        html_parts.append(f'<details class="accordion-item"{open_attr}><summary>{html_module.escape(name)}</summary><div class="accordion-body"><div class="table-scroll">{table_html}</div></div></details>')
    return '\n'.join(html_parts)


_pagination_counter = 0


def _csv_to_html_table(csv_path: Path | str, max_rows: int | None = None, page_size: int | None = None) -> str:
    """Конвертирует CSV файл в HTML-таблицу с форматированием чисел."""
    global _pagination_counter

    if not csv_path.is_file():
        return ''
    try:
        df = pd.read_csv(csv_path, encoding='utf-8-sig', nrows=(max_rows + 1) if max_rows else None)
    except (pd.errors.ParserError, UnicodeDecodeError, OSError):
        return ''
    if df.empty:
        return ''
    total_read = len(df)
    truncated = max_rows and total_read > max_rows
    if truncated:
        df = df.head(max_rows)

    use_pagination = page_size and len(df) > page_size
    table_id = ''
    if use_pagination:
        _pagination_counter += 1
        table_id = f' id="ptable-{_pagination_counter}" data-page-size="{page_size}"'

    html_rows = []
    html_rows.append('<thead><tr>' + ''.join(f'<th>{html_module.escape(str(c))}</th>' for c in df.columns) + '</tr></thead>')
    html_rows.append('<tbody>')
    for _, row in df.iterrows():
        cells = []
        for c in df.columns:
            v = row[c]
            if pd.isna(v):
                v = ''
            else:
                if isinstance(v, (int, float, np.integer, np.floating)):
                    if isinstance(v, (int, np.integer)) or abs(v) >= 100:
                        v = f'{v:.0f}'
                    elif abs(v) >= 10:
                        v = f'{v:.1f}'
                    else:
                        v = f'{v:.2f}'
                else:
                    v = str(v)
            cls = ''
            if c == 'STAT' and v:
                if '✅' in v or 'OK' in v:
                    cls = ' class="stat-ok"'
                elif '⚠' in v or 'WARNING' in v:
                    cls = ' class="stat-warn"'
                elif '❌' in v or 'ERROR' in v:
                    cls = ' class="stat-err"'
            cells.append(f'<td{cls}>{html_module.escape(v)}</td>')
        html_rows.append('<tr>' + ''.join(cells) + '</tr>')
    html_rows.append('</tbody>')
    note = ''
    if truncated:
        note = f'<p class="report-note">{t("html.messages.records_shown", shown=len(df), total=total_read)}</p>'
    elif use_pagination:
        note = f'<p class="report-note">{t("html.messages.total_records", total=len(df))}</p>'
    table_html = f'<table{table_id}>' + '\n'.join(html_rows) + '</table>' + note
    if use_pagination:
        table_html += f'<div class="pagination" data-for="ptable-{_pagination_counter}"></div>'
    return table_html


def _escape_srcdoc(html_str: str) -> str:
    """Экранирует HTML-строку для атрибута srcdoc в iframe."""
    return html_str.replace('&', '&amp;').replace('"', '&quot;')


def _build_chart_panel(
    plotly_charts: list | None,
    no_charts: bool,
    inline_warning_html: str,
    chart_filter: str | None,
    chart_height: int | str,
    png_mappings: list[tuple[str, str]],
    output_dir: Path,
    base: str,
) -> list[str]:
    """Строит содержимое панели графиков (Plotly iframe или PNG fallback)."""
    parts: list[str] = []
    if plotly_charts is not None:
        parts.append(inline_warning_html)
    if no_charts:
        parts.append(f'<p class="report-msg report-msg-info">{t("html.messages.no_charts")}</p>')
    elif plotly_charts is not None:
        for chart_title, html_str in plotly_charts:
            if chart_filter(chart_title):
                h = chart_height(chart_title) if callable(chart_height) else chart_height
                escaped = _escape_srcdoc(html_str)
                parts.append(
                    '<details class="collapsible">'
                    f'<summary>{html_module.escape(chart_title)}</summary>'
                    f'<div class="collapsible-body"><div class="chart-wrap">'
                    f'<div class="chart-loading"><div class="chart-loading-spinner"></div>{t("html.messages.loading_chart")}</div>'
                    f'<iframe class="lazy-iframe" data-src="{escaped}" height="{h}"></iframe></div></div></details>'
                )
    else:
        import base64 as _b64
        for png_suffix, chart_title in png_mappings:
            png_path = output_dir / f'{base}_{png_suffix}'
            if png_path.is_file():
                try:
                    b64data = _b64.b64encode(png_path.read_bytes()).decode('ascii')
                    img_src = f'data:image/png;base64,{b64data}'
                except OSError:
                    img_src = html_module.escape(png_path.name)
                parts.append(
                    '<details class="collapsible">'
                    f'<summary>{html_module.escape(chart_title)}</summary>'
                    f'<div class="collapsible-body"><div class="chart-wrap"><img src="{img_src}" alt="{html_module.escape(chart_title)}"></div></div></details>'
                )
    return parts


# ---------------------------------------------------------------------------
# Подфункции для create_report_html
# ---------------------------------------------------------------------------


def _build_summary_card(title: str, rows: list[str]) -> str:
    """Создаёт HTML-карточку сводки с заголовком и строками."""
    body = '\n'.join(rows)
    return f'<div class="summary-card"><h3>{title}</h3>\n{body}\n</div>'


def _build_summary_panel(metrics_path: Path) -> str:
    """Строит панель «Сводка» из файла метрик.

    Args:
        metrics_path: Путь к CSV файлу метрик.

    Returns:
        HTML-строка панели сводки.
    """
    parts = []

    if not metrics_path.is_file():
        return f'<div id="panel-summary" class="report-panel active"><p class="report-msg report-msg-info">{t("html.messages.metrics_not_found")}</p></div>'

    try:
        mdf = pd.read_csv(metrics_path, encoding='utf-8-sig')
    except (pd.errors.ParserError, UnicodeDecodeError, OSError) as e:
        return f'<div id="panel-summary" class="report-panel active"><p class="report-msg report-msg-info">{t("html.messages.metrics_read_error", error=e)}</p></div>'

    val = lambda code, default=t('common.unknown'): get_metric_val(mdf, code, default)
    stat = lambda code, default=STATUS_NEUTRAL: get_metric_stat(mdf, code, default)

    try:
        # Карточка «Основные параметры»
        parts.append('<div class="summary-grid">')
        parts.append(_build_summary_card(t('html.cards.basic_params'), [
            f'<p><strong>{t("html.card_fields.fuel")}</strong> {val("RUN_FUEL_TYPE")}</p>',
            f'<p><strong>{t("html.card_fields.temp_outside")}</strong> {val("RUN_TEMP_OUTSIDE")}°C</p>',
            f'<p><strong>{t("html.card_fields.duration")}</strong> {val("RUN_DURATION")} {t("units.min")}</p>',
        ]))

        # Карточка «Температура ОЖ» - расширенная с анализом системы охлаждения
        temp_metrics = mdf[mdf['CODE'].str.contains('TEMP_COOLANT', na=False)]
        coolant_system_metrics = mdf[mdf['CODE'].str.contains('COOLANT_', na=False)]

        if not temp_metrics.empty or not coolant_system_metrics.empty:
            temp_rows = []

            # Базовые показатели температуры — суммарные по всей поездке
            temp_mean = val("ALL_TEMP_COOLANT_Mean", None)
            temp_max = val("ALL_TEMP_COOLANT_Max", None)
            if temp_mean is not None:
                temp_rows.append(f'<p><strong>{t("html.card_fields.coolant_mean")}</strong> {temp_mean}°C</p>')
            if temp_max is not None:
                temp_rows.append(f'<p><strong>{t("html.card_fields.coolant_max")}</strong> {temp_max}°C</p>')

            # Оценка прогрева
            warmup_assessment = val('COOLANT_WARMUP_ASSESSMENT', None)
            if warmup_assessment:
                warmup_stat = stat('COOLANT_WARMUP_ASSESSMENT')
                temp_rows.append(f'<p><strong>{t("html.card_fields.warmup")}</strong> {warmup_stat} {warmup_assessment}</p>')

            # Термостат: итоговая оценка или статус стабильности как запасной вариант
            thermostat_assessment = val('COOLANT_THERMOSTAT_ASSESSMENT', None) or val('COOLANT_THERMOSTAT_STABILITY', None)
            thermostat_stat = stat('COOLANT_THERMOSTAT_ASSESSMENT') if val('COOLANT_THERMOSTAT_ASSESSMENT', None) else stat('COOLANT_THERMOSTAT_STABILITY')

            if thermostat_assessment and thermostat_assessment != 'N/A':
                temp_rows.append(f'<p><strong>{t("html.card_fields.thermostat")}</strong> {thermostat_stat} {thermostat_assessment}</p>')

            fan_assessment = val('COOLANT_FAN_ASSESSMENT', None)
            fan_stat = stat('COOLANT_FAN_ASSESSMENT', STATUS_NEUTRAL)

            if fan_assessment and fan_assessment != 'N/A' and fan_assessment != 'Недостаточно данных':
                temp_rows.append(f'<p><strong>{t("html.card_fields.fan")}</strong> {fan_stat} {fan_assessment}</p>')

            overheat_assessment = val('COOLANT_OVERHEAT_ASSESSMENT', None)
            overheat_stat = stat('COOLANT_OVERHEAT_ASSESSMENT', STATUS_NEUTRAL)

            if overheat_assessment and overheat_assessment != 'N/A' and overheat_assessment != 'Перегревов нет':
                temp_rows.append(f'<p><strong>⚠️ {overheat_assessment}</strong></p>')

            if temp_rows:
                parts.append(_build_summary_card(t('html.cards.coolant_temp'), temp_rows))

        # Карточка «Заглохи и пропуски»
        stalled_metrics = mdf[mdf['CODE'].str.contains('STALLED_COUNT', na=False)]
        misfire_metrics = mdf[mdf['CODE'].str.contains('MISFIRE_', na=False)]
        if not stalled_metrics.empty or not misfire_metrics.empty:
            all_stalled = int(val('ALL_STALLED_COUNT', 0))
            stalled_status = get_status('STALLED', all_stalled, 'ALL')

            _misfire_raw = int(val('MISFIRE_TOTAL_COUNT', 0))
            if _misfire_raw == -1:
                misfire_status = STATUS_NEUTRAL
                misfire_display = t('common.no_data')
            else:
                misfire_status = get_status('MISFIRE', _misfire_raw, 'ALL')
                misfire_display = str(_misfire_raw)

            _sm_label = t('html.cards.stalls_misfires')
            if stalled_status == STATUS_ERROR or misfire_status == STATUS_ERROR:
                group_icon = f'❌ {_sm_label}'
            elif stalled_status == STATUS_WARNING or misfire_status == STATUS_WARNING:
                group_icon = f'⚠️ {_sm_label}'
            else:
                group_icon = f'✅ {_sm_label}'

            parts.append(_build_summary_card(group_icon, [
                f'<p><strong>{t("html.card_fields.stalls")}</strong> {stalled_status} {all_stalled}</p>',
                f'<p><strong>{t("html.card_fields.misfires")}</strong> {misfire_status} {misfire_display}</p>',
            ]))

        # Карточка «Детонация»
        knock_metrics = mdf[mdf['CODE'].str.contains('KNOCK_', na=False)]
        if not knock_metrics.empty:
            parts.append(_build_summary_card(t('html.cards.knock'), [
                f'<p><strong>{t("html.card_fields.knock_total")}</strong> {stat("KNOCK_TOTAL_COUNT")} {val("KNOCK_TOTAL_COUNT", 0)}</p>',
                f'<p><strong>{t("html.card_fields.knock_weak")}</strong> {stat("KNOCK_WEAK_COUNT")} {val("KNOCK_WEAK_COUNT", 0)}</p>',
                f'<p><strong>{t("html.card_fields.knock_medium")}</strong> {stat("KNOCK_MEDIUM_COUNT")} {val("KNOCK_MEDIUM_COUNT", 0)}</p>',
                f'<p><strong>{t("html.card_fields.knock_strong")}</strong> {stat("KNOCK_STRONG_COUNT")} {val("KNOCK_STRONG_COUNT", 0)}</p>',
            ]))

        # Карточка «Коррекции топлива»
        fuel_metrics = mdf[mdf['CODE'].str.contains('LTFT|STFT', na=False)]
        if not fuel_metrics.empty:
            _ltft_val = val("ALL_DRIVE_LTFT_Mean", None) or val("ALL_LTFT_Mean", None)
            _stft_val = val("ALL_DRIVE_STFT_Mean", None) or val("ALL_STFT_Mean", None)
            fuel_rows = [
                f'<p><strong>{t("html.card_fields.ltft_mean")}</strong> {_ltft_val}%</p>' if _ltft_val is not None else '',
                f'<p><strong>{t("html.card_fields.stft_mean")}</strong> {_stft_val}%</p>' if _stft_val is not None else '',
            ]
            # Катализатор: объединённый статус двух методов
            cat_aging_stat = stat('CAT_AGING_MEAN', None)
            cat_o2_stat = stat('CAT_O2_STATE', None)
            # Если оценка невозможна (NEUTRAL) — короткий текст вместо длинного диагноза
            _cat_o2_val = t('catalyst.cant_assess') if cat_o2_stat == STATUS_NEUTRAL else val('CAT_O2_STATE')
            if cat_aging_stat is not None or cat_o2_stat is not None:
                if cat_aging_stat is not None and cat_o2_stat is not None:
                    if cat_aging_stat == cat_o2_stat:
                        cat_combined_stat = cat_aging_stat
                        cat_combined_val = val('CAT_AGING_MEAN')
                    else:
                        status_priority = {STATUS_NEUTRAL: 0, STATUS_OK: 1, STATUS_WARNING: 2, STATUS_ERROR: 3}
                        if status_priority[cat_aging_stat] >= status_priority[cat_o2_stat]:
                            cat_combined_stat = cat_aging_stat
                            cat_combined_val = val('CAT_AGING_MEAN')
                        else:
                            cat_combined_stat = cat_o2_stat
                            cat_combined_val = _cat_o2_val
                else:
                    cat_combined_stat = cat_aging_stat if cat_aging_stat is not None else cat_o2_stat
                    cat_combined_val = _cat_o2_val if cat_o2_stat is not None else val('CAT_AGING_MEAN')
                fuel_rows.append(f'<p><strong>{t("html.card_fields.catalyst")}</strong> {cat_combined_stat} {cat_combined_val}</p>')
            parts.append(_build_summary_card(t('html.cards.fuel_corrections'), fuel_rows))

        # Карточка «Качество топлива (O2)»
        o2_metrics = mdf[mdf['CODE'].str.contains('O2_', na=False)]
        if not o2_metrics.empty:
            o2_card = _build_o2_quality_card(mdf)
            if o2_card:
                parts.append(o2_card)

        parts.append('</div>')  # summary-grid

    except (ValueError, KeyError) as e:
        parts.append(f'<p class="report-msg report-msg-info">{t("html.messages.summary_error", error=e)}</p>')

    return '<div id="panel-summary" class="report-panel active">' + '\n'.join(parts) + '</div>'


def _build_o2_quality_card(mdf: pd.DataFrame) -> str | None:
    """Строит карточку оценки качества топлива по O2 датчику."""
    val = lambda code, default=None: get_metric_val(mdf, code, default)
    stat = lambda code, default=STATUS_NEUTRAL: get_metric_stat(mdf, code, default)

    o2_rich_time = val('O2_RICH_TIME')
    o2_lean_time = val('O2_LEAN_TIME')
    o2_normal_time = val('O2_NORMAL_TIME')
    o2_crossing_rate = val('O2_CROSSING_RATE')

    fuel_quality = val('FUEL_QUALITY', t('common.unknown'))
    fuel_quality_icon = stat('FUEL_QUALITY', '❓')

    rows = [f'<p><strong>{t("html.card_fields.o2_quality_label")}</strong> {fuel_quality}</p>']
    if o2_normal_time is not None:
        rows.append(f'<p><strong>{t("html.card_fields.stoichiometry")}</strong> {o2_normal_time}%</p>')
    if o2_rich_time is not None and o2_lean_time is not None:
        rows.append(f'<p><strong>{t("html.card_fields.rich_lean")}</strong> {o2_rich_time}% / {o2_lean_time}%</p>')
    if o2_crossing_rate is not None:
        rows.append(f'<p><strong>{t("html.card_fields.crossings")}</strong> {o2_crossing_rate} {t("units.per_min")}</p>')

    return _build_summary_card(f'{fuel_quality_icon} {t("html.cards.o2_quality")}', rows)


def _build_reports_panel(output_dir: Path, base: str, no_csv: bool) -> str:
    """Строит панель «Отчёты» с CSV таблицами."""
    parts = []
    if no_csv:
        parts.append(f'<p class="report-msg report-msg-info">{t("html.messages.no_csv")}</p>')
    metrics_path = output_dir / f'{base}_metrics.csv'
    metrics_accordion = _metrics_csv_to_accordion_html(metrics_path)
    if metrics_accordion:
        parts.append(
            '<details class="collapsible" open>'
            f'<summary>{t("html.sections.metrics_by_regime")}</summary>'
            '<div class="collapsible-body">' + metrics_accordion + '</div></details>'
        )
    csv_sections = [
        (t('html.sections.speed_profile'), output_dir / f'{base}_profile.csv', None, None),
        (t('html.sections.joker_events'), output_dir / f'{base}_joker.csv', None, _PAGE_SIZE),
        (t('html.sections.knock_groups'), output_dir / f'{base}_knock_groups.csv', None, _PAGE_SIZE),
        (t('html.sections.knock_timeline'), output_dir / f'{base}_knock_timeline.csv', _MAX_TABLE_ROWS, _PAGE_SIZE),
        (t('html.sections.misfire_timeline'), output_dir / f'{base}_misfire_timeline.csv', _MAX_TABLE_ROWS, _PAGE_SIZE),
    ]
    for title, csv_path, max_rows, page_size in csv_sections:
        table_html = _csv_to_html_table(csv_path, max_rows=max_rows, page_size=page_size)
        if table_html:
            parts.append(
                '<details class="collapsible">'
                f'<summary>{html_module.escape(title)}</summary>'
                '<div class="collapsible-body"><div class="table-scroll">' + table_html + '</div></div></details>'
            )
    return '<div id="panel-reports" class="report-panel">' + '\n'.join(parts) + '</div>'


def _build_chart_panels(plotly_charts_cache: dict | None, no_png: bool, no_plot: bool,
                        inline_warning_html: str, output_dir: Path, base: str) -> str:
    """Строит все панели графиков (Дашборд, Матрицы, Таймлайн (только PNG), Аналитика, 3D)."""
    no_charts = no_png and no_plot

    # Определяем, нужна ли панель "Таймлайн" (только для режима PNG без Plotly)
    show_timeline_panel = no_plot and not no_png

    _dashboard_titles = {t('plotly.chart_labels.dashboard'), t('plotly.chart_labels.ltft_stft')}
    _matrices_titles = {t('plotly.chart_labels.knock_heatmap'), t('plotly.chart_labels.corr_matrix')}
    _analytics_titles = {
        t('plotly.chart_labels.timeline'), t('plotly.chart_labels.engine_load'),
        t('plotly.chart_labels.maf'), t('plotly.chart_labels.misfire'),
    }
    _timeline_title = t('plotly.chart_labels.timeline')
    _dashboard_title = t('plotly.chart_labels.dashboard')
    _3d_titles = {
        t('plotly.chart_labels.3d_engine_map'), t('plotly.chart_labels.3d_trajectory'),
        t('plotly.chart_labels.3d_knock'),
    }

    def _is_dashboard_chart(title: str) -> bool:
        return title in _dashboard_titles

    def _dashboard_height(title: str) -> int:
        return 820 if title == _dashboard_title else 520

    def _is_matrices_chart(title: str) -> bool:
        return title in _matrices_titles

    def _is_analytics_chart(title: str) -> bool:
        return title in _analytics_titles

    def _analytics_height(title: str) -> int:
        return 1420 if title == _timeline_title else 720

    def _is_3d_chart(title: str) -> bool:
        return title in _3d_titles

    panel_configs = [
        ('dashboard', _is_dashboard_chart, _dashboard_height,
         [('viz_dashboard.png', t('pdf.panel_png.viz_dashboard_png')),
          ('viz_ltft_stft_hist.png', t('pdf.panel_png.viz_ltft_stft_hist_png'))]),
        ('matrices', _is_matrices_chart, 720,
         [('viz_knock_heatmap.png', t('pdf.panel_png.viz_knock_heatmap_png')),
          ('viz_corr_matrix.png', t('pdf.panel_png.viz_corr_matrix_png'))]),
    ]

    # Добавляем панель "Таймлайн" только для режима PNG
    if show_timeline_panel:
        panel_configs.append(
            ('timeline', lambda _: False,  # Не используется для Plotly графиков
             1220,
             [('viz_timeline.png', t('pdf.panel_png.viz_timeline_png')),
              ('viz_fuel_correction.png', t('pdf.panel_png.viz_fuel_correction_png')),
              ('viz_o2_sensors.png', t('pdf.panel_png.viz_o2_sensors_png')),
              ('viz_temperatures.png', t('pdf.panel_png.viz_temperatures_png'))])
        )

    panel_configs.extend([
        ('analytics', _is_analytics_chart, _analytics_height,
         [('viz_engine_load.png', t('pdf.panel_png.viz_engine_load_png')),
          ('viz_maf_analysis.png', t('pdf.panel_png.viz_maf_analysis_png')),
          ('viz_misfire_analysis.png', t('pdf.panel_png.viz_misfire_analysis_png'))]),
        ('3d', _is_3d_chart, 700, []),
    ])

    result = []
    for panel_id, filt, height, png_maps in panel_configs:
        if panel_id == '3d' and not PLOTLY_AVAILABLE:
            panel_parts = [f'<p class="report-msg report-msg-info">{t("html.messages.no_3d_plotly")}</p>']
        elif panel_id == '3d' and no_plot:
            panel_parts = [f'<p class="report-msg report-msg-info">{t("html.messages.no_3d_noplot")}</p>']
        else:
            panel_parts = _build_chart_panel(
                plotly_charts_cache, no_charts, inline_warning_html,
                filt, height, png_maps, output_dir, base)
        result.append(f'<div id="panel-{panel_id}" class="report-panel">' + '\n'.join(panel_parts) + '</div>')
    return '\n'.join(result)


# ---------------------------------------------------------------------------
# Основная функция генерации HTML-отчёта
# ---------------------------------------------------------------------------

def create_report_html(output_dir: Path, base_filename: str, no_plot: bool = False, no_html: bool = False,
                       no_csv: bool = False, no_png: bool = False, df_clean: Optional[pd.DataFrame] = None,
                       geojson_path: Optional[Path] = None) -> None:
    """Создаёт единый HTML-отчёт с табами или отдельные HTML-страницы с плотами.

    При no_html=True единый отчёт не создаётся, вместо этого каждый Plotly-график
    сохраняется в отдельный HTML-файл с увеличенным в 3 раза лимитом записей.
    """
    # Режим отдельных HTML-страниц: каждый Plotly-график в свой файл с 3x лимитом
    if no_html:
        if not no_plot and df_clean is not None and PLOTLY_AVAILABLE:
            save_separate_plot_files(df_clean, output_dir, base_filename)
        return

    if _jinja_env is None:
        logger.error('jinja2 не установлен — HTML-отчёт пропущен')
        return

    out_path = output_dir / f'{base_filename}_report.html'
    base = base_filename

    show_timeline_tab = no_plot and not no_png

    map_panel_html = ''
    if geojson_path is not None:
        map_panel_html = build_map_panel(Path(geojson_path))
    show_map_tab = bool(map_panel_html)

    metrics_path = output_dir / f'{base}_metrics.csv'

    plotly_charts_cache = None
    if not no_plot and df_clean is not None:
        plotly_charts_cache = build_plotly_html_charts(df_clean, output_dir, base)

    inline_warning_html = (
        '<div class="inline-warning report-msg report-msg-warning">'
        f'<strong>{t("html.messages.csp_warning_title")}</strong><br>'
        f'{t("html.messages.csp_warning_plotly")}'
        '</div>'
    )

    trip_start_sec = 0
    if df_clean is not None and 'TIME' in df_clean.columns:
        try:
            v = float(df_clean['TIME'].dropna().iloc[0])
            if 0 <= v < 86400:
                trip_start_sec = int(v)
        except (ValueError, IndexError):
            pass

    context = {
        'logo_svg':         _brand_svg(),
        'lang':             get_language(),
        'base':             html_module.escape(base),
        'generated_at':     datetime.now().strftime('%Y-%m-%d %H:%M'),
        'css':              _REPORT_CSS,
        'js':               (_SCRIPT_DIR / 'build_html.js').read_text(encoding='utf-8'),
        'show_timeline_tab': show_timeline_tab,
        'show_map_tab':     show_map_tab,
        'trip_start_sec':   trip_start_sec,
        'summary_panel':    _build_summary_panel(metrics_path),
        'reports_panel':    _build_reports_panel(output_dir, base, no_csv),
        'chart_panels':     _build_chart_panels(plotly_charts_cache, no_png, no_plot,
                                                inline_warning_html, output_dir, base),
        'map_panel':        map_panel_html,
    }

    try:
        html_content = _jinja_env.get_template('build_html.j2').render(context)
        out_path.write_text(html_content, encoding='utf-8')
        logger.info(t('console.html_report_saved', path=out_path))
    except OSError as e:
        logger.error(t('console.html_create_error', e=e))
