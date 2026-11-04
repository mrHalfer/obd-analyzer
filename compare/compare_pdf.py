#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Модуль генерации PDF-отчёта сравнения поездок OBD-II.

Содержит:
- Сводную таблицу метрик по всем поездкам с цветовым кодированием
- Встроенные PNG-графики (тренды, детонация, режимы, heatmap)
"""

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
from compare_core import build_compare_rows
from core_obd import brand_logo_flowable as _brand_logo_flowable, BRAND_LOGO_W as _BRAND_LOGO_W

logger = logging.getLogger(__name__)

try:
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.lib import colors
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, Image,
        PageBreak, Table, TableStyle,
    )
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    REPORTLAB_AVAILABLE = True


except ImportError:
    REPORTLAB_AVAILABLE = False


# ---------------------------------------------------------------------------
# Шрифты
# ---------------------------------------------------------------------------

def _register_fonts() -> tuple[str, str]:
    """Регистрирует системные шрифты (Arial / Calibri / DejaVu) для PDF.

    Returns:
        (font_name, font_name_bold) — имена зарегистрированных шрифтов.
        Возвращает ('Helvetica', 'Helvetica-Bold') если ни один шрифт не найден.
    """
    font_name, font_name_bold = 'Helvetica', 'Helvetica-Bold'
    font_paths = [
        ('C:/Windows/Fonts/arial.ttf',   'C:/Windows/Fonts/arialbd.ttf'),
        ('C:/Windows/Fonts/calibri.ttf', 'C:/Windows/Fonts/calibrib.ttf'),
        ('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
         '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'),
    ]
    for reg_path, bold_path in font_paths:
        if Path(reg_path).exists():
            try:
                pdfmetrics.registerFont(TTFont('CmpFont', reg_path))
                font_name = 'CmpFont'
                if Path(bold_path).exists():
                    pdfmetrics.registerFont(TTFont('CmpFontBold', bold_path))
                    font_name_bold = 'CmpFontBold'
                else:
                    font_name_bold = font_name
                break
            except (OSError, RuntimeError):
                continue
    return font_name, font_name_bold


# ---------------------------------------------------------------------------
# Вспомогательные функции
# ---------------------------------------------------------------------------

_STAT_COLORS = {
    '✅': colors.Color(0.78, 0.93, 0.78),   # светло-зелёный
    '⚠️': colors.Color(1.0,  0.90, 0.70),   # светло-оранжевый
    '❌': colors.Color(0.99, 0.80, 0.80),   # светло-красный
    '○':  colors.Color(0.92, 0.93, 0.94),   # светло-серый
    '':   colors.white,
}


def _stat_bg(stat_str: str) -> object:
    """Возвращает цвет фона ячейки PDF по строке статуса (✅/⚠️/❌/○)."""
    return _STAT_COLORS.get(str(stat_str).strip(), colors.white)


def _add_png(story: list, png_path: Path | None, width_mm: float = 230, max_height_mm: float = 155) -> None:
    """Добавляет PNG в story с ограничением размера под страницу landscape A4."""
    if not png_path or not png_path.exists():
        return
    try:
        from PIL import Image as PILImage
        with PILImage.open(str(png_path)) as pil_img:
            w_px, h_px = pil_img.size
        aspect = h_px / w_px
        draw_w = width_mm
        draw_h = draw_w * aspect
        if draw_h > max_height_mm:
            draw_h = max_height_mm
            draw_w = max_height_mm / aspect
        img = Image(str(png_path), width=draw_w * mm, height=draw_h * mm)
        story.append(img)
        story.append(Spacer(1, 4 * mm))
    except (OSError, ValueError) as e:
        logger.warning(f'Не удалось вставить PNG {png_path.name}: {e}')


def _add_tall_png(
    story: list,
    png_path: Path | None,
    width_mm: float = 255,
    page_h_mm: float = 165,
    padding_px: int = 12,
) -> None:
    """Добавляет высокий PNG по-подграфику: каждый subplot вырезается точно
    по своим border-линиям и пакуется на страницы по мере заполнения.

    Алгоритм:
    1. Сканирует строки пикселей → находит все горизонтальные тёмные полосы
       (spine-линии matplotlib) → группирует в «бэнды».
    2. Пары бэндов с большим зазором между ними = один subplot
       (top-spine + bottom-spine, между ними контент).
    3. Паки subplot-ов на страницы не превышая page_h_mm.
    Требует Pillow; при отсутствии — откатывается к _add_png.
    """
    if not png_path or not png_path.exists():
        return
    import io as _io
    try:
        from PIL import Image as PILImage
    except ImportError:
        _add_png(story, png_path, width_mm, page_h_mm)
        return
    try:
        with PILImage.open(str(png_path)) as pil_img:
            pil_img.load()
            w_px, h_px = pil_img.size
            px_per_mm  = w_px / width_mm
            page_h_px  = int(page_h_mm * px_per_mm)

            # ------------------------------------------------------------------
            # Шаг 1: найти все строки с тёмными пикселями (spine-линии)
            # ------------------------------------------------------------------
            gray = pil_img.convert('L')
            pix  = gray.load()
            step = max(1, w_px // 80)          # ~80 проб по ширине
            n_samples = w_px // step

            dark_rows: list[int] = []
            for y in range(h_px):
                n_dark = sum(1 for x in range(0, w_px, step) if pix[x, y] < 50)
                if n_dark > n_samples * 0.35:
                    dark_rows.append(y)

            # ------------------------------------------------------------------
            # Шаг 2: сгруппировать в «бэнды» (последовательные тёмные строки)
            # ------------------------------------------------------------------
            bands: list[tuple[int, int]] = []   # (y_start, y_end) каждого бэнда
            if dark_rows:
                bs, prev = dark_rows[0], dark_rows[0]
                for y in dark_rows[1:]:
                    if y - prev > 5:
                        bands.append((bs, prev))
                        bs = y
                    prev = y
                bands.append((bs, prev))

            # ------------------------------------------------------------------
            # Шаг 3: выделить прямоугольники подграфиков
            # Паттерн: band[0](top) → большой зазор → band[1](bottom) → малый зазор
            #          → band[2](top следующего) → ...
            # «Большой» зазор (> 80px) = контент subplot между top/bottom spine.
            # ------------------------------------------------------------------
            subplot_rects: list[tuple[int, int]] = []
            i = 0
            while i + 1 < len(bands):
                top_band = bands[i]
                bot_band = bands[i + 1]
                gap = bot_band[0] - top_band[1]
                if gap > 80:
                    y0 = max(0,    top_band[0] - padding_px)
                    y1 = min(h_px, bot_band[1] + padding_px)
                    subplot_rects.append((y0, y1))
                    i += 2
                else:
                    i += 1

            # Fallback: не нашли подграфиков — вставляем целиком
            if not subplot_rects:
                subplot_rects = [(0, h_px)]

            # ------------------------------------------------------------------
            # Шаг 4: паковать подграфики на страницы, не превышая page_h_px
            # ------------------------------------------------------------------
            pages: list[list[tuple[int, int]]] = []
            cur_page: list[tuple[int, int]] = []
            cur_h = 0
            for (y0, y1) in subplot_rects:
                rect_h = y1 - y0
                if cur_page and cur_h + rect_h > page_h_px:
                    pages.append(cur_page)
                    cur_page = [(y0, y1)]
                    cur_h = rect_h
                else:
                    cur_page.append((y0, y1))
                    cur_h += rect_h
            if cur_page:
                pages.append(cur_page)

            # ------------------------------------------------------------------
            # Шаг 5: вставить в story
            # ------------------------------------------------------------------
            for page_i, page_rects in enumerate(pages):
                if page_i > 0:
                    story.append(PageBreak())
                for (y0, y1) in page_rects:
                    chunk = pil_img.crop((0, y0, w_px, y1))
                    buf = _io.BytesIO()
                    chunk.save(buf, format='PNG')
                    buf.seek(0)
                    chunk_h_mm = (y1 - y0) / px_per_mm
                    story.append(Image(buf, width=width_mm * mm, height=chunk_h_mm * mm))
                    story.append(Spacer(1, 3 * mm))

    except (OSError, ValueError) as e:
        logger.warning(f'Не удалось вставить PNG {png_path.name}: {e}')


# ---------------------------------------------------------------------------
# Построение таблицы метрик
# ---------------------------------------------------------------------------

# Ширина usable-области страницы landscape A4 при полях 15мм с каждой стороны
_PAGE_W_MM = 267
_METRIC_COL_W_MM = 48
_TRIP_COL_MIN_MM = 28
# Максимум колонок поездок на одну таблицу
_MAX_TRIPS_PER_TABLE = (_PAGE_W_MM - _METRIC_COL_W_MM) // _TRIP_COL_MIN_MM  # = 7


def _build_one_chunk_table(
    rows_data: list,
    chunk_ids: list,
    font_name: str,
    font_name_bold: str,
) -> 'Table':
    """Строит одну ReportLab-таблицу для chunk_ids поездок."""
    n_cols = len(chunk_ids)
    trip_col_w = (_PAGE_W_MM - _METRIC_COL_W_MM) / n_cols * mm

    header = [t('compare.table.metric')] + [str(tid) for tid in chunk_ids]
    table_data = [header]
    style_cmds = [
        ('BACKGROUND', (0, 0), (-1, 0), colors.Color(0.85, 0.87, 0.98)),
        ('TEXTCOLOR',  (0, 0), (-1, 0), colors.Color(0.1, 0.13, 0.5)),
        ('FONTNAME',   (0, 0), (-1, 0), font_name_bold),
        ('FONTSIZE',   (0, 0), (-1, 0), 8),
        ('ALIGN',      (0, 0), (-1, 0), 'CENTER'),
        ('ALIGN',      (0, 0), (0, -1), 'LEFT'),
        ('FONTSIZE',   (0, 1), (-1, -1), 7.5),
        ('FONTNAME',   (0, 1), (-1, -1), font_name),
        ('GRID',       (0, 0), (-1, -1), 0.4, colors.Color(0.8, 0.8, 0.85)),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1),
         [colors.white, colors.Color(0.97, 0.97, 0.99)]),
        ('VALIGN',     (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ('LEFTPADDING',   (0, 0), (-1, -1), 4),
        ('RIGHTPADDING',  (0, 0), (-1, -1), 4),
    ]

    for r_idx, row in enumerate(rows_data, start=1):
        data_row = [row['label']]
        for c_idx, tid in enumerate(chunk_ids, start=1):
            val_str  = row['trip_vals'].get(tid,  '')
            stat_str = row['trip_stats'].get(tid, '')
            cell_text = val_str if val_str not in ('', 'nan') else '—'
            data_row.append(cell_text)
            bg = _stat_bg(stat_str)
            if bg != colors.white:
                style_cmds.append(
                    ('BACKGROUND', (c_idx, r_idx), (c_idx, r_idx), bg)
                )
        table_data.append(data_row)

    col_widths = [_METRIC_COL_W_MM * mm] + [trip_col_w] * n_cols
    tbl = Table(table_data, colWidths=col_widths, repeatRows=1)
    tbl.setStyle(TableStyle(style_cmds))
    return tbl


def _build_metrics_tables(
    vals_df: pd.DataFrame,
    stats_df: pd.DataFrame,
    font_name: str,
    font_name_bold: str,
) -> list:
    """Строит список таблиц ReportLab (по одной на каждый chunk поездок).

    Разбивает поездки на группы по _MAX_TRIPS_PER_TABLE чтобы таблица
    не выходила за границы страницы landscape A4.

    Returns:
        Список объектов Table (пустой если нет данных).
    """
    if vals_df.empty:
        return []
    trip_ids = list(vals_df.index)
    rows_data = build_compare_rows(vals_df, stats_df)
    if not rows_data:
        return []

    # Разбиваем поездки на чанки
    chunks = [
        trip_ids[i: i + _MAX_TRIPS_PER_TABLE]
        for i in range(0, len(trip_ids), _MAX_TRIPS_PER_TABLE)
    ]
    return [
        _build_one_chunk_table(rows_data, chunk, font_name, font_name_bold)
        for chunk in chunks
    ]


# ---------------------------------------------------------------------------
# Публичная функция
# ---------------------------------------------------------------------------

def create_compare_pdf(
    output_dir: Path,
    vals_df: pd.DataFrame,
    stats_df: pd.DataFrame,
    png_paths: dict[str, Path],
) -> Path | None:
    """Генерирует PDF-отчёт сравнения поездок.

    Args:
        output_dir: Директория для сохранения.
        vals_df: DataFrame значений (индекс=trip_id, столбцы=CODE).
        stats_df: DataFrame статусов.
        png_paths: Словарь {name: path} сгенерированных PNG.

    Returns:
        Путь к PDF или None при ошибке/недоступности reportlab.
    """
    if not REPORTLAB_AVAILABLE:
        logger.warning('compare_pdf: reportlab не установлен, PDF пропущен')
        return None

    if vals_df.empty:
        logger.warning('compare_pdf: нет данных для отчёта')
        return None

    font_name, font_name_bold = _register_fonts()
    styles = getSampleStyleSheet()

    out_path = output_dir / 'comparison_report.pdf'
    doc = SimpleDocTemplate(
        str(out_path),
        pagesize=landscape(A4),
        leftMargin=15 * mm, rightMargin=15 * mm,
        topMargin=15 * mm,  bottomMargin=15 * mm,
    )

    story = []
    now_str = datetime.now().strftime('%Y-%m-%d %H:%M')
    n_trips = len(vals_df)

    title_style = ParagraphStyle(
        'CmpTitle', parent=styles['Heading1'],
        fontName=font_name_bold, fontSize=16,
        textColor=colors.Color(0.1, 0.13, 0.5),
        spaceAfter=4,
    )
    sub_style = ParagraphStyle(
        'CmpSub', parent=styles['Normal'],
        fontName=font_name, fontSize=9,
        textColor=colors.Color(0.4, 0.4, 0.4),
        spaceAfter=12,
    )
    h2_style = ParagraphStyle(
        'CmpH2', parent=styles['Heading2'],
        fontName=font_name_bold, fontSize=11,
        textColor=colors.Color(0.1, 0.13, 0.5),
        spaceBefore=8, spaceAfter=4,
    )

    # Заголовок (слева) + логотип (справа)
    _hdr = Table(
        [[[Paragraph(t('compare.pdf.title'), title_style),
           Paragraph(t('compare.pdf.generated', date=now_str, n=n_trips), sub_style)],
          _brand_logo_flowable()]],
        colWidths=[None, _BRAND_LOGO_W + 4],
    )
    _hdr.setStyle(TableStyle([
        ('VALIGN',        (0, 0), (-1, -1), 'TOP'),
        ('ALIGN',         (1, 0), (1, 0),   'RIGHT'),
        ('LEFTPADDING',   (0, 0), (-1, -1), 0),
        ('RIGHTPADDING',  (0, 0), (-1, -1), 0),
        ('TOPPADDING',    (0, 0), (-1, -1), 0),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
    ]))
    story.append(_hdr)

    # Сводная таблица метрик (разбитая на чанки при большом числе поездок)
    tables = _build_metrics_tables(vals_df, stats_df, font_name, font_name_bold)
    for i, tbl in enumerate(tables):
        if i == 0:
            story.append(Paragraph(t('compare.table.title'), h2_style))
        else:
            story.append(PageBreak())
            story.append(Paragraph(
                f'{t("compare.table.title")} ({i + 1}/{len(tables)})', h2_style,
            ))
        story.append(tbl)
        story.append(Spacer(1, 8 * mm))

    # PNG-графики
    chart_titles = {
        'trends':  t('compare.trends.title'),
        'knock':   t('compare.knock.title'),
        'modes':   t('compare.modes.title'),
        'heatmap': t('compare.heatmap.title'),
    }
    for key, title in chart_titles.items():
        if key in png_paths:
            story.append(PageBreak())
            story.append(Paragraph(title, h2_style))
            if key == 'trends':
                _add_tall_png(story, png_paths[key])
            else:
                _add_png(story, png_paths[key])

    try:
        doc.build(story)
        logger.info(t('console.compare_pdf_saved', path=out_path))
        return out_path
    except (OSError, RuntimeError) as e:
        logger.error(f'Ошибка создания PDF сравнения: {e}', exc_info=True)
        return None
