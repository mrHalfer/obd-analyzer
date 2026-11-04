#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Анализ состояния катализатора по фактору старения и сигналам ДК1/ДК2.
Две независимых оценки:
1) Фактор старения нейтрализатора (CAT_AGING) — среднее за
поездку.
2) Анализ по ДК1/ДК2 — оконный метод: сравнение амплитуды и корреляции
сигналов до и после катализатора на прогретом двигателе под нагрузкой.
ВАЖНО: Исключаются режимы холостого хода и отсечки топлива по MAF.
Пороги вычисляются адаптивно из самих данных.
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
    O2_LEAN_THRESHOLD, O2_RICH_THRESHOLD,
    O2_CROSSING_MIN_COOLANT_TEMP,
    CAT_AGING_BAD_VALUE, CAT_AGING_ERR, CAT_AGING_WARN,
    CAT_COOLANT_MIN, CAT_RPM_MIN, CAT_SPEED_MIN, CAT_MAF_MIN, CAT_MAF_MAX_STD, CAT_MIN_STD1, CAT_WINDOW_SIZE, CAT_MIN_WINDOWS,
    CAT_PHYSICAL_GOOD_MAX_RATIO, CAT_PHYSICAL_GOOD_MAX_CORR,
    CAT_HARD_GOOD_RATIO, CAT_HARD_GOOD_CORR, CAT_HARD_WARN_RATIO, CAT_HARD_WARN_CORR,
    CAT_DK2_GOOD_STD, CAT_DK2_WARN_STD,
    STATUS_OK, STATUS_WARNING, STATUS_ERROR, STATUS_NEUTRAL
)

def analyze_fuel_quality(df: pd.DataFrame) -> list[dict[str, Any]]:
    """Анализирует качество топливной смеси по напряжению O2_B1S1.

    Вычисляет % времени богатой (>0.6V) / бедной (<0.4V) / стехиометрической смеси
    и частоту переключений датчика.

    Args:
        df: DataFrame с колонкой 'O2_B1S1'.

    Returns:
        Список метрик {CODE, DESC, VAL, STAT} качества топлива.
    """
    metrics = []

    if 'O2_B1S1' not in df.columns:
        return metrics

    o2_data = df['O2_B1S1'].dropna()
    if len(o2_data) == 0:
        return metrics

    # Процент времени в богатой / бедной / нормальной смеси
    rich_time = (o2_data > O2_RICH_THRESHOLD).sum() / len(o2_data) * 100
    lean_time = (o2_data < O2_LEAN_THRESHOLD).sum() / len(o2_data) * 100
    normal_time = ((o2_data >= O2_LEAN_THRESHOLD) & (o2_data <= O2_RICH_THRESHOLD)).sum() / len(o2_data) * 100

    # Частота переключений ДК1 (показатель замкнутого контура управления).
    #
    # Алгоритм — автомат состояний с гистерезисом:
    #   бедная  ≤ O2_LEAN_THRESHOLD  (0.4 В) → состояние -1
    #   богатая ≥ O2_RICH_THRESHOLD  (0.6 В) → состояние +1
    #   промежуточные значения [0.4–0.6 В] — игнорируются, состояние не меняется
    # Каждый переход -1 → +1 или +1 → -1 считается одним переключением.
    # Это корректно работает при LOG_DT=1s, когда сигнал проходит через
    # промежуточные значения за несколько шагов (shift-подход пропустил бы их).
    #
    # Фильтр: только прогретый двигатель (closed-loop ≥ O2_CROSSING_MIN_COOLANT_TEMP).
    # Длительность — по числу строк прогретого периода × LOG_DT, чтобы не занижать
    # время в разреженных логах (VAG и аналогичные).
    if 'COOLANT_TEMP' in df.columns:
        cl_mask = df['COOLANT_TEMP'] >= O2_CROSSING_MIN_COOLANT_TEMP
        o2_cl = df.loc[cl_mask, 'O2_B1S1'].dropna()
        duration_min = cl_mask.sum() * LOG_DT / 60
    else:
        o2_cl = o2_data
        duration_min = len(df) * LOG_DT / 60

    vals = o2_cl.values
    # −1 = бедная, +1 = богатая, 0 = промежуточное (не учитывается)
    states = np.where(vals <= O2_LEAN_THRESHOLD, -1,
             np.where(vals >= O2_RICH_THRESHOLD,  1, 0))
    def_states = states[states != 0]  # только определённые состояния
    crossings = int((def_states[1:] != def_states[:-1]).sum()) if len(def_states) > 1 else 0
    crossing_rate = crossings / duration_min if duration_min > 0 else 0.0

    metrics.extend([
        {
            'CODE': 'O2_RICH_TIME',
            'DESC': t('catalyst.o2_rich_time_desc'),
            'VAL': f'{rich_time:.1f}',
            'STAT': STATUS_NEUTRAL,
        },
        {
            'CODE': 'O2_LEAN_TIME',
            'DESC': t('catalyst.o2_lean_time_desc'),
            'VAL': f'{lean_time:.1f}',
            'STAT': STATUS_NEUTRAL,
        },
        {
            'CODE': 'O2_NORMAL_TIME',
            'DESC': t('catalyst.o2_normal_time_desc'),
            'VAL': f'{normal_time:.1f}',
            'STAT': STATUS_NEUTRAL,
        },
        {
            'CODE': 'O2_CROSSING_RATE',
            'DESC': t('catalyst.o2_crossing_rate_desc'),
            'VAL': f'{crossing_rate:.2f}',
            'STAT': STATUS_NEUTRAL,
        },
    ])

    # Итоговая оценка качества топлива
    quality_label, quality_status = _score_fuel_quality(
        normal_time, crossing_rate, rich_time, lean_time,
    )
    metrics.append({
        'CODE': 'FUEL_QUALITY',
        'DESC': t('catalyst.fuel_quality.desc'),
        'VAL': quality_label,
        'STAT': quality_status,
    })

    return metrics


def _score_fuel_quality(
    normal_pct: float, crossing_rate: float,
    rich_pct: float, lean_pct: float,
) -> tuple[str, str]:
    """Оценивает качество топливной смеси по балльной системе.

    Критерии (макс 5 баллов):
    - Стехиометрия ≥20% → +2, ≥10% → +1
    - Переключения ≥40/мин → +2, ≥25/мин → +1
    - Баланс богатой/бедной (ratio < 2.5) → +1

    Returns:
        (label, status) — текстовая оценка и статус (OK/WARNING/ERROR).
    """
    score = 0
    if normal_pct >= 20:
        score += 2
    elif normal_pct >= 10:
        score += 1

    if crossing_rate >= 40:
        score += 2
    elif crossing_rate >= 25:
        score += 1

    if rich_pct > 0 and lean_pct > 0:
        ratio = max(rich_pct, lean_pct) / min(rich_pct, lean_pct)
        if ratio < 2.5:
            score += 1

    if score >= 4:
        return t('catalyst.fuel_quality.good'), STATUS_OK
    elif score >= 2:
        return t('catalyst.fuel_quality.ok'), STATUS_WARNING
    else:
        return t('catalyst.fuel_quality.bad'), STATUS_ERROR

def _get_adaptive_thresholds(ratio_values, corr_values):
    """
    Вычисляет адаптивные пороги с учётом физики катализатора.
    """
    # Если медиана меньше физических пределов — кат скорее всего жив
    median_ratio = np.median(ratio_values)
    median_corr = np.median(corr_values)

    if median_ratio < CAT_PHYSICAL_GOOD_MAX_RATIO and median_corr < CAT_PHYSICAL_GOOD_MAX_CORR:
        # Кат выглядит живым — используем процентили
        good_ratio = np.percentile(ratio_values, 40)
        good_corr = np.percentile(corr_values, 40)
        warn_ratio = np.percentile(ratio_values, 70)
        warn_corr = np.percentile(corr_values, 70)
    else:
        # Кат выглядит убитым — используем жёсткие пороги
        good_ratio = CAT_HARD_GOOD_RATIO
        good_corr = CAT_HARD_GOOD_CORR
        warn_ratio = CAT_HARD_WARN_RATIO
        warn_corr = CAT_HARD_WARN_CORR
    
    return good_ratio, good_corr, warn_ratio, warn_corr


def _get_final_state(state_counts: dict[str, int]) -> str:
    """Взвешенное голосование с медианным уклоном."""
    total_windows = sum(state_counts.values())
    
    # Весовой счёт
    weights = {'BAD': 3, 'WARN': 1.5, 'GOOD': 0}
    weighted_score = sum(state_counts[state] * weights[state] for state in state_counts)
    
    score = weighted_score / total_windows
    
    if score >= 2.2:
        return 'BAD'
    elif score >= 1.0:
        return 'WARN'
    else:
        return 'GOOD'

def _collect_window_metrics(
    df: pd.DataFrame,
    warm_indices: np.ndarray,
    has_maf: bool,
) -> tuple[list[float], list[float], dict[str, int]]:
    """Первый проход по окнам: собирает ratio_std и corr для адаптивных порогов.

    Args:
        df: Исходный DataFrame с колонками O2_B1S1, O2_B1S2, MAF.
        warm_indices: Индексы строк, прошедших фильтр прогрева/нагрузки.
        has_maf: True если колонка MAF присутствует в df.

    Returns:
        (ratio_std_values, corr_values, stats), где stats — словарь
        с детализацией пропущенных окон по причинам.
    """
    ratio_std_values = []
    corr_values = []
    half_window = CAT_WINDOW_SIZE // 2

    stats = {
        'total_windows': 0,
        'skipped_too_small': 0,
        'skipped_no_valid_data': 0,
        'skipped_low_maf': 0,
        'skipped_unstable_maf': 0,
        'skipped_dk2_near_zero': 0,
        'skipped_dk1_no_activity': 0,
        'skipped_corr_nan': 0,
    }

    for start_pos in range(0, len(warm_indices), CAT_WINDOW_SIZE):
        stats['total_windows'] += 1
        window_idx = warm_indices[start_pos:start_pos + CAT_WINDOW_SIZE]

        if len(window_idx) < half_window:
            stats['skipped_too_small'] += 1
            continue

        o2_1 = df.iloc[window_idx]['O2_B1S1'].astype(float)
        o2_2 = df.iloc[window_idx]['O2_B1S2'].astype(float)

        valid_mask = o2_1.notna() & o2_2.notna()
        if valid_mask.sum() < half_window:
            stats['skipped_no_valid_data'] += 1
            continue

        o2_1 = o2_1[valid_mask]
        o2_2 = o2_2[valid_mask]

        if len(o2_1) < 10:
            stats['skipped_no_valid_data'] += 1
            continue

        # Проверка MAF в окне
        if has_maf:
            maf_window = df.iloc[window_idx[valid_mask]]['MAF'].astype(float)

            # Пропускаем окна с низким средним MAF (холостой ход)
            if maf_window.mean() <= CAT_MAF_MIN:
                stats['skipped_low_maf'] += 1
                continue

            # Пропускаем окна с высокой вариативностью MAF (переходные режимы)
            if maf_window.std() >= CAT_MAF_MAX_STD:
                stats['skipped_unstable_maf'] += 1
                continue

        # Пропускаем окна где ДК2 находится преимущественно у нуля
        # (режимы отсечки топлива при торможении)
        dk2_median = o2_2.median()
        dk2_below_threshold = (o2_2 < 0.15).sum() / len(o2_2)

        if dk2_median < 0.2 or dk2_below_threshold > 0.5:
            stats['skipped_dk2_near_zero'] += 1
            continue

        std1 = o2_1.std()
        std2 = o2_2.std()

        # Если ДК1 не пилит — нет замкнутого контура, пропускаем окно
        if std1 <= CAT_MIN_STD1:
            stats['skipped_dk1_no_activity'] += 1
            continue

        ratio_std = std2 / std1
        corr = np.corrcoef(o2_1, o2_2)[0, 1]

        if np.isnan(corr):
            stats['skipped_corr_nan'] += 1
            continue

        ratio_std_values.append(ratio_std)
        corr_values.append(corr)

    return ratio_std_values, corr_values, stats


def _analyze_catalyst_dk2_only(df: pd.DataFrame, warm_indices: np.ndarray, has_maf: bool) -> list[dict[str, Any]]:
    """Анализ катализатора только по ДК2, когда ДК1 недоступен (широкополосный датчик).

    Здоровый катализатор гасит колебания ДК1: ДК2 остаётся стабильным (малое СКО).
    Изношенный/мёртвый катализатор: ДК2 начинает колебаться — СКО растёт.

    Метрика: СКО сигнала ДК2 в каждом отобранном окне.
    Классификация: СКО ≤ CAT_DK2_GOOD_STD → GOOD, ≥ CAT_DK2_WARN_STD → BAD, иначе WARN.
    Итог — взвешенное голосование по окнам (_get_final_state).
    """
    half_window = CAT_WINDOW_SIZE // 2
    std_values: list[float] = []
    stats = {
        'total_windows': 0,
        'skipped_too_small': 0,
        'skipped_no_valid_data': 0,
        'skipped_low_maf': 0,
        'skipped_unstable_maf': 0,
        'skipped_dk2_near_zero': 0,
    }

    for start_pos in range(0, len(warm_indices), CAT_WINDOW_SIZE):
        stats['total_windows'] += 1
        window_idx = warm_indices[start_pos:start_pos + CAT_WINDOW_SIZE]

        if len(window_idx) < half_window:
            stats['skipped_too_small'] += 1
            continue

        o2_2 = df.iloc[window_idx]['O2_B1S2'].astype(float)
        valid_mask = o2_2.notna()
        if valid_mask.sum() < half_window or valid_mask.sum() < 10:
            stats['skipped_no_valid_data'] += 1
            continue

        if has_maf:
            maf_window = df.iloc[window_idx[valid_mask]]['MAF'].astype(float)
            if maf_window.mean() <= CAT_MAF_MIN:
                stats['skipped_low_maf'] += 1
                continue
            if maf_window.std() >= CAT_MAF_MAX_STD:
                stats['skipped_unstable_maf'] += 1
                continue

        o2_2 = o2_2[valid_mask]

        dk2_median = o2_2.median()
        dk2_below_threshold = (o2_2 < 0.15).sum() / len(o2_2)
        if dk2_median < 0.2 or dk2_below_threshold > 0.5:
            stats['skipped_dk2_near_zero'] += 1
            continue

        std_values.append(float(o2_2.std()))

    metrics: list[dict[str, Any]] = []

    if len(std_values) < CAT_MIN_WINDOWS:
        skip_reasons = []
        if stats['skipped_too_small'] > 0:
            skip_reasons.append(t('catalyst.skip_too_small', n=stats['skipped_too_small']))
        if stats['skipped_no_valid_data'] > 0:
            skip_reasons.append(t('catalyst.skip_no_valid_dk2', n=stats['skipped_no_valid_data']))
        if stats['skipped_low_maf'] > 0:
            skip_reasons.append(t('catalyst.skip_low_maf', n=stats['skipped_low_maf']))
        if stats['skipped_unstable_maf'] > 0:
            skip_reasons.append(t('catalyst.skip_unstable_maf', n=stats['skipped_unstable_maf']))
        if stats['skipped_dk2_near_zero'] > 0:
            skip_reasons.append(t('catalyst.skip_dk2_near_zero', n=stats['skipped_dk2_near_zero']))
        skip_msg = '; '.join(skip_reasons) if skip_reasons else t('catalyst.skip_unknown')
        metrics.append({
            'CODE': 'CAT_O2_STATE',
            'DESC': t('catalyst.o2_state_dk2_desc'),
            'VAL': t('catalyst.not_enough_windows', analyzed=len(std_values), min=CAT_MIN_WINDOWS,
                     total=stats['total_windows'], skip_msg=skip_msg),
            'STAT': STATUS_NEUTRAL,
        })
        return metrics

    std_arr = np.array(std_values)
    good_count = int((std_arr <= CAT_DK2_GOOD_STD).sum())
    bad_count = int((std_arr > CAT_DK2_WARN_STD).sum())
    warn_count = len(std_arr) - good_count - bad_count

    state_counts = {'GOOD': good_count, 'WARN': warn_count, 'BAD': bad_count}
    final_state = _get_final_state(state_counts)
    total_windows = sum(state_counts.values())

    status_map = {'GOOD': STATUS_OK, 'WARN': STATUS_WARNING, 'BAD': STATUS_ERROR}
    desc_map = {
        'GOOD': t('catalyst.state_good'),
        'WARN': t('catalyst.state_warn'),
        'BAD': t('catalyst.state_bad'),
    }

    good_pct = good_count / total_windows * 100
    warn_pct = warn_count / total_windows * 100
    bad_pct = bad_count / total_windows * 100
    median_std = float(np.median(std_arr))

    metrics.extend([
        {
            'CODE': 'CAT_O2_STATE',
            'DESC': t('catalyst.o2_state_dk2_desc'),
            'VAL': desc_map[final_state],
            'STAT': status_map[final_state],
        },
        {
            'CODE': 'CAT_DK2_NOTE',
            'DESC': t('catalyst.dk2_note_desc'),
            'VAL': t('catalyst.dk2_only_note'),
            'STAT': STATUS_NEUTRAL,
        },
        {
            'CODE': 'CAT_DK2_MEDIAN_STD',
            'DESC': t('catalyst.dk2_std_desc'),
            'VAL': f'{median_std:.4f}',
            'STAT': STATUS_NEUTRAL,
        },
        {
            'CODE': 'CAT_O2_GOOD_PCT',
            'DESC': t('catalyst.good_pct_desc'),
            'VAL': f'{good_pct:.1f}',
            'STAT': STATUS_NEUTRAL,
        },
        {
            'CODE': 'CAT_O2_WARN_PCT',
            'DESC': t('catalyst.warn_pct_desc'),
            'VAL': f'{warn_pct:.1f}',
            'STAT': STATUS_NEUTRAL,
        },
        {
            'CODE': 'CAT_O2_BAD_PCT',
            'DESC': t('catalyst.bad_pct_desc'),
            'VAL': f'{bad_pct:.1f}',
            'STAT': STATUS_NEUTRAL,
        },
        {
            'CODE': 'CAT_O2_WINDOWS_ANALYZED',
            'DESC': t('catalyst.windows_analyzed_desc'),
            'VAL': t('catalyst.windows_analyzed_val', analyzed=total_windows, total=stats['total_windows']),
            'STAT': STATUS_NEUTRAL,
        },
    ])

    return metrics


def _calculate_adaptive_thresholds(ratio_vals, corr_vals):
    """Вычисляет адаптивные пороги классификации окон и возвращает их в виде словаря."""
    good_ratio, good_corr, warn_ratio, warn_corr = _get_adaptive_thresholds(ratio_vals, corr_vals)
    return {
        'good_ratio': good_ratio,
        'good_corr': good_corr,
        'warn_ratio': warn_ratio,
        'warn_corr': warn_corr,
    }


def _classify_windows(ratio_vals, corr_vals, thresholds):
    """Второй проход: классифицирует каждое окно по адаптивным порогам.

    Возвращает (good_count, warn_count, bad_count) — количество окон каждой категории.
    """
    good_threshold = 0.6 * thresholds['good_ratio'] + 0.4 * thresholds['good_corr']
    warn_threshold = 0.6 * thresholds['warn_ratio'] + 0.4 * thresholds['warn_corr']

    scores = 0.6 * np.array(ratio_vals) + 0.4 * np.array(corr_vals)
    good_count = int((scores <= good_threshold).sum())
    bad_count = int((scores > warn_threshold).sum())
    warn_count = len(scores) - good_count - bad_count

    return good_count, warn_count, bad_count


def _insufficient_warm_points_metric(df: pd.DataFrame, warm_indices: np.ndarray, has_maf: bool) -> dict[str, Any]:
    """Строит метрику CAT_O2_STATE с причинами нехватки точек прогретого двигателя."""
    total_points = len(df)
    filtered_temp = (df['COOLANT_TEMP'] >= CAT_COOLANT_MIN).sum()
    filtered_rpm = (df['RPM'] >= CAT_RPM_MIN).sum()
    filtered_speed = (df['SPEED'] >= CAT_SPEED_MIN).sum()
    filtered_maf = (df['MAF'] > CAT_MAF_MIN).sum() if has_maf else total_points
    temp_rpm_speed = (
        (df['COOLANT_TEMP'] >= CAT_COOLANT_MIN) &
        (df['RPM'] >= CAT_RPM_MIN) &
        (df['SPEED'] >= CAT_SPEED_MIN)
    ).sum()

    reason_parts = [
        t('catalyst.points_total', n=total_points),
        t('catalyst.points_temp', temp=CAT_COOLANT_MIN, n=filtered_temp),
        t('catalyst.points_rpm', rpm=CAT_RPM_MIN, n=filtered_rpm),
        t('catalyst.points_speed', speed=CAT_SPEED_MIN, n=filtered_speed),
    ]
    if has_maf:
        reason_parts.append(t('catalyst.points_maf', maf=CAT_MAF_MIN, n=filtered_maf))
        reason_parts.append(t('catalyst.points_temp_rpm_speed', n=temp_rpm_speed))
        reason_parts.append(t('catalyst.points_all_with_maf', n=len(warm_indices)))
    else:
        reason_parts.append(t('catalyst.points_temp_rpm_speed', n=temp_rpm_speed))
        reason_parts.append(t('catalyst.points_all', n=len(warm_indices)))
    reason_parts.append(t('catalyst.points_required', n=CAT_WINDOW_SIZE))

    bottleneck = min([
        (t('catalyst.bottleneck_temp'), filtered_temp),
        (t('catalyst.bottleneck_rpm'), filtered_rpm),
        (t('catalyst.bottleneck_speed'), filtered_speed),
        (t('catalyst.bottleneck_maf'), filtered_maf) if has_maf else (t('catalyst.bottleneck_maf'), total_points),
    ], key=lambda x: x[1])

    return {
        'CODE': 'CAT_O2_STATE',
        'DESC': t('catalyst.o2_state_desc'),
        'VAL': t('catalyst.not_enough_points', reason='; '.join(reason_parts),
                 bottleneck=bottleneck[0], count=bottleneck[1]),
        'STAT': STATUS_NEUTRAL,
    }


def _insufficient_windows_metric(ratio_std_values: list, stats: dict[str, int]) -> dict[str, Any]:
    """Строит метрику CAT_O2_STATE с причинами нехватки валидных окон анализа."""
    skip_reasons = []
    for key, tkey in [
        ('skipped_too_small',       'catalyst.skip_too_small'),
        ('skipped_no_valid_data',   'catalyst.skip_no_valid_data'),
        ('skipped_low_maf',         'catalyst.skip_low_maf'),
        ('skipped_unstable_maf',    'catalyst.skip_unstable_maf'),
        ('skipped_dk2_near_zero',   'catalyst.skip_dk2_near_zero'),
        ('skipped_dk1_no_activity', 'catalyst.skip_dk1_no_activity'),
        ('skipped_corr_nan',        'catalyst.skip_corr_nan'),
    ]:
        if stats[key] > 0:
            skip_reasons.append(t(tkey, n=stats[key]))

    skip_msg = '; '.join(skip_reasons) if skip_reasons else t('catalyst.skip_unknown')
    return {
        'CODE': 'CAT_O2_STATE',
        'DESC': t('catalyst.o2_state_desc'),
        'VAL': t('catalyst.not_enough_windows', analyzed=len(ratio_std_values),
                 min=CAT_MIN_WINDOWS, total=stats['total_windows'], skip_msg=skip_msg),
        'STAT': STATUS_NEUTRAL,
    }


def analyze_catalyst(df: pd.DataFrame) -> list[dict[str, Any]]:
    """Анализирует состояние катализатора по фактору старения и сигналам ДК1/ДК2.

    Две независимых оценки:
    1) Фактор старения нейтрализатора (CAT_AGING) — среднее за поездку.
    2) Анализ по ДК1/ДК2 — оконный метод: сравнение амплитуды и корреляции
       сигналов до и после катализатора на прогретом двигателе под нагрузкой.
       ВАЖНО: Исключаются режимы холостого хода и отсечки топлива по MAF.
       Пороги вычисляются адаптивно из самих данных.
       Итог — голосование по большинству окон (GOOD/WARN/BAD).

    Args:
        df: DataFrame с колонками 'CAT_AGING', 'O2_B1S1', 'O2_B1S2',
            'COOLANT_TEMP', 'RPM', 'SPEED', 'MAF' (все опциональны).

    Returns:
        Список метрик {CODE, DESC, VAL, STAT}.
    """
    metrics: list[dict[str, Any]] = []

    # --- 1. Фактор старения нейтрализатора ---
    if 'CAT_AGING' in df.columns:
        aging_data = df['CAT_AGING'].dropna()
        if len(aging_data) > 0:
            raw_mean = aging_data.mean()
            normalized_mean = raw_mean if CAT_AGING_BAD_VALUE == 1 else (1.0 - raw_mean)

            if normalized_mean >= CAT_AGING_ERR:
                status_aging = STATUS_ERROR
            elif normalized_mean >= CAT_AGING_WARN:
                status_aging = STATUS_WARNING
            else:
                status_aging = STATUS_OK

            metrics.append({
                'CODE': 'CAT_AGING_MEAN',
                'DESC': t('catalyst.aging_mean_desc'),
                'VAL': f'{raw_mean:.3f}',
                'STAT': status_aging,
            })

    # --- 2. Анализ по ДК1/ДК2 (или только ДК2 при наличии широкополосного ДК1) ---
    base_required = ['O2_B1S2', 'COOLANT_TEMP', 'RPM', 'SPEED']
    dk1_available = 'O2_B1S1' in df.columns
    dk2_only = not dk1_available and all(c in df.columns for c in base_required)

    missing_cols = [col for col in (['O2_B1S1'] + base_required) if col not in df.columns]
    if missing_cols and not dk2_only:
        metrics.append({
            'CODE': 'CAT_O2_STATE',
            'DESC': t('catalyst.o2_state_desc'),
            'VAL': t('catalyst.missing_cols', cols=', '.join(missing_cols)),
            'STAT': STATUS_NEUTRAL,
        })
        return metrics

    # Проверка наличия MAF
    has_maf = 'MAF' in df.columns

    # Маска «двигатель прогрет и есть нагрузка»
    warm_mask = (
        (df['COOLANT_TEMP'] >= CAT_COOLANT_MIN) &
        (df['RPM'] >= CAT_RPM_MIN) &
        (df['SPEED'] >= CAT_SPEED_MIN)
    )
    
    # Добавляем фильтр по MAF если доступен
    if has_maf:
        warm_mask = warm_mask & (df['MAF'] > CAT_MAF_MIN)

    metrics.append({
            'CODE': 'CAT_O2_HAS_MAF',
            'DESC': t('catalyst.has_maf_desc'),
            'VAL': t('catalyst.yes') if has_maf else t('catalyst.no'),
            'STAT': STATUS_OK if has_maf else STATUS_WARNING,
        })

    # Индексы точек, соответствующих условиям прогрева и нагрузки
    warm_indices = np.where(warm_mask)[0]
    
    # Проверяем достаточно ли данных в окнах проверки для диагностики
    if len(warm_indices) <= CAT_WINDOW_SIZE:
        metrics.append(_insufficient_warm_points_metric(df, warm_indices, has_maf))
        return metrics

    # --- Ветка: только ДК2 (ДК1 — широкополосный, voltage недоступен) ---
    if dk2_only:
        metrics.extend(_analyze_catalyst_dk2_only(df, warm_indices, has_maf))
        return metrics

    # --- ПЕРВЫЙ ПРОХОД: собираем метрики по всем окнам ---
    ratio_std_values, corr_values, stats = _collect_window_metrics(df, warm_indices, has_maf)

    # Проверка: достаточно ли данных для анализа
    if len(ratio_std_values) < CAT_MIN_WINDOWS:
        metrics.append(_insufficient_windows_metric(ratio_std_values, stats))
        return metrics

    # --- ВЫЧИСЛЕНИЕ АДАПТИВНЫХ ПОРОГОВ ---
    thresholds = _calculate_adaptive_thresholds(ratio_std_values, corr_values)
    good_ratio = thresholds['good_ratio']
    good_corr = thresholds['good_corr']
    warn_ratio = thresholds['warn_ratio']
    warn_corr = thresholds['warn_corr']

    # --- ВТОРОЙ ПРОХОД: классификация по адаптивным порогам ---
    good_count, warn_count, bad_count = _classify_windows(ratio_std_values, corr_values, thresholds)
    state_counts = {'GOOD': good_count, 'WARN': warn_count, 'BAD': bad_count}

    total_windows = sum(state_counts.values())
    final_state = _get_final_state(state_counts)

    status_map = {'GOOD': STATUS_OK, 'WARN': STATUS_WARNING, 'BAD': STATUS_ERROR}
    desc_map = {
        'GOOD': t('catalyst.state_good'),
        'WARN': t('catalyst.state_warn'),
        'BAD': t('catalyst.state_bad'),
    }

    good_pct = state_counts['GOOD'] / total_windows * 100
    warn_pct = state_counts['WARN'] / total_windows * 100
    bad_pct = state_counts['BAD'] / total_windows * 100

    avg_ratio = np.median(ratio_std_values)
    avg_corr = np.median(corr_values)

    metrics.extend([
        {
            'CODE': 'CAT_O2_STATE',
            'DESC': t('catalyst.o2_state_weighted_desc'),
            'VAL': desc_map[final_state],
            'STAT': status_map[final_state],
        },
        {
            'CODE': 'CAT_O2_GOOD_PCT',
            'DESC': t('catalyst.good_pct_desc'),
            'VAL': f'{good_pct:.1f}',
            'STAT': STATUS_NEUTRAL,
        },
        {
            'CODE': 'CAT_O2_WARN_PCT',
            'DESC': t('catalyst.warn_pct_desc'),
            'VAL': f'{warn_pct:.1f}',
            'STAT': STATUS_NEUTRAL,
        },
        {
            'CODE': 'CAT_O2_BAD_PCT',
            'DESC': t('catalyst.bad_pct_desc'),
            'VAL': f'{bad_pct:.1f}',
            'STAT': STATUS_NEUTRAL,
        },
        {
            'CODE': 'CAT_O2_AVG_RATIO',
            'DESC': t('catalyst.avg_ratio_desc'),
            'VAL': f'{avg_ratio:.3f}',
            'STAT': STATUS_NEUTRAL,
        },
        {
            'CODE': 'CAT_O2_AVG_CORR',
            'DESC': t('catalyst.avg_corr_desc'),
            'VAL': f'{avg_corr:.3f}',
            'STAT': STATUS_NEUTRAL,
        },
        {
            'CODE': 'CAT_O2_WINDOWS_ANALYZED',
            'DESC': t('catalyst.windows_analyzed_desc'),
            'VAL': t('catalyst.windows_analyzed_val', analyzed=total_windows, total=stats['total_windows']),
            'STAT': STATUS_NEUTRAL,
        },
        {
            'CODE': 'CAT_O2_WINDOWS_SKIPPED',
            'DESC': t('catalyst.windows_skipped_desc'),
            'VAL': t('catalyst.windows_skipped_val',
                     maf=stats['skipped_low_maf'] + stats['skipped_unstable_maf'],
                     dk2=stats['skipped_dk2_near_zero'],
                     dk1=stats['skipped_dk1_no_activity'],
                     bad=stats['skipped_no_valid_data'] + stats['skipped_too_small'] + stats['skipped_corr_nan']),
            'STAT': STATUS_NEUTRAL,
        },
        {
            'CODE': 'CAT_O2_THRESHOLD_GOOD_RATIO',
            'DESC': t('catalyst.threshold_good_ratio_desc'),
            'VAL': f'{good_ratio:.3f}',
            'STAT': STATUS_NEUTRAL,
        },
        {
            'CODE': 'CAT_O2_THRESHOLD_GOOD_CORR',
            'DESC': t('catalyst.threshold_good_corr_desc'),
            'VAL': f'{good_corr:.3f}',
            'STAT': STATUS_NEUTRAL,
        },
        {
            'CODE': 'CAT_O2_THRESHOLD_WARN_RATIO',
            'DESC': t('catalyst.threshold_warn_ratio_desc'),
            'VAL': f'{warn_ratio:.3f}',
            'STAT': STATUS_NEUTRAL,
        },
        {
            'CODE': 'CAT_O2_THRESHOLD_WARN_CORR',
            'DESC': t('catalyst.threshold_warn_corr_desc'),
            'VAL': f'{warn_corr:.3f}',
            'STAT': STATUS_NEUTRAL,
        },
    ])

    return metrics