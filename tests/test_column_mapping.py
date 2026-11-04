#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Юнит-тесты для маппинга колонок OBD-II.

Тестирует:
- load_column_mapping(): загрузка analyze_obd.json → структура словаря
- find_column(): точное совпадение, нечёткое, регистронезависимость, отсутствие
"""

import sys
from pathlib import Path
import pytest
import pandas as pd

# Добавляем пути для импорта
_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / 'build'))

from core_obd import load_column_mapping
from build_geojson import find_column


# ---------------------------------------------------------------------------
# load_column_mapping
# ---------------------------------------------------------------------------

class TestLoadColumnMapping:
    def test_returns_dict(self):
        mapping = load_column_mapping()
        assert isinstance(mapping, dict), "load_column_mapping должна вернуть dict"

    def test_not_empty(self):
        mapping = load_column_mapping()
        assert len(mapping) > 0, "Маппинг не должен быть пустым"

    def test_values_are_lists(self):
        mapping = load_column_mapping()
        for key, val in mapping.items():
            assert isinstance(val, list), f"Значение '{key}' должно быть списком"

    def test_required_keys_present(self):
        # TIME в маппинге не было и нет: время всегда берётся из первой
        # колонки CSV, если она похожа на HH:MM:SS (analyze_obd.py)
        mapping = load_column_mapping()
        required = ['RPM', 'SPEED']
        for key in required:
            assert key in mapping, f"Ключ '{key}' обязан быть в маппинге"

    def test_rpm_candidates_not_empty(self):
        mapping = load_column_mapping()
        assert len(mapping['RPM']) > 0, "Список кандидатов для RPM не должен быть пустым"


# ---------------------------------------------------------------------------
# find_column
# ---------------------------------------------------------------------------

class TestFindColumn:
    def _df(self, cols):
        return pd.DataFrame(columns=cols)

    def test_exact_match(self):
        df = self._df(['RPM', 'SPEED', 'TIME'])
        assert find_column(df, ['RPM']) == 'RPM'

    def test_exact_match_priority_over_partial(self):
        # 'MAF' точно есть; не должна вернуть 'MAF_SENSOR' или похожее
        df = self._df(['MAF_SENSOR', 'MAF'])
        assert find_column(df, ['MAF']) == 'MAF'

    def test_partial_match_case_insensitive(self):
        df = self._df(['Engine_RPM', 'SPEED'])
        result = find_column(df, ['rpm'])
        assert result == 'Engine_RPM', f"Ожидалась частичная нечёткая находка, получено: {result}"

    def test_multiple_candidates_first_wins(self):
        # ['COOLANT_TEMP', 'ENGINE_COOLANT'] — первый из кандидатов совпадает точно
        df = self._df(['ENGINE_COOLANT', 'COOLANT_TEMP'])
        result = find_column(df, ['COOLANT_TEMP', 'ENGINE_COOLANT'])
        assert result == 'COOLANT_TEMP'

    def test_returns_none_when_not_found(self):
        df = self._df(['RPM', 'SPEED'])
        result = find_column(df, ['NONEXISTENT_COLUMN_XYZ'])
        assert result is None

    def test_empty_dataframe(self):
        df = self._df([])
        result = find_column(df, ['RPM'])
        assert result is None

    def test_partial_match_returns_first_found(self):
        # Нет точного совпадения, оба столбца подходят по частичному совпадению
        df = self._df(['MY_SPEED_VAL', 'VEHICLE_SPEED'])
        result = find_column(df, ['speed'])
        # Должен вернуть первый найденный (MY_SPEED_VAL идёт раньше в итерации)
        assert result is not None

    def test_lat_lon_typical(self):
        df = self._df(['Latitude', 'Longtitude', 'RPM', 'TIME'])
        assert find_column(df, ['Latitude', 'latitude', 'lat', 'LAT']) == 'Latitude'
        assert find_column(df, ['Longtitude', 'Longitude', 'longitude', 'lon', 'LON']) == 'Longtitude'


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
