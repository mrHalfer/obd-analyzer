#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Модуль формирования CSV-отчётов для анализа OBD-II данных.

Содержит функции сохранения:
- Джокер-событий (заглохи)
- Профиля скорости
- Групп детонации
- Хронологии детонации
- Хронологии пропусков зажигания
"""

import logging
from pathlib import Path

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
    STALLED_RPM_THRESHOLD,
    KNOCK_WEAK_MAX,
    KNOCK_MEDIUM_MAX,
    parse_time_to_seconds_vectorized,
    filter_stalled_events,
)

from check_knock import classify_knock_groups_with_remission
from translation import t

logger = logging.getLogger(__name__)


def save_joker_events(df: pd.DataFrame, output_dir: Path, base_filename: str) -> None:
    """Сохраняет события заглохов (RPM < STALLED_RPM_THRESHOLD) в CSV файл.

    Группирует события по времени, фильтрует намеренные остановки
    (длительность >= MAX_STALLED_DURATION_SEC) и заглушение в конце поездки.

    Args:
        df: DataFrame с полными данными (включая низкие RPM).
        output_dir: Директория для сохранения.
        base_filename: Базовое имя файла без расширения.
    """
    if 'RPM' not in df.columns or 'TIME' not in df.columns:
        logger.warning(t('console.csv_joker_no_data'))
        return

    try:
        # Используем общую функцию фильтрации
        joker_events_filtered, valid_groups_count = filter_stalled_events(df)

        if joker_events_filtered.empty:
            logger.warning(t('console.csv_joker_none_found'))
            return

        cols_to_save = ['TIME', 'RPM', 'MAF', 'SPEED', 'COOLANT_TEMP', 'ENGINE_LOAD', 'THROTTLE_POS', 'REGIME']
        cols_available = [col for col in cols_to_save if col in joker_events_filtered.columns]

        if len(cols_available) < 2:
            logger.warning(t('console.csv_joker_insufficient'))
            return

        joker_timeline = joker_events_filtered[cols_available].copy()
        joker_timeline['REASON'] = t('csv.joker.stalled_reason', rpm=int(STALLED_RPM_THRESHOLD))

        output_file = output_dir / f'{base_filename}_joker.csv'
        joker_timeline.to_csv(output_file, index=False, encoding='utf-8-sig')

        total_duration = len(joker_events_filtered) * LOG_DT

        logger.info(t('console.csv_joker_saved', path=output_file))
        logger.info(t('console.csv_joker_records', n=len(joker_events_filtered)))
        logger.info(t('console.csv_joker_groups', n=valid_groups_count))
        logger.info(t('console.csv_joker_duration', sec=total_duration, min=total_duration / 60))
    except (OSError, ValueError) as e:
        logger.error(t('console.csv_joker_error', e=e), exc_info=True)


def create_speed_profile(df: pd.DataFrame, output_dir: Path, base_filename: str) -> None:
    """Создаёт профиль скорости — статистику параметров по бинам скорости (каждые 5 км/ч).

    Args:
        df: DataFrame с колонкой 'SPEED'.
        output_dir: Директория для сохранения.
        base_filename: Базовое имя файла.
    """
    if 'SPEED' not in df.columns:
        logger.warning(t('console.csv_speed_no_data'))
        return

    try:
        speed_bins = list(range(0, 180, 5))
        df_temp = df.copy()
        df_temp['SPEED_BIN'] = pd.cut(df_temp['SPEED'], bins=speed_bins, include_lowest=True)
        profile_data = []

        for speed_range in df_temp['SPEED_BIN'].dropna().unique():
            bin_data = df_temp[df_temp['SPEED_BIN'] == speed_range]
            if len(bin_data) == 0:
                continue
            speed_min = speed_range.left
            speed_max = speed_range.right
            row = {
                t('csv.profile.speed_min'): speed_min,
                t('csv.profile.speed_max'): speed_max,
                t('csv.profile.rpm_mean'): bin_data['RPM'].mean() if 'RPM' in bin_data.columns else np.nan,
                t('csv.profile.fuel_mean'): bin_data['FUEL_CONSUMPTION'].mean() if 'FUEL_CONSUMPTION' in bin_data.columns else np.nan,
                t('csv.profile.load_mean'): bin_data['ENGINE_LOAD'].mean() if 'ENGINE_LOAD' in bin_data.columns else np.nan,
                t('csv.profile.spark_mean'): bin_data['SPARK_ADVANCE'].mean() if 'SPARK_ADVANCE' in bin_data.columns else np.nan,
                t('csv.profile.coolant_mean'): bin_data['COOLANT_TEMP'].mean() if 'COOLANT_TEMP' in bin_data.columns else np.nan,
                t('csv.profile.coolant_min'): bin_data['COOLANT_TEMP'].min() if 'COOLANT_TEMP' in bin_data.columns else np.nan,
                t('csv.profile.coolant_max'): bin_data['COOLANT_TEMP'].max() if 'COOLANT_TEMP' in bin_data.columns else np.nan,
                t('csv.profile.maf_mean'): bin_data['MAF'].mean() if 'MAF' in bin_data.columns else np.nan,
                t('csv.profile.injection_mean'): bin_data['INJECTION_TIME'].mean() if 'INJECTION_TIME' in bin_data.columns else np.nan,
                t('csv.profile.throttle_mean'): bin_data['THROTTLE_POS'].mean() if 'THROTTLE_POS' in bin_data.columns else np.nan,
                t('csv.profile.accel_mean'): bin_data['ACCEL_POS'].mean() if 'ACCEL_POS' in bin_data.columns else np.nan,
                t('csv.profile.intake_mean'): bin_data['INTAKE_TEMP'].mean() if 'INTAKE_TEMP' in bin_data.columns else np.nan,
                t('csv.profile.count'): len(bin_data)
            }
            profile_data.append(row)

        if len(profile_data) > 0:
            profile_df = pd.DataFrame(profile_data)
            profile_df = profile_df.sort_values(t('csv.profile.speed_min'))
            output_file = output_dir / f'{base_filename}_profile.csv'
            profile_df.to_csv(output_file, index=False, encoding='utf-8-sig')
            logger.info(t('console.csv_speed_saved', path=output_file))
        else:
            logger.warning(t('console.csv_speed_insufficient'))
    except (OSError, ValueError) as e:
        logger.error(t('console.csv_speed_error', e=e))


def _prepare_knock_groups_rows(
    groups_info: list[dict],
    kdf: pd.DataFrame,
) -> tuple[list[dict], list[int]]:
    """Формирует строки CSV для групп детонации и собирает индексы учтённых событий.

    Возвращает (rows, accounted_events_indices), где rows — список dict для DataFrame,
    accounted_events_indices — плоский список индексов событий из kdf.
    """
    rows = []
    accounted_events_indices = []
    new_group_id = 1

    for group_info in groups_info:
        s = group_info['start_idx']
        e = group_info['end_idx']
        g = kdf.iloc[s:e+1]

        accounted_events_indices.extend(range(s, e+1))

        row = {
            'GROUP_ID': new_group_id,
            'TIME_START': group_info['time_start'],
            'TIME_END': group_info['time_end'],
            'DURATION_SEC': round(group_info['duration'], 2),
            'EVENT_COUNT': group_info['event_count'],
            'MAX_RETARD': round(group_info['max_retard'], 2),
            'MEAN_RETARD': round(group_info['mean_retard'], 2),
            'INTENSITY': t(f'intensity.{group_info["final_severity"]}'),
        }

        if 'RPM' in kdf.columns:
            row['MAX_RPM'] = round(group_info['max_rpm'], 0)
        if 'SPEED' in kdf.columns:
            row['MAX_SPEED'] = round(group_info['max_speed'], 1)

        for col_src, col_out in [('RPM', 'RPM_MEAN'), ('SPEED', 'SPEED_MEAN'),
                                 ('ENGINE_LOAD', 'LOAD_MEAN'), ('SPARK_ADVANCE', 'SPARK_MEAN'),
                                 ('COOLANT_TEMP', 'COOLANT_MEAN')]:
            if col_src in g.columns:
                row[col_out] = round(g[col_src].mean(), 2)
            else:
                row[col_out] = None

        if 'ACCEL_POS' in g.columns:
            row['ACCEL_POS_MAX'] = round(g['ACCEL_POS'].max(), 2)
        else:
            row['ACCEL_POS_MAX'] = None

        if 'REGIME' in g.columns:
            regime_mode = g['REGIME'].mode()
            row['REGIME'] = regime_mode.iloc[0] if len(regime_mode) > 0 else 'UNKNOWN'

        rows.append(row)
        new_group_id += 1

    return rows, accounted_events_indices


def save_knock_groups(df: pd.DataFrame, output_dir: Path, base_filename: str,
                     max_gap_sec: float | None = None) -> tuple[pd.DataFrame, dict[int, int]] | None:
    """Группирует события детонации по времени и сохраняет статистику в CSV с учетом снисходительности.

    Использует classify_knock_groups_with_remission из core_obd для группировки и классификации.
    Неучтенные группы (final_severity='remitted') исключаются из результата.

    Args:
        df: DataFrame с колонками 'KNOCK_RETARD', 'TIME', опционально 'RPM', 'SPEED'.
        output_dir: Директория для сохранения.
        base_filename: Базовое имя файла.
        max_gap_sec: Макс. разрыв между событиями в группе (по умолчанию MAX_KNOCK_GROUP_GAP_SEC).

    Returns:
        (kdf_accounted, group_map) - только учтенные события с перенумерованными группами, None при ошибке.
    """
    if 'KNOCK_RETARD' not in df.columns or 'TIME' not in df.columns:
        logger.warning(t('console.csv_knock_groups_no_data'))
        return None

    try:
        # Используем общую функцию классификации из core
        groups_info = classify_knock_groups_with_remission(df, max_gap_sec)

        if not groups_info:
            logger.warning(t('console.csv_knock_groups_none'))
            return None

        # Фильтруем неучтенные группы
        total_groups = len(groups_info)
        accounted_groups = [g for g in groups_info if g['final_severity'] != 'remitted']
        remitted_count = total_groups - len(accounted_groups)

        if not accounted_groups:
            if remitted_count > 0:
                logger.warning(t('console.csv_knock_groups_all_remitted', n=total_groups))
            return None

        # Получаем kdf для доступа к полным данным
        kdf = df[df['KNOCK_RETARD'] > 0].copy()
        if 'TIME_SEC' not in kdf.columns:
            kdf['TIME_SEC'] = parse_time_to_seconds_vectorized(kdf['TIME'])
        kdf = kdf.dropna(subset=['TIME_SEC']).reset_index(drop=True)

        # Формируем CSV данные и собираем индексы учтенных событий
        rows, accounted_events_indices = _prepare_knock_groups_rows(accounted_groups, kdf)

        # Создаем новый DataFrame только с учтенными событиями
        kdf_accounted = kdf.iloc[accounted_events_indices].reset_index(drop=True)

        # Создаем group_map для учтенных событий с новыми номерами групп
        group_map = {}
        idx_offset = 0
        for group_id, row in enumerate(rows, start=1):
            event_count = row['EVENT_COUNT']
            for local_idx in range(event_count):
                group_map[idx_offset + local_idx] = group_id
            idx_offset += event_count

        out_df = pd.DataFrame(rows)
        out_file = output_dir / f'{base_filename}_knock_groups.csv'
        out_df.to_csv(out_file, index=False, encoding='utf-8-sig')
        logger.info(t('console.csv_knock_groups_saved', path=out_file))
        logger.info(t('console.csv_knock_groups_stats', total=total_groups, accounted=len(rows), remitted=remitted_count))
        return kdf_accounted, group_map
    except (OSError, ValueError, KeyError) as e:
        logger.error(t('console.csv_knock_groups_error', e=e), exc_info=True)
        return None


def save_knock_timeline(df: pd.DataFrame, output_dir: Path, base_filename: str,
                       kdf: pd.DataFrame | None = None, group_map: dict[int, int] | None = None) -> None:
    """Сохраняет хронологию событий детонации с параметрами двигателя в CSV.

    Args:
        df: DataFrame с колонками 'KNOCK_RETARD', 'TIME'.
        output_dir: Директория для сохранения.
        base_filename: Базовое имя файла.
        kdf: DataFrame с учтенными событиями из save_knock_groups (опционально).
        group_map: Маппинг индексов на GROUP_ID (опционально).
    """
    if 'KNOCK_RETARD' not in df.columns:
        logger.warning(t('console.csv_knock_no_retard'))
        return

    if 'TIME' not in df.columns:
        logger.warning(t('console.csv_knock_no_time'))
        return

    if kdf is None:
        knock_events = df[df['KNOCK_RETARD'] > 0].copy()
        if len(knock_events) == 0:
            logger.warning(t('console.csv_knock_none'))
            return
        kdf = knock_events.reset_index(drop=True)

    cols_to_save = ['TIME', 'KNOCK_RETARD', 'RPM', 'SPEED', 'ENGINE_LOAD', 'COOLANT_TEMP', 'SPARK_ADVANCE', 'ACCEL_POS', 'REGIME']
    cols_available = [col for col in cols_to_save if col in kdf.columns]

    if len(cols_available) < 2:
        logger.warning(t('console.csv_knock_insufficient'))
        return

    try:
        knock_timeline = kdf[cols_available].copy()

        def _intensity(x: float) -> str:
            if x <= KNOCK_WEAK_MAX:
                return t('intensity.weak')
            elif x <= KNOCK_MEDIUM_MAX:
                return t('intensity.medium')
            else:
                return t('intensity.strong')

        knock_timeline['INTENSITY'] = knock_timeline['KNOCK_RETARD'].apply(_intensity)

        if group_map is not None:
            knock_timeline['GROUP_ID'] = knock_timeline.index.map(lambda i: group_map.get(i, None))

        output_file = output_dir / f'{base_filename}_knock_timeline.csv'
        knock_timeline.to_csv(output_file, index=False, encoding='utf-8-sig')
        logger.info(t('console.csv_knock_saved', path=output_file))
    except OSError as e:
        logger.error(t('console.csv_knock_error', e=e))


def save_misfire_timeline(df: pd.DataFrame, output_dir: Path, base_filename: str) -> None:
    """Сохраняет хронологию пропусков зажигания с контекстом в CSV.

    Args:
        df: DataFrame с колонками MISFIRE_CYL1..4.
        output_dir: Директория для сохранения.
        base_filename: Базовое имя файла.
    """
    cylinders = ['MISFIRE_CYL1', 'MISFIRE_CYL2', 'MISFIRE_CYL3', 'MISFIRE_CYL4']

    available_cylinders = [cyl for cyl in cylinders if cyl in df.columns]
    if not available_cylinders:
        logger.warning(t('console.csv_misfire_no_data'))
        return

    misfire_mask = pd.Series([False] * len(df), index=df.index)
    for cyl_col in available_cylinders:
        misfire_mask = misfire_mask | (df[cyl_col] > 0)

    misfire_events = df[misfire_mask].copy()
    if len(misfire_events) == 0:
        logger.warning(t('console.csv_misfire_none'))
        return

    cols_to_save = ['TIME', 'REGIME'] + available_cylinders + ['RPM', 'SPEED', 'ENGINE_LOAD', 'COOLANT_TEMP']
    cols_available = [col for col in cols_to_save if col in misfire_events.columns]

    if not cols_available:
        logger.warning(t('console.csv_misfire_insufficient'))
        return

    try:
        misfire_timeline = misfire_events[cols_available].copy()
        output_file = output_dir / f'{base_filename}_misfire_timeline.csv'
        misfire_timeline.to_csv(output_file, index=False, encoding='utf-8-sig')
        logger.info(t('console.csv_misfire_saved', path=output_file))
    except OSError as e:
        logger.error(t('console.csv_misfire_error', e=e))
