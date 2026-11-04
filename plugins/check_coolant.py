#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Анализ системы охлаждения двигателя (термостат + вентилятор).

Проверки:
1. Термостат:
   - Скорость прогрева в режиме WARMUP
   - Стабильность температуры после прогрева
   - Охлаждение на высокой скорости
2. Вентилятор:
   - Включение при достижении температуры
   - Эффективность охлаждения
   - Выключение при снижении температуры
3. Перегрев:
   - Наличие и длительность перегревов
"""

import numpy as np
import pandas as pd
from typing import Any

import sys as _sys
from pathlib import Path as _Path
_root = _Path(__file__).parent.parent
for _d in [str(_root), str(_root / 'build'), str(_root / 'plugins')]:
    if _d not in _sys.path:
        _sys.path.insert(0, _d)

from translation import t
from core_obd import (
    LOG_DT,
    STATUS_OK, STATUS_WARNING, STATUS_ERROR, STATUS_NEUTRAL,
    COOLANT_FAN_ON_TEMP, COOLANT_FAN_SPEED_THRESHOLD,
    COOLANT_WARMUP_TARGET_TEMP,
    COOLANT_WARMUP_MIN_RATE_GOOD, COOLANT_WARMUP_MIN_RATE_WARN, COOLANT_WARMUP_MAX_TIME_MIN,
    COOLANT_WARMUP_COLD_START_MAX_TEMP, COOLANT_WARMUP_MIN_DURATION_MIN,
    COOLANT_THERMOSTAT_OPEN_TEMP, COOLANT_THERMOSTAT_STABLE_TEMP_MIN, COOLANT_THERMOSTAT_STABLE_TEMP_MAX,
    COOLANT_THERMOSTAT_CHECK_SPEED_MIN, COOLANT_THERMOSTAT_COOLING_RATE_MIN,
    COOLANT_THERMOSTAT_MIN_ANALYSIS_SEC, COOLANT_THERMOSTAT_WINDOW_SEC,
    COOLANT_OVERHEAT_WARNING_TEMP, COOLANT_OVERHEAT_ERROR_TEMP, COOLANT_OVERHEAT_MIN_DURATION_SEC,
)


def _analyze_warmup(df: pd.DataFrame) -> list[dict[str, Any]]:
    """Анализирует скорость прогрева двигателя в режиме WARMUP.

    Args:
        df: DataFrame с колонками 'COOLANT_TEMP', 'REGIME', 'TIME_SEC'.

    Returns:
        Список метрик прогрева.
    """
    metrics = []

    if 'REGIME' not in df.columns:
        return metrics

    warmup_data = df[df['REGIME'] == 'WARMUP'].copy()

    if len(warmup_data) == 0:
        metrics.append({
            'CODE': 'COOLANT_WARMUP_RATE',
            'DESC': t('coolant.warmup_rate_desc'),
            'VAL': t('coolant.no_warmup_regime'),
            'STAT': STATUS_NEUTRAL,
        })
        return metrics

    # Находим начальную и конечную температуру (первое/последнее ненулевое значение)
    temp_series = warmup_data['COOLANT_TEMP'].dropna()
    if temp_series.empty:
        metrics.append({
            'CODE': 'COOLANT_WARMUP_RATE',
            'DESC': t('coolant.warmup_rate_desc'),
            'VAL': t('coolant.no_coolant_temp'),
            'STAT': STATUS_NEUTRAL,
        })
        return metrics
    temp_start = temp_series.iloc[0]
    temp_end = temp_series.iloc[-1]

    # Длительность прогрева в минутах
    duration_min = len(warmup_data) * LOG_DT / 60.0

    # Скорость прогрева (°C/мин)
    warmup_rate = (temp_end - temp_start) / duration_min if duration_min > 0 else 0.0

    # Оценка скорости прогрева — только для холодного старта достаточной длительности
    cold_start = temp_start < COOLANT_WARMUP_COLD_START_MAX_TEMP
    long_enough = duration_min > COOLANT_WARMUP_MIN_DURATION_MIN

    if not cold_start:
        warmup_status = STATUS_NEUTRAL
        warmup_label = t('coolant.warmup_not_assessed')
        warmup_rate_val = t(
            'coolant.warmup_skipped_warm_engine',
            temp=f'{temp_start:.0f}',
            threshold=int(COOLANT_WARMUP_COLD_START_MAX_TEMP),
        )
    elif not long_enough:
        warmup_status = STATUS_NEUTRAL
        warmup_label = t('coolant.warmup_not_assessed')
        warmup_rate_val = t(
            'coolant.warmup_skipped_too_short',
            minutes=f'{duration_min:.1f}',
            min_dur=COOLANT_WARMUP_MIN_DURATION_MIN,
        )
    elif warmup_rate >= COOLANT_WARMUP_MIN_RATE_GOOD:
        warmup_status = STATUS_OK
        warmup_label = t('coolant.warmup_fast')
        warmup_rate_val = f'{warmup_rate:.2f}'
    elif warmup_rate >= COOLANT_WARMUP_MIN_RATE_WARN:
        warmup_status = STATUS_WARNING
        warmup_label = t('coolant.warmup_slow')
        warmup_rate_val = f'{warmup_rate:.2f}'
    else:
        warmup_status = STATUS_ERROR
        warmup_label = t('coolant.warmup_very_slow')
        warmup_rate_val = f'{warmup_rate:.2f}'

    # Проверка достижения целевой температуры
    target_reached = temp_end >= COOLANT_WARMUP_TARGET_TEMP

    metrics.extend([
        {
            'CODE': 'COOLANT_WARMUP_START_TEMP',
            'DESC': t('coolant.warmup_start_temp_desc'),
            'VAL': f'{temp_start:.1f}',
            'STAT': STATUS_NEUTRAL,
        },
        {
            'CODE': 'COOLANT_WARMUP_END_TEMP',
            'DESC': t('coolant.warmup_end_temp_desc'),
            'VAL': f'{temp_end:.1f}',
            'STAT': STATUS_OK if target_reached else STATUS_WARNING,
        },
        {
            'CODE': 'COOLANT_WARMUP_DURATION',
            'DESC': t('coolant.warmup_duration_desc'),
            'VAL': f'{duration_min:.1f}',
            'STAT': STATUS_OK if duration_min <= COOLANT_WARMUP_MAX_TIME_MIN else STATUS_WARNING,
        },
        {
            'CODE': 'COOLANT_WARMUP_RATE',
            'DESC': t('coolant.warmup_rate_val_desc'),
            'VAL': warmup_rate_val,
            'STAT': warmup_status,
        },
        {
            'CODE': 'COOLANT_WARMUP_ASSESSMENT',
            'DESC': t('coolant.warmup_assessment_desc'),
            'VAL': warmup_label,
            'STAT': warmup_status,
        },
    ])

    return metrics


def _analyze_thermostat_stability(df: pd.DataFrame) -> list[dict[str, Any]]:
    """Анализирует стабильность температуры после прогрева (работа термостата).

    Args:
        df: DataFrame с колонками 'COOLANT_TEMP', 'SPEED', 'REGIME'.

    Returns:
        Список метрик стабильности температуры.
    """
    metrics = []

    # Фильтруем данные после прогрева (температура >= THERMOSTAT_OPEN_TEMP)
    warmed_data = df[df['COOLANT_TEMP'] >= COOLANT_THERMOSTAT_OPEN_TEMP].copy()

    if len(warmed_data) == 0:
        metrics.append({
            'CODE': 'COOLANT_THERMOSTAT_STABILITY',
            'DESC': t('coolant.thermostat_stability_desc'),
            'VAL': t('coolant.engine_not_warmed'),
            'STAT': STATUS_NEUTRAL,
        })
        return metrics

    # Средняя и максимальная температура после прогрева
    temp_mean = warmed_data['COOLANT_TEMP'].mean()
    temp_max = warmed_data['COOLANT_TEMP'].max()
    temp_min = warmed_data['COOLANT_TEMP'].min()
    temp_std = warmed_data['COOLANT_TEMP'].std()

    # Проверка стабильности (средняя температура в рабочем диапазоне)
    stable = COOLANT_THERMOSTAT_STABLE_TEMP_MIN <= temp_mean <= COOLANT_THERMOSTAT_STABLE_TEMP_MAX

    # Проверка охлаждения на высокой скорости
    high_speed_data = warmed_data[warmed_data['SPEED'] >= COOLANT_THERMOSTAT_CHECK_SPEED_MIN]

    cooling_ok = False
    cooling_rate = 0.0
    min_points = int(COOLANT_THERMOSTAT_MIN_ANALYSIS_SEC / LOG_DT)
    window_sz = int(COOLANT_THERMOSTAT_WINDOW_SEC / LOG_DT)

    if len(high_speed_data) >= min_points:
        # Разбиваем на окна и проверяем охлаждение
        for i in range(0, len(high_speed_data) - window_sz, window_sz):
            window = high_speed_data.iloc[i:i+window_sz]
            temp_start_win = window['COOLANT_TEMP'].iloc[0]
            temp_end_win = window['COOLANT_TEMP'].iloc[-1]
            duration_min_win = len(window) * LOG_DT / 60.0

            if duration_min_win > 0:
                rate = (temp_start_win - temp_end_win) / duration_min_win  # Положительное значение = охлаждение
                if rate >= COOLANT_THERMOSTAT_COOLING_RATE_MIN:
                    cooling_ok = True
                    cooling_rate = max(cooling_rate, rate)

    # Итоговая оценка термостата
    if stable and (not cooling_ok or len(high_speed_data) < min_points):
        # Стабильная температура, но нет данных о высокой скорости
        thermostat_status = STATUS_OK
        thermostat_label = t('coolant.thermostat_ok')
    elif stable and cooling_ok:
        # Стабильная температура и есть охлаждение на высокой скорости
        thermostat_status = STATUS_OK
        thermostat_label = t('coolant.thermostat_ok')
    elif not stable and temp_mean < COOLANT_THERMOSTAT_STABLE_TEMP_MIN:
        # Температура ниже нормы - возможно заклинил в открытом положении
        thermostat_status = STATUS_ERROR
        thermostat_label = t('coolant.thermostat_stuck_open')
    elif not stable and temp_mean > COOLANT_THERMOSTAT_STABLE_TEMP_MAX:
        # Температура выше нормы - возможно заклинил в закрытом положении
        thermostat_status = STATUS_ERROR
        thermostat_label = t('coolant.thermostat_stuck_closed')
    else:
        thermostat_status = STATUS_WARNING
        thermostat_label = t('coolant.thermostat_unstable')

    metrics.extend([
        {
            'CODE': 'COOLANT_TEMP_MEAN_WARMED',
            'DESC': t('coolant.temp_mean_warmed_desc'),
            'VAL': f'{temp_mean:.1f}',
            'STAT': STATUS_OK if stable else STATUS_WARNING,
        },
        {
            'CODE': 'COOLANT_TEMP_MAX',
            'DESC': t('coolant.temp_max_desc'),
            'VAL': f'{temp_max:.1f}',
            'STAT': STATUS_OK if temp_max < COOLANT_OVERHEAT_WARNING_TEMP else STATUS_WARNING,
        },
        {
            'CODE': 'COOLANT_TEMP_MIN_WARMED',
            'DESC': t('coolant.temp_min_warmed_desc'),
            'VAL': f'{temp_min:.1f}',
            'STAT': STATUS_NEUTRAL,
        },
        {
            'CODE': 'COOLANT_TEMP_STD',
            'DESC': t('coolant.temp_std_desc'),
            'VAL': f'{temp_std:.2f}',
            'STAT': STATUS_OK if temp_std < 5 else STATUS_WARNING,
        },
        {
            'CODE': 'COOLANT_THERMOSTAT_STABILITY',
            'DESC': t('coolant.thermostat_stability_desc'),
            'VAL': t('coolant.temp_stable') if stable else t('coolant.temp_unstable'),
            'STAT': STATUS_OK if stable else STATUS_WARNING,
        },
    ])

    # Добавляем метрики охлаждения на высокой скорости если есть данные
    if len(high_speed_data) >= min_points:
        metrics.extend([
            {
                'CODE': 'COOLANT_COOLING_AT_HIGH_SPEED',
                'DESC': t('coolant.cooling_at_speed_desc', speed=COOLANT_THERMOSTAT_CHECK_SPEED_MIN),
                'VAL': t('coolant.cooling_at_speed_yes', rate=f'{cooling_rate:.2f}') if cooling_ok else t('coolant.no'),
                'STAT': STATUS_OK if cooling_ok else STATUS_WARNING,
            },
        ])

    metrics.append({
        'CODE': 'COOLANT_THERMOSTAT_ASSESSMENT',
        'DESC': t('coolant.thermostat_assessment_desc'),
        'VAL': thermostat_label,
        'STAT': thermostat_status,
    })

    return metrics


def _analyze_fan(df: pd.DataFrame) -> list[dict[str, Any]]:
    """Анализирует работу вентилятора охлаждения.

    Args:
        df: DataFrame с колонками 'COOLANT_TEMP', 'SPEED'.

    Returns:
        Список метрик работы вентилятора.
    """
    metrics = []

    # Ищем периоды когда температура достигала порога включения вентилятора
    # При низкой скорости движения (вентилятор должен включиться)
    hot_low_speed = df[
        (df['COOLANT_TEMP'] >= COOLANT_FAN_ON_TEMP) &
        (df['SPEED'] <= COOLANT_FAN_SPEED_THRESHOLD)
    ].copy()

    if len(hot_low_speed) == 0:
        metrics.append({
            'CODE': 'COOLANT_FAN_CHECK',
            'DESC': t('coolant.fan_check_desc'),
            'VAL': t('coolant.fan_no_threshold'),
            'STAT': STATUS_NEUTRAL,
        })
        return metrics

    # Анализируем динамику температуры при низкой скорости и высокой температуре
    # Если вентилятор работает, температура должна снижаться

    # Разбиваем на окна по 1 минуте (300 точек при LOG_DT=0.2)
    window_size = int(60 / LOG_DT)  # 60 секунд

    cooling_events = 0
    total_windows = 0
    avg_cooling_rate = []

    for i in range(0, len(hot_low_speed) - window_size, window_size // 2):
        window = hot_low_speed.iloc[i:i+window_size]
        if len(window) < window_size // 2:
            continue

        total_windows += 1
        temp_start = window['COOLANT_TEMP'].iloc[0]
        temp_end = window['COOLANT_TEMP'].iloc[-1]

        # Если температура снизилась - вентилятор работает
        if temp_start > temp_end:
            cooling_events += 1
            duration_min = len(window) * LOG_DT / 60.0
            if duration_min > 0:
                rate = (temp_start - temp_end) / duration_min
                avg_cooling_rate.append(rate)

    # Оценка работы вентилятора
    if total_windows == 0:
        fan_status = STATUS_NEUTRAL
        fan_label = t('coolant.fan_no_data')
    else:
        cooling_pct = cooling_events / total_windows * 100

        if cooling_pct >= 70:
            fan_status = STATUS_OK
            fan_label = t('coolant.fan_ok')
        elif cooling_pct >= 40:
            fan_status = STATUS_WARNING
            fan_label = t('coolant.fan_inefficient')
        else:
            fan_status = STATUS_ERROR
            fan_label = t('coolant.fan_not_working')

    # Средняя скорость охлаждения
    mean_cooling_rate = np.mean(avg_cooling_rate) if avg_cooling_rate else 0.0

    # Максимальная температура при низкой скорости
    max_temp_low_speed = hot_low_speed['COOLANT_TEMP'].max()

    metrics.extend([
        {
            'CODE': 'COOLANT_FAN_ACTIVATION_COUNT',
            'DESC': t('coolant.fan_periods_desc', temp=COOLANT_FAN_ON_TEMP),
            'VAL': f'{total_windows}',
            'STAT': STATUS_NEUTRAL,
        },
        {
            'CODE': 'COOLANT_FAN_COOLING_PCT',
            'DESC': t('coolant.fan_cooling_pct_desc'),
            'VAL': f'{cooling_pct:.1f}' if total_windows > 0 else 'N/A',
            'STAT': fan_status if total_windows > 0 else STATUS_NEUTRAL,
        },
        {
            'CODE': 'COOLANT_FAN_COOLING_RATE',
            'DESC': t('coolant.fan_cooling_rate_desc'),
            'VAL': f'{mean_cooling_rate:.2f}' if mean_cooling_rate > 0 else 'N/A',
            'STAT': STATUS_NEUTRAL,
        },
        {
            'CODE': 'COOLANT_FAN_MAX_TEMP',
            'DESC': t('coolant.fan_max_temp_desc'),
            'VAL': f'{max_temp_low_speed:.1f}',
            'STAT': STATUS_OK if max_temp_low_speed < COOLANT_OVERHEAT_WARNING_TEMP else STATUS_WARNING,
        },
        {
            'CODE': 'COOLANT_FAN_ASSESSMENT',
            'DESC': t('coolant.fan_assessment_desc'),
            'VAL': fan_label,
            'STAT': fan_status,
        },
    ])

    return metrics


def _analyze_overheat(df: pd.DataFrame) -> list[dict[str, Any]]:
    """Анализирует наличие перегревов двигателя.

    Args:
        df: DataFrame с колонками 'COOLANT_TEMP'.

    Returns:
        Список метрик перегрева.
    """
    metrics = []

    # Поиск перегревов (температура >= OVERHEAT_WARNING_TEMP)
    overheat_warning = df[df['COOLANT_TEMP'] >= COOLANT_OVERHEAT_WARNING_TEMP]
    overheat_error = df[df['COOLANT_TEMP'] >= COOLANT_OVERHEAT_ERROR_TEMP]

    warning_duration_sec = len(overheat_warning) * LOG_DT
    error_duration_sec = len(overheat_error) * LOG_DT

    # Проверка длительных перегревов
    long_overheat_warning = warning_duration_sec >= COOLANT_OVERHEAT_MIN_DURATION_SEC
    long_overheat_error = error_duration_sec >= COOLANT_OVERHEAT_MIN_DURATION_SEC

    # Итоговая оценка
    if long_overheat_error:
        overheat_status = STATUS_ERROR
        overheat_label = t('coolant.overheat_critical')
    elif long_overheat_warning:
        overheat_status = STATUS_WARNING
        overheat_label = t('coolant.overheat_elevated')
    elif len(overheat_warning) > 0:
        overheat_status = STATUS_WARNING
        overheat_label = t('coolant.overheat_brief')
    else:
        overheat_status = STATUS_OK
        overheat_label = t('coolant.overheat_none')

    metrics.extend([
        {
            'CODE': 'COOLANT_OVERHEAT_WARNING_DURATION',
            'DESC': t('coolant.overheat_duration_desc', temp=COOLANT_OVERHEAT_WARNING_TEMP),
            'VAL': f'{warning_duration_sec:.1f}',
            'STAT': STATUS_OK if warning_duration_sec == 0 else STATUS_WARNING,
        },
        {
            'CODE': 'COOLANT_OVERHEAT_ERROR_DURATION',
            'DESC': t('coolant.overheat_duration_desc', temp=COOLANT_OVERHEAT_ERROR_TEMP),
            'VAL': f'{error_duration_sec:.1f}',
            'STAT': STATUS_OK if error_duration_sec == 0 else STATUS_ERROR,
        },
        {
            'CODE': 'COOLANT_OVERHEAT_ASSESSMENT',
            'DESC': t('coolant.overheat_assessment_desc'),
            'VAL': overheat_label,
            'STAT': overheat_status,
        },
    ])

    return metrics


def analyze_coolant_system(df: pd.DataFrame, temp_outside: float | None = None) -> list[dict[str, Any]]:
    """Анализирует систему охлаждения двигателя (термостат + вентилятор).

    Выполняет комплексный анализ:
    1. Скорость прогрева (термостат)
    2. Стабильность температуры после прогрева (термостат)
    3. Охлаждение на высокой скорости (термостат)
    4. Работа вентилятора (включение/охлаждение)
    5. Наличие перегревов

    Args:
        df: DataFrame с колонками 'COOLANT_TEMP', 'SPEED', 'REGIME', 'TIME_SEC'.
        temp_outside: Температура снаружи (°C). Используется для контекста анализа.

    Returns:
        Список метрик {CODE, DESC, VAL, STAT}.
    """
    metrics: list[dict[str, Any]] = []

    # Проверка наличия необходимых колонок
    if 'COOLANT_TEMP' not in df.columns:
        metrics.append({
            'CODE': 'COOLANT_SYSTEM_CHECK',
            'DESC': t('coolant.system_check_desc'),
            'VAL': t('coolant.no_coolant_temp'),
            'STAT': STATUS_NEUTRAL,
        })
        return metrics

    # Температура окружающей среды (RUN_TEMP_OUTSIDE)
    if temp_outside is not None:
        metrics.append({
            'CODE': 'COOLANT_AMBIENT_TEMP',
            'DESC': t('coolant.ambient_temp_desc'),
            'VAL': f'{temp_outside:.1f}',
            'STAT': STATUS_NEUTRAL,
        })

    # 1. Анализ прогрева
    metrics.extend(_analyze_warmup(df))

    # 2. Анализ стабильности температуры (термостат)
    if 'SPEED' in df.columns:
        metrics.extend(_analyze_thermostat_stability(df))

    # 3. Анализ работы вентилятора
    if 'SPEED' in df.columns:
        metrics.extend(_analyze_fan(df))

    # 4. Анализ перегревов
    metrics.extend(_analyze_overheat(df))

    return metrics
