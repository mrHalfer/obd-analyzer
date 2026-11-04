#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Модуль формирования PDF-отчёта для анализа OBD-II данных.

Содержит:
- Функцию создания PDF отчёта с метриками и PNG иллюстрациями
- Красивые карточки со сводной информацией
- Таблицы по режимам с цветовым кодированием
- Профиль скорости и группы детонации
- Визуализации (PNG графики)
"""

import logging
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
import sys as _sys
from pathlib import Path as _Path
_root = _Path(__file__).parent.parent
for _d in [str(_root), str(_root / 'build'), str(_root / 'plugins')]:
    if _d not in _sys.path:
        _sys.path.insert(0, _d)

from core_obd import (
    SEPARATOR_LINE,
    STATUS_OK, STATUS_WARNING, STATUS_ERROR, STATUS_NEUTRAL,
    STATUS_COLOR_OK, STATUS_COLOR_WARNING, STATUS_COLOR_ERROR, STATUS_COLOR_NEUTRAL,
    get_metric_val,
    get_metric_stat,
    brand_logo_flowable as _brand_logo_flowable,
    BRAND_LOGO_W as _BRAND_LOGO_W,
)
from translation import t

logger = logging.getLogger(__name__)

try:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.lib import colors
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image, PageBreak, Table, TableStyle, KeepTogether, Flowable
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    REPORTLAB_AVAILABLE = True


except ImportError:
    REPORTLAB_AVAILABLE = False


# ============================================================================
# Вспомогательные функции PDF
# ============================================================================

def _register_fonts() -> tuple[str, str]:
    """Регистрирует кириллический шрифт для PDF.

    Returns:
        (font_name, font_name_bold) — имена зарегистрированных шрифтов.
    """
    font_name = 'CustomFont'
    font_name_bold = 'CustomFontBold'
    try:
        font_paths = [
            ('C:/Windows/Fonts/arial.ttf', 'C:/Windows/Fonts/arialbd.ttf'),
            ('C:/Windows/Fonts/calibri.ttf', 'C:/Windows/Fonts/calibrib.ttf'),
            ('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'),
        ]
        font_registered = False
        for regular_path, bold_path in font_paths:
            if Path(regular_path).exists():
                try:
                    pdfmetrics.registerFont(TTFont(font_name, regular_path))
                    if Path(bold_path).exists():
                        pdfmetrics.registerFont(TTFont(font_name_bold, bold_path))
                    else:
                        font_name_bold = font_name
                    font_registered = True
                    break
                except (OSError, RuntimeError):
                    continue
        if not font_registered:
            font_name = 'Helvetica'
            font_name_bold = 'Helvetica-Bold'
    except (OSError, RuntimeError):
        font_name = 'Helvetica'
        font_name_bold = 'Helvetica-Bold'
    return font_name, font_name_bold


def _get_metric_val(metrics_df: pd.DataFrame, code: str) -> str:
    """Возвращает значение метрики по коду."""
    return get_metric_val(metrics_df, code, default='N/A')


def _get_metric_stat(metrics_df: pd.DataFrame, code: str) -> str:
    """Возвращает текстовый статус метрики по коду (OK/WARN/ERR)."""
    return get_metric_stat(metrics_df, code, default='', as_text=True)


def _get_metric_stat_raw(metrics_df: pd.DataFrame, code: str) -> str:
    """Возвращает сырой статус метрики (эмодзи) по коду."""
    return get_metric_stat(metrics_df, code, default='', as_text=False)


def _create_card(title: str, data_rows: list, font_name: str,
                 subheading_style: Any, bg_color: Any = None) -> 'Table':
    """Создаёт красивую карточку с заголовком и данными.

    Args:
        title: Заголовок карточки.
        data_rows: Список строк [[label, value], ...].
        font_name: Имя шрифта для данных.
        subheading_style: ParagraphStyle для заголовка карточки.
        bg_color: Цвет фона данных (по умолчанию светло-голубой).
    """
    if bg_color is None:
        bg_color = colors.HexColor('#e3f2fd')

    # На вырошенных логах (метрики отсутствуют) data_rows пуст: reportlab
    # падает на пустой таблице с ValueError — подставляем строку-заглушку
    if not data_rows:
        data_rows = [[t('common.no_data'), '']]

    # Стиль заголовка карточки (белый текст)
    card_title_style = ParagraphStyle(
        'CardTitle',
        parent=subheading_style,
        textColor=colors.HexColor('#F5F5F5')
    )

    # Заголовок карточки
    title_data = [[Paragraph(f'<b>{title}</b>', card_title_style)]]
    title_table = Table(title_data, colWidths=[8*cm])
    title_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#1976d2')),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('LEFTPADDING', (0, 0), (-1, -1), 10),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
    ]))

    # Данные карточки
    data_table = Table(data_rows, colWidths=[5.5*cm, 2.5*cm])
    data_table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, -1), font_name),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('ALIGN', (0, 0), (0, -1), 'LEFT'),
        ('ALIGN', (1, 0), (-1, -1), 'RIGHT'),
        ('BACKGROUND', (0, 0), (-1, -1), bg_color),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ('LEFTPADDING', (0, 0), (-1, -1), 10),
        ('RIGHTPADDING', (0, 0), (-1, -1), 10),
        ('LINEBELOW', (0, 0), (-1, -2), 0.5, colors.HexColor('#bbdefb')),
    ]))

    # Обёртка карточки с рамкой
    card_data = [[title_table], [data_table]]
    card = Table(card_data, colWidths=[8*cm])
    card.setStyle(TableStyle([
        ('BOX', (0, 0), (-1, -1), 1.5, colors.HexColor('#1976d2')),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('TOPPADDING', (0, 0), (-1, -1), 0),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
    ]))
    return card


def _get_param_group(code: str) -> int:
    """Определяет группу параметра для цветового кодирования в таблицах режимов."""
    if any(x in code for x in ['COUNT', 'DURATION', 'STALLED']):
        return 1  # Основные: количество, длительность, заглохи
    elif 'TEMP_COOLANT' in code:
        return 2  # Температура ОЖ
    elif 'LTFT' in code:
        return 3  # LTFT
    elif 'STFT' in code:
        return 4  # STFT
    elif 'O2_' in code or 'O2S' in code:
        return 5  # ДК (датчики кислорода)
    elif 'MAF' in code:
        return 6  # Расход воздуха
    elif 'INJECTION' in code:
        return 7  # Время впрыска
    elif 'THROTTLE' in code:
        return 8  # Дроссель
    elif 'FUEL' in code and 'LTFT' not in code and 'STFT' not in code:
        return 9  # Расход топлива
    elif 'RPM' in code:
        return 10  # Обороты
    elif 'SPEED' in code:
        return 11  # Скорость
    elif 'LOAD' in code:
        return 12  # Нагрузка
    elif 'SPARK' in code:
        return 13  # УОЗ
    elif 'ACCEL' in code:
        return 14  # Педаль
    elif 'INTAKE_TEMP' in code:
        return 15  # Температура впуска
    else:
        return 0  # Неизвестная группа


# Цвета для групп параметров (чередующиеся оттенки)
_GROUP_COLORS = {
    0: None,   # whitesmoke — подставляется при использовании (reportlab может быть недоступен)
    1: '#e8eaf6',     # Основные (COUNT, DURATION, STALLED)
    2: '#fff3e0',     # Температура ОЖ
    3: '#e0f2f1',     # LTFT
    4: '#f3e5f5',     # STFT
    5: '#e8f5e9',     # ДК (датчики кислорода)
    6: '#fce4ec',     # MAF (расход воздуха)
    7: '#fff9c4',     # Время впрыска
    8: '#e1f5fe',     # Дроссель
    9: '#f1f8e9',     # Расход топлива
    10: '#ede7f6',    # RPM (обороты)
    11: '#fff8e1',    # Скорость
    12: '#e0f7fa',    # Нагрузка
    13: '#fbe9e7',    # УОЗ (spark advance)
    14: '#efebe9',    # Педаль акселератора
    15: '#f3e5f5',    # Температура впуска
}


# ============================================================================
# Секции PDF-отчёта
# ============================================================================

def _card_basic_params(metrics_df: pd.DataFrame, font_name: str, subheading_style: Any) -> 'Table':
    """Карточка основных параметров поездки (топливо, температура, длительность, дистанция)."""
    data = [
        [t('pdf.card_fields.fuel'), _get_metric_val(metrics_df, 'RUN_FUEL_TYPE')],
        [t('pdf.card_fields.temp_outside'), _get_metric_val(metrics_df, 'RUN_TEMP_OUTSIDE') + ' °C'],
        [t('pdf.card_fields.duration'), _get_metric_val(metrics_df, 'RUN_DURATION') + ' ' + t('units.min')],
        [t('pdf.card_fields.distance'), _get_metric_val(metrics_df, 'ALL_DRIVE_DISTANCE') + ' ' + t('units.km')],
    ]
    return _create_card(t('pdf.cards.basic_params'), data, font_name, subheading_style, colors.HexColor('#e8f5e9'))


def _card_coolant_temp(metrics_df: pd.DataFrame, font_name: str, subheading_style: Any) -> 'Table':
    """Карточка температуры ОЖ с оценкой термостата, вентилятора и перегрева."""
    warmup_assessment = _get_metric_val(metrics_df, 'COOLANT_WARMUP_ASSESSMENT')
    warmup_stat = _get_metric_stat(metrics_df, 'COOLANT_WARMUP_ASSESSMENT')
    # Термостат: итоговая оценка или статус стабильности как запасной вариант
    thermostat_assessment = _get_metric_val(metrics_df, 'COOLANT_THERMOSTAT_ASSESSMENT')
    thermostat_stat = _get_metric_stat(metrics_df, 'COOLANT_THERMOSTAT_ASSESSMENT')
    if thermostat_assessment == 'N/A':
        thermostat_assessment = _get_metric_val(metrics_df, 'COOLANT_THERMOSTAT_STABILITY')
        thermostat_stat = _get_metric_stat(metrics_df, 'COOLANT_THERMOSTAT_STABILITY')
    fan_assessment = _get_metric_val(metrics_df, 'COOLANT_FAN_ASSESSMENT')
    fan_stat = _get_metric_stat(metrics_df, 'COOLANT_FAN_ASSESSMENT')
    overheat_assessment = _get_metric_val(metrics_df, 'COOLANT_OVERHEAT_ASSESSMENT')
    overheat_stat = _get_metric_stat(metrics_df, 'COOLANT_OVERHEAT_ASSESSMENT')

    temp_mean = _get_metric_val(metrics_df, 'ALL_TEMP_COOLANT_Mean')
    temp_min = _get_metric_val(metrics_df, 'ALL_TEMP_COOLANT_Min')
    temp_max = _get_metric_val(metrics_df, 'ALL_TEMP_COOLANT_Max')

    data = []
    if temp_mean != 'N/A':
        data.append([t('pdf.card_fields.coolant_mean'), temp_mean + ' °C'])
    if temp_min != 'N/A':
        data.append([t('pdf.card_fields.coolant_min'), temp_min + ' °C'])
    if temp_max != 'N/A':
        data.append([t('pdf.card_fields.coolant_max'), temp_max + ' °C'])
    if warmup_assessment != 'N/A':
        data.append([t('pdf.card_fields.warmup'), f'{warmup_assessment} ({warmup_stat})'])
    if thermostat_assessment != 'N/A':
        data.append([t('pdf.card_fields.thermostat'), f'{thermostat_assessment} ({thermostat_stat})'])
    if fan_assessment != 'N/A' and fan_assessment != 'Недостаточно данных':
        data.append([t('pdf.card_fields.fan'), f'{fan_assessment} ({fan_stat})'])
    if overheat_assessment != 'N/A' and overheat_assessment != 'Перегревов нет':
        data.append([t('pdf.card_fields.overheat'), overheat_assessment])

    statuses = [s for s in [warmup_stat, thermostat_stat, fan_stat, overheat_stat] if s]
    if 'ERR' in statuses:
        color = colors.HexColor('#ffebee')
    elif 'WARN' in statuses:
        color = colors.HexColor('#fff9c4')
    else:
        color = colors.HexColor('#fff3e0')
    return _create_card(t('pdf.cards.coolant_temp'), data, font_name, subheading_style, color)


def _card_stalls_misfires(metrics_df: pd.DataFrame, font_name: str, subheading_style: Any) -> 'Table':
    """Карточка заглохов двигателя и пропусков зажигания."""
    stalled = _get_metric_val(metrics_df, 'ALL_STALLED_COUNT')
    stalled_stat = _get_metric_stat(metrics_df, 'ALL_STALLED_COUNT')
    misfires_raw = _get_metric_val(metrics_df, 'MISFIRE_TOTAL_COUNT')
    misfire_stat = _get_metric_stat(metrics_df, 'MISFIRE_TOTAL_COUNT')
    misfires = t('common.no_data') if misfires_raw == '-1' else misfires_raw

    data = [
        [t('pdf.card_fields.stalls'), f'{stalled} ({stalled_stat})'],
        [t('pdf.card_fields.misfires'), f'{misfires} ({misfire_stat})'],
    ]
    if 'ERR' in stalled_stat or 'ERR' in misfire_stat:
        color = colors.HexColor('#ffebee')
    elif 'WARN' in stalled_stat or 'WARN' in misfire_stat:
        color = colors.HexColor('#fff9c4')
    else:
        color = colors.HexColor('#e8f5e9')
    return _create_card(t('pdf.cards.stalls_misfires'), data, font_name, subheading_style, color)


def _card_knock(metrics_df: pd.DataFrame, font_name: str, subheading_style: Any) -> 'Table':
    """Карточка детонации с разбивкой по силе удара (слабая / средняя / сильная)."""
    total_knock = _get_metric_val(metrics_df, 'KNOCK_TOTAL_COUNT')
    total_knock_stat = _get_metric_stat(metrics_df, 'KNOCK_TOTAL_COUNT')
    data = [
        [t('pdf.card_fields.knock_total'), f'{total_knock} ({total_knock_stat})'],
        [t('pdf.card_fields.knock_weak'), _get_metric_val(metrics_df, 'KNOCK_WEAK_COUNT')],
        [t('pdf.card_fields.knock_medium'), _get_metric_val(metrics_df, 'KNOCK_MEDIUM_COUNT')],
        [t('pdf.card_fields.knock_strong'), _get_metric_val(metrics_df, 'KNOCK_STRONG_COUNT')],
    ]
    color = (colors.HexColor('#ffe0b2')
             if (int(total_knock) if total_knock != 'N/A' else 0) > 0
             else colors.HexColor('#e8f5e9'))
    return _create_card(t('pdf.cards.knock'), data, font_name, subheading_style, color)


def _cat_combined_label(metrics_df: pd.DataFrame) -> str:
    """Возвращает строку с объединённой оценкой катализатора (aging + O2)."""
    aging_val = _get_metric_val(metrics_df, 'CAT_AGING_MEAN')
    aging_stat = _get_metric_stat(metrics_df, 'CAT_AGING_MEAN')
    o2_val = _get_metric_val(metrics_df, 'CAT_O2_STATE')
    o2_stat = _get_metric_stat(metrics_df, 'CAT_O2_STATE')
    aging_exists = aging_val != 'N/A'
    o2_exists = o2_val != 'N/A'

    # Когда оценка невозможна (NEUTRAL / пусто) — показываем короткий текст
    o2_display = t('catalyst.cant_assess') if o2_stat == '' else o2_val

    if not aging_exists and not o2_exists:
        return ''
    if aging_exists and o2_exists:
        if aging_stat == o2_stat or o2_stat == '':
            return f'{aging_val} ({aging_stat})'
        priority = {'': 0, 'OK': 1, 'WARN': 2, 'ERR': 3}
        if priority[aging_stat] >= priority[o2_stat]:
            return f'{aging_val} ({aging_stat})'
        return f'{o2_display} ({o2_stat})'
    return f'{o2_display} ({o2_stat})' if o2_exists else f'{aging_val} ({aging_stat})'


def _card_fuel_corrections(metrics_df: pd.DataFrame, font_name: str, subheading_style: Any) -> 'Table':
    """Карточка топливных коррекций (LTFT/STFT) и состояния катализатора."""
    ltft_mean = _get_metric_val(metrics_df, 'ALL_DRIVE_LTFT_Mean') or _get_metric_val(metrics_df, 'ALL_LTFT_Mean')
    ltft_stat = _get_metric_stat(metrics_df, 'ALL_DRIVE_LTFT_Mean') or _get_metric_stat(metrics_df, 'ALL_LTFT_Mean')
    stft_mean = _get_metric_val(metrics_df, 'ALL_DRIVE_STFT_Mean') or _get_metric_val(metrics_df, 'ALL_STFT_Mean')
    stft_stat = _get_metric_stat(metrics_df, 'ALL_DRIVE_STFT_Mean') or _get_metric_stat(metrics_df, 'ALL_STFT_Mean')
    data = [
        [t('pdf.card_fields.ltft_mean'), f'{ltft_mean}% ({ltft_stat})' if ltft_mean and ltft_mean != 'N/A' else 'N/A'],
        [t('pdf.card_fields.stft_mean'), f'{stft_mean}% ({stft_stat})' if stft_mean and stft_mean != 'N/A' else 'N/A'],
    ]
    cat_label = _cat_combined_label(metrics_df)
    if cat_label:
        data.append([t('pdf.card_fields.catalyst'), cat_label])
    return _create_card(t('pdf.cards.fuel_corrections'), data, font_name, subheading_style, colors.HexColor('#e1f5fe'))


def _card_o2_quality(metrics_df: pd.DataFrame, font_name: str, subheading_style: Any) -> 'Table':
    """Карточка качества смеси по показаниям ДК1 (O2-датчик): стехиометрия, богатая/бедная, переключения."""
    o2_normal = _get_metric_val(metrics_df, 'O2_NORMAL_TIME')
    o2_rich = _get_metric_val(metrics_df, 'O2_RICH_TIME')
    o2_lean = _get_metric_val(metrics_df, 'O2_LEAN_TIME')
    o2_crossing = _get_metric_val(metrics_df, 'O2_CROSSING_RATE')
    fuel_quality = _get_metric_val(metrics_df, 'FUEL_QUALITY')
    fuel_quality_stat = _get_metric_stat(metrics_df, 'FUEL_QUALITY')
    stat_colors = {'OK': STATUS_COLOR_OK, 'WARN': STATUS_COLOR_WARNING, 'ERR': STATUS_COLOR_ERROR}
    color = colors.HexColor(stat_colors.get(fuel_quality_stat, STATUS_COLOR_NEUTRAL))
    data = [
        [t('pdf.card_fields.o2_quality_label'), f'{fuel_quality} ({fuel_quality_stat})'],
        [t('pdf.card_fields.stoichiometry'), o2_normal + '%' if o2_normal != 'N/A' else 'N/A'],
        [t('pdf.card_fields.rich_lean'), f'{o2_rich}% / {o2_lean}%' if o2_rich != 'N/A' else 'N/A'],
        [t('pdf.card_fields.crossings'), o2_crossing + ' ' + t('units.per_min') if o2_crossing != 'N/A' else 'N/A'],
    ]
    return _create_card(t('pdf.cards.o2_quality'), data, font_name, subheading_style, color)


def _build_summary_cards(metrics_df: pd.DataFrame, font_name: str,
                         heading_style: Any, subheading_style: Any) -> list:
    """Строит секцию сводных карточек (6 карточек в 3 ряда).

    Returns:
        Список элементов story для секции СВОДКА.
    """
    elements = []
    elements.append(Paragraph(t('pdf.sections.summary'), heading_style))
    elements.append(Spacer(1, 0.3*cm))

    card1 = _card_basic_params(metrics_df, font_name, subheading_style)
    card2 = _card_coolant_temp(metrics_df, font_name, subheading_style)
    card3 = _card_stalls_misfires(metrics_df, font_name, subheading_style)
    card4 = _card_knock(metrics_df, font_name, subheading_style)
    card5 = _card_fuel_corrections(metrics_df, font_name, subheading_style)
    card6 = _card_o2_quality(metrics_df, font_name, subheading_style)

    row_style = TableStyle([('VALIGN', (0, 0), (-1, -1), 'TOP')])
    col_widths = [8.5*cm, 8.5*cm]
    rows = [(card1, card2), (card4, card3), (card6, card5)]
    for i, (left, right) in enumerate(rows):
        row = Table([[left, right]], colWidths=col_widths, rowHeights=[None])
        row.setStyle(row_style)
        elements.append(row)
        elements.append(Spacer(1, (0.5 if i == len(rows) - 1 else 0.4)*cm))

    return elements


def _extract_sections(metrics_df: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Разбивает metrics_df на именованные секции по SEPARATOR_LINE.

    Первая секция (до первого сепаратора) получает ключ 'Информация о поездке'.

    Returns:
        Словарь {название_секции: DataFrame строк секции}.
    """
    sections: dict[str, pd.DataFrame] = {}
    current_name = t('sections.trip_info')
    current_rows: list[int] = []

    for idx, row in metrics_df.iterrows():
        if str(row.get('CODE', '')).strip() == SEPARATOR_LINE:
            if current_rows:
                sections[current_name] = metrics_df.loc[current_rows]
            current_name = str(row.get('DESC', '')).strip() or 'Раздел'
            current_rows = []
        else:
            current_rows.append(idx)

    if current_rows:
        sections[current_name] = metrics_df.loc[current_rows]

    return sections


_STAT_ROW_COLORS = {
    STATUS_OK:      STATUS_COLOR_OK,
    STATUS_WARNING: STATUS_COLOR_WARNING,
    STATUS_ERROR:   STATUS_COLOR_ERROR,
    STATUS_NEUTRAL: STATUS_COLOR_NEUTRAL,
}


def _build_section_table(section_df: pd.DataFrame, title: str,
                         font_name: str, subheading_style: Any,
                         override_color: str | None = None) -> list:
    """Строит PDF-таблицу из секции метрик (DESC / VAL / STAT).

    Args:
        override_color: Если задан — все строки красятся этим цветом (hex).

    Returns:
        Список элементов story (заголовок + таблица + отступ).
    """
    elements = []
    stat_map = {STATUS_OK: 'OK', STATUS_WARNING: 'WARN', STATUS_ERROR: 'ERR', STATUS_NEUTRAL: ''}

    data = []
    row_stats: list[str] = []
    for _, row in section_df.iterrows():
        desc = str(row.get('DESC', ''))
        val = str(row.get('VAL', ''))
        if len(val) > 18: continue
        raw_stat = str(row.get('STAT', ''))
        stat = stat_map.get(raw_stat, raw_stat)
        data.append([desc, val, stat])
        row_stats.append(raw_stat)

    if not data:
        return elements

    elements.append(Paragraph(title, subheading_style))
    table = Table(data, colWidths=[12*cm, 3*cm, 2*cm])

    table_style = [
        ('FONTNAME', (0, 0), (-1, -1), font_name),
        ('FONTSIZE', (0, 0), (-1, -1), 8),
        ('ALIGN', (0, 0), (0, -1), 'LEFT'),
        ('ALIGN', (1, 0), (-1, -1), 'RIGHT'),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
    ]

    if override_color:
        table_style.append(('BACKGROUND', (0, 0), (-1, -1), colors.HexColor(override_color)))
    else:
        for i, raw_stat in enumerate(row_stats):
            hex_color = _STAT_ROW_COLORS.get(raw_stat, '#f5f5f5')
            table_style.append(('BACKGROUND', (0, i), (-1, i), colors.HexColor(hex_color)))

    table.setStyle(TableStyle(table_style))
    elements.append(table)
    elements.append(Spacer(1, 0.4*cm))

    return elements


def _build_trip_info(metrics_df: pd.DataFrame, font_name: str,
                     heading_style: Any) -> list:
    """Строит таблицу «Информация о поездке» из первой секции метрик.

    Returns:
        Список элементов story.
    """
    sections = _extract_sections(metrics_df)
    section = sections.get(t('sections.trip_info'))
    if section is None or section.empty:
        return []
    return _build_section_table(section, t('pdf.sections.trip_info'), font_name, heading_style)


def _build_diagnostic_tables(metrics_df: pd.DataFrame, font_name: str,
                              heading_style: Any, subheading_style: Any) -> list:
    """Строит таблицы диагностики: Детонация, Пропуски, Качество топлива, Катализатор.

    Returns:
        Список элементов story.
    """
    sections = _extract_sections(metrics_df)
    diag_names = [
        t('sections.misfire'), t('sections.knock'), t('sections.fuel_quality'),
        t('sections.catalyst'), t('sections.coolant_system'),
    ]

    elements = []
    has_any = any(name in sections for name in diag_names)
    if not has_any:
        return elements

    elements.append(PageBreak())
    elements.append(Paragraph(t('pdf.sections.diagnostics'), heading_style))

    # Определяем единый цвет для секции «Качество топлива» по итоговой оценке
    fuel_quality_stat = _get_metric_stat_raw(metrics_df, 'FUEL_QUALITY')
    fuel_section_color = _STAT_ROW_COLORS.get(fuel_quality_stat) if fuel_quality_stat else None

    for name in diag_names:
        section = sections.get(name)
        if section is not None and not section.empty:
            if name == t('sections.fuel_quality') and fuel_section_color:
                color = fuel_section_color
            else:
                color = None
            if name == t('sections.coolant_system'):
                elements.append(PageBreak())
            elements += _build_section_table(section, name, font_name, subheading_style, color)

    return elements


def _build_one_regime_table(
    regime_code: str,
    regime_name: str,
    metrics_df: pd.DataFrame,
    font_name: str,
    subheading_style: Any,
    group_colors: dict,
) -> list:
    """Строит PDF-таблицу метрик для одного режима с цветовым кодированием по группам параметров.

    Возвращает список элементов story (заголовок + таблица + отступ) или [] если данных нет.
    """
    regime_metrics = metrics_df[metrics_df['CODE'].str.startswith(regime_code + '_')]

    if regime_metrics.empty:
        return []

    elements = []
    elements.append(Paragraph(t(f'regimes.{regime_code}'), subheading_style))

    data = []
    row_groups = []
    for _, row in regime_metrics.iterrows():
        code = row['CODE'] if 'CODE' in row else ''
        if code == regime_code + '_COUNT': continue
        if code == regime_code + '_ACCEL_Min': continue
        desc = row['DESC'] if 'DESC' in row else ''
        metric_part = desc.split(': ', 1)[-1] if ': ' in desc else desc
        desc = f'{regime_name}: {metric_part}'
        val = str(row['VAL']) if 'VAL' in row else ''
        stat = row['STAT'] if 'STAT' in row else ''
        stat_map = {STATUS_OK: 'OK', STATUS_WARNING: 'WARN', STATUS_ERROR: 'ERR', STATUS_NEUTRAL: ''}
        stat = stat_map.get(stat, stat)
        data.append([desc, val, stat])
        row_groups.append(_get_param_group(code))

    if not data:
        return []

    table = Table(data, colWidths=[12*cm, 3*cm, 2*cm])

    table_style = [
        ('FONTNAME', (0, 0), (-1, -1), font_name),
        ('FONTSIZE', (0, 0), (-1, -1), 8),
        ('ALIGN', (0, 0), (0, -1), 'LEFT'),
        ('ALIGN', (1, 0), (-1, -1), 'RIGHT'),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
    ]

    for i, group in enumerate(row_groups):
        bg_color = group_colors.get(group, colors.whitesmoke)
        table_style.append(('BACKGROUND', (0, i), (-1, i), bg_color))

    table.setStyle(TableStyle(table_style))
    elements.append(table)
    elements.append(Spacer(1, 0.4*cm))

    return elements


def _build_regime_tables(metrics_df: pd.DataFrame, font_name: str,
                         heading_style: Any, subheading_style: Any) -> list:
    """Строит секцию таблиц метрик по режимам с цветовым кодированием.

    Returns:
        Список элементов story для секции МЕТРИКИ ПО РЕЖИМАМ.
    """
    elements = []
    elements.append(PageBreak())
    elements.append(Paragraph(t('pdf.sections.regime_metrics'), heading_style))

    # Словарь для названий режимов
    regime_names = {
        'WARMUP': t('regimes.WARMUP_short'),
        'DRIVE_CITY': t('regimes.DRIVE_CITY_short'),
        'DRIVE_SUBURBAN': t('regimes.DRIVE_SUBURBAN_short'),
        'DRIVE_HIGHWAY': t('regimes.DRIVE_HIGHWAY_short'),
    }

    # Маппинг group_id → reportlab color
    group_colors = {group_id: colors.HexColor(hex_color) if hex_color else colors.whitesmoke
                    for group_id, hex_color in _GROUP_COLORS.items()}

    regime_num = 0
    for regime_code, regime_name in regime_names.items():
        regime_elements = _build_one_regime_table(
            regime_code, regime_name, metrics_df, font_name, subheading_style, group_colors
        )
        if regime_elements:
            if regime_num > 0:
                elements.append(PageBreak())
            regime_num += 1
            elements.extend(regime_elements)

    return elements


def _build_speed_profile(output_dir: Path, base_filename: str,
                         font_name: str, heading_style: Any, normal_style: Any) -> list:
    """Строит секцию профиля скорости из CSV.

    Returns:
        Список элементов story для секции ПРОФИЛЬ СКОРОСТИ.
    """
    elements = []
    profile_path = output_dir / f'{base_filename}_profile.csv'
    if not profile_path.is_file():
        return elements

    try:
        profile_df = pd.read_csv(profile_path, encoding='utf-8-sig')
        if profile_df.empty:
            return elements

        elements.append(PageBreak())
        elements.append(Paragraph(t('pdf.sections.speed_profile'), heading_style))
        elements.append(Spacer(1, 0.2*cm))

        # Выбираем важные колонки для PDF (остальные не поместятся)
        cols_mapping = {
            t('csv.profile.speed_min'): t('pdf.profile_speed_cols.speed_min'),
            t('csv.profile.speed_max'): t('pdf.profile_speed_cols.speed_max'),
            t('csv.profile.rpm_mean'): t('pdf.profile_speed_cols.rpm_mean'),
            t('csv.profile.fuel_mean'): t('pdf.profile_speed_cols.fuel_mean'),
            t('csv.profile.load_mean'): t('pdf.profile_speed_cols.load_mean'),
            t('csv.profile.spark_mean'): t('pdf.profile_speed_cols.spark_mean'),
            t('csv.profile.coolant_mean'): t('pdf.profile_speed_cols.coolant_mean'),
            t('csv.profile.count'): t('pdf.profile_speed_cols.count'),
        }
        _speed_cols = {t('csv.profile.speed_min'), t('csv.profile.speed_max')}
        _rpm_col = t('csv.profile.rpm_mean')
        _count_col = t('csv.profile.count')

        # Готовим данные для таблицы
        data = [list(cols_mapping.values())]  # Заголовки
        for _, row in profile_df.iterrows():
            row_data = []
            for orig_col, short_col in cols_mapping.items():
                if orig_col in profile_df.columns:
                    val = row[orig_col]
                    if pd.isna(val):
                        row_data.append('-')
                    elif orig_col == _count_col:
                        row_data.append(str(int(val)))
                    elif orig_col in _speed_cols or orig_col == _rpm_col:
                        row_data.append(f'{val:.0f}')
                    else:
                        row_data.append(f'{val:.1f}')
                else:
                    row_data.append('-')
            data.append(row_data)

        # Создаём таблицу (общая ширина 18 см)
        col_widths = [2.2*cm, 2.2*cm, 2.3*cm, 2.3*cm, 2.2*cm, 2.2*cm, 2.3*cm, 2.3*cm]
        table = Table(data, colWidths=col_widths)
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#0d47a1')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, -1), font_name),
            ('FONTSIZE', (0, 0), (-1, 0), 8),
            ('FONTSIZE', (0, 1), (-1, -1), 7),
            ('TOPPADDING', (0, 0), (-1, 0), 6),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 6),
            ('TOPPADDING', (0, 1), (-1, -1), 3),
            ('BOTTOMPADDING', (0, 1), (-1, -1), 3),
            ('BACKGROUND', (0, 1), (-1, -1), colors.whitesmoke),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.whitesmoke, colors.HexColor('#f5f5f5')]),
        ]))
        elements.append(table)



    except (OSError, pd.errors.ParserError, ValueError) as e:
        elements.append(PageBreak())
        elements.append(Paragraph(t('pdf.sections.speed_profile'), heading_style))
        elements.append(Paragraph(t('pdf.error_reading_profile', error=str(e)), normal_style))

    return elements


def _build_knock_groups(output_dir: Path, base_filename: str,
                        font_name: str, heading_style: Any, normal_style: Any) -> list:
    """Строит секцию групп детонации из CSV.

    Returns:
        Список элементов story для секции ГРУППЫ ДЕТОНАЦИИ.
    """
    elements = []
    knock_groups_path = output_dir / f'{base_filename}_knock_groups.csv'
    if not knock_groups_path.is_file():
        return elements

    try:
        knock_df = pd.read_csv(knock_groups_path, encoding='utf-8-sig')
        if knock_df.empty:
            return elements

        # story.append(PageBreak())
        elements.append(Paragraph(t('pdf.sections.knock_groups'), heading_style))
        elements.append(Spacer(1, 0.2*cm))

        # Маппинг колонок из CSV в читаемые названия
        cols_mapping = {
            'TIME_START': t('pdf.knock_group_cols.TIME_START'),
            'DURATION_SEC': t('pdf.knock_group_cols.DURATION_SEC'),
            'MAX_RETARD': t('pdf.knock_group_cols.MAX_RETARD'),
            'MEAN_RETARD': t('pdf.knock_group_cols.MEAN_RETARD'),
            'EVENT_COUNT': t('pdf.knock_group_cols.EVENT_COUNT'),
            'INTENSITY': t('pdf.knock_group_cols.INTENSITY'),
            'RPM_MEAN': t('pdf.knock_group_cols.RPM_MEAN'),
            'SPEED_MEAN': t('pdf.knock_group_cols.SPEED_MEAN'),
            'LOAD_MEAN': t('pdf.knock_group_cols.LOAD_MEAN'),
        }

        # Готовим данные для таблицы
        data = [list(cols_mapping.values())]  # Заголовки
        for _, row in knock_df.head(25).iterrows():  # Ограничиваем 25 строками
            row_data = []
            for orig_col, short_col in cols_mapping.items():
                if orig_col in knock_df.columns:
                    val = row[orig_col]
                    if pd.isna(val):
                        row_data.append('-')
                    elif orig_col == 'TIME_START':
                        # Убираем миллисекунды для экономии места
                        row_data.append(str(val).split('.')[0] if '.' in str(val) else str(val))
                    elif orig_col == 'EVENT_COUNT':
                        row_data.append(str(int(val)))
                    elif orig_col == 'INTENSITY':
                        intensity_map = {
                            t('intensity.weak'): t('intensity.weak_abbrev'),
                            t('intensity.medium'): t('intensity.medium_abbrev'),
                            t('intensity.strong'): t('intensity.strong_abbrev'),
                        }
                        row_data.append(intensity_map.get(val, str(val)))
                    elif orig_col in ['RPM_MEAN', 'SPEED_MEAN']:
                        row_data.append(f'{val:.0f}')
                    else:
                        row_data.append(f'{val:.1f}')
                else:
                    row_data.append('-')
            data.append(row_data)

        # Создаём таблицу (общая ширина 18 см)
        col_widths = [2.8*cm, 1.9*cm, 1.9*cm, 1.9*cm, 1.9*cm, 1.9*cm, 1.9*cm, 1.9*cm, 1.9*cm]
        table = Table(data, colWidths=col_widths)
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#d32f2f')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (0, -1), 'LEFT'),  # Начало - влево
            ('ALIGN', (1, 0), (-1, -1), 'CENTER'),  # Остальное - по центру
            ('FONTNAME', (0, 0), (-1, -1), font_name),
            ('FONTSIZE', (0, 0), (-1, 0), 7),
            ('FONTSIZE', (0, 1), (-1, -1), 6.5),
            ('TOPPADDING', (0, 0), (-1, 0), 6),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 6),
            ('TOPPADDING', (0, 1), (-1, -1), 3),
            ('BOTTOMPADDING', (0, 1), (-1, -1), 3),
            ('BACKGROUND', (0, 1), (-1, -1), colors.whitesmoke),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.whitesmoke, colors.HexColor('#ffebee')]),
        ]))
        elements.append(table)

        if len(knock_df) > 25:
            elements.append(Spacer(1, 0.2*cm))
            elements.append(Paragraph(t('pdf.rows_shown', shown=25, total=len(knock_df)), normal_style))

    except (OSError, pd.errors.ParserError, ValueError) as e:
        elements.append(PageBreak())
        elements.append(Paragraph(t('pdf.sections.knock_groups'), heading_style))
        elements.append(Paragraph(t('pdf.error_reading_knock', error=str(e)), normal_style))

    return elements


def _build_one_panel(
    panel_name: str,
    png_files: list,
    output_dir: Path,
    base_filename: str,
    subheading_style: Any,
    normal_style: Any,
) -> list:
    """Строит одну панель с PNG иллюстрациями для секции ГРАФИКИ.

    Возвращает список элементов story (заголовок панели + изображения).
    Отсутствующие файлы пропускаются без ошибки.
    """
    elements = []
    elements.append(Paragraph(panel_name, subheading_style))
    elements.append(Spacer(1, 0.15*cm))

    for png_name, title in png_files:
        png_path = output_dir / f'{base_filename}_{png_name}'
        if png_path.is_file():
            try:
                img_elements = []
                img_elements.append(Paragraph(f'<b>{title}</b>', normal_style))

                if 'corr_matrix' in png_name or 'knock_heatmap' in png_name:
                    img = Image(str(png_path), width=17*cm, height=12*cm)
                elif 'dashboard' in png_name:
                    img = Image(str(png_path), width=17*cm, height=12.5*cm)
                elif any(x in png_name for x in ['ltft_stft_hist', 'temperatures']):
                    img = Image(str(png_path), width=17*cm, height=8.5*cm)
                elif any(x in png_name for x in ['o2_sensors', 'maf_analysis', 'misfire_analysis', 'engine_load']):
                    img = Image(str(png_path), width=17*cm, height=11*cm)
                else:
                    img = Image(str(png_path), width=17*cm, height=10*cm)

                img_elements.append(img)
                img_elements.append(Spacer(1, 0.2*cm))

                elements.append(KeepTogether(img_elements))
            except (OSError, ValueError):
                elements.append(Paragraph(t('pdf.error_loading_image', name=png_name), normal_style))

    return elements


def _build_illustrations(output_dir: Path, base_filename: str, no_png: bool,
                         heading_style: Any, subheading_style: Any, normal_style: Any) -> list:
    """Строит секцию PNG иллюстраций.

    Returns:
        Список элементов story для секции ГРАФИКИ И ВИЗУАЛИЗАЦИИ.
    """
    elements = []

    if not no_png:
        elements.append(PageBreak())
        elements.append(Paragraph(t('pdf.sections.visualizations'), heading_style))
        elements.append(Spacer(1, 0.3*cm))

        # Структура графиков по панелям (порядок как в HTML отчёте)
        panels = [
            (t('pdf.panels.dashboard'), [
                ('viz_dashboard.png', t('pdf.panel_png.viz_dashboard_png')),
                ('viz_ltft_stft_hist.png', t('pdf.panel_png.viz_ltft_stft_hist_png')),
            ]),
            (t('pdf.panels.matrices'), [
                ('viz_knock_heatmap.png', t('pdf.panel_png.viz_knock_heatmap_png')),
                ('viz_corr_matrix.png', t('pdf.panel_png.viz_corr_matrix_png')),
            ]),
            (t('pdf.panels.timeline'), [
                ('viz_timeline.png', t('pdf.panel_png.viz_timeline_png')),
                ('viz_fuel_correction.png', t('pdf.panel_png.viz_fuel_correction_png')),
                ('viz_o2_sensors.png', t('pdf.panel_png.viz_o2_sensors_png')),
                ('viz_temperatures.png', t('pdf.panel_png.viz_temperatures_png')),
            ]),
            (t('pdf.panels.analytics'), [
                ('viz_engine_load.png', t('pdf.panel_png.viz_engine_load_png')),
                ('viz_maf_analysis.png', t('pdf.panel_png.viz_maf_analysis_png')),
                ('viz_misfire_analysis.png', t('pdf.panel_png.viz_misfire_analysis_png')),
            ]),
        ]

        for panel_idx, (panel_name, png_files) in enumerate(panels):
            if panel_idx > 0:
                elements.append(PageBreak())
            elements.extend(_build_one_panel(
                panel_name, png_files, output_dir, base_filename, subheading_style, normal_style
            ))
    else:
        elements.append(PageBreak())
        elements.append(Paragraph(t('pdf.sections.visualizations'), heading_style))
        elements.append(Paragraph(t('pdf.no_png_msg'), normal_style))

    return elements


# ============================================================================
# Главная функция создания PDF
# ============================================================================

def create_pdf_report(output_dir: Path, base_filename: str, no_png: bool = False) -> None:
    """Создаёт PDF отчёт с основными метриками и PNG иллюстрациями.

    Args:
        output_dir: Директория для сохранения PDF
        base_filename: Базовое имя файла
        no_png: Если True, PNG графики не будут включены в PDF
    """
    if not REPORTLAB_AVAILABLE:
        logger.warning(t('console.pdf_no_reportlab'))
        logger.warning(t('console.pdf_install_hint'))
        return

    pdf_path = output_dir / f'{base_filename}_report.pdf'
    font_name, font_name_bold = _register_fonts()

    # Создаём документ с минимальными отступами для большего места под графики
    doc = SimpleDocTemplate(str(pdf_path), pagesize=A4,
                           rightMargin=1.5*cm, leftMargin=2*cm,
                           topMargin=0.90*cm, bottomMargin=0.90*cm)

    # Стили
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle('CustomTitle', parent=styles['Heading1'],
                                 fontName=font_name_bold, fontSize=18, spaceAfter=12)
    heading_style = ParagraphStyle('CustomHeading', parent=styles['Heading2'],
                                   fontName=font_name_bold, fontSize=14, spaceAfter=8,
                                   textColor=colors.HexColor('#0d47a1'))
    subheading_style = ParagraphStyle('CustomSubheading', parent=styles['Heading3'],
                                      fontName=font_name_bold, fontSize=11, spaceAfter=4)
    normal_style = ParagraphStyle('CustomNormal', parent=styles['Normal'],
                                  fontName=font_name, fontSize=10, spaceAfter=4)

    story = []

    # Заголовок (слева) + логотип (справа)
    _now = datetime.now().strftime('%Y-%m-%d %H:%M')
    _hdr = Table(
        [[[Paragraph(t('pdf.report_title'), title_style),
           Paragraph(f'{t("pdf.file_label")} {base_filename}.csv', normal_style),
           Paragraph(f'{t("pdf.date_label")} {_now}', normal_style)],
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
    story.append(Spacer(1, 0.5*cm))

    # Читаем метрики
    metrics_path = output_dir / f'{base_filename}_metrics.csv'
    metrics_df = None
    if metrics_path.is_file():
        try:
            metrics_df = pd.read_csv(metrics_path, encoding='utf-8-sig')
        except (pd.errors.ParserError, UnicodeDecodeError, OSError) as e:
            story.append(Paragraph(t('pdf.error_reading_metrics', error=str(e)), normal_style))

    # Секции отчёта
    if metrics_df is not None:
        story += _build_trip_info(metrics_df, font_name, heading_style)
        story += _build_summary_cards(metrics_df, font_name, heading_style, subheading_style)
        story += _build_regime_tables(metrics_df, font_name, heading_style, subheading_style)
        story += _build_diagnostic_tables(metrics_df, font_name, heading_style, subheading_style)

    story += _build_speed_profile(output_dir, base_filename, font_name, heading_style, normal_style)
    story += _build_knock_groups(output_dir, base_filename, font_name, heading_style, normal_style)
    story += _build_illustrations(output_dir, base_filename, no_png, heading_style, subheading_style, normal_style)

    # Генерируем PDF
    try:
        doc.build(story)
        logger.info(t('console.pdf_saved', path=pdf_path))
    except (OSError, RuntimeError) as e:
        logger.error(t('console.pdf_error', e=e), exc_info=True)
