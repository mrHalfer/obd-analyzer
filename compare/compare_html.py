#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Модуль генерации HTML-отчёта сравнения поездок OBD-II.

Создаёт единый HTML-файл с вкладками:
- Сводка           — таблица ключевых метрик по всем поездкам
- Тренды           — графики трендов LTFT/STFT/T ОЖ и др.
- Детонация        — столбчатая диаграмма
- Режимы           — распределение времени по режимам езды
- Статусы          — heatmap статусов
- Профили          — полные таблицы профилей скорости по поездкам (если есть *_profile.csv)
- Тренды профилей  — Plotly-графики по метрикам профиля (X=бин скорости, lazy iframe)
"""

import base64
import html as html_module
import logging
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

_root = Path(__file__).parent.parent
for _d in [str(_root)]:
    if _d not in sys.path:
        sys.path.insert(0, _d)

from translation import t
from compare_core import (
    build_compare_rows,
)
try:
    from compare_plotly import generate_all_plotly_html, PLOTLY_AVAILABLE as _PLOTLY_AVAILABLE
except ImportError:
    _PLOTLY_AVAILABLE = False
    def generate_all_plotly_html(*_a: object, **_kw: object) -> dict:  # type: ignore[misc]
        return {}

try:
    from compare_profiles import (
        load_profiles,
        build_profiles_table_html,
        build_profile_trends_html,
        _PLOTLY_AVAILABLE as _PROFILES_PLOTLY,
    )
except ImportError:
    _PROFILES_PLOTLY = False
    def load_profiles(*_a: object, **_kw: object) -> dict:  # type: ignore[misc]
        return {}
    def build_profiles_table_html(*_a: object, **_kw: object) -> str:  # type: ignore[misc]
        return ''
    def build_profile_trends_html(*_a: object, **_kw: object) -> str:  # type: ignore[misc]
        return ''

logger = logging.getLogger(__name__)

_SCRIPT_DIR = Path(__file__).parent
_STATUS_CLASS = {'✅': 's-ok', '⚠️': 's-warn', '❌': 's-err', '○': 's-neu', '': ''}

# ---------------------------------------------------------------------------
# Jinja2 — шаблонизатор HTML-отчёта сравнения
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
    logger.warning('jinja2 не установлен — HTML-отчёт сравнения недоступен. Установите: pip install jinja2')


def _load_asset(name: str) -> str:
    """Читает CSS/JS-ресурс из директории модуля. Возвращает пустую строку при ошибке."""
    path = _SCRIPT_DIR / name
    try:
        return path.read_text(encoding='utf-8')
    except OSError:
        return ''


from core_obd import brand_svg as _brand_svg


def _img_tag(png_path: Path) -> str:
    """Возвращает <img> с base64-встроенным PNG или пустую строку."""
    if not png_path or not png_path.exists():
        return f'<p class="no-data-msg">{html_module.escape(t("compare.html.no_chart"))}</p>'
    try:
        data = png_path.read_bytes()
        b64 = base64.b64encode(data).decode('ascii')
        return f'<img src="data:image/png;base64,{b64}" alt="{png_path.stem}">'
    except OSError:
        return f'<p class="no-data-msg">{html_module.escape(t("compare.html.no_chart"))}</p>'


def _stat_cell(val_str: str, stat_str: str, col_idx: int, tooltip: str = '') -> str:
    """HTML ячейка с окраской по статусу, data-col и title-тултипом."""
    stat_str = str(stat_str).strip()
    css = _STATUS_CLASS.get(stat_str, '')
    v = html_module.escape(str(val_str)) if val_str not in ('', 'nan') else '—'
    cls = f' class="{css}"' if css else ''
    tip = f' title="{html_module.escape(tooltip)}"' if tooltip else ''
    return f'<td{cls}{tip} data-col="{col_idx}">{v}</td>'


def _build_summary_table(
    vals_df: pd.DataFrame,
    stats_df: pd.DataFrame,
) -> str:
    """Формирует HTML-таблицу сводки: строки=метрики, столбцы=поездки с окраской по статусу."""
    if vals_df.empty:
        return f'<p class="no-data-msg">{html_module.escape(t("compare.html.no_data"))}</p>'

    trip_ids = list(vals_df.index)
    rows = build_compare_rows(vals_df, stats_df)

    # Заголовок таблицы
    header_cells = ''.join(
        f'<th data-col="{i}">{html_module.escape(str(tid))}</th>'
        for i, tid in enumerate(trip_ids)
    )
    col_param = html_module.escape(t('compare.html.col_param'))
    header = f'<tr><th class="metric-col">{col_param}</th>{header_cells}</tr>'

    # Строки данных
    body_rows = []
    for row in rows:
        label = row['label']
        cells = ''.join(
            _stat_cell(row['trip_vals'].get(tid, ''), row['trip_stats'].get(tid, ''), i,
                       tooltip=f'{tid} · {label}')
            for i, tid in enumerate(trip_ids)
        )
        body_rows.append(f'<tr><td class="metric-name">{html_module.escape(label)}</td>{cells}</tr>')

    body = ''.join(body_rows)
    return (
        '<div class="compare-table-wrap" data-tscope="summary">'
        f'<table class="compare-table"><thead>{header}</thead><tbody>{body}</tbody></table>'
        '</div>'
    )


def _build_chart_panel(title: str, chart_id: str, plotly_json: str | None, png_path: Path | None) -> str:
    """Панель с графиком: Plotly lazy-init (приоритет) или PNG (fallback)."""
    if plotly_json:
        content = (
            '<div class="chart-wrap">'
            f'<div id="{chart_id}" class="lazy-chart"></div>'
            f'<script type="application/json" id="{chart_id}-spec">{plotly_json}</script>'
            '</div>'
        )
    elif png_path:
        content = f'<div class="chart-wrap">{_img_tag(png_path)}</div>'
    else:
        content = f'<p class="no-data-msg">{html_module.escape(t("compare.html.no_chart"))}</p>'
    return f'<div class="panel"><h2>{html_module.escape(title)}</h2>{content}</div>'


def _build_trip_badges(trip_ids: list[str], scope: str = 'summary') -> str:
    """Строка кликабельных бейджей поездок + кнопка скрыть/показать все."""
    tooltip   = html_module.escape(t('compare.html.badge_tooltip'))
    trips_lbl = html_module.escape(t('compare.html.trips_label'))
    show_lbl  = html_module.escape(t('compare.html.show_all'))
    hide_lbl  = html_module.escape(t('compare.html.hide_all'))
    badges = ''.join(
        f'<span class="trip-badge" data-col="{i}" data-scope="{scope}" title="{tooltip}">'
        f'{html_module.escape(tid)}</span>'
        for i, tid in enumerate(trip_ids)
    )
    btn = (
        f'<button class="btn-toggle-all" data-scope="{scope}"'
        f' data-show="{show_lbl}" data-hide="{hide_lbl}">{hide_lbl}</button>'
    )
    return f'<p class="badges-row"><b>{trips_lbl}</b> {badges} {btn}</p>'


def create_compare_html(
    output_dir: Path,
    vals_df: pd.DataFrame,
    stats_df: pd.DataFrame,
    png_paths: dict[str, Path],
) -> Path | None:
    """Генерирует HTML-отчёт сравнения поездок.

    Args:
        output_dir: Директория для сохранения файла.
        vals_df: DataFrame значений (индекс=trip_id, столбцы=CODE).
        stats_df: DataFrame статусов.
        png_paths: Словарь {name: path} сгенерированных PNG.

    Returns:
        Путь к созданному HTML-файлу или None при ошибке.
    """
    if _jinja_env is None:
        logger.error('jinja2 не установлен — HTML-отчёт сравнения пропущен')
        return None

    if vals_df.empty:
        logger.warning('compare_html: нет данных для отчёта')
        return None

    trip_ids = list(vals_df.index)
    n_trips  = len(trip_ids)
    now_str  = datetime.now().strftime('%Y-%m-%d %H:%M')

    plotly_html: dict[str, str] = generate_all_plotly_html(vals_df, stats_df)

    # Загружаем профили скорости из той же директории
    profiles = load_profiles(output_dir)
    has_profiles = bool(profiles)

    has_plotly = bool(plotly_html) or (has_profiles and _PROFILES_PLOTLY)

    tab_defs = [
        ('ctab-summary',        'cpanel-summary',        '📊 ' + t('compare.html.tab_summary'),        True),
        ('ctab-trends',         'cpanel-trends',         '📈 ' + t('compare.html.tab_trends'),         'trends'  in plotly_html or 'trends'  in png_paths),
        ('ctab-profiles',       'cpanel-profiles',       '🚗 '  + t('compare.html.tab_profiles'),      has_profiles),
        ('ctab-profile-trends', 'cpanel-profile-trends', '📉 ' + t('compare.html.tab_profile_trends'), has_profiles),
        ('ctab-knock',          'cpanel-knock',          '💥 ' + t('compare.html.tab_knock'),          'knock'   in plotly_html or 'knock'   in png_paths),
        ('ctab-modes',          'cpanel-modes',          '⏲️ '  + t('compare.html.tab_modes'),         'modes'   in plotly_html or 'modes'   in png_paths),
        ('ctab-heatmap',        'cpanel-heatmap',        '⁉️ '  + t('compare.html.tab_heatmap'),       'heatmap' in plotly_html or 'heatmap' in png_paths),
    ]
    tab_defs = [(tid, pid, lbl, vis) for tid, pid, lbl, vis in tab_defs if vis]

    panel_title = html_module.escape(t('compare.html.panel_title', n=n_trips))
    summary_content = (
        f'<div class="panel"><h2>{panel_title}</h2>'
        f'{_build_trip_badges(trip_ids)}'
        f'{_build_summary_table(vals_df, stats_df)}'
        '</div>'
    )

    profiles_title   = html_module.escape(t('compare.html.profiles_title'))
    prof_trends_title = html_module.escape(t('compare.html.profile_trends_title'))

    panels_html = {
        'cpanel-summary': summary_content,
        'cpanel-trends':  _build_chart_panel(t('compare.trends.title'),
                                             'cmpchart-trends',  plotly_html.get('trends'),  png_paths.get('trends')),
        'cpanel-knock':   _build_chart_panel(t('compare.knock.title'),
                                             'cmpchart-knock',   plotly_html.get('knock'),   png_paths.get('knock')),
        'cpanel-modes':   _build_chart_panel(t('compare.modes.title'),
                                             'cmpchart-modes',   plotly_html.get('modes'),   png_paths.get('modes')),
        'cpanel-heatmap': _build_chart_panel(t('compare.heatmap.title'),
                                             'cmpchart-heatmap', plotly_html.get('heatmap'), png_paths.get('heatmap')),
        'cpanel-profiles': (
            f'<div class="panel"><h2>{profiles_title}</h2>'
            f'{_build_trip_badges(trip_ids, scope="profiles")}'
            f'{build_profiles_table_html(profiles)}</div>'
        ),
        'cpanel-profile-trends': (
            f'<div class="panel"><h2>{prof_trends_title}</h2>'
            f'{build_profile_trends_html(profiles, plotly_available=has_plotly)}</div>'
        ),
    }

    page_title = html_module.escape(t('compare.pdf.title'))
    meta = html_module.escape(t('compare.pdf.generated', date=now_str, n=n_trips))

    inline_warning = (
        '<div class="inline-warning report-msg report-msg-warning">'
        f'<strong>{t("html.messages.csp_warning_title")}</strong><br>'
        f'{t("html.messages.csp_warning_plotly")}'
        '</div>'
    ) if has_plotly else ''

    context = {
        'logo_svg':         _brand_svg(),
        'page_title':       page_title,
        'meta':             meta,
        'inline_warning':   inline_warning,
        'plotly_cdn':       '<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>' if has_plotly else '',
        'css':              _load_asset('compare_html.css'),
        'js':               _load_asset('compare_html.js'),
        'tab_defs':         tab_defs,
        'panels_html':      panels_html,
    }

    out_path = output_dir / 'comparison_report.html'
    try:
        html_content = _jinja_env.get_template('compare_html.j2').render(context)
        out_path.write_text(html_content, encoding='utf-8')
        logger.info(t('console.compare_html_saved', path=out_path))
        return out_path
    except OSError as e:
        logger.error(f'Ошибка записи HTML сравнения: {e}')
        return None
