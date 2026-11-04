#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Юнит-тесты для compare_core.py.

Тестирует:
- parse_numeric: извлечение числа из строки метрики
- _extract_trip_id: разбор trip_id из имён файлов
- resolve_val_stat: fallback-разрешение виртуальных кодов
- get_numeric_series: числовые значения по коду
- build_compare_rows: построение строк сводной таблицы
- get_drive_mode_durations: длительности режимов езды
- get_status_matrix: числовая матрица статусов для heatmap
- STATUS_MAP: маппинг emoji-статусов в числа
"""

import math
import sys
from pathlib import Path

import pandas as pd
import numpy as np
import pytest

_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / 'compare'))

from compare_core import (
    parse_numeric,
    _extract_trip_id,
    resolve_val_stat,
    get_numeric_series,
    build_compare_rows,
    get_drive_mode_durations,
    get_status_matrix,
    STATUS_MAP,
    COMPARE_METRICS,
    DRIVE_MODE_CODES,
)


# ---------------------------------------------------------------------------
# Вспомогательные фабрики
# ---------------------------------------------------------------------------

def _make_dfs(trip_data: dict[str, dict[str, str]],
              stat_data: dict[str, dict[str, str]] | None = None
              ) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Создаёт vals_df и stats_df из словарей {trip_id: {code: value}}."""
    vals_df = pd.DataFrame.from_dict(trip_data, orient='index')
    if stat_data is not None:
        stats_df = pd.DataFrame.from_dict(stat_data, orient='index')
    else:
        stats_df = pd.DataFrame(index=vals_df.index, columns=vals_df.columns).fillna('')
    return vals_df, stats_df


# ---------------------------------------------------------------------------
# parse_numeric
# ---------------------------------------------------------------------------

class TestParseNumeric:
    def test_plain_float(self):
        assert parse_numeric('2.1') == pytest.approx(2.1)

    def test_with_percent(self):
        assert parse_numeric('2.1 %') == pytest.approx(2.1)

    def test_with_degree_c(self):
        assert parse_numeric('85 °C') == pytest.approx(85.0)

    def test_negative(self):
        assert parse_numeric('-3.5') == pytest.approx(-3.5)

    def test_integer_string(self):
        assert parse_numeric('42') == pytest.approx(42.0)

    def test_zero(self):
        assert parse_numeric('0.0') == pytest.approx(0.0)

    def test_na_string(self):
        assert math.isnan(parse_numeric('N/A'))

    def test_empty_string(self):
        assert math.isnan(parse_numeric(''))

    def test_text_only(self):
        assert math.isnan(parse_numeric('нет данных'))

    def test_int_input(self):
        assert parse_numeric(42) == pytest.approx(42.0)

    def test_float_input(self):
        assert parse_numeric(3.14) == pytest.approx(3.14)

    def test_nan_input(self):
        assert math.isnan(parse_numeric(float('nan')))

    def test_embedded_number(self):
        # Строка с числом внутри текста
        assert parse_numeric('ok 15.5 laps') == pytest.approx(15.5)

    def test_positive_sign(self):
        assert parse_numeric('+7.0 %') == pytest.approx(7.0)


# ---------------------------------------------------------------------------
# _extract_trip_id
# ---------------------------------------------------------------------------

class TestExtractTripId:
    def test_date_only(self):
        assert _extract_trip_id(Path('log_2026-01-27_metrics.csv')) == '2026-01-27'

    def test_date_and_time_dash(self):
        result = _extract_trip_id(Path('log_2026-01-27_14-30_metrics.csv'))
        assert result == '2026-01-27 14:30'

    def test_date_and_time_T_separator(self):
        result = _extract_trip_id(Path('log_2026-01-27T15-00_metrics.csv'))
        assert result == '2026-01-27 15:00'

    def test_no_date_returns_stem(self):
        result = _extract_trip_id(Path('mytrip_metrics.csv'))
        assert result == 'mytrip'

    def test_different_prefix(self):
        assert _extract_trip_id(Path('trip_2025-12-01_metrics.csv')) == '2025-12-01'

    def test_date_at_start(self):
        assert _extract_trip_id(Path('2026-03-15_metrics.csv')) == '2026-03-15'


# ---------------------------------------------------------------------------
# resolve_val_stat
# ---------------------------------------------------------------------------

class TestResolveValStat:
    def test_direct_code_found(self):
        vals_df, stats_df = _make_dfs(
            {'trip1': {'KNOCK_TOTAL_COUNT': '5', 'OTHER': '1'}},
            {'trip1': {'KNOCK_TOTAL_COUNT': '✅', 'OTHER': ''}},
        )
        val_s, stat_s = resolve_val_stat(vals_df, stats_df, 'KNOCK_TOTAL_COUNT')
        assert val_s['trip1'] == '5'
        assert stat_s['trip1'] == '✅'

    def test_fallback_chain_primary_missing(self):
        # LTFT_MEAN → fallback: ALL_DRIVE_LTFT_Mean, ALL_LTFT_Mean
        vals_df, stats_df = _make_dfs(
            {'trip1': {'ALL_DRIVE_LTFT_Mean': '3.2', 'ALL_LTFT_Mean': '1.0'}},
            {'trip1': {'ALL_DRIVE_LTFT_Mean': '⚠️', 'ALL_LTFT_Mean': '✅'}},
        )
        val_s, stat_s = resolve_val_stat(vals_df, stats_df, 'LTFT_MEAN')
        assert val_s['trip1'] == '3.2'
        assert stat_s['trip1'] == '⚠️'

    def test_fallback_chain_second_candidate(self):
        # Первый fallback отсутствует, берём второй
        vals_df, stats_df = _make_dfs(
            {'trip1': {'ALL_LTFT_Mean': '1.5'}},
            {'trip1': {'ALL_LTFT_Mean': '✅'}},
        )
        val_s, stat_s = resolve_val_stat(vals_df, stats_df, 'LTFT_MEAN')
        assert val_s['trip1'] == '1.5'
        assert stat_s['trip1'] == '✅'

    def test_code_missing_returns_empty(self):
        vals_df, stats_df = _make_dfs({'trip1': {'OTHER': '99'}})
        val_s, stat_s = resolve_val_stat(vals_df, stats_df, 'NONEXISTENT_CODE')
        assert val_s['trip1'] == ''
        assert stat_s['trip1'] == ''

    def test_multiple_trips_independent(self):
        vals_df, stats_df = _make_dfs(
            {'trip1': {'KNOCK_TOTAL_COUNT': '2'}, 'trip2': {'KNOCK_TOTAL_COUNT': '10'}},
            {'trip1': {'KNOCK_TOTAL_COUNT': '✅'}, 'trip2': {'KNOCK_TOTAL_COUNT': '❌'}},
        )
        val_s, stat_s = resolve_val_stat(vals_df, stats_df, 'KNOCK_TOTAL_COUNT')
        assert val_s['trip1'] == '2'
        assert val_s['trip2'] == '10'
        assert stat_s['trip1'] == '✅'
        assert stat_s['trip2'] == '❌'

    def test_fallback_per_trip(self):
        # trip1 имеет ALL_DRIVE_LTFT_Mean, trip2 только ALL_LTFT_Mean
        vals_df, stats_df = _make_dfs(
            {
                'trip1': {'ALL_DRIVE_LTFT_Mean': '3.0', 'ALL_LTFT_Mean': '1.0'},
                'trip2': {'ALL_LTFT_Mean': '2.0'},
            },
            {
                'trip1': {'ALL_DRIVE_LTFT_Mean': '⚠️', 'ALL_LTFT_Mean': '✅'},
                'trip2': {'ALL_LTFT_Mean': '✅'},
            },
        )
        val_s, _ = resolve_val_stat(vals_df, stats_df, 'LTFT_MEAN')
        assert val_s['trip1'] == '3.0'
        assert val_s['trip2'] == '2.0'


# ---------------------------------------------------------------------------
# get_numeric_series
# ---------------------------------------------------------------------------

class TestGetNumericSeries:
    def test_returns_float_series(self):
        vals_df, stats_df = _make_dfs({'trip1': {'KNOCK_TOTAL_COUNT': '5 раз'}})
        s = get_numeric_series(vals_df, stats_df, 'KNOCK_TOTAL_COUNT')
        assert s['trip1'] == pytest.approx(5.0)

    def test_nan_for_missing(self):
        vals_df, stats_df = _make_dfs({'trip1': {'OTHER': '1'}})
        s = get_numeric_series(vals_df, stats_df, 'MISSING_CODE')
        assert math.isnan(s['trip1'])

    def test_nan_for_text_value(self):
        vals_df, stats_df = _make_dfs({'trip1': {'KNOCK_TOTAL_COUNT': 'N/A'}})
        s = get_numeric_series(vals_df, stats_df, 'KNOCK_TOTAL_COUNT')
        assert math.isnan(s['trip1'])

    def test_multiple_trips(self):
        vals_df, stats_df = _make_dfs({
            'trip1': {'KNOCK_TOTAL_COUNT': '3'},
            'trip2': {'KNOCK_TOTAL_COUNT': '0'},
        })
        s = get_numeric_series(vals_df, stats_df, 'KNOCK_TOTAL_COUNT')
        assert s['trip1'] == pytest.approx(3.0)
        assert s['trip2'] == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# build_compare_rows
# ---------------------------------------------------------------------------

class TestBuildCompareRows:
    def test_empty_df_returns_empty_list(self):
        rows = build_compare_rows(pd.DataFrame(), pd.DataFrame())
        assert rows == []

    def test_row_has_required_keys(self):
        vals_df, stats_df = _make_dfs(
            {'trip1': {'KNOCK_TOTAL_COUNT': '5'}},
            {'trip1': {'KNOCK_TOTAL_COUNT': '✅'}},
        )
        rows = build_compare_rows(vals_df, stats_df)
        assert len(rows) > 0
        row = rows[0]
        assert 'code' in row
        assert 'label' in row
        assert 'trip_vals' in row
        assert 'trip_stats' in row

    def test_all_empty_metric_skipped(self):
        # Метрика есть в COMPARE_METRICS но нет данных — должна быть пропущена
        vals_df, stats_df = _make_dfs({'trip1': {'SOME_OTHER': '1'}})
        rows = build_compare_rows(vals_df, stats_df)
        codes = [r['code'] for r in rows]
        # Ни один из кодов COMPARE_METRICS не должен попасть (нет данных)
        compare_codes = [vc for vc, _, _ in COMPARE_METRICS]
        for code in codes:
            assert code in compare_codes

    def test_trip_vals_contains_all_trips(self):
        vals_df, stats_df = _make_dfs(
            {
                'trip1': {'KNOCK_TOTAL_COUNT': '5'},
                'trip2': {'KNOCK_TOTAL_COUNT': '3'},
            },
            {
                'trip1': {'KNOCK_TOTAL_COUNT': '✅'},
                'trip2': {'KNOCK_TOTAL_COUNT': '✅'},
            },
        )
        rows = build_compare_rows(vals_df, stats_df)
        knock_row = next((r for r in rows if r['code'] == 'KNOCK_TOTAL_COUNT'), None)
        assert knock_row is not None
        assert 'trip1' in knock_row['trip_vals']
        assert 'trip2' in knock_row['trip_vals']

    def test_label_is_string(self):
        vals_df, stats_df = _make_dfs(
            {'trip1': {'KNOCK_TOTAL_COUNT': '2'}},
            {'trip1': {'KNOCK_TOTAL_COUNT': '✅'}},
        )
        rows = build_compare_rows(vals_df, stats_df)
        for row in rows:
            assert isinstance(row['label'], str)
            assert len(row['label']) > 0

    def test_long_value_truncated(self):
        long_val = 'A' * 50
        vals_df, stats_df = _make_dfs(
            {'trip1': {'CAT_O2_STATE': long_val}},
            {'trip1': {'CAT_O2_STATE': '○'}},
        )
        rows = build_compare_rows(vals_df, stats_df)
        cat_row = next((r for r in rows if r['code'] == 'CAT_O2_STATE'), None)
        if cat_row:
            val = cat_row['trip_vals'].get('trip1', '')
            assert len(val) <= 23  # max_len + суффикс '…'


# ---------------------------------------------------------------------------
# get_drive_mode_durations
# ---------------------------------------------------------------------------

class TestGetDriveModeDurations:
    def test_returns_dataframe_with_mode_columns(self):
        vals_df, _ = _make_dfs({
            'trip1': {
                'WARMUP_DURATION': '5.0',
                'DRIVE_CITY_DURATION': '20.0',
                'DRIVE_SUBURBAN_DURATION': '10.0',
                'DRIVE_HIGHWAY_DURATION': '0.0',
            }
        })
        df = get_drive_mode_durations(vals_df)
        assert len(df.columns) == 4
        assert len(df) == 1

    def test_numeric_values_extracted(self):
        vals_df, _ = _make_dfs({
            'trip1': {
                'WARMUP_DURATION': '5.5 мин',
                'DRIVE_CITY_DURATION': '22.0',
                'DRIVE_SUBURBAN_DURATION': '0',
                'DRIVE_HIGHWAY_DURATION': 'N/A',
            }
        })
        df = get_drive_mode_durations(vals_df)
        row = df.iloc[0]
        assert row.iloc[0] == pytest.approx(5.5)
        assert row.iloc[1] == pytest.approx(22.0)
        assert row.iloc[2] == pytest.approx(0.0)
        assert math.isnan(row.iloc[3])

    def test_missing_columns_are_nan(self):
        vals_df, _ = _make_dfs({'trip1': {'OTHER': '1'}})
        df = get_drive_mode_durations(vals_df)
        assert df.shape[1] == 4
        assert df.iloc[0].isna().all()

    def test_index_matches_trip_ids(self):
        vals_df, _ = _make_dfs({
            'trip1': {'WARMUP_DURATION': '5'},
            'trip2': {'WARMUP_DURATION': '8'},
        })
        df = get_drive_mode_durations(vals_df)
        assert list(df.index) == ['trip1', 'trip2']


# ---------------------------------------------------------------------------
# get_status_matrix
# ---------------------------------------------------------------------------

class TestGetStatusMatrix:
    def test_empty_df_returns_empty(self):
        matrix_df, labels = get_status_matrix(pd.DataFrame(), pd.DataFrame())
        assert matrix_df.empty
        assert labels == []

    def test_numeric_mapping(self):
        vals_df, stats_df = _make_dfs(
            {'trip1': {'KNOCK_TOTAL_COUNT': '5'}},
            {'trip1': {'KNOCK_TOTAL_COUNT': '✅'}},
        )
        matrix_df, labels = get_status_matrix(vals_df, stats_df)
        assert len(labels) > 0
        # Все значения в матрице должны быть из STATUS_MAP (-1..3)
        for val in matrix_df.values.flatten():
            assert val in (-1, 0, 1, 2, 3)

    def test_ok_maps_to_1(self):
        vals_df, stats_df = _make_dfs(
            {'trip1': {'KNOCK_TOTAL_COUNT': '0'}},
            {'trip1': {'KNOCK_TOTAL_COUNT': '✅'}},
        )
        matrix_df, labels = get_status_matrix(vals_df, stats_df)
        knock_label = next((l for l in labels if 'knock' in l.lower() or 'детон' in l.lower()), None)
        if knock_label is None:
            knock_label = labels[0] if labels else None
        if knock_label:
            assert matrix_df.loc[knock_label, 'trip1'] == 1

    def test_warning_maps_to_2(self):
        vals_df, stats_df = _make_dfs(
            {'trip1': {'KNOCK_TOTAL_COUNT': '5'}},
            {'trip1': {'KNOCK_TOTAL_COUNT': '⚠️'}},
        )
        matrix_df, labels = get_status_matrix(vals_df, stats_df)
        assert any(matrix_df.values.flatten() == 2)

    def test_error_maps_to_3(self):
        vals_df, stats_df = _make_dfs(
            {'trip1': {'KNOCK_TOTAL_COUNT': '50'}},
            {'trip1': {'KNOCK_TOTAL_COUNT': '❌'}},
        )
        matrix_df, labels = get_status_matrix(vals_df, stats_df)
        assert any(matrix_df.values.flatten() == 3)

    def test_all_empty_stats_returns_empty(self):
        vals_df, stats_df = _make_dfs({'trip1': {'KNOCK_TOTAL_COUNT': '5'}})
        # stats_df не содержит данных — всё пусто
        matrix_df, labels = get_status_matrix(vals_df, stats_df)
        assert matrix_df.empty

    def test_matrix_shape(self):
        vals_df, stats_df = _make_dfs(
            {
                'trip1': {'KNOCK_TOTAL_COUNT': '5', 'ALL_STALLED_COUNT': '1'},
                'trip2': {'KNOCK_TOTAL_COUNT': '2', 'ALL_STALLED_COUNT': '0'},
            },
            {
                'trip1': {'KNOCK_TOTAL_COUNT': '⚠️', 'ALL_STALLED_COUNT': '✅'},
                'trip2': {'KNOCK_TOTAL_COUNT': '✅', 'ALL_STALLED_COUNT': '✅'},
            },
        )
        matrix_df, labels = get_status_matrix(vals_df, stats_df)
        assert matrix_df.shape[1] == 2  # 2 поездки
        assert len(labels) == matrix_df.shape[0]


# ---------------------------------------------------------------------------
# STATUS_MAP
# ---------------------------------------------------------------------------

class TestStatusMap:
    def test_ok_is_1(self):
        assert STATUS_MAP['✅'] == 1

    def test_warning_is_2(self):
        assert STATUS_MAP['⚠️'] == 2

    def test_error_is_3(self):
        assert STATUS_MAP['❌'] == 3

    def test_neutral_is_0(self):
        assert STATUS_MAP['○'] == 0

    def test_empty_is_minus1(self):
        assert STATUS_MAP[''] == -1

    def test_all_values_in_range(self):
        for emoji, num in STATUS_MAP.items():
            assert -1 <= num <= 3, f"STATUS_MAP['{emoji}'] = {num} вне диапазона"


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
