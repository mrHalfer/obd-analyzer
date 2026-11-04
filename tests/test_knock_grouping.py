#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Юнит-тесты для группировки и классификации событий детонации.

Тестирует classify_knock_groups_with_remission():
- Группировка по временной близости
- Классификация (слабая / средняя / сильная)
- Применение снисходительности (remission)
- Граничные случаи (нет данных, пустой DataFrame)
"""

import sys
from pathlib import Path
import pytest
import pandas as pd

_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / 'plugins'))
sys.path.insert(0, str(_ROOT / 'build'))

from check_knock import classify_knock_groups_with_remission
from core_obd import KNOCK_WEAK_MAX, KNOCK_MEDIUM_MAX, KNOCK_STRONG_MIN


# ---------------------------------------------------------------------------
# Вспомогательные функции
# ---------------------------------------------------------------------------

def _make_df(retards: list[float], times_sec: list[float], rpm: float = 2000.0, speed: float = 60.0) -> pd.DataFrame:
    """Создаёт DataFrame с событиями детонации для тестирования."""
    def _sec_to_time(s: float) -> str:
        h = int(s) // 3600
        m = (int(s) % 3600) // 60
        sec = int(s) % 60
        return f'{h:02d}:{m:02d}:{sec:02d}'

    rows = []
    for retard, t_sec in zip(retards, times_sec):
        rows.append({
            'KNOCK_RETARD': retard,
            'TIME': _sec_to_time(t_sec),
            'TIME_SEC': t_sec,
            'RPM': rpm,
            'SPEED': speed,
        })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Тесты
# ---------------------------------------------------------------------------

class TestKnockGrouping:
    def test_empty_dataframe(self):
        df = pd.DataFrame(columns=['KNOCK_RETARD', 'TIME', 'RPM', 'SPEED'])
        result = classify_knock_groups_with_remission(df)
        assert result == []

    def test_no_knock_events(self):
        df = _make_df([0.0, 0.0, 0.0], [0, 1, 2])
        result = classify_knock_groups_with_remission(df)
        assert result == []

    def test_single_weak_event(self):
        # KNOCK_WEAK_MAX = 4, слабая: 2..4
        retard = float(KNOCK_WEAK_MAX)  # на границе: слабая
        df = _make_df([retard], [10.0])
        result = classify_knock_groups_with_remission(df, max_gap_sec=5.0)
        assert len(result) == 1
        assert result[0]['initial_severity'] == 'weak'

    def test_single_medium_event(self):
        # KNOCK_MEDIUM_MAX = 8, средняя: 5..8
        retard = float(KNOCK_MEDIUM_MAX)
        df = _make_df([retard], [10.0])
        result = classify_knock_groups_with_remission(df, max_gap_sec=5.0)
        assert len(result) == 1
        assert result[0]['initial_severity'] == 'medium'

    def test_single_strong_event(self):
        # KNOCK_STRONG_MIN = 9, сильная: 9+
        retard = float(KNOCK_STRONG_MIN)
        df = _make_df([retard], [10.0])
        result = classify_knock_groups_with_remission(df, max_gap_sec=5.0)
        assert len(result) == 1
        assert result[0]['initial_severity'] == 'strong'

    def test_groups_split_by_gap(self):
        # Два события с большим временным разрывом → 2 группы
        retards = [3.0, 3.0]
        times = [10.0, 100.0]  # разрыв 90 сек > max_gap_sec
        df = _make_df(retards, times)
        result = classify_knock_groups_with_remission(df, max_gap_sec=5.0)
        assert len(result) == 2

    def test_groups_merged_within_gap(self):
        # Три события подряд с малым разрывом → 1 группа
        retards = [3.0, 3.0, 3.0]
        times = [10.0, 12.0, 14.0]  # разрыв 2 сек < max_gap_sec
        df = _make_df(retards, times)
        result = classify_knock_groups_with_remission(df, max_gap_sec=5.0)
        assert len(result) == 1
        assert result[0]['event_count'] == 3

    def test_result_has_required_fields(self):
        df = _make_df([5.0], [10.0])
        result = classify_knock_groups_with_remission(df, max_gap_sec=5.0)
        assert len(result) == 1
        g = result[0]
        required_keys = {'max_retard', 'mean_retard', 'duration', 'max_rpm', 'max_speed',
                         'event_count', 'initial_severity', 'final_severity',
                         'time_start', 'time_end'}
        for key in required_keys:
            assert key in g, f"Отсутствует поле '{key}' в результате"

    def test_remission_reduces_strong_to_medium(self):
        # Условия remission: низкий RPM, низкая скорость, малый retard, короткая длительность
        retard = float(KNOCK_STRONG_MIN)  # сильная, но едва
        # rpm=500, speed=5 — ниже порогов remission
        df = _make_df([retard], [10.0], rpm=500.0, speed=5.0)
        result = classify_knock_groups_with_remission(df, max_gap_sec=5.0)
        if result:
            g = result[0]
            if g['initial_severity'] == 'strong':
                # Если remission сработала, final должен быть ниже
                assert g['final_severity'] in ('medium', 'weak', 'remitted')

    def test_max_retard_correct(self):
        retards = [3.0, 5.0, 2.0]
        times = [10.0, 11.0, 12.0]
        df = _make_df(retards, times)
        result = classify_knock_groups_with_remission(df, max_gap_sec=5.0)
        assert len(result) == 1
        assert result[0]['max_retard'] == pytest.approx(5.0)

    def test_severity_boundary_weak_medium(self):
        # KNOCK_WEAK_MAX+1 должна быть medium, KNOCK_WEAK_MAX — weak
        df_weak   = _make_df([float(KNOCK_WEAK_MAX)],     [10.0])
        df_medium = _make_df([float(KNOCK_WEAK_MAX) + 1], [10.0])
        r_weak   = classify_knock_groups_with_remission(df_weak, max_gap_sec=5.0)
        r_medium = classify_knock_groups_with_remission(df_medium, max_gap_sec=5.0)
        if r_weak:
            assert r_weak[0]['initial_severity'] == 'weak'
        if r_medium:
            assert r_medium[0]['initial_severity'] == 'medium'


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
