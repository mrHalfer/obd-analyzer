#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Тесты для core_obd.json:
- Наличие всех ожидаемых ключей.
- Корректные типы значений (числовые параметры, hex-цвета).
- Диапазонная логичность (min < max).
"""

import json
import re
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).parent.parent
_CONFIG_PATH = _ROOT / "core_obd.json"

with _CONFIG_PATH.open(encoding="utf-8") as _f:
    _CFG: dict = json.load(_f)

# ---------------------------------------------------------------------------
# Списки ожидаемых ключей
# ---------------------------------------------------------------------------

_NUMERIC_KEYS = [
    # 1. Базовые параметры
    "LOG_DT",
    "MIN_RPM_THRESHOLD",
    "MIN_MOVEMENT_DURATION_SEC",
    # 2. Заглохи
    "STALLED_RPM_THRESHOLD",
    "MAX_STALLED_DURATION_SEC",
    "MAX_STALLED_GROUP_GAP_SEC",
    "STALLED_COUNT_WARMUP_WARNING",
    "STALLED_COUNT_OTHER_WARNING",
    # 3. Детонация
    "MAX_KNOCK_GROUP_GAP_SEC",
    "KNOCK_WEAK_MAX",
    "KNOCK_MEDIUM_MAX",
    "KNOCK_STRONG_MIN",
    "KNOCK_WEAK_INTERVAL_MIN",
    "KNOCK_MEDIUM_INTERVAL_MIN",
    "KNOCK_WEAK_THRESHOLD_GOOD",
    "KNOCK_WEAK_THRESHOLD_BAD",
    "KNOCK_MEDIUM_THRESHOLD_GOOD",
    "KNOCK_MEDIUM_THRESHOLD_BAD",
    "KNOCK_STRONG_THRESHOLD_ATTENTION",
    "KNOCK_STRONG_THRESHOLD_BAD",
    "KNOCK_RETARD_TOLERANCE",
    "KNOCK_RETARD_MEAN_DIVISOR",
    "KNOCK_MAX_RPM_REMISSION",
    "KNOCK_MAX_SPEED_REMISSION",
    "KNOCK_MAX_RETARD_REMISSION",
    "KNOCK_DURATION_REMISSION",
    "KNOCK_COUNT_WARNING",
    "KNOCK_INTENSITY_WARNING",
    # 4. Топливные коррекции
    "CHART_FUEL_OK_LINE",
    "CHART_FUEL_WARN_LINE",
    "LTFT_PERCENTILE_LOW",
    "LTFT_PERCENTILE_HIGH",
    "LTFT_OK_MIN",
    "LTFT_OK_MAX",
    "LTFT_WARNING_MIN",
    "LTFT_WARNING_MAX",
    "SHORT_TERM_PERCENTILE_LOW",
    "SHORT_TERM_PERCENTILE_HIGH",
    "STFT_OK_MIN",
    "STFT_OK_MAX",
    "STFT_WARNING_MIN",
    "STFT_WARNING_MAX",
    # 5. Пороговые значения
    "COOLANT_TEMP_NORMAL_MIN",
    "COOLANT_TEMP_NORMAL_MAX",
    "COOLANT_TEMP_WARNING_MIN",
    "COOLANT_TEMP_WARNING_MAX",
    "COOLANT_TEMP_MAX_MIN",
    "COOLANT_TEMP_MAX_ERROR",
    "O2_RICH_THRESHOLD",
    "O2_LEAN_THRESHOLD",
    "O2_NORMAL_MIN",
    "O2_NORMAL_MAX",
    "O2_DK2_NORM_MIN",
    "O2_DK2_NORM_MAX",
    "MISFIRE_WARNING",
    "INJECTION_TIME_WARNING",
    "INJECTION_TIME_ERROR",
    "MAF_MIN_ERROR",
    "MAF_MIN_WARNING",
    "MAF_MAX_WARNING",
    "THROTTLE_MIN_WARNING",
    "THROTTLE_MAX_MIN",
    "THROTTLE_MAX_HIGH",
    # 6. Катализатор
    "CAT_MIN_WINDOWS",
    "CAT_WINDOW_SIZE",
    "CAT_MIN_STD1",
    "CAT_COOLANT_MIN",
    "CAT_RPM_MIN",
    "CAT_SPEED_MIN",
    "CAT_MAF_MIN",
    "CAT_MAF_MAX_STD",
    "CAT_AGING_BAD_VALUE",
    "CAT_AGING_WARN",
    "CAT_AGING_ERR",
    "CAT_PHYSICAL_GOOD_MAX_RATIO",
    "CAT_PHYSICAL_GOOD_MAX_CORR",
    "CAT_HARD_GOOD_RATIO",
    "CAT_HARD_GOOD_CORR",
    "CAT_HARD_WARN_RATIO",
    "CAT_HARD_WARN_CORR",
    "CAT_DK2_GOOD_STD",
    "CAT_DK2_WARN_STD",
    # 7. Охлаждение
    "COOLANT_FAN_ON_TEMP",
    "COOLANT_FAN_OFF_TEMP",
    "COOLANT_FAN_SPEED_THRESHOLD",
    "COOLANT_WARMUP_MIN_TEMP",
    "COOLANT_WARMUP_TARGET_TEMP",
    "COOLANT_WARMUP_MIN_RATE_GOOD",
    "COOLANT_WARMUP_MIN_RATE_WARN",
    "COOLANT_WARMUP_MAX_TIME_MIN",
    "COOLANT_THERMOSTAT_OPEN_TEMP",
    "COOLANT_THERMOSTAT_STABLE_TEMP_MIN",
    "COOLANT_THERMOSTAT_STABLE_TEMP_MAX",
    "COOLANT_THERMOSTAT_MIN_ANALYSIS_SEC",
    "COOLANT_THERMOSTAT_WINDOW_SEC",
    "COOLANT_THERMOSTAT_CHECK_SPEED_MIN",
    "COOLANT_THERMOSTAT_COOLING_RATE_MIN",
    "COOLANT_OVERHEAT_WARNING_TEMP",
    "COOLANT_OVERHEAT_ERROR_TEMP",
    "COOLANT_OVERHEAT_MIN_DURATION_SEC",
    # 8. GeoJSON
    "GEOJSON_DUPLICATE_DIST",
    "GEOJSON_MIN_DISTANCE",
    "GEOJSON_MAX_TURN_ANGLE",
]

_COLOR_KEYS = [
    "STATUS_COLOR_NO_DATA",
    "STATUS_COLOR_NEUTRAL",
    "STATUS_COLOR_OK",
    "STATUS_COLOR_WARNING",
    "STATUS_COLOR_ERROR",
    "STATUS_TEXT_OK",
    "STATUS_TEXT_WARNING",
    "STATUS_TEXT_ERROR",
    "STATUS_TEXT_NEUTRAL",
]

_HEX_COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{3}([0-9A-Fa-f]{3})?$")

# ---------------------------------------------------------------------------
# Тесты наличия ключей
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("key", _NUMERIC_KEYS)
def test_numeric_key_present(key: str) -> None:
    assert key in _CFG, f"Ожидаемый ключ '{key}' отсутствует в core_obd.json"


@pytest.mark.parametrize("key", _COLOR_KEYS)
def test_color_key_present(key: str) -> None:
    assert key in _CFG, f"Ожидаемый ключ цвета '{key}' отсутствует в core_obd.json"


# ---------------------------------------------------------------------------
# Тесты типов значений
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("key", _NUMERIC_KEYS)
def test_numeric_key_is_number(key: str) -> None:
    if key not in _CFG:
        pytest.skip(f"Ключ {key!r} отсутствует")
    assert isinstance(_CFG[key], (int, float)), (
        f"Ключ '{key}' должен быть числом, получено {type(_CFG[key]).__name__!r}"
    )


@pytest.mark.parametrize("key", _COLOR_KEYS)
def test_color_key_is_hex_string(key: str) -> None:
    if key not in _CFG:
        pytest.skip(f"Ключ {key!r} отсутствует")
    val = _CFG[key]
    assert isinstance(val, str), f"Ключ '{key}' должен быть строкой"
    assert _HEX_COLOR_RE.match(val), (
        f"Ключ '{key}' должен быть hex-цветом (#RGB или #RRGGBB), получено: {val!r}"
    )


# ---------------------------------------------------------------------------
# Тесты диапазонной логики: min < max
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("min_key, max_key", [
    ("LTFT_OK_MIN",              "LTFT_OK_MAX"),
    ("LTFT_WARNING_MIN",         "LTFT_WARNING_MAX"),
    ("STFT_OK_MIN",              "STFT_OK_MAX"),
    ("STFT_WARNING_MIN",         "STFT_WARNING_MAX"),
    ("COOLANT_TEMP_NORMAL_MIN",  "COOLANT_TEMP_NORMAL_MAX"),
    ("COOLANT_TEMP_WARNING_MIN", "COOLANT_TEMP_WARNING_MAX"),
    ("O2_NORMAL_MIN",            "O2_NORMAL_MAX"),
    ("O2_DK2_NORM_MIN",          "O2_DK2_NORM_MAX"),
    ("COOLANT_THERMOSTAT_STABLE_TEMP_MIN", "COOLANT_THERMOSTAT_STABLE_TEMP_MAX"),
    ("COOLANT_OVERHEAT_WARNING_TEMP",      "COOLANT_OVERHEAT_ERROR_TEMP"),
    ("COOLANT_FAN_OFF_TEMP",               "COOLANT_FAN_ON_TEMP"),
    ("CAT_AGING_WARN",                     "CAT_AGING_ERR"),
    ("KNOCK_WEAK_MAX",                     "KNOCK_MEDIUM_MAX"),
    ("INJECTION_TIME_WARNING",             "INJECTION_TIME_ERROR"),
    ("MAF_MIN_ERROR",                      "MAF_MIN_WARNING"),
])
def test_min_less_than_max(min_key: str, max_key: str) -> None:
    if min_key not in _CFG or max_key not in _CFG:
        pytest.skip(f"Один из ключей отсутствует: {min_key!r}, {max_key!r}")
    assert _CFG[min_key] < _CFG[max_key], (
        f"Ожидается {min_key} < {max_key}, "
        f"получено {_CFG[min_key]} >= {_CFG[max_key]}"
    )


# ---------------------------------------------------------------------------
# Тесты дополнительных инвариантов
# ---------------------------------------------------------------------------

def test_ltft_percentiles_in_0_1_range() -> None:
    assert 0.0 < _CFG["LTFT_PERCENTILE_LOW"] < _CFG["LTFT_PERCENTILE_HIGH"] < 1.0


def test_stft_percentiles_in_0_1_range() -> None:
    assert 0.0 < _CFG["SHORT_TERM_PERCENTILE_LOW"] < _CFG["SHORT_TERM_PERCENTILE_HIGH"] < 1.0


def test_o2_thresholds_in_sensor_range() -> None:
    assert 0.0 < _CFG["O2_LEAN_THRESHOLD"] < _CFG["O2_RICH_THRESHOLD"] < 1.0


def test_cat_aging_index_in_0_1() -> None:
    assert 0.0 <= _CFG["CAT_AGING_WARN"] < _CFG["CAT_AGING_ERR"] <= _CFG["CAT_AGING_BAD_VALUE"]


def test_log_dt_positive() -> None:
    assert _CFG["LOG_DT"] > 0


def test_rpm_thresholds_ordering() -> None:
    assert _CFG["STALLED_RPM_THRESHOLD"] < _CFG["MIN_RPM_THRESHOLD"]


def test_geojson_distance_positive() -> None:
    assert _CFG["GEOJSON_DUPLICATE_DIST"] > 0
    assert _CFG["GEOJSON_MIN_DISTANCE"] > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
