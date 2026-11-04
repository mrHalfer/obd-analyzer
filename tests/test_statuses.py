#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Юнит-тесты для расчёта статусов параметров OBD-II.

Тестирует get_status():
- LTFT/STFT: диапазонные статусы (OK / WARNING / ERROR)
- Температура ОЖ: статус по превышению порога
- PRE_START режим → NEUTRAL для всех параметров
- NaN значение → NEUTRAL
- Неизвестный параметр → NEUTRAL
"""

import math
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "build"))

from core_obd import (
    LTFT_OK_MAX,
    LTFT_OK_MIN,
    LTFT_WARNING_MAX,
    LTFT_WARNING_MIN,
    STATUS_ERROR,
    STATUS_NEUTRAL,
    STATUS_OK,
    STATUS_WARNING,
    STFT_OK_MAX,
    STFT_OK_MIN,
    STFT_WARNING_MAX,
    STFT_WARNING_MIN,
    get_status,
)

# ---------------------------------------------------------------------------
# LTFT
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("value, expected", [
    (0.0,                                          STATUS_OK),
    (float(LTFT_OK_MAX),                           STATUS_OK),
    (float(LTFT_OK_MIN),                           STATUS_OK),
    ((LTFT_OK_MAX + LTFT_WARNING_MAX) / 2,         STATUS_WARNING),
    ((LTFT_OK_MIN + LTFT_WARNING_MIN) / 2,         STATUS_WARNING),
    (LTFT_WARNING_MAX + 1.0,                       STATUS_ERROR),
    (LTFT_WARNING_MIN - 1.0,                       STATUS_ERROR),
])
def test_ltft_status(value: float, expected: str) -> None:
    assert get_status("LTFT", value) == expected


@pytest.mark.parametrize("value", [
    99.0,
    float("nan"),
])
def test_ltft_pre_start_and_nan_neutral(value: float) -> None:
    if math.isnan(value):
        assert get_status("LTFT", value) == STATUS_NEUTRAL
    else:
        assert get_status("LTFT", value, regime="PRE_START") == STATUS_NEUTRAL


# ---------------------------------------------------------------------------
# STFT
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("value, expected", [
    (0.0,                                          STATUS_OK),
    (float(STFT_OK_MAX),                           STATUS_OK),
    (float(STFT_OK_MIN),                           STATUS_OK),
    ((STFT_OK_MAX + STFT_WARNING_MAX) / 2,         STATUS_WARNING),
    ((STFT_OK_MIN + STFT_WARNING_MIN) / 2,         STATUS_WARNING),
    (STFT_WARNING_MAX + 1.0,                       STATUS_ERROR),
    (STFT_WARNING_MIN - 1.0,                       STATUS_ERROR),
])
def test_stft_status(value: float, expected: str) -> None:
    assert get_status("STFT", value) == expected


# ---------------------------------------------------------------------------
# Температура ОЖ
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("value, expected_set", [
    (95.0,  {STATUS_OK}),
    (120.0, {STATUS_ERROR}),
    (20.0,  {STATUS_WARNING, STATUS_NEUTRAL, STATUS_ERROR}),
    (115.0, {STATUS_WARNING, STATUS_ERROR}),
])
def test_coolant_temp_status(value: float, expected_set: set) -> None:
    param = "TEMP_COOLANT_Max" if value == 115.0 else "TEMP_COOLANT_Mean"
    assert get_status(param, value) in expected_set


# ---------------------------------------------------------------------------
# PRE_START → всегда NEUTRAL
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("param", [
    "LTFT",
    "STFT",
    "TEMP_COOLANT_Mean",
    "KNOCK_COUNT",
])
def test_pre_start_always_neutral(param: str) -> None:
    assert get_status(param, 999.0, regime="PRE_START") == STATUS_NEUTRAL


# ---------------------------------------------------------------------------
# NaN → всегда NEUTRAL
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("param", [
    "LTFT",
    "STFT",
    "TEMP_COOLANT_Mean",
])
def test_nan_always_neutral(param: str) -> None:
    assert get_status(param, math.nan) == STATUS_NEUTRAL


# ---------------------------------------------------------------------------
# Неизвестный параметр → NEUTRAL
# ---------------------------------------------------------------------------

def test_unknown_param_neutral() -> None:
    assert get_status("UNKNOWN_PARAM_XYZ", 100.0) == STATUS_NEUTRAL


# ---------------------------------------------------------------------------
# Детонация
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("value, expected_set", [
    (0.0,   {STATUS_OK, STATUS_NEUTRAL}),
    (100.0, {STATUS_WARNING, STATUS_ERROR}),
])
def test_knock_count_status(value: float, expected_set: set) -> None:
    assert get_status("KNOCK_COUNT", value) in expected_set


# ---------------------------------------------------------------------------
# Все возвращаемые значения допустимы
# ---------------------------------------------------------------------------

_VALID_STATUSES = {STATUS_OK, STATUS_WARNING, STATUS_ERROR, STATUS_NEUTRAL}


@pytest.mark.parametrize("param, value", [
    (param, val)
    for param in ["LTFT", "STFT", "TEMP_COOLANT_Mean", "KNOCK_COUNT", "UNKNOWN"]
    for val in [0.0, 10.0, -10.0, 100.0, -100.0]
])
def test_status_values_are_valid(param: str, value: float) -> None:
    result = get_status(param, value)
    assert result in _VALID_STATUSES, f"Недопустимый статус '{result}' для {param}={value}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
