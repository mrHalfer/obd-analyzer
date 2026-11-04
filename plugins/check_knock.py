#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
check_knock.py
Анализирует детонацию двигателя по данным KNOCK_RETARD
и пропуски зажигания по MISFIRE_CYL1-4.
Используется в модулях оркестратора и формировании csv
"""

import pandas as pd
from typing import Any, Optional

import sys as _sys
from pathlib import Path as _Path
_root = _Path(__file__).parent.parent
for _d in [str(_root), str(_root / 'build'), str(_root / 'plugins')]:
    if _d not in _sys.path:
        _sys.path.insert(0, _d)

from translation import t
from core_obd import (
    get_status, parse_time_to_seconds_vectorized, group_events_by_time,
    STATUS_OK, STATUS_WARNING, STATUS_ERROR, STATUS_NEUTRAL,
    KNOCK_WEAK_MAX, KNOCK_MEDIUM_MAX, KNOCK_STRONG_MIN,
    MAX_KNOCK_GROUP_GAP_SEC, KNOCK_WEAK_INTERVAL_MIN, KNOCK_MEDIUM_INTERVAL_MIN,
    KNOCK_WEAK_THRESHOLD_GOOD, KNOCK_WEAK_THRESHOLD_BAD,
    KNOCK_MEDIUM_THRESHOLD_GOOD, KNOCK_MEDIUM_THRESHOLD_BAD,
    KNOCK_STRONG_THRESHOLD_ATTENTION, KNOCK_STRONG_THRESHOLD_BAD,
    KNOCK_RETARD_MEAN_DIVISOR, KNOCK_RETARD_TOLERANCE, KNOCK_MAX_RETARD_REMISSION,
    KNOCK_MAX_RPM_REMISSION, KNOCK_MAX_SPEED_REMISSION, KNOCK_MAX_RETARD_REMISSION, KNOCK_DURATION_REMISSION,
)

def classify_knock_groups_with_remission(df: pd.DataFrame, max_gap_sec: float | None = None) -> list[dict[str, Any]]:
    """Группирует и классифицирует события детонации с применением снисходительности (remission).

    Группирует по временной близости (разрыв <= max_gap_sec). Для каждой группы
    вычисляет параметры (max RPM, max SPEED, max RETARD, duration) и проверяет условия снисходительности.
    Если >= 3 из 4 параметров <= соответствующим порогам, критичность снижается на 1 уровень.

    Классификация: слабая 2-4°, средняя 5-8°, сильная 9+°.
    После снисходительности: сильная → средняя, средняя → слабая, слабая → неучтенная.

    Args:
        df: DataFrame с колонками 'KNOCK_RETARD', 'TIME', опционально 'TIME_SEC', 'RPM', 'SPEED'.
        max_gap_sec: Макс. разрыв между событиями в группе (по умолчанию MAX_KNOCK_GROUP_GAP_SEC).

    Returns:
        Список словарей с параметрами каждой группы:
        {
            'start_idx': int,           # индекс начала группы в kdf
            'end_idx': int,             # индекс конца группы в kdf
            'max_retard': float,        # максимальный угол отскока
            'mean_retard': float,       # средний угол отскока
            'duration': float,          # длительность группы в секундах
            'max_rpm': float,           # максимальные обороты
            'max_speed': float,         # максимальная скорость
            'event_count': int,         # количество событий в группе
            'initial_severity': str,    # 'weak'/'medium'/'strong' до remission
            'final_severity': str,      # 'weak'/'medium'/'strong'/'remitted' после remission
            'time_start': str,          # время начала (строка TIME)
            'time_end': str,            # время конца (строка TIME)
            'time_start_sec': float,    # время начала в секундах
            'time_end_sec': float,      # время конца в секундах
        }
        Пустой список при отсутствии данных или событий детонации.
    """
    if max_gap_sec is None:
        max_gap_sec = MAX_KNOCK_GROUP_GAP_SEC

    kdf = df[df['KNOCK_RETARD'] > 0].copy()
    if len(kdf) == 0 or 'TIME' not in kdf.columns:
        return []

    # Предпочитаем уже готовый TIME_SEC (созданный в analyze_data),
    # чтобы не парсить время построчно.
    if 'TIME_SEC' not in kdf.columns:
        if 'TIME_SEC' in df.columns:
            kdf['TIME_SEC'] = df.loc[kdf.index, 'TIME_SEC'].values
        else:
            kdf['TIME_SEC'] = parse_time_to_seconds_vectorized(kdf['TIME'])

    kdf = kdf.dropna(subset=['TIME_SEC']).reset_index(drop=True)

    if len(kdf) == 0:
        return []

    # Проверяем наличие колонок RPM и SPEED для remission
    has_rpm = 'RPM' in kdf.columns
    has_speed = 'SPEED' in kdf.columns

    # Формируем группы
    idx_groups = group_events_by_time(kdf['TIME_SEC'], max_gap_sec)

    groups_info = []

    for s, e in idx_groups:
        g = kdf.iloc[s:e+1]

        # Вычисляем параметры группы
        max_retard = g['KNOCK_RETARD'].max()
        mean_retard = g['KNOCK_RETARD'].mean()
        max_rpm = g['RPM'].max() if has_rpm else 0.0
        max_speed = g['SPEED'].max() if has_speed else 0.0

        time_start_sec = g.loc[g.index[0], 'TIME_SEC']
        time_end_sec = g.loc[g.index[-1], 'TIME_SEC']
        duration = time_end_sec - time_start_sec

        # Проверяем условия снисходительности (remission)
        remission_conditions = 0
        if max_rpm <= KNOCK_MAX_RPM_REMISSION:
            remission_conditions += 1
        if max_speed <= KNOCK_MAX_SPEED_REMISSION:
            remission_conditions += 1
        if max_retard <= KNOCK_MAX_RETARD_REMISSION:
            remission_conditions += 1
        if duration <= KNOCK_DURATION_REMISSION:
            remission_conditions += 1

        # Если >= 3 условия выполнены - применяем снисходительность
        apply_remission = remission_conditions >= 3

        # Исходная классификация по max_retard
        # Слабая: <= 4°, Средняя: 5-8°, Сильная: 9+°
        if max_retard <= KNOCK_WEAK_MAX:
            initial_severity = 'weak'
        elif max_retard <= KNOCK_MEDIUM_MAX:
            initial_severity = 'medium'
        else:
            initial_severity = 'strong'

        # Применяем снисходительность (снижаем на 1 уровень)
        if apply_remission:
            if initial_severity == 'strong':
                final_severity = 'medium'
            elif initial_severity == 'medium':
                final_severity = 'weak'
            else:  # weak
                final_severity = 'remitted'
        else:
            final_severity = initial_severity

        groups_info.append({
            'start_idx': s,
            'end_idx': e,
            'max_retard': max_retard,
            'mean_retard': mean_retard,
            'duration': duration,
            'max_rpm': max_rpm,
            'max_speed': max_speed,
            'event_count': len(g),
            'initial_severity': initial_severity,
            'final_severity': final_severity,
            'time_start': g['TIME'].iloc[0],
            'time_end': g['TIME'].iloc[-1],
            'time_start_sec': time_start_sec,
            'time_end_sec': time_end_sec,
        })

    return groups_info


def _group_knock_events(df: pd.DataFrame) -> tuple[int, int, int, int, int]:
    """Группирует события детонации и классифицирует по интенсивности с учетом снисходительности.

    Использует classify_knock_groups_with_remission для группировки и классификации,
    затем подсчитывает количество групп каждого типа.

    Args:
        df: DataFrame с колонками 'KNOCK_RETARD', 'TIME', опционально 'TIME_SEC', 'RPM', 'SPEED'.

    Returns:
        (total_groups, weak_groups, medium_groups, strong_groups, remitted_groups).
        total_groups - учтенные группы (без неучтенных).
        remitted_groups - количество неучтенных групп (норма).
    """
    groups_info = classify_knock_groups_with_remission(df)

    if not groups_info:
        return 0, 0, 0, 0, 0

    # Подсчитываем количество групп каждого типа
    sevs = [g['final_severity'] for g in groups_info]
    weak_groups = sevs.count('weak')
    medium_groups = sevs.count('medium')
    strong_groups = sevs.count('strong')
    remitted_groups = sevs.count('remitted')

    total_groups = weak_groups + medium_groups + strong_groups

    return total_groups, weak_groups, medium_groups, strong_groups, remitted_groups


def _evaluate_knock_count_statuses(
    total_groups: int, weak_groups: int, medium_groups: int, strong_groups: int,
    all_drive_duration_min: Optional[float],
) -> tuple[str, str, str, str]:
    """Вычисляет статусы по количеству групп детонаций.

    При наличии длительности движения — нормирует на интервалы.
    Без длительности — использует абсолютные пороги через get_status().

    Args:
        total_groups: Общее количество групп (без неучтенных).
        weak_groups: Количество слабых групп (2-4°).
        medium_groups: Количество средних групп (5-8°).
        strong_groups: Количество сильных групп (9+°).
        all_drive_duration_min: Длительность движения (мин) или None.

    Returns:
        (status_total, status_weak, status_medium, status_strong).
    """
    if all_drive_duration_min is not None and all_drive_duration_min > 0:
        d = all_drive_duration_min

        # Слабые: нормируем на интервал KNOCK_WEAK_INTERVAL_MIN
        weak_per_interval = weak_groups / (d / KNOCK_WEAK_INTERVAL_MIN) if d >= KNOCK_WEAK_INTERVAL_MIN else weak_groups
        if weak_per_interval <= KNOCK_WEAK_THRESHOLD_GOOD:
            status_weak = STATUS_OK
        elif weak_per_interval <= KNOCK_WEAK_THRESHOLD_BAD:
            status_weak = STATUS_WARNING
        else:
            status_weak = STATUS_ERROR

        # Средние: нормируем на интервал KNOCK_MEDIUM_INTERVAL_MIN
        medium_per_interval = medium_groups / (d / KNOCK_MEDIUM_INTERVAL_MIN) if d >= KNOCK_MEDIUM_INTERVAL_MIN else medium_groups
        if medium_per_interval <= KNOCK_MEDIUM_THRESHOLD_GOOD:
            status_medium = STATUS_OK
        elif medium_per_interval <= KNOCK_MEDIUM_THRESHOLD_BAD:
            status_medium = STATUS_WARNING
        else:
            status_medium = STATUS_ERROR

        # Сильные: абсолютное количество за поездку
        if strong_groups < KNOCK_STRONG_THRESHOLD_ATTENTION:
            status_strong = STATUS_OK
        elif strong_groups < KNOCK_STRONG_THRESHOLD_BAD:
            status_strong = STATUS_WARNING
        else:
            status_strong = STATUS_ERROR

        # Общий статус = наихудший из трёх
        status_priority = {STATUS_OK: 0, STATUS_NEUTRAL: 0, STATUS_WARNING: 1, STATUS_ERROR: 2}
        status_total = max([status_weak, status_medium, status_strong], key=lambda s: status_priority.get(s, 0))
    else:
        status_total = get_status('KNOCK_COUNT', total_groups)
        status_weak = get_status('KNOCK_COUNT', weak_groups)
        status_medium = get_status('KNOCK_COUNT', medium_groups)
        status_strong = get_status('KNOCK_COUNT', strong_groups)

    return status_total, status_weak, status_medium, status_strong


def _evaluate_knock_retard_statuses(knock_data: pd.Series) -> list[dict[str, Any]]:
    """Вычисляет метрики и статусы по величине отскока детонации.

    Анализирует максимальный и средний отскок (только значения > 1°).
    Пороги: MAX на основе KNOCK_STRONG_MIN ± KNOCK_RETARD_TOLERANCE,
    MEAN — в KNOCK_RETARD_MEAN_DIVISOR раз меньше.

    Args:
        knock_data: Series значений KNOCK_RETARD (без NaN).

    Returns:
        Список метрик (0 или 2 элемента) {CODE, DESC, VAL, STAT}.
    """
    metrics = []
    valid_knock = knock_data[knock_data > 1]
    if len(valid_knock) == 0:
        return metrics

    max_retard_val = valid_knock.max()
    mean_retard_val = valid_knock.mean()

    # MAX: пороги на основе KNOCK_STRONG_MIN ± KNOCK_RETARD_TOLERANCE
    max_ok_threshold = KNOCK_STRONG_MIN - KNOCK_RETARD_TOLERANCE
    max_error_threshold = KNOCK_STRONG_MIN + KNOCK_RETARD_TOLERANCE
    if max_retard_val < max_ok_threshold:
        status_max = STATUS_OK
    elif max_retard_val <= max_error_threshold:
        status_max = STATUS_WARNING
    else:
        status_max = STATUS_ERROR

    # MEAN: пороги в KNOCK_RETARD_MEAN_DIVISOR раз меньше
    mean_ok_threshold = max_ok_threshold / KNOCK_RETARD_MEAN_DIVISOR
    mean_error_threshold = max_error_threshold / KNOCK_RETARD_MEAN_DIVISOR
    if mean_retard_val < mean_ok_threshold:
        status_mean = STATUS_OK
    elif mean_retard_val <= mean_error_threshold:
        status_mean = STATUS_WARNING
    else:
        status_mean = STATUS_ERROR

    metrics.append({'CODE': 'KNOCK_MAX_RETARD', 'DESC': t('knock.max_retard_desc'), 'VAL': f'{max_retard_val:.1f}', 'STAT': status_max})
    metrics.append({'CODE': 'KNOCK_MEAN_RETARD', 'DESC': t('knock.mean_retard_desc'), 'VAL': f'{mean_retard_val:.2f}', 'STAT': status_mean})

    return metrics


def analyze_knock(df: pd.DataFrame,
                  all_drive_duration_min: Optional[float] = None) -> list[dict[str, Any]]:
    """Анализирует детонацию двигателя по данным KNOCK_RETARD.

    Группирует события (разрыв <= MAX_KNOCK_GROUP_GAP_SEC), классифицирует
    по интенсивности (слабая 2-4°, средняя 5-8°, сильная 9+°) с учетом
    снисходительности для слабых детонаций. Вычисляет статусы с учётом длительности поездки.

    Args:
        df: DataFrame с колонками 'KNOCK_RETARD', 'TIME', опционально 'TIME_SEC', 'RPM', 'SPEED'.
        all_drive_duration_min: Длительность движения (мин) для оценки статусов.

    Returns:
        Список метрик {CODE, DESC, VAL, STAT} по детонации.
    """
    if 'KNOCK_RETARD' not in df.columns:
        return []

    knock_data = df['KNOCK_RETARD'].dropna()

    # Фаза 1: Группировка событий и классификация по интенсивности с учетом remission
    total_groups, weak_groups, medium_groups, strong_groups, remitted_groups = _group_knock_events(df)

    # Фаза 2: Статусы по количеству групп
    status_total, status_weak, status_medium, status_strong = _evaluate_knock_count_statuses(
        total_groups, weak_groups, medium_groups, strong_groups, all_drive_duration_min,
    )

    metrics = []
    metrics.append({'CODE': 'KNOCK_TOTAL_COUNT', 'DESC': t('knock.total_count_desc'), 'VAL': int(total_groups), 'STAT': status_total})
    metrics.append({'CODE': 'KNOCK_WEAK_COUNT', 'DESC': t('knock.weak_count_desc'), 'VAL': int(weak_groups), 'STAT': status_weak})
    metrics.append({'CODE': 'KNOCK_MEDIUM_COUNT', 'DESC': t('knock.medium_count_desc'), 'VAL': int(medium_groups), 'STAT': status_medium})
    metrics.append({'CODE': 'KNOCK_STRONG_COUNT', 'DESC': t('knock.strong_count_desc'), 'VAL': int(strong_groups), 'STAT': status_strong})

    # Добавляем метрику для неучтенных детонаций (норма)
    metrics.append({'CODE': 'KNOCK_REMITTED_COUNT', 'DESC': t('knock.remitted_count_desc'), 'VAL': int(remitted_groups), 'STAT': STATUS_NEUTRAL})

    # Фаза 3: Статусы по величине отскока
    metrics += _evaluate_knock_retard_statuses(knock_data)

    return metrics


def analyze_misfires(df: pd.DataFrame) -> list[dict[str, Any]]:
    """Анализирует пропуски зажигания по данным MISFIRE_CYL1-4.

    Args:
        df: DataFrame с колонками MISFIRE_CYL1..4.

    Returns:
        Список метрик {CODE, DESC, VAL, STAT} по каждому цилиндру и суммарно.
    """
    metrics = []
    cylinders = ['MISFIRE_CYL1', 'MISFIRE_CYL2', 'MISFIRE_CYL3', 'MISFIRE_CYL4']
    found_columns = [c for c in cylinders if c in df.columns]

    if not found_columns:
        metrics.append({'CODE': 'MISFIRE_TOTAL_COUNT', 'DESC': t('knock.misfire_no_data_desc'), 'VAL': -1, 'STAT': STATUS_NEUTRAL})
        return metrics

    total_misfires = 0
    for cyl_col in found_columns:
        cyl_misfires = df[cyl_col].fillna(0).sum()
        total_misfires += cyl_misfires
        cyl_num = cyl_col.replace('MISFIRE_CYL', '')
        metrics.append({'CODE': f'MISFIRE_CYL{cyl_num}_COUNT', 'DESC': t('knock.misfire_cyl_count_desc', cyl=cyl_num), 'VAL': int(cyl_misfires), 'STAT': get_status('MISFIRE', cyl_misfires)})
    metrics.append({'CODE': 'MISFIRE_TOTAL_COUNT', 'DESC': t('knock.misfire_total_desc'), 'VAL': int(total_misfires), 'STAT': get_status('MISFIRE', total_misfires)})
    return metrics

