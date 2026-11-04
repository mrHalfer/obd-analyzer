#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Тесты модулей генерации отчётов: build_html, build_png, build_csv.

Стратегия:
- build_html: проверяем корректность HTML-вывода и создание файла.
- build_png:  проверяем, что функции выполняются без исключений.
- build_csv:  проверяем создание _metrics.csv и _knock.csv.

Для графиков содержимое изображения не проверяется — только отсутствие ошибок.
Фикстуры создают временные файлы и минимальные DataFrame с нужными колонками.
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "build"))
sys.path.insert(0, str(_ROOT / "plugins"))


# ---------------------------------------------------------------------------
# Фикстуры
# ---------------------------------------------------------------------------

@pytest.fixture
def minimal_df() -> pd.DataFrame:
    """Минимальный DataFrame с обязательными OBD-колонками."""
    n = 60
    return pd.DataFrame({
        "TIME":           np.arange(n) * 0.2,
        "RPM":            [1500.0] * n,
        "SPEED":          [50.0] * n,
        "COOLANT_TEMP":   [90.0] * n,
        "LTFT":           [2.0] * n,
        "STFT":           [-1.0] * n,
        "ENGINE_LOAD":    [45.0] * n,
        "THROTTLE_POS":   [30.0] * n,
        "SPARK_ADVANCE":  [12.0] * n,
        "MAF":            [8.0] * n,
        "INTAKE_TEMP":    [25.0] * n,
        "ACCEL_POS":      [30.0] * n,
        "FUEL_CONSUMPTION": [8.5] * n,
        "O2_B1S1":        [0.5] * n,
        "O2_B1S2":        [0.72] * n,
        "INJECTION_TIME": [5.0] * n,
        "KNOCK_RETARD":   [0.0] * n,
        "MISFIRE_CYL1":   [0.0] * n,
        "MISFIRE_CYL2":   [0.0] * n,
        "MISFIRE_CYL3":   [0.0] * n,
        "MISFIRE_CYL4":   [0.0] * n,
        "DISTANCE":       np.linspace(0, 2.0, n),
        "REGIME":         ["ALL_DRIVE"] * n,
        "REGIME_CODE":    ["ALL_DRIVE"] * n,
    })


@pytest.fixture
def minimal_metrics_df() -> pd.DataFrame:
    """Минимальный DataFrame метрик, имитирующий _metrics.csv."""
    return pd.DataFrame([
        {"REGIME": "ALL", "CODE": "RUN_FUEL_TYPE",        "VALUE": "АИ-95",  "STAT": "✅"},
        {"REGIME": "ALL", "CODE": "RUN_DURATION",          "VALUE": "12.5",   "STAT": "✅"},
        {"REGIME": "ALL", "CODE": "RUN_TEMP_OUTSIDE",      "VALUE": "15",     "STAT": "✅"},
        {"REGIME": "ALL", "CODE": "ALL_TEMP_COOLANT_Mean", "VALUE": "90.0",   "STAT": "✅"},
        {"REGIME": "ALL", "CODE": "ALL_TEMP_COOLANT_Max",  "VALUE": "95.0",   "STAT": "✅"},
        {"REGIME": "ALL", "CODE": "ALL_LTFT_P05",          "VALUE": "1.5",    "STAT": "✅"},
        {"REGIME": "ALL", "CODE": "ALL_LTFT_P95",          "VALUE": "3.2",    "STAT": "✅"},
        {"REGIME": "ALL", "CODE": "ALL_STFT_P025",         "VALUE": "-2.0",   "STAT": "✅"},
        {"REGIME": "ALL", "CODE": "ALL_STFT_P975",         "VALUE": "2.5",    "STAT": "✅"},
    ])


@pytest.fixture
def metrics_csv(tmp_path: Path, minimal_metrics_df: pd.DataFrame) -> Path:
    """Записывает minimal_metrics_df во временный CSV и возвращает путь."""
    p = tmp_path / "test_metrics.csv"
    minimal_metrics_df.to_csv(p, index=False, encoding="utf-8-sig")
    return p


# ---------------------------------------------------------------------------
# build_html
# ---------------------------------------------------------------------------

class TestBuildSummaryCard:
    def test_contains_title(self) -> None:
        from build_html import _build_summary_card
        html = _build_summary_card("Заголовок", ["<p>Строка 1</p>", "<p>Строка 2</p>"])
        assert "Заголовок" in html

    def test_contains_rows(self) -> None:
        from build_html import _build_summary_card
        html = _build_summary_card("T", ["<p>alpha</p>", "<p>beta</p>"])
        assert "alpha" in html
        assert "beta" in html

    def test_returns_div(self) -> None:
        from build_html import _build_summary_card
        html = _build_summary_card("T", [])
        assert "<div" in html
        assert isinstance(html, str)

    def test_empty_rows(self) -> None:
        from build_html import _build_summary_card
        html = _build_summary_card("Empty", [])
        assert "Empty" in html
        assert "</div>" in html


class TestBuildSummaryPanel:
    def test_missing_metrics_file_returns_html(self, tmp_path: Path) -> None:
        from build_html import _build_summary_panel
        result = _build_summary_panel(tmp_path / "nonexistent_metrics.csv")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_valid_metrics_returns_nonempty_html(self, metrics_csv: Path) -> None:
        from build_html import _build_summary_panel
        result = _build_summary_panel(metrics_csv)
        assert isinstance(result, str)
        assert "<div" in result

    def test_corrupted_file_returns_html(self, tmp_path: Path) -> None:
        from build_html import _build_summary_panel
        bad = tmp_path / "bad_metrics.csv"
        bad.write_bytes(b"\xff\xfe not valid csv \x00\x00")
        result = _build_summary_panel(bad)
        assert isinstance(result, str)


class TestCreateReportHtml:
    def test_creates_html_file(self, tmp_path: Path, minimal_metrics_df: pd.DataFrame,
                               minimal_df: pd.DataFrame) -> None:
        from build_html import create_report_html
        minimal_metrics_df.to_csv(tmp_path / "trip_metrics.csv", index=False, encoding="utf-8-sig")
        create_report_html(tmp_path, "trip", no_plot=True, no_png=True, df_clean=minimal_df)
        assert (tmp_path / "trip_report.html").exists()

    def test_html_file_not_empty(self, tmp_path: Path, minimal_metrics_df: pd.DataFrame,
                                 minimal_df: pd.DataFrame) -> None:
        from build_html import create_report_html
        minimal_metrics_df.to_csv(tmp_path / "trip_metrics.csv", index=False, encoding="utf-8-sig")
        create_report_html(tmp_path, "trip", no_plot=True, no_png=True, df_clean=minimal_df)
        content = (tmp_path / "trip_report.html").read_text(encoding="utf-8")
        assert len(content) > 100

    def test_no_html_flag_skips_file(self, tmp_path: Path, minimal_df: pd.DataFrame) -> None:
        from build_html import create_report_html
        # no_plot=True также отключает Plotly, чтобы не требовать строковый формат TIME
        create_report_html(tmp_path, "trip", no_html=True, no_plot=True, df_clean=minimal_df)
        assert not (tmp_path / "trip_report.html").exists()


# ---------------------------------------------------------------------------
# build_png
# ---------------------------------------------------------------------------

class TestBuildPng:
    """Проверяем, что каждая функция выполняется без исключений.
    Содержимое PNG не проверяется."""

    def test_plot_time_series(self, tmp_path: Path, minimal_df: pd.DataFrame) -> None:
        from build_png import plot_time_series
        plot_time_series(minimal_df, tmp_path, "trip")

    def test_plot_time_series_missing_cols(self, tmp_path: Path) -> None:
        from build_png import plot_time_series
        # Без обязательных колонок — функция должна молча вернуться, не падать
        plot_time_series(pd.DataFrame({"X": [1, 2, 3]}), tmp_path, "trip")

    def test_plot_knock_heatmap(self, tmp_path: Path, minimal_df: pd.DataFrame) -> None:
        from build_png import plot_knock_heatmap
        plot_knock_heatmap(minimal_df, tmp_path, "trip")

    def test_plot_ltft_stft_hist(self, tmp_path: Path, minimal_df: pd.DataFrame) -> None:
        from build_png import plot_ltft_stft_hist
        plot_ltft_stft_hist(minimal_df, tmp_path, "trip")

    def test_plot_fuel_correction_timeline(self, tmp_path: Path, minimal_df: pd.DataFrame) -> None:
        from build_png import plot_fuel_correction_timeline
        plot_fuel_correction_timeline(minimal_df, tmp_path, "trip")

    def test_plot_o2_sensors_timeline(self, tmp_path: Path, minimal_df: pd.DataFrame) -> None:
        from build_png import plot_o2_sensors_timeline
        plot_o2_sensors_timeline(minimal_df, tmp_path, "trip")

    def test_plot_temperature_profiles(self, tmp_path: Path, minimal_df: pd.DataFrame) -> None:
        from build_png import plot_temperature_profiles
        plot_temperature_profiles(minimal_df, tmp_path, "trip")

    def test_plot_engine_load_profile(self, tmp_path: Path, minimal_df: pd.DataFrame) -> None:
        from build_png import plot_engine_load_profile
        plot_engine_load_profile(minimal_df, tmp_path, "trip")

    def test_plot_maf_analysis(self, tmp_path: Path, minimal_df: pd.DataFrame) -> None:
        from build_png import plot_maf_analysis
        plot_maf_analysis(minimal_df, tmp_path, "trip")

    def test_plot_misfire_analysis(self, tmp_path: Path, minimal_df: pd.DataFrame) -> None:
        from build_png import plot_misfire_analysis
        plot_misfire_analysis(minimal_df, tmp_path, "trip")

    def test_create_summary_dashboard(self, tmp_path: Path, minimal_df: pd.DataFrame) -> None:
        from build_png import create_summary_dashboard
        create_summary_dashboard(minimal_df, tmp_path, "trip")

    def test_plot_correlation_matrix(self, tmp_path: Path, minimal_df: pd.DataFrame) -> None:
        from build_png import plot_correlation_matrix
        plot_correlation_matrix(minimal_df, tmp_path, "trip")


# ---------------------------------------------------------------------------
# build_csv — save_knock_timeline
# ---------------------------------------------------------------------------

class TestBuildCsv:
    def test_save_knock_timeline_no_knock_col(self, tmp_path: Path, minimal_df: pd.DataFrame) -> None:
        from build_csv import save_knock_timeline
        df_no_knock = minimal_df.drop(columns=["KNOCK_RETARD"])
        # Без колонки KNOCK_RETARD — функция должна молча вернуться
        save_knock_timeline(df_no_knock, tmp_path, "trip")

    def test_save_knock_timeline_with_knock(self, tmp_path: Path, minimal_df: pd.DataFrame) -> None:
        from build_csv import save_knock_timeline
        # Добавляем несколько ненулевых ударов
        df = minimal_df.copy()
        df.loc[10, "KNOCK_RETARD"] = 5.0
        df.loc[11, "KNOCK_RETARD"] = 3.0
        df.loc[30, "KNOCK_RETARD"] = 8.0
        save_knock_timeline(df, tmp_path, "trip")
        # При наличии ударов файл _knock_timeline.csv должен быть создан
        knock_files = list(tmp_path.glob("*_knock_timeline.csv"))
        assert len(knock_files) == 1

    def test_knock_csv_has_expected_columns(self, tmp_path: Path, minimal_df: pd.DataFrame) -> None:
        from build_csv import save_knock_timeline
        df = minimal_df.copy()
        df.loc[5, "KNOCK_RETARD"] = 6.0
        save_knock_timeline(df, tmp_path, "trip")
        knock_path = tmp_path / "trip_knock_timeline.csv"
        if knock_path.exists():
            kdf = pd.read_csv(knock_path)
            assert "KNOCK_RETARD" in kdf.columns


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
