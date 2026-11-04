#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Модуль генерации GeoJSON из CSV логов OBD.

Фильтрация GPS-выбросов по внутреннему углу в средней точке треугольника:
  Берём тройку (N1, N2, N3), считаем внутренний угол в вершине N2.
    180° = прямое движение
     90° = поворот 90° (граница)
      0° = разворот / выброс

  Если угол >= GEOJSON_MAX_TURN_ANGLE -> N2 валидна, следующая тройка (N3, N4, N5)
  Если угол <  GEOJSON_MAX_TURN_ANGLE -> N2 выброс, УДАЛЯЕТСЯ, следующая тройка (N1, N3, N4)
"""

import json
import logging
import sys as _sys
from collections import defaultdict
from math import acos, asin, cos, degrees, radians, sin, sqrt
from pathlib import Path
from typing import Any

import pandas as pd

from pathlib import Path as _Path
_root = _Path(__file__).parent.parent
for _d in [str(_root), str(_root / 'build'), str(_root / 'plugins')]:
    if _d not in _sys.path:
        _sys.path.insert(0, _d)

from core_obd import (
    load_column_mapping,
    find_gps_columns,
    GEOJSON_DUPLICATE_DIST,
    GEOJSON_MIN_DISTANCE,
    GEOJSON_MAX_TURN_ANGLE,
    STALLED_RPM_THRESHOLD,
)
from translation import t

logger = logging.getLogger(__name__)


def find_column(df: pd.DataFrame, possible_names: list[str]) -> str | None:
    """Ищет колонку в DataFrame по точному имени или нечёткому совпадению (без учёта регистра).

    Приоритет: точное совпадение > первое частичное совпадение по любому из имён-кандидатов.

    Args:
        df: DataFrame с колонками для поиска.
        possible_names: Список кандидатов в порядке убывания приоритета.

    Returns:
        Имя найденной колонки или None, если совпадений нет.
    """
    partial_match = None
    for name in possible_names:
        if name in df.columns:
            return name
        if partial_match is None:
            name_lower = name.lower()
            for col in df.columns:
                if name_lower in col.lower():
                    partial_match = col
                    break
    return partial_match


def _haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Возвращает расстояние между двумя точками на сфере (в метрах) по формуле Гаверсинуса.

    Args:
        lat1, lon1: Широта и долгота первой точки (градусы).
        lat2, lon2: Широта и долгота второй точки (градусы).

    Returns:
        Расстояние в метрах.
    """
    lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = sin(dlat / 2)**2 + cos(lat1) * cos(lat2) * sin(dlon / 2)**2
    return 2 * asin(sqrt(a)) * 6371000


def _inner_angle_at_b(x1: float, y1: float, x2: float, y2: float, x3: float, y3: float) -> float:
    """
    Внутренний угол в вершине B(x2,y2) треугольника A-B-C.
    Векторы из B: BA = A-B, BC = C-B
    180° = прямое движение, 90° = поворот 90°, 0° = разворот/выброс
    """
    bax, bay = x1 - x2, y1 - y2
    bcx, bcy = x3 - x2, y3 - y2
    len_ba = sqrt(bax**2 + bay**2)
    len_bc = sqrt(bcx**2 + bcy**2)
    if len_ba == 0 or len_bc == 0:
        return 0.0
    cos_theta = (bax * bcx + bay * bcy) / (len_ba * len_bc)
    cos_theta = max(-1.0, min(1.0, cos_theta))
    return degrees(acos(cos_theta))


def _group_by_coordinates(df: pd.DataFrame, lat_col: str, lon_col: str, min_distance: float = 0.5) -> list[list[int]]:
    """Разбивает последовательные строки на группы по близости GPS-координат.

    Последовательные строки попадают в одну группу, пока расстояние между ними < min_distance м.
    Новая группа начинается, когда расстояние превышает порог (движение / смена позиции).

    Args:
        df: DataFrame с координатными колонками.
        lat_col: Имя колонки широты.
        lon_col: Имя колонки долготы.
        min_distance: Порог расстояния в метрах (по умолчанию 0.5 м).

    Returns:
        Список групп — каждая группа это список индексов строк df.
    """
    if len(df) == 0:
        return []
    groups = []
    current_group = [0]
    for i in range(1, len(df)):
        lat1, lon1 = df.iloc[i - 1][lat_col], df.iloc[i - 1][lon_col]
        lat2, lon2 = df.iloc[i][lat_col], df.iloc[i][lon_col]
        if _haversine_distance(lat1, lon1, lat2, lon2) < min_distance:
            current_group.append(i)
        else:
            groups.append(current_group)
            current_group = [i]
    if current_group:
        groups.append(current_group)
    return groups


def _aggregate_group(df: pd.DataFrame, indices: list[int], lat_col: str, lon_col: str, value_cols_map: dict[str, str]) -> dict[str, Any]:
    """Агрегирует группу строк в одну запись с усреднёнными координатами и OBD-статистиками.

    Для числовых OBD-параметров вычисляет _mean, _min, _max, _first, _last.
    Для нечисловых — только _first и _last как строки.

    Args:
        df: Исходный DataFrame.
        indices: Индексы строк, входящих в группу.
        lat_col: Имя колонки широты.
        lon_col: Имя колонки долготы.
        value_cols_map: Словарь {короткое_имя: реальная_колонка} для OBD-параметров.

    Returns:
        Словарь с ключами "lat", "lon", "count", "values".
    """
    group_df = df.iloc[indices]
    result = {
        "lat": group_df[lat_col].mean(),
        "lon": group_df[lon_col].mean(),
        "count": len(indices),
        "values": {},
    }
    for short_name, actual_col in value_cols_map.items():
        if actual_col not in group_df.columns:
            continue
        values = group_df[actual_col].dropna()
        if len(values) == 0:
            continue
        try:
            nums = pd.to_numeric(values, errors="coerce").dropna()
            if len(nums) > 0:
                result["values"][f"{short_name}_mean"]  = round(float(nums.mean()),   2)
                result["values"][f"{short_name}_min"]   = round(float(nums.min()),    2)
                result["values"][f"{short_name}_max"]   = round(float(nums.max()),    2)
                result["values"][f"{short_name}_first"] = round(float(nums.iloc[0]),  2)
                result["values"][f"{short_name}_last"]  = round(float(nums.iloc[-1]), 2)
            else:
                result["values"][f"{short_name}_first"] = str(values.iloc[0])
                result["values"][f"{short_name}_last"]  = str(values.iloc[-1])
        except (ValueError, TypeError):
            result["values"][f"{short_name}_first"] = str(values.iloc[0])
            result["values"][f"{short_name}_last"]  = str(values.iloc[-1])
    return result


def _create_aggregated_dataframe(df: pd.DataFrame, groups: list[list[int]], lat_col: str, lon_col: str, value_cols_map: dict[str, str]) -> pd.DataFrame:
    """Создаёт DataFrame агрегированных GPS-точек из списка групп индексов.

    Args:
        df: Исходный DataFrame.
        groups: Список групп индексов (результат _group_by_coordinates).
        lat_col: Имя колонки широты.
        lon_col: Имя колонки долготы.
        value_cols_map: Словарь {короткое_имя: реальная_колонка}.

    Returns:
        DataFrame с одной строкой на группу и колонкой group_size.
    """
    rows = []
    for group_indices in groups:
        agg = _aggregate_group(df, group_indices, lat_col, lon_col, value_cols_map)
        row = {lat_col: agg["lat"], lon_col: agg["lon"], "group_size": agg["count"]}
        row.update(agg["values"])
        rows.append(row)
    return pd.DataFrame(rows)


def _filter_gps_outliers(df: pd.DataFrame, lat_col: str, lon_col: str, max_turn_angle: float = 90.0) -> tuple[pd.DataFrame, int]:
    """
    Удаляет GPS-выбросы по внутреннему углу в средней точке.

    Алгоритм:
      n1 — последняя валидная точка (база)
      n2 — кандидат (проверяем угол в ней)
      n3 — следующая точка

      Если угол в n2 >= max_turn_angle:
          n2 ВАЛИДНА — добавляем в valid
          следующая тройка: (n3, n4, n5) — n3 становится новой базой

      Если угол в n2 < max_turn_angle:
          n2 ВЫБРОС — НЕ добавляем
          n1 остаётся, следующая тройка: (n1, n3, n4)

    Первая и последняя точки всегда включаются.
    """
    n = len(df)
    if n < 3:
        return df, 0

    valid_indices = [0]
    removed_count = 0

    n1_idx = 0
    n2_idx = 1

    while n2_idx < n - 1:
        n3_idx = n2_idx + 1

        lat1, lon1 = df.iloc[n1_idx][lat_col], df.iloc[n1_idx][lon_col]
        lat2, lon2 = df.iloc[n2_idx][lat_col], df.iloc[n2_idx][lon_col]
        lat3, lon3 = df.iloc[n3_idx][lat_col], df.iloc[n3_idx][lon_col]

        angle = _inner_angle_at_b(lon1, lat1, lon2, lat2, lon3, lat3)

        if angle >= max_turn_angle:
            # n2 валидна — добавляем, n2 становится новой базой
            valid_indices.append(n2_idx)
            n1_idx = n2_idx
            n2_idx = n3_idx
        else:
            # n2 выброс — пропускаем
            removed_count += 1
            n2_idx = n3_idx

    # Последнюю точку всегда добавляем
    if valid_indices[-1] != n - 1:
        valid_indices.append(n - 1)

    df_filtered = df.iloc[valid_indices].reset_index(drop=True)
    return df_filtered, removed_count


def _find_stall_gps_points(
    df_gps: pd.DataFrame,
    rpm_col: str,
    lat_col: str,
    lon_col: str,
    time_col: str | None,
) -> list[dict]:
    """Находит GPS-точки событий заглохов (RPM упал ниже порога после работы двигателя).

    Каждое событие — первая строка группы последовательных строк с RPM < порога,
    которой предшествует работающий двигатель и после которой двигатель запускается снова.

    Args:
        df_gps: DataFrame с GPS-координатами (уже фильтрован по ненулевым lat/lon).
        rpm_col: Имя колонки RPM.
        lat_col: Имя колонки широты.
        lon_col: Имя колонки долготы.
        time_col: Имя колонки времени (или None).

    Returns:
        Список словарей {lat, lon, time, rpm} для каждого события заглоха.
    """
    if rpm_col not in df_gps.columns:
        return []

    # Используем только строки с реальным (не-NaN) значением RPM.
    # fillna(0) на GPS-строках без RPM создаёт ложные «заглохи».
    rpm_raw = pd.to_numeric(df_gps[rpm_col], errors='coerce')
    df_gps = df_gps[rpm_raw.notna()].reset_index(drop=True)
    if df_gps.empty:
        return []
    rpm = pd.to_numeric(df_gps[rpm_col], errors='coerce').fillna(0)
    stall_mask = rpm < STALLED_RPM_THRESHOLD

    points: list[dict] = []
    i = 0
    n = len(df_gps)
    while i < n:
        if stall_mask.iloc[i]:
            group_start = i
            while i < n and stall_mask.iloc[i]:
                i += 1
            group_end = i - 1

            # Двигатель должен был работать до заглоха
            if group_start == 0 or not (rpm.iloc[:group_start] >= STALLED_RPM_THRESHOLD).any():
                continue
            # Двигатель должен запуститься снова (не конец поездки)
            if group_end + 1 >= n or not (rpm.iloc[group_end + 1:] >= STALLED_RPM_THRESHOLD).any():
                continue

            row = df_gps.iloc[group_start]
            lat = row[lat_col]
            lon = row[lon_col]
            if pd.isna(lat) or pd.isna(lon):
                continue

            time_val = None
            if time_col and time_col in df_gps.columns:
                v = row[time_col]
                if pd.notna(v):
                    time_val = str(v).split('.')[0]

            points.append({
                'lat': float(lat),
                'lon': float(lon),
                'time': time_val,
                'rpm': round(float(rpm.iloc[group_start]), 1),
            })
        else:
            i += 1

    return points


def _find_error_count_gps_points(
    df_gps: pd.DataFrame,
    error_col: str,
    lat_col: str,
    lon_col: str,
    time_col: str | None,
) -> list[dict]:
    """Находит GPS-точки, в которых количество ошибок (DTC) увеличилось.

    Работает корректно с разреженными логами (VAG и аналогичные), где
    ERROR_COUNT заполняется не в каждой строке: анализируются только строки
    с ненулевым значением, разность между последовательными такими строками
    определяет момент появления новых кодов.

    Args:
        df_gps: DataFrame, отфильтрованный по ненулевым GPS-координатам.
        error_col: Имя колонки количества ошибок.
        lat_col: Имя колонки широты.
        lon_col: Имя колонки долготы.
        time_col: Имя колонки времени (или None).

    Returns:
        Список словарей {lat, lon, time, error_count, delta} для каждого
        момента увеличения счётчика ошибок.
    """
    if error_col not in df_gps.columns:
        return []

    # Разреженные логи: ERROR_COUNT присутствует не в каждой строке с GPS.
    # Фильтруем только строки, где значение реально записано.
    err_raw = pd.to_numeric(df_gps[error_col], errors='coerce')
    df_err = df_gps[err_raw.notna()].copy()
    if len(df_err) < 2:
        return []

    err = pd.to_numeric(df_err[error_col], errors='coerce').fillna(0)

    points: list[dict] = []
    for i in range(1, len(df_err)):
        prev_val = err.iloc[i - 1]
        curr_val = err.iloc[i]
        if curr_val <= prev_val:
            continue

        row = df_err.iloc[i]
        lat = row[lat_col]
        lon = row[lon_col]
        if pd.isna(lat) or pd.isna(lon):
            continue

        time_val = None
        if time_col and time_col in df_err.columns:
            v = row[time_col]
            if pd.notna(v):
                time_val = str(v).split('.')[0]

        points.append({
            'lat': float(lat),
            'lon': float(lon),
            'time': time_val,
            'error_count': int(curr_val),
            'delta': int(curr_val - prev_val),
        })

    return points


def _step1_load_and_filter(
    input_csv: str | Path,
    column_mapping: dict[str, list[str]],
) -> tuple[pd.DataFrame, pd.DataFrame, str, str, dict[str, str]] | None:
    """Шаг 1: Загрузка CSV, поиск GPS-колонок, фильтрация по RPM.

    Returns:
        (df_valid, df_gps_all, lat_col, lon_col, value_cols_map) или None при ошибке.
        df_gps_all — строки с GPS до фильтрации по RPM (нужен для поиска заглохов).
    """
    logger.info(t('console.geojson_reading_csv', path=input_csv))
    try:
        df = pd.read_csv(input_csv)
    except (pd.errors.ParserError, UnicodeDecodeError, OSError) as e:
        logger.error(t('console.geojson_csv_error', e=e))
        return None

    logger.debug(t('console.geojson_total_rows', n=len(df)))

    lat_col, lon_col = find_gps_columns(df)
    if lat_col is None or lon_col is None:
        logger.warning(t('console.geojson_no_gps_cols'))
        return None

    logger.debug(t('console.geojson_gps_cols', lat=lat_col, lon=lon_col))

    df_gps_all = df.dropna(subset=[lat_col, lon_col]).copy()
    df_valid = df_gps_all.copy()
    logger.debug(t('console.geojson_gps_rows', n=len(df_valid)))

    rpm_col = find_column(df_valid, column_mapping.get("RPM", []))
    if rpm_col is not None:
        logger.info(t('console.geojson_step1'))
        rows_before = len(df_valid)
        df_valid = df_valid[(df_valid[rpm_col].notna()) & (df_valid[rpm_col] > 0)].copy()
        logger.debug(t('console.geojson_step1_removed', n=rows_before - len(df_valid)))
        logger.debug(t('console.geojson_step1_remaining', n=len(df_valid)))
        if len(df_valid) == 0:
            logger.warning(t('console.geojson_step1_empty'))
            return None

    df_valid = df_valid.reset_index(drop=True)

    value_cols_map = {}
    for short_name, possible_names in column_mapping.items():
        actual_col = find_column(df_valid, possible_names)
        if actual_col:
            value_cols_map[short_name] = actual_col

    return df_valid, df_gps_all, lat_col, lon_col, value_cols_map


def _step2_aggregate_duplicates(df_valid: pd.DataFrame, lat_col: str, lon_col: str, value_cols_map: dict[str, str]) -> tuple[pd.DataFrame, pd.DataFrame] | None:
    """Шаг 2: Объединение почти идентичных GPS-точек (стоянка, светофор).

    Точки ближе GEOJSON_DUPLICATE_DIST м агрегируются в одну.
    Сохраняется копия до фильтрации выбросов: данные OBD удалённых точек
    позже будут переданы ближайшей выжившей.

    Returns:
        (df_agg, df_agg_full) или None если точек недостаточно.
    """
    logger.info(t('console.geojson_step2', dist=GEOJSON_DUPLICATE_DIST))
    groups = _group_by_coordinates(df_valid, lat_col, lon_col, min_distance=GEOJSON_DUPLICATE_DIST)
    logger.debug(t('console.geojson_step2_before', n=len(df_valid)))
    df_agg = _create_aggregated_dataframe(df_valid, groups, lat_col, lon_col, value_cols_map)
    logger.debug(t('console.geojson_step2_after', n=len(df_agg)))

    if len(df_agg) < 3:
        logger.warning(t('console.geojson_step2_insufficient'))
        return None

    df_agg_full = df_agg.copy()          # сохраняем ДО удаления выбросов
    df_agg["__orig_idx"] = range(len(df_agg))
    return df_agg, df_agg_full


def _step3_filter_outliers(df_agg: pd.DataFrame, df_agg_full: pd.DataFrame, lat_col: str, lon_col: str, max_turn_angle: float) -> tuple[pd.DataFrame, defaultdict[int, list[int]], list[str]] | None:
    """Шаг 3: Итеративное удаление GPS-выбросов по внутреннему углу.

    Одного прохода недостаточно: точка принята по углу (prev→curr→next),
    но после удаления next угол (prev→curr→next2) может оказаться острым.
    Повторяем до стабилизации.

    Строит маппинг survivor_full_rows: выжившая точка → список строк df_agg_full,
    включая поглощённые выбросы, чтобы их OBD-данные не терялись.

    Returns:
        (df_agg_filtered, survivor_full_rows, prop_cols) или None при ошибке.
    """
    logger.info(t('console.geojson_step3', angle=max_turn_angle))
    total_removed = 0
    for pass_num in range(1, 50):
        df_agg, removed = _filter_gps_outliers(df_agg, lat_col, lon_col, max_turn_angle)
        total_removed += removed
        logger.debug(t('console.geojson_step3_pass', pass_num=pass_num, removed=removed, remaining=len(df_agg)))
        if removed == 0:
            break
    logger.debug(t('console.geojson_step3_total', n=total_removed))

    if len(df_agg) < 2:
        logger.warning(t('console.geojson_step3_insufficient'))
        return None

    # Каждая удалённая строка df_agg_full приписывается к следующей выжившей точке
    surviving_orig = sorted(df_agg["__orig_idx"].tolist())
    N_full = len(df_agg_full)
    row_to_survivor = {}
    surv_pos = 0
    for i in range(N_full):
        while surv_pos < len(surviving_orig) - 1 and surviving_orig[surv_pos] < i:
            surv_pos += 1
        row_to_survivor[i] = surviving_orig[surv_pos]

    survivor_full_rows = defaultdict(list)
    for i in range(N_full):
        survivor_full_rows[row_to_survivor[i]].append(i)

    prop_cols = [c for c in df_agg_full.columns
                 if c not in (lat_col, lon_col, "group_size", "__orig_idx")]

    return df_agg, survivor_full_rows, prop_cols


def _step4_build_final_points(df_agg: pd.DataFrame, df_agg_full: pd.DataFrame,
                               survivor_full_rows: defaultdict[int, list[int]],
                               lat_col: str, lon_col: str, prop_cols: list[str],
                               min_distance: float, max_turn_angle: float) -> list[dict]:
    """Шаги 4+5: Финальная группировка, повторная фильтрация и вычисление OBD-характеристик.

    Шаг 4: точки ближе min_distance м объединяются в финальные сегменты.
    Шаг 5: усреднение координат в шаге 4 может создать новые острые углы —
            повторяем фильтрацию по углу, передавая full_rows удалённых точек вперёд.
    Затем вычисляем OBD-характеристики каждого сегмента из всех накопленных строк.

    Returns:
        Список финальных точек с полями lat, lon, count, values.
    """
    logger.debug(t('console.geojson_step4', dist=min_distance))
    final_groups = _group_by_coordinates(df_agg, lat_col, lon_col, min_distance)
    final_points = []
    for group_indices in final_groups:
        group_df = df_agg.iloc[group_indices]
        full_rows = []
        for orig_idx in group_df["__orig_idx"].tolist():
            full_rows.extend(survivor_full_rows[orig_idx])
        final_points.append({
            "lat": float(group_df[lat_col].mean()),
            "lon": float(group_df[lon_col].mean()),
            "full_rows": sorted(set(full_rows)),
        })
    logger.debug(t('console.geojson_step4_count', n=len(final_points)))

    # Шаг 5: повторная фильтрация после усреднения координат
    if len(final_points) >= 3:
        tmp_df = pd.DataFrame({
            "__fp_idx": range(len(final_points)),
            lat_col: [p["lat"] for p in final_points],
            lon_col: [p["lon"] for p in final_points],
        })
        extra_removed = 0
        for _ in range(50):
            tmp_df, removed = _filter_gps_outliers(tmp_df, lat_col, lon_col, max_turn_angle)
            extra_removed += removed
            if removed == 0:
                break
        if extra_removed > 0:
            logger.debug(t('console.geojson_step4_extra', n=extra_removed))

        surviving_fp = tmp_df["__fp_idx"].tolist()
        surviving_fp_set = set(surviving_fp)
        fp_full_rows = {i: list(final_points[i]["full_rows"]) for i in range(len(final_points))}
        for removed_fp in sorted(set(range(len(final_points))) - surviving_fp_set):
            next_fp = next((s for s in surviving_fp if s > removed_fp), surviving_fp[-1])
            fp_full_rows[next_fp].extend(final_points[removed_fp]["full_rows"])
        final_points = [
            {"lat": final_points[i]["lat"], "lon": final_points[i]["lon"],
             "full_rows": sorted(set(fp_full_rows[i]))}
            for i in surviving_fp
        ]

    logger.debug(t('console.geojson_step4_final', n=len(final_points)))

    # Вычисляем OBD-характеристики: _min/_max по всем строкам; _mean — взвешенное по group_size
    for fp in final_points:
        rows_df = df_agg_full.iloc[fp["full_rows"]]
        sizes = pd.to_numeric(rows_df.get("group_size", pd.Series([1] * len(rows_df))),
                              errors="coerce").fillna(1)
        fp["count"] = int(sizes.sum())
        values = {}
        for col in prop_cols:
            col_vals = pd.to_numeric(rows_df[col], errors="coerce")
            valid = col_vals.dropna()
            if valid.empty:
                # Нечисловой столбец (например, TIME_first/TIME_last)
                str_vals = rows_df[col].dropna()
                if not str_vals.empty:
                    values[col] = str(str_vals.iloc[-1] if col.endswith("_last") else str_vals.iloc[0])
                continue
            if col.endswith("_min"):
                values[col] = round(float(valid.min()), 2)
            elif col.endswith("_max"):
                values[col] = round(float(valid.max()), 2)
            elif col.endswith("_mean"):
                w = sizes[valid.index]
                values[col] = round(float((valid * w).sum() / w.sum()), 2)
            elif col.endswith("_first"):
                values[col] = round(float(valid.iloc[0]), 2)
            elif col.endswith("_last"):
                values[col] = round(float(valid.iloc[-1]), 2)
            else:
                values[col] = round(float(valid.mean()), 2)
        fp["values"] = values

    return final_points


def generate_geojson(input_csv: str | Path, output_geojson: str | Path | None = None,
                     min_distance: float = GEOJSON_MIN_DISTANCE,
                     max_turn_angle: float = GEOJSON_MAX_TURN_ANGLE) -> Path | None:
    """Генерирует GeoJSON маршрута из CSV лога OBD.

    Args:
        input_csv: Путь к исходному CSV файлу.
        output_geojson: Путь к выходному файлу (по умолчанию рядом с CSV).
        min_distance: Мин. расстояние между итоговыми точками (м).
        max_turn_angle: Мин. допустимый угол в вершине N2 (°); меньше — выброс.

    Returns:
        Путь к записанному файлу или None при ошибке.
    """
    if output_geojson is None:
        output_geojson = Path(input_csv).with_suffix(".geojson")

    column_mapping = load_column_mapping()
    if not column_mapping:
        return None

    result = _step1_load_and_filter(input_csv, column_mapping)
    if result is None:
        return None
    df_valid, df_gps_all, lat_col, lon_col, value_cols_map = result

    result = _step2_aggregate_duplicates(df_valid, lat_col, lon_col, value_cols_map)
    if result is None:
        return None
    df_agg, df_agg_full = result

    result = _step3_filter_outliers(df_agg, df_agg_full, lat_col, lon_col, max_turn_angle)
    if result is None:
        return None
    df_agg, survivor_full_rows, prop_cols = result

    final_points = _step4_build_final_points(
        df_agg, df_agg_full, survivor_full_rows,
        lat_col, lon_col, prop_cols, min_distance, max_turn_angle,
    )

    geojson = {"type": "FeatureCollection", "features": []}
    for i in range(len(final_points) - 1):
        p1, p2 = final_points[i], final_points[i + 1]
        properties = p2["values"].copy()
        properties["points_in_group"] = p2["count"]
        geojson["features"].append({
            "type": "Feature",
            "geometry": {"type": "LineString", "coordinates": [[p1["lon"], p1["lat"]], [p2["lon"], p2["lat"]]]},
            "properties": properties,
        })

    # Добавляем точки заглохов
    rpm_col = find_column(df_gps_all, column_mapping.get("RPM", []))
    time_col = find_column(df_gps_all, column_mapping.get("TIME", []))
    if rpm_col is not None:
        stall_points = _find_stall_gps_points(df_gps_all, rpm_col, lat_col, lon_col, time_col)
        for sp in stall_points:
            props: dict = {"event_type": "stall"}
            if sp["time"] is not None:
                props["time"] = sp["time"]
            if sp["rpm"] is not None:
                props["rpm"] = sp["rpm"]
            geojson["features"].append({
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [sp["lon"], sp["lat"]]},
                "properties": props,
            })
        if stall_points:
            logger.info(f'GeoJSON: добавлено {len(stall_points)} точек заглохов')

    # Добавляем точки увеличения счётчика ошибок (DTC)
    error_col = find_column(df_gps_all, column_mapping.get("ERROR_COUNT", []))
    if error_col is not None:
        error_points = _find_error_count_gps_points(df_gps_all, error_col, lat_col, lon_col, time_col)
        for ep in error_points:
            props: dict = {
                "event_type": "dtc_increase",
                "error_count": ep["error_count"],
                "delta": ep["delta"],
            }
            if ep["time"] is not None:
                props["time"] = ep["time"]
            geojson["features"].append({
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [ep["lon"], ep["lat"]]},
                "properties": props,
            })
        if error_points:
            logger.info(f'GeoJSON: добавлено {len(error_points)} точек увеличения ошибок DTC')

    try:
        with open(output_geojson, "w", encoding="utf-8") as f:
            json.dump(geojson, f, ensure_ascii=False, indent=2)
    except OSError as e:
        logger.error(t('console.geojson_write_error', e=e))
        return None

    logger.info(t('console.geojson_saved', path=output_geojson))
    logger.info(t('console.geojson_segments', n=len(geojson["features"])))
    return output_geojson
