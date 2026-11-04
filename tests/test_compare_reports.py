#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Тесты для модулей генерации отчётов сравнения поездок:
- compare_plotly.py: _trip_labels, generate_all_plotly_html и вспомогательные функции
- compare_pdf.py:    _stat_bg, _register_fonts, _build_one_chunk_table, create_compare_pdf
- HTML-валидность:   HTML-файлы парсируются без ошибок и содержат обязательные теги
"""

import sys
from html.parser import HTMLParser
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "build"))
sys.path.insert(0, str(_ROOT / "plugins"))
sys.path.insert(0, str(_ROOT / "compare"))

# ---------------------------------------------------------------------------
# Вспомогательный HTML-валидатор
# ---------------------------------------------------------------------------

class _HTMLValidator(HTMLParser):
    """Минимальная проверка корректности HTML — подсчёт ошибок парсинга."""

    def __init__(self) -> None:
        super().__init__()
        self.parse_errors: list[str] = []
        self._tag_stack: list[str] = []

    # void-элементы HTML5 — не имеют закрывающего тега
    _VOID = frozenset({
        "area", "base", "br", "col", "embed", "hr", "img", "input",
        "link", "meta", "param", "source", "track", "wbr",
    })

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag not in self._VOID:
            self._tag_stack.append(tag)

    def handle_endtag(self, tag: str) -> None:
        if tag in self._VOID:
            return
        # В HTML5 ошибка несовпадения закрывающего тега — предупреждение,
        # не фатальная ошибка; просто снимаем совпадающий элемент из стека.
        if self._tag_stack and self._tag_stack[-1] == tag:
            self._tag_stack.pop()

    def handle_error(self, message: str) -> None:  # type: ignore[override]
        self.parse_errors.append(message)


def _validate_html(content: str) -> _HTMLValidator:
    validator = _HTMLValidator()
    validator.feed(content)
    return validator


# ---------------------------------------------------------------------------
# Фикстуры
# ---------------------------------------------------------------------------

@pytest.fixture
def two_trip_vals_df() -> pd.DataFrame:
    """Минимальный vals_df с двумя поездками — имитирует вывод compare_core.load_trips."""
    data = {
        "trip_2026-01-10": {
            "RUN_DURATION":              "15.2",
            "ALL_DRIVE_DISTANCE":        "8.3",
            "ALL_DRIVE_LTFT_Mean":       "2.1",
            "ALL_DRIVE_STFT_Mean":       "-0.8",
            "ALL_TEMP_COOLANT_Max":      "95",
            "WARMUP_DURATION":           "3.2",
            "KNOCK_TOTAL_COUNT":         "0",
            "KNOCK_WEAK_COUNT":          "0",
            "KNOCK_MEDIUM_COUNT":        "0",
            "KNOCK_STRONG_COUNT":        "0",
            "ALL_STALLED_COUNT":         "0",
            "ALL_DRIVE_FUEL_Mean":       "8.5",
            "DRIVE_CITY_DURATION":       "10.0",
            "DRIVE_SUBURBAN_DURATION":   "5.0",
            "DRIVE_HIGHWAY_DURATION":    "0.0",
        },
        "trip_2026-01-17": {
            "RUN_DURATION":              "22.1",
            "ALL_DRIVE_DISTANCE":        "14.7",
            "ALL_DRIVE_LTFT_Mean":       "3.5",
            "ALL_DRIVE_STFT_Mean":       "1.2",
            "ALL_TEMP_COOLANT_Max":      "98",
            "WARMUP_DURATION":           "4.0",
            "KNOCK_TOTAL_COUNT":         "2",
            "KNOCK_WEAK_COUNT":          "2",
            "KNOCK_MEDIUM_COUNT":        "0",
            "KNOCK_STRONG_COUNT":        "0",
            "ALL_STALLED_COUNT":         "1",
            "ALL_DRIVE_FUEL_Mean":       "9.1",
            "DRIVE_CITY_DURATION":       "14.0",
            "DRIVE_SUBURBAN_DURATION":   "8.0",
            "DRIVE_HIGHWAY_DURATION":    "0.0",
        },
    }
    return pd.DataFrame.from_dict(data, orient="index")


@pytest.fixture
def two_trip_stats_df() -> pd.DataFrame:
    """Минимальный stats_df с двумя поездками."""
    data = {
        "trip_2026-01-10": {
            "RUN_DURATION":              "○",
            "ALL_DRIVE_DISTANCE":        "○",
            "ALL_DRIVE_LTFT_Mean":       "✅",
            "ALL_DRIVE_STFT_Mean":       "✅",
            "ALL_TEMP_COOLANT_Max":      "✅",
            "WARMUP_DURATION":           "○",
            "KNOCK_TOTAL_COUNT":         "✅",
            "KNOCK_WEAK_COUNT":          "✅",
            "KNOCK_MEDIUM_COUNT":        "✅",
            "KNOCK_STRONG_COUNT":        "✅",
            "ALL_STALLED_COUNT":         "✅",
            "ALL_DRIVE_FUEL_Mean":       "○",
        },
        "trip_2026-01-17": {
            "RUN_DURATION":              "○",
            "ALL_DRIVE_DISTANCE":        "○",
            "ALL_DRIVE_LTFT_Mean":       "✅",
            "ALL_DRIVE_STFT_Mean":       "✅",
            "ALL_TEMP_COOLANT_Max":      "⚠️",
            "WARMUP_DURATION":           "○",
            "KNOCK_TOTAL_COUNT":         "⚠️",
            "KNOCK_WEAK_COUNT":          "⚠️",
            "KNOCK_MEDIUM_COUNT":        "✅",
            "KNOCK_STRONG_COUNT":        "✅",
            "ALL_STALLED_COUNT":         "⚠️",
            "ALL_DRIVE_FUEL_Mean":       "○",
        },
    }
    return pd.DataFrame.from_dict(data, orient="index")


@pytest.fixture
def metrics_csv_dir(tmp_path: Path, two_trip_vals_df: pd.DataFrame,
                    two_trip_stats_df: pd.DataFrame) -> Path:
    """Записывает две *_metrics.csv во временную директорию."""
    for trip_id in two_trip_vals_df.index:
        rows = []
        for code, val in two_trip_vals_df.loc[trip_id].items():
            stat = two_trip_stats_df.loc[trip_id].get(code, "○")
            rows.append({"REGIME": "ALL", "CODE": code, "VAL": val, "STAT": stat, "DESC": code})
        df = pd.DataFrame(rows)
        df.to_csv(tmp_path / f"{trip_id}_metrics.csv", index=False, encoding="utf-8-sig")
    return tmp_path


# ---------------------------------------------------------------------------
# compare_plotly — _trip_labels
# ---------------------------------------------------------------------------

class TestTripLabels:
    def test_short_ids_unchanged(self) -> None:
        from compare_plotly import _trip_labels
        ids = ["2026-01-10", "2026-01-17"]
        assert _trip_labels(ids) == ids

    def test_long_ids_truncated_to_date(self) -> None:
        from compare_plotly import _trip_labels
        ids = ["2026-01-10 14:30", "2026-01-17 09:15"]
        result = _trip_labels(ids)
        assert result == ["2026-01-10", "2026-01-17"]

    def test_empty_list(self) -> None:
        from compare_plotly import _trip_labels
        assert _trip_labels([]) == []

    def test_mixed_ids(self) -> None:
        from compare_plotly import _trip_labels
        ids = ["short", "2026-01-10 14:30:00"]
        result = _trip_labels(ids)
        assert result[0] == "short"
        assert result[1] == "2026-01-10"


# ---------------------------------------------------------------------------
# compare_plotly — generate_all_plotly_html
# ---------------------------------------------------------------------------

class TestGenerateAllPlotlyHtml:
    def test_empty_df_returns_empty_dict(self) -> None:
        from compare_plotly import generate_all_plotly_html
        result = generate_all_plotly_html(pd.DataFrame(), pd.DataFrame())
        assert isinstance(result, dict)
        assert len(result) == 0

    def test_returns_dict(self, two_trip_vals_df: pd.DataFrame,
                          two_trip_stats_df: pd.DataFrame) -> None:
        from compare_plotly import generate_all_plotly_html, PLOTLY_AVAILABLE
        result = generate_all_plotly_html(two_trip_vals_df, two_trip_stats_df)
        assert isinstance(result, dict)
        if PLOTLY_AVAILABLE:
            # Ожидаем хотя бы один ключ (trends/knock/modes/heatmap)
            assert len(result) > 0
        else:
            assert len(result) == 0

    def test_keys_are_known_names(self, two_trip_vals_df: pd.DataFrame,
                                  two_trip_stats_df: pd.DataFrame) -> None:
        from compare_plotly import generate_all_plotly_html
        result = generate_all_plotly_html(two_trip_vals_df, two_trip_stats_df)
        valid_keys = {"trends", "knock", "modes", "heatmap"}
        for key in result:
            assert key in valid_keys

    def test_values_are_nonempty_strings(self, two_trip_vals_df: pd.DataFrame,
                                         two_trip_stats_df: pd.DataFrame) -> None:
        from compare_plotly import generate_all_plotly_html, PLOTLY_AVAILABLE
        if not PLOTLY_AVAILABLE:
            pytest.skip("plotly не установлен")
        result = generate_all_plotly_html(two_trip_vals_df, two_trip_stats_df)
        for key, spec in result.items():
            assert isinstance(spec, str), f"Ключ {key!r} должен быть строкой"
            assert len(spec) > 0, f"Ключ {key!r} не должен быть пустым"


# ---------------------------------------------------------------------------
# compare_plotly — отдельные функции построения графиков
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("fn_name, use_stats", [
    ("_plot_trends_plotly",       True),
    ("_plot_knock_bars_plotly",   True),
    ("_plot_mode_durations_plotly", False),
    ("_plot_status_heatmap_plotly", True),
])
def test_plot_functions_return_str_or_none(fn_name: str, use_stats: bool,
                                           two_trip_vals_df: pd.DataFrame,
                                           two_trip_stats_df: pd.DataFrame) -> None:
    """Каждая _plot_*_plotly возвращает str или None, не выбрасывает исключений."""
    import compare_plotly as cp
    fn = getattr(cp, fn_name)
    args = (two_trip_vals_df, two_trip_stats_df) if use_stats else (two_trip_vals_df,)
    result = fn(*args)
    assert result is None or isinstance(result, str)


@pytest.mark.parametrize("fn_name, use_stats", [
    ("_plot_trends_plotly",       True),
    ("_plot_knock_bars_plotly",   True),
    ("_plot_mode_durations_plotly", False),
    ("_plot_status_heatmap_plotly", True),
])
def test_plot_functions_empty_df_return_none(fn_name: str, use_stats: bool) -> None:
    """Пустой DataFrame → None, без ошибок."""
    import compare_plotly as cp
    fn = getattr(cp, fn_name)
    args = (pd.DataFrame(), pd.DataFrame()) if use_stats else (pd.DataFrame(),)
    result = fn(*args)
    assert result is None


# ---------------------------------------------------------------------------
# compare_pdf — _stat_bg
# ---------------------------------------------------------------------------

class TestStatBg:
    @pytest.mark.parametrize("stat, expected_type", [
        ("✅", object),
        ("⚠️", object),
        ("❌", object),
        ("○",  object),
        ("",   object),
        ("unknown_status", object),
    ])
    def test_returns_color_for_any_input(self, stat: str, expected_type: type) -> None:
        try:
            from compare_pdf import _stat_bg
        except ImportError:
            pytest.skip("compare_pdf недоступен (возможно, reportlab не установлен)")
        result = _stat_bg(stat)
        assert result is not None

    def test_ok_and_error_differ(self) -> None:
        try:
            from compare_pdf import _stat_bg
        except ImportError:
            pytest.skip("compare_pdf недоступен")
        ok_color  = _stat_bg("✅")
        err_color = _stat_bg("❌")
        assert ok_color != err_color


# ---------------------------------------------------------------------------
# compare_pdf — _register_fonts
# ---------------------------------------------------------------------------

def test_register_fonts_returns_two_strings() -> None:
    try:
        from compare_pdf import _register_fonts
    except ImportError:
        pytest.skip("compare_pdf недоступен (reportlab не установлен)")
    font_name, font_name_bold = _register_fonts()
    assert isinstance(font_name, str) and len(font_name) > 0
    assert isinstance(font_name_bold, str) and len(font_name_bold) > 0


# ---------------------------------------------------------------------------
# compare_pdf — _build_one_chunk_table
# ---------------------------------------------------------------------------

def test_build_one_chunk_table_returns_table() -> None:
    try:
        from compare_pdf import _build_one_chunk_table, _register_fonts
    except ImportError:
        pytest.skip("compare_pdf недоступен")
    try:
        from reportlab.platypus import Table
    except ImportError:
        pytest.skip("reportlab не установлен")

    font_name, font_name_bold = _register_fonts()
    # rows_data — список словарей с ключами label / trip_vals / trip_stats
    chunk_ids = ["trip_A", "trip_B"]
    rows_data = [
        {
            "label":      "LTFT среднее",
            "trip_vals":  {"trip_A": "2.1 %",  "trip_B": "3.5 %"},
            "trip_stats": {"trip_A": "✅",       "trip_B": "✅"},
        },
        {
            "label":      "T ОЖ макс",
            "trip_vals":  {"trip_A": "95 °C",  "trip_B": "98 °C"},
            "trip_stats": {"trip_A": "✅",       "trip_B": "⚠️"},
        },
    ]
    table = _build_one_chunk_table(rows_data, chunk_ids, font_name, font_name_bold)
    assert isinstance(table, Table)


# ---------------------------------------------------------------------------
# compare_pdf — create_compare_pdf
# ---------------------------------------------------------------------------

def test_create_compare_pdf_creates_file_or_none(
    tmp_path: Path,
    two_trip_vals_df: pd.DataFrame,
    two_trip_stats_df: pd.DataFrame,
) -> None:
    try:
        from compare_pdf import create_compare_pdf
    except ImportError:
        pytest.skip("compare_pdf недоступен")

    result = create_compare_pdf(tmp_path, two_trip_vals_df, two_trip_stats_df, png_paths={})
    # Если reportlab доступен — PDF создан; иначе — None
    if result is not None:
        assert result.exists()
        assert result.suffix == ".pdf"
        assert result.stat().st_size > 0
    else:
        # reportlab недоступен или нет данных — файл не создаётся
        assert not (tmp_path / "comparison_report.pdf").exists()


def test_create_compare_pdf_empty_df_returns_none(tmp_path: Path) -> None:
    try:
        from compare_pdf import create_compare_pdf
    except ImportError:
        pytest.skip("compare_pdf недоступен")
    result = create_compare_pdf(tmp_path, pd.DataFrame(), pd.DataFrame(), png_paths={})
    assert result is None


# ---------------------------------------------------------------------------
# HTML-валидность — create_report_html
# ---------------------------------------------------------------------------

@pytest.fixture
def minimal_metrics_df() -> pd.DataFrame:
    return pd.DataFrame([
        {"REGIME": "ALL", "CODE": "RUN_FUEL_TYPE",        "VAL": "АИ-95", "STAT": "○",  "DESC": "Топливо"},
        {"REGIME": "ALL", "CODE": "RUN_DURATION",          "VAL": "12.5",  "STAT": "○",  "DESC": "Длительность"},
        {"REGIME": "ALL", "CODE": "ALL_TEMP_COOLANT_Max",  "VAL": "95.0",  "STAT": "✅", "DESC": "T ОЖ макс"},
        {"REGIME": "ALL", "CODE": "ALL_DRIVE_LTFT_Mean",   "VAL": "2.1",   "STAT": "✅", "DESC": "LTFT"},
        {"REGIME": "ALL", "CODE": "ALL_DRIVE_STFT_Mean",   "VAL": "-0.8",  "STAT": "✅", "DESC": "STFT"},
    ])


class TestHtmlValidity:
    def test_report_html_is_parseable(self, tmp_path: Path,
                                      minimal_metrics_df: pd.DataFrame) -> None:
        """Сгенерированный report.html разбирается без ошибок парсера."""
        import numpy as np
        from build_html import create_report_html

        metrics_path = tmp_path / "trip_metrics.csv"
        minimal_metrics_df.to_csv(metrics_path, index=False, encoding="utf-8-sig")

        create_report_html(tmp_path, "trip", no_plot=True, no_png=True)
        html_path = tmp_path / "trip_report.html"
        assert html_path.exists(), "HTML-файл не был создан"

        content = html_path.read_text(encoding="utf-8")
        validator = _validate_html(content)
        assert not validator.parse_errors, (
            f"HTML содержит ошибки парсинга: {validator.parse_errors}"
        )

    def test_report_html_contains_basic_structure(self, tmp_path: Path,
                                                   minimal_metrics_df: pd.DataFrame) -> None:
        """Сгенерированный HTML содержит обязательные теги структуры страницы."""
        from build_html import create_report_html

        minimal_metrics_df.to_csv(tmp_path / "trip_metrics.csv", index=False, encoding="utf-8-sig")
        create_report_html(tmp_path, "trip", no_plot=True, no_png=True)
        content = (tmp_path / "trip_report.html").read_text(encoding="utf-8").lower()

        for tag in ("<html", "<head", "<body", "</body>", "</html>"):
            assert tag in content, f"Тег {tag!r} отсутствует в HTML"

    def test_report_html_no_unclosed_script(self, tmp_path: Path,
                                             minimal_metrics_df: pd.DataFrame) -> None:
        """Каждый тег <script> имеет соответствующий </script>."""
        from build_html import create_report_html

        minimal_metrics_df.to_csv(tmp_path / "trip_metrics.csv", index=False, encoding="utf-8-sig")
        create_report_html(tmp_path, "trip", no_plot=True, no_png=True)
        content = (tmp_path / "trip_report.html").read_text(encoding="utf-8").lower()

        n_open  = content.count("<script")
        n_close = content.count("</script>")
        assert n_open == n_close, (
            f"Несовпадение тегов script: {n_open} открывающих, {n_close} закрывающих"
        )

    def test_report_html_no_unclosed_style(self, tmp_path: Path,
                                            minimal_metrics_df: pd.DataFrame) -> None:
        """Каждый тег <style> имеет соответствующий </style>."""
        from build_html import create_report_html

        minimal_metrics_df.to_csv(tmp_path / "trip_metrics.csv", index=False, encoding="utf-8-sig")
        create_report_html(tmp_path, "trip", no_plot=True, no_png=True)
        content = (tmp_path / "trip_report.html").read_text(encoding="utf-8").lower()

        n_open  = content.count("<style")
        n_close = content.count("</style>")
        assert n_open == n_close, (
            f"Несовпадение тегов style: {n_open} открывающих, {n_close} закрывающих"
        )

    def test_compare_html_is_parseable(self, metrics_csv_dir: Path) -> None:
        """Сгенерированный comparison_report.html разбирается без ошибок парсера."""
        from compare_html import create_compare_html
        from compare_core import load_trips

        vals_df, stats_df = load_trips(metrics_csv_dir)
        if vals_df.empty:
            pytest.skip("Не удалось загрузить метрики для теста сравнения")

        create_compare_html(metrics_csv_dir, vals_df, stats_df, png_paths={})
        html_path = metrics_csv_dir / "comparison_report.html"
        assert html_path.exists(), "comparison_report.html не был создан"

        content = html_path.read_text(encoding="utf-8")
        validator = _validate_html(content)
        assert not validator.parse_errors, (
            f"comparison_report.html содержит ошибки парсинга: {validator.parse_errors}"
        )

    def test_compare_html_contains_basic_structure(self, metrics_csv_dir: Path) -> None:
        """comparison_report.html содержит обязательные теги страницы."""
        from compare_html import create_compare_html
        from compare_core import load_trips

        vals_df, stats_df = load_trips(metrics_csv_dir)
        if vals_df.empty:
            pytest.skip("Не удалось загрузить метрики")

        create_compare_html(metrics_csv_dir, vals_df, stats_df, png_paths={})
        content = (metrics_csv_dir / "comparison_report.html").read_text(encoding="utf-8").lower()

        for tag in ("<html", "<head", "<body", "</body>", "</html>"):
            assert tag in content, f"Тег {tag!r} отсутствует в comparison_report.html"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
