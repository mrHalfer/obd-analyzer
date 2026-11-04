#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Модуль формирования PNG-графиков (matplotlib) для анализа OBD-II данных.

Содержит функции визуализации:
- Таймлайн RPM/скорость/температура
- Heatmap детонации
- Гистограммы LTFT/STFT
- Матрица корреляций
- Коррекции топлива по времени
- Кислородные датчики
- Температурные профили
- Профиль нагрузки двигателя
- Анализ MAF
- Анализ пропусков зажигания
- Сводный дашборд
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

# matplotlib — опциональная зависимость формата PNG: при отсутствии
# вместо голой ModuleNotFoundError бросаем MissingDependencyError с pip-командой
from deps import require
matplotlib = require('matplotlib', 'для PNG-графиков')
matplotlib.use('Agg')
import matplotlib.pyplot as plt

from core_obd import (
    LOG_DT,
    COOLANT_TEMP_MAX_MIN,
    COOLANT_TEMP_MAX_ERROR,
    CHART_FUEL_OK_LINE,
    CHART_FUEL_WARN_LINE,
    O2_DK2_NORM_MIN,
    O2_DK2_NORM_MAX,
    get_time_axis_minutes,
)
from translation import t

logger = logging.getLogger(__name__)

_PNG_DPI = 150


def _save_plot(out_path: Path, log_key: str, **save_kwargs) -> None:
    """Сохраняет текущий plt-рисунок в PNG и закрывает его."""
    plt.savefig(out_path, dpi=_PNG_DPI, **save_kwargs)
    plt.close()
    logger.debug(t(log_key, path=out_path))


def plot_time_series(df_clean: pd.DataFrame, output_dir: Path, base_name: str) -> None:
    """Строит таймлайн RPM / SPEED / COOLANT_TEMP по времени."""
    required = ['RPM', 'SPEED', 'COOLANT_TEMP']
    if not all(col in df_clean.columns for col in required):
        logger.warning(t('console.png_timeline_missing_cols', cols=required))
        return

    x = get_time_axis_minutes(df_clean)

    plt.figure(figsize=(12, 7))

    plt.subplot(3, 1, 1)
    plt.plot(x, df_clean['RPM'], color='tab:blue')
    plt.ylabel(t('png.timeline.ylabel_rpm'))
    plt.grid(True, alpha=0.3)
    plt.title(t('png.timeline.title'))

    plt.subplot(3, 1, 2)
    plt.plot(x, df_clean['SPEED'], color='tab:green')
    plt.ylabel(t('png.timeline.ylabel_speed'))
    plt.grid(True, alpha=0.3)

    plt.subplot(3, 1, 3)
    plt.plot(x, df_clean['COOLANT_TEMP'], color='tab:red')
    plt.ylabel(t('png.timeline.ylabel_coolant'))
    plt.xlabel(t('common.time_min'))
    plt.grid(True, alpha=0.3)

    plt.tight_layout()
    out_path = output_dir / f'{base_name}_viz_timeline.png'
    _save_plot(out_path, 'console.png_timeline_saved')


def plot_knock_heatmap(df_clean: pd.DataFrame, output_dir: Path, base_name: str) -> None:
    """Строит тепловую карту детонации в пространстве RPM vs ENGINE_LOAD."""
    if 'KNOCK_RETARD' not in df_clean.columns or 'RPM' not in df_clean.columns or 'ENGINE_LOAD' not in df_clean.columns:
        logger.warning(t('console.png_knock_heatmap_missing_cols'))
        return

    kdf = df_clean[(df_clean['KNOCK_RETARD'] > 1) &
                   df_clean['RPM'].notna() &
                   df_clean['ENGINE_LOAD'].notna()].copy()
    if kdf.empty:
        logger.warning(t('console.png_knock_heatmap_no_events'))
        return

    rpm = kdf['RPM'].to_numpy()
    load = kdf['ENGINE_LOAD'].to_numpy()

    rpm_max = max(4000, np.nanmax(rpm) + 200)
    rpm_bins = np.arange(0, rpm_max + 1, 250)
    load_bins = np.arange(0, 101, 5)

    plt.figure(figsize=(8, 6))
    h = plt.hist2d(rpm, load, bins=[rpm_bins, load_bins], cmap='inferno')
    plt.colorbar(h[3], label=t('png.knock_heatmap.colorbar'))
    plt.xlabel('RPM')
    plt.ylabel(t('png.knock_heatmap.ylabel'))
    plt.title(t('png.knock_heatmap.title'))
    plt.tight_layout()

    out_path = output_dir / f'{base_name}_viz_knock_heatmap.png'
    _save_plot(out_path, 'console.png_knock_heatmap_saved')


def plot_ltft_stft_hist(df_clean: pd.DataFrame, output_dir: Path, base_name: str) -> None:
    """Строит гистограммы распределения LTFT и STFT."""
    has_ltft = ('LTFT_PERCENT' in df_clean.columns) or ('LTFT' in df_clean.columns)
    has_stft = 'STFT_PERCENT' in df_clean.columns

    if not (has_ltft or has_stft):
        logger.warning(t('console.png_ltft_missing'))
        return

    plt.figure(figsize=(10, 5))

    if has_ltft:
        if 'LTFT_PERCENT' in df_clean.columns:
            ltft = df_clean['LTFT_PERCENT'].dropna()
        else:
            ltft_raw = df_clean['LTFT'].dropna()
            if ltft_raw.empty:
                ltft = pd.Series(dtype=float)
            else:
                ltft = (ltft_raw - 1.0) * 100.0

        if not ltft.empty:
            plt.hist(ltft, bins=40, alpha=0.6, label='LTFT (%)')

    if has_stft:
        stft = df_clean['STFT_PERCENT'].dropna()
        if not stft.empty:
            plt.hist(stft, bins=40, alpha=0.6, label='STFT (%)')

    plt.xlabel(t('png.ltft_stft.xlabel'))
    plt.ylabel(t('png.ltft_stft.ylabel'))
    plt.title(t('png.ltft_stft.title'))
    plt.grid(True, alpha=0.3)
    plt.legend()
    plt.tight_layout()

    out_path = output_dir / f'{base_name}_viz_ltft_stft_hist.png'
    _save_plot(out_path, 'console.png_ltft_saved')


def plot_correlation_matrix(df_clean: pd.DataFrame, output_dir: Path, base_name: str) -> None:
    """Строит матрицу корреляций между ключевыми параметрами двигателя."""
    params = ['RPM', 'SPEED', 'ENGINE_LOAD', 'MAF', 'THROTTLE_POS', 'COOLANT_TEMP']
    available = [p for p in params if p in df_clean.columns]

    if len(available) < 3:
        logger.warning(t('console.png_corr_few_params'))
        return

    corr = df_clean[available].corr()

    plt.figure(figsize=(6, 5))
    im = plt.imshow(corr, cmap='coolwarm', vmin=-1, vmax=1)
    plt.colorbar(im, fraction=0.046, pad=0.04, label=t('png.corr_matrix.colorbar'))

    plt.xticks(range(len(available)), available, rotation=45, ha='right')
    plt.yticks(range(len(available)), available)
    plt.title(t('png.corr_matrix.title'))
    plt.tight_layout()

    out_path = output_dir / f'{base_name}_viz_corr_matrix.png'
    _save_plot(out_path, 'console.png_corr_saved')


def plot_fuel_correction_timeline(df_clean: pd.DataFrame, output_dir: Path, base_name: str) -> None:
    """Строит графики LTFT и STFT по времени с пороговыми линиями."""
    has_ltft = ('LTFT_PERCENT' in df_clean.columns) or ('LTFT' in df_clean.columns)
    has_stft = 'STFT_PERCENT' in df_clean.columns

    if not (has_ltft or has_stft):
        logger.warning(t('console.png_fuel_missing'))
        return

    x = get_time_axis_minutes(df_clean)

    plt.figure(figsize=(14, 8))

    if has_ltft:
        plt.subplot(2, 1, 1)
        if 'LTFT_PERCENT' in df_clean.columns:
            ltft_data = df_clean['LTFT_PERCENT']
        else:
            ltft_data = (df_clean['LTFT'] - 1) * 100

        plt.plot(x, ltft_data, color='tab:blue', label='LTFT (%)', linewidth=1)
        plt.axhline(y=0,                    color='gray',    linestyle='--', alpha=0.5)
        plt.axhline(y= CHART_FUEL_WARN_LINE, color='#d62728', linestyle='--', alpha=0.7)
        plt.axhline(y=-CHART_FUEL_WARN_LINE, color='#d62728', linestyle='--', alpha=0.7)
        plt.axhline(y= CHART_FUEL_OK_LINE,   color='#ff7f0e', linestyle=':',  alpha=0.7, label=t('png.fuel_correction.lean'))
        plt.axhline(y=-CHART_FUEL_OK_LINE,   color='#ff7f0e', linestyle=':',  alpha=0.7, label=t('png.fuel_correction.rich'))
        plt.ylabel(t('png.fuel_correction.ltft_label'))
        plt.title(t('png.fuel_correction.ltft_title'))
        plt.grid(True, alpha=0.3)
        plt.legend()
        plt.ylim(-20, 20)

    if has_stft:
        plt.subplot(2, 1, 2)
        stft_data = df_clean['STFT_PERCENT']
        plt.plot(x, stft_data, color='tab:red', label='STFT (%)', linewidth=1)
        plt.axhline(y=0,                    color='gray',    linestyle='--', alpha=0.5)
        plt.axhline(y= CHART_FUEL_WARN_LINE, color='#d62728', linestyle='--', alpha=0.7)
        plt.axhline(y=-CHART_FUEL_WARN_LINE, color='#d62728', linestyle='--', alpha=0.7)
        plt.axhline(y= CHART_FUEL_OK_LINE,   color='#ff7f0e', linestyle=':',  alpha=0.7, label=t('png.fuel_correction.lean'))
        plt.axhline(y=-CHART_FUEL_OK_LINE,   color='#ff7f0e', linestyle=':',  alpha=0.7, label=t('png.fuel_correction.rich'))
        plt.ylabel(t('png.fuel_correction.stft_label'))
        plt.xlabel(t('common.time_min'))
        plt.title(t('png.fuel_correction.stft_title'))
        plt.grid(True, alpha=0.3)
        plt.legend()
        plt.ylim(-30, 30)

    plt.tight_layout()
    out_path = output_dir / f'{base_name}_viz_fuel_correction.png'
    _save_plot(out_path, 'console.png_fuel_saved')


def plot_o2_sensors_timeline(df_clean: pd.DataFrame, output_dir: Path, base_name: str) -> None:
    """Строит графики напряжения кислородных датчиков во времени."""
    o2_cols = [col for col in ['O2_B1S1', 'O2_B1S2'] if col in df_clean.columns]

    if not o2_cols:
        logger.warning(t('console.png_o2_missing'))
        return

    x = get_time_axis_minutes(df_clean)

    plt.figure(figsize=(14, 10))

    for i, col in enumerate(o2_cols, 1):
        plt.subplot(len(o2_cols), 1, i)
        o2_data = df_clean[col].dropna()
        if len(o2_data) > 0:
            plt.plot(x[:len(o2_data)], o2_data.values,
                     label=f'{col} (V)', linewidth=0.5, alpha=0.8)
            plt.axhline(y=O2_DK2_NORM_MIN, color='green', linestyle='--', alpha=0.5)
            plt.axhline(y=O2_DK2_NORM_MAX, color='green', linestyle='--', alpha=0.5, label=t('png.o2_sensors.dk2_norm'))
            plt.ylabel(f'{col} (V)')
            plt.title(f'{col}: {t("png.o2_sensors.voltage_label")}')
            plt.grid(True, alpha=0.3)
            plt.legend(loc='upper right')
            plt.ylim(0, 1.0)

    plt.xlabel(t('common.time_min'))
    plt.tight_layout()
    out_path = output_dir / f'{base_name}_viz_o2_sensors.png'
    _save_plot(out_path, 'console.png_o2_saved')


def plot_temperature_profiles(df_clean: pd.DataFrame, output_dir: Path, base_name: str) -> None:
    """Строит сравнительный график температур ОЖ и впуска во времени."""
    temp_cols = [col for col in ['COOLANT_TEMP', 'INTAKE_TEMP'] if col in df_clean.columns]

    if len(temp_cols) < 1:
        logger.warning(t('console.png_temp_missing'))
        return

    x = get_time_axis_minutes(df_clean)

    plt.figure(figsize=(14, 6))

    colors_map = {'COOLANT_TEMP': 'red', 'INTAKE_TEMP': 'blue'}
    labels = {
        'COOLANT_TEMP': t('png.temperatures.coolant_label'),
        'INTAKE_TEMP': t('png.temperatures.intake_label'),
    }

    for col in temp_cols:
        temp_data = df_clean[col].dropna()
        if len(temp_data) > 0:
            plt.plot(x[:len(temp_data)], temp_data.values,
                     color=colors_map.get(col, 'black'),
                     label=labels.get(col, col),
                     linewidth=1)

    plt.axhline(y=COOLANT_TEMP_MAX_MIN, color='green', linestyle='--', alpha=0.5,
                label=t('png.temperatures.coolant_norm', temp=COOLANT_TEMP_MAX_MIN))
    plt.axhline(y=COOLANT_TEMP_MAX_ERROR, color='red', linestyle='--', alpha=0.5,
                label=t('png.temperatures.coolant_max', temp=COOLANT_TEMP_MAX_ERROR))

    plt.xlabel(t('common.time_min'))
    plt.ylabel(t('png.temperatures.ylabel'))
    plt.title(t('png.temperatures.title'))
    plt.grid(True, alpha=0.3)
    plt.legend()
    plt.tight_layout()

    out_path = output_dir / f'{base_name}_viz_temperatures.png'
    _save_plot(out_path, 'console.png_temp_saved')


def plot_engine_load_profile(df_clean: pd.DataFrame, output_dir: Path, base_name: str) -> None:
    """Строит 4-панельный анализ нагрузки двигателя."""
    if 'ENGINE_LOAD' not in df_clean.columns or 'RPM' not in df_clean.columns:
        logger.warning(t('console.png_load_missing'))
        return

    plt.figure(figsize=(12, 8))

    plt.subplot(2, 2, 1)
    scatter = plt.scatter(
        df_clean['RPM'],
        df_clean['ENGINE_LOAD'],
        c=df_clean['COOLANT_TEMP'] if 'COOLANT_TEMP' in df_clean.columns else None,
        cmap='viridis',
        alpha=0.6,
        s=10,
    )
    if 'COOLANT_TEMP' in df_clean.columns:
        plt.colorbar(scatter, label=t('png.engine_load.colorbar'))
    plt.xlabel('RPM')
    plt.ylabel(t('png.engine_load.scatter_ylabel'))
    plt.title(t('png.engine_load.scatter_title'))
    plt.grid(True, alpha=0.3)

    plt.subplot(2, 2, 2)
    load_data = df_clean['ENGINE_LOAD'].dropna()
    plt.hist(load_data, bins=50, edgecolor='black', alpha=0.7)
    plt.xlabel(t('png.engine_load.hist_xlabel'))
    plt.ylabel(t('png.engine_load.hist_ylabel'))
    plt.title(t('png.engine_load.hist_title'))
    plt.grid(True, alpha=0.3)

    plt.subplot(2, 2, 3)
    if 'REGIME' in df_clean.columns:
        regimes = df_clean['REGIME'].unique()
        regime_loads = []
        regime_labels = []
        for regime in regimes:
            regime_data = df_clean[df_clean['REGIME'] == regime]['ENGINE_LOAD']
            if len(regime_data) > 0:
                regime_loads.append(regime_data.mean())
                regime_labels.append(regime)

        if regime_loads:
            plt.bar(range(len(regime_loads)), regime_loads, tick_label=regime_labels)
            plt.xlabel(t('png.engine_load.x_mode_label'))
            plt.ylabel(t('png.engine_load.mean_ylabel'))
            plt.title(t('png.engine_load.mean_title'))
            plt.xticks(rotation=45)
            plt.grid(True, alpha=0.3)

    plt.subplot(2, 2, 4)
    if 'REGIME' in df_clean.columns:
        regimes = df_clean['REGIME'].unique()
        regime_data = []
        regime_labels = []
        for regime in regimes:
            data = df_clean[df_clean['REGIME'] == regime]['ENGINE_LOAD'].dropna()
            if len(data) > 10:
                regime_data.append(data)
                regime_labels.append(regime)

        if regime_data:
            try:
                plt.boxplot(regime_data, tick_labels=regime_labels)
            except TypeError:
                plt.boxplot(regime_data, labels=regime_labels)
            plt.xlabel(t('png.engine_load.x_mode_label'))
            plt.ylabel(t('png.engine_load.box_ylabel'))
            plt.title(t('png.engine_load.box_title'))
            plt.xticks(rotation=45)
            plt.grid(True, alpha=0.3)

    plt.tight_layout()
    out_path = output_dir / f'{base_name}_viz_engine_load.png'
    _save_plot(out_path, 'console.png_load_saved')


def plot_maf_analysis(df_clean: pd.DataFrame, output_dir: Path, base_name: str) -> None:
    """Строит 6-панельный анализ массового расхода воздуха (MAF)."""
    if 'MAF' not in df_clean.columns:
        logger.warning(t('console.png_maf_missing'))
        return

    plt.figure(figsize=(14, 10))

    x = get_time_axis_minutes(df_clean)
    maf_data = df_clean['MAF'].dropna()

    plt.subplot(3, 2, 1)
    if len(maf_data) > 0:
        plt.plot(x[:len(maf_data)], maf_data.values,
                 color='purple', linewidth=0.5, alpha=0.8)
    plt.xlabel(t('common.time_min'))
    plt.ylabel(t('png.maf.ylabel'))
    plt.title(t('png.maf.time_title'))
    plt.grid(True, alpha=0.3)

    plt.subplot(3, 2, 2)
    if len(maf_data) > 0:
        plt.hist(maf_data, bins=50, edgecolor='black', alpha=0.7)
    plt.xlabel(t('png.maf.ylabel'))
    plt.ylabel(t('png.maf.hist_ylabel'))
    plt.title(t('png.maf.hist_title'))
    plt.grid(True, alpha=0.3)

    plt.subplot(3, 2, 3)
    if 'RPM' in df_clean.columns:
        plt.scatter(df_clean['RPM'], df_clean['MAF'], alpha=0.5, s=5)
        plt.xlabel('RPM')
        plt.ylabel(t('png.maf.ylabel'))
        plt.title(t('png.maf.vs_rpm_title'))
        plt.grid(True, alpha=0.3)

    plt.subplot(3, 2, 4)
    if 'THROTTLE_POS' in df_clean.columns:
        plt.scatter(df_clean['THROTTLE_POS'], df_clean['MAF'], alpha=0.5, s=5)
        plt.xlabel(t('png.maf.throttle_xlabel'))
        plt.ylabel(t('png.maf.ylabel'))
        plt.title(t('png.maf.vs_throttle_title'))
        plt.grid(True, alpha=0.3)

    plt.subplot(3, 2, 5)
    if 'REGIME' in df_clean.columns:
        regimes = df_clean['REGIME'].unique()
        regime_data = []
        regime_labels = []
        for regime in regimes:
            data = df_clean[df_clean['REGIME'] == regime]['MAF'].dropna()
            if len(data) > 10:
                regime_data.append(data)
                regime_labels.append(regime)

        if regime_data:
            try:
                plt.boxplot(regime_data, tick_labels=regime_labels)
            except TypeError:
                plt.boxplot(regime_data, labels=regime_labels)
            plt.xlabel(t('png.engine_load.x_mode_label'))
            plt.ylabel(t('png.maf.ylabel'))
            plt.title(t('png.maf.by_regime_title'))
            plt.xticks(rotation=45)
            plt.grid(True, alpha=0.3)

    plt.subplot(3, 2, 6)
    if 'ENGINE_LOAD' in df_clean.columns:
        plt.scatter(df_clean['ENGINE_LOAD'], df_clean['MAF'], alpha=0.5, s=5)
        plt.xlabel(t('png.maf.load_xlabel'))
        plt.ylabel(t('png.maf.ylabel'))
        plt.title(t('png.maf.vs_load_title'))
        plt.grid(True, alpha=0.3)

    plt.tight_layout()
    out_path = output_dir / f'{base_name}_viz_maf_analysis.png'
    _save_plot(out_path, 'console.png_maf_saved')


def plot_misfire_analysis(df_clean: pd.DataFrame, output_dir: Path, base_name: str) -> None:
    """Строит 4-панельную визуализацию пропусков зажигания."""
    misfire_cols = [
        col for col in ['MISFIRE_CYL1', 'MISFIRE_CYL2', 'MISFIRE_CYL3', 'MISFIRE_CYL4']
        if col in df_clean.columns
    ]

    if not misfire_cols:
        logger.warning(t('console.png_misfire_missing'))
        return

    total_misfires = sum(df_clean[col].fillna(0).sum() for col in misfire_cols)
    if total_misfires == 0:
        logger.warning(t('console.png_misfire_no_events'))
        return

    plt.figure(figsize=(14, 10))
    cyl_prefix = t('png.misfire.cyl_prefix')

    plt.subplot(2, 2, 1)
    misfire_counts = [df_clean[col].fillna(0).sum() for col in misfire_cols]
    cylinder_nums = [int(col.replace('MISFIRE_CYL', '')) for col in misfire_cols]

    bars = plt.bar(cylinder_nums, misfire_counts, color='tab:red')
    plt.xlabel(t('png.misfire.cyl_xlabel'))
    plt.ylabel(t('png.misfire.cyl_ylabel'))
    plt.title(t('png.misfire.by_cyl_title'))
    plt.grid(True, alpha=0.3)

    for bar, count in zip(bars, misfire_counts):
        plt.text(bar.get_x() + bar.get_width() / 2, bar.get_height(),
                 f'{int(count)}', ha='center', va='bottom')

    plt.subplot(2, 2, 2)
    x = get_time_axis_minutes(df_clean)
    for col in misfire_cols:
        misfire_data = df_clean[col].fillna(0)
        if misfire_data.any():
            misfire_mask = misfire_data > 0
            misfire_times = x[misfire_mask]
            misfire_values = misfire_data[misfire_mask]
            cylinder_num = int(col.replace('MISFIRE_CYL', ''))
            plt.scatter(misfire_times, misfire_values,
                        label=f'{cyl_prefix}{cylinder_num}', s=20, alpha=0.7)

    plt.xlabel(t('common.time_min'))
    plt.ylabel(t('png.misfire.timeline_ylabel'))
    plt.title(t('png.misfire.timeline_title'))
    plt.legend()
    plt.grid(True, alpha=0.3)

    plt.subplot(2, 2, 3)
    if 'RPM' in df_clean.columns:
        for col in misfire_cols:
            misfire_mask = df_clean[col].fillna(0) > 0
            if misfire_mask.any():
                cylinder_num = int(col.replace('MISFIRE_CYL', ''))
                plt.scatter(
                    df_clean.loc[misfire_mask, 'RPM'],
                    df_clean.loc[misfire_mask, 'ENGINE_LOAD'] if 'ENGINE_LOAD' in df_clean.columns else 0,
                    label=f'{cyl_prefix}{cylinder_num}',
                    s=30,
                    alpha=0.7,
                )

        plt.xlabel('RPM')
        plt.ylabel(t('png.misfire.load_ylabel') if 'ENGINE_LOAD' in df_clean.columns else '')
        plt.title(t('png.misfire.rpm_load_title'))
        plt.legend()
        plt.grid(True, alpha=0.3)

    plt.subplot(2, 2, 4)
    if 'REGIME' in df_clean.columns:
        regime_misfires = {}
        for regime in df_clean['REGIME'].unique():
            regime_mask = df_clean['REGIME'] == regime
            regime_total = sum(df_clean.loc[regime_mask, col].fillna(0).sum() for col in misfire_cols)
            regime_misfires[regime] = regime_total

        regimes = list(regime_misfires.keys())
        misfire_counts = [regime_misfires[r] for r in regimes]

        bars = plt.bar(range(len(regimes)), misfire_counts, tick_label=regimes)
        plt.xlabel(t('png.engine_load.x_mode_label'))
        plt.ylabel(t('png.misfire.timeline_ylabel'))
        plt.title(t('png.misfire.by_regime_title'))
        plt.xticks(rotation=45)
        plt.grid(True, alpha=0.3)

    plt.tight_layout()
    out_path = output_dir / f'{base_name}_viz_misfire_analysis.png'
    _save_plot(out_path, 'console.png_misfire_saved')


def create_summary_dashboard(df_clean: pd.DataFrame, output_dir: Path, base_name: str) -> None:
    """Создаёт сводный дашборд с 9 панелями ключевых распределений."""
    fig = plt.figure(figsize=(16, 12))

    ylabel_count = t('png.dashboard.ylabel')

    ax1 = plt.subplot(3, 3, 1)
    if 'RPM' in df_clean.columns:
        ax1.hist(df_clean['RPM'].dropna(), bins=50, alpha=0.7, color='blue')
        ax1.set_xlabel(t('png.dashboard.rpm_xlabel'))
        ax1.set_ylabel(ylabel_count)
        ax1.set_title(t('png.dashboard.rpm_title'))
        ax1.grid(True, alpha=0.3)

    ax2 = plt.subplot(3, 3, 2)
    if 'COOLANT_TEMP' in df_clean.columns:
        ax2.hist(df_clean['COOLANT_TEMP'].dropna(), bins=30, alpha=0.7, color='red')
        ax2.axvline(x=COOLANT_TEMP_MAX_MIN, color='green', linestyle='--', alpha=0.7, label=t('png.dashboard.coolant_norm'))
        ax2.axvline(x=COOLANT_TEMP_MAX_ERROR, color='red', linestyle='--', alpha=0.7, label=t('png.dashboard.coolant_max_label'))
        ax2.set_xlabel(t('png.dashboard.coolant_xlabel'))
        ax2.set_ylabel(ylabel_count)
        ax2.set_title(t('png.dashboard.coolant_title'))
        ax2.legend()
        ax2.grid(True, alpha=0.3)

    ax3 = plt.subplot(3, 3, 3)
    if 'ENGINE_LOAD' in df_clean.columns:
        ax3.hist(df_clean['ENGINE_LOAD'].dropna(), bins=40, alpha=0.7, color='green')
        ax3.set_xlabel(t('png.dashboard.load_xlabel'))
        ax3.set_ylabel(ylabel_count)
        ax3.set_title(t('png.dashboard.load_title'))
        ax3.grid(True, alpha=0.3)

    ax4 = plt.subplot(3, 3, 4)
    if ('LTFT_PERCENT' in df_clean.columns) or ('LTFT' in df_clean.columns):
        if 'LTFT_PERCENT' in df_clean.columns:
            ltft_data = df_clean['LTFT_PERCENT']
        else:
            ltft_data = (df_clean['LTFT'] - 1) * 100

        ax4.hist(ltft_data.dropna(), bins=40, alpha=0.7, color='orange')
        ax4.axvline(x=0, color='gray', linestyle='--', alpha=0.5)
        ax4.axvline(x=10, color='yellow', linestyle=':', alpha=0.5)
        ax4.axvline(x=-10, color='yellow', linestyle=':', alpha=0.5)
        ax4.set_xlabel(t('png.dashboard.ltft_xlabel'))
        ax4.set_ylabel(ylabel_count)
        ax4.set_title(t('png.dashboard.ltft_title'))
        ax4.grid(True, alpha=0.3)

    ax5 = plt.subplot(3, 3, 5)
    if 'STFT_PERCENT' in df_clean.columns:
        ax5.hist(df_clean['STFT_PERCENT'].dropna(), bins=40, alpha=0.7, color='purple')
        ax5.axvline(x=0, color='gray', linestyle='--', alpha=0.5)
        ax5.axvline(x=15, color='yellow', linestyle=':', alpha=0.5)
        ax5.axvline(x=-15, color='yellow', linestyle=':', alpha=0.5)
        ax5.set_xlabel(t('png.dashboard.stft_xlabel'))
        ax5.set_ylabel(ylabel_count)
        ax5.set_title(t('png.dashboard.stft_title'))
        ax5.grid(True, alpha=0.3)

    ax6 = plt.subplot(3, 3, 6)
    if 'MAF' in df_clean.columns:
        ax6.hist(df_clean['MAF'].dropna(), bins=40, alpha=0.7, color='brown')
        ax6.set_xlabel(t('png.dashboard.maf_xlabel'))
        ax6.set_ylabel(ylabel_count)
        ax6.set_title(t('png.dashboard.maf_title'))
        ax6.grid(True, alpha=0.3)

    ax7 = plt.subplot(3, 3, 7)
    if 'INJECTION_TIME' in df_clean.columns:
        ax7.hist(df_clean['INJECTION_TIME'].dropna(), bins=40, alpha=0.7, color='cyan')
        ax7.set_xlabel(t('png.dashboard.injection_xlabel'))
        ax7.set_ylabel(ylabel_count)
        ax7.set_title(t('png.dashboard.injection_title'))
        ax7.grid(True, alpha=0.3)

    ax8 = plt.subplot(3, 3, 8)
    if 'THROTTLE_POS' in df_clean.columns:
        ax8.hist(df_clean['THROTTLE_POS'].dropna(), bins=40, alpha=0.7, color='pink')
        ax8.set_xlabel(t('png.dashboard.throttle_xlabel'))
        ax8.set_ylabel(ylabel_count)
        ax8.set_title(t('png.dashboard.throttle_title'))
        ax8.grid(True, alpha=0.3)

    ax9 = plt.subplot(3, 3, 9)
    if 'REGIME' in df_clean.columns:
        regime_counts = df_clean['REGIME'].value_counts()
        ax9.pie(regime_counts.values, labels=regime_counts.index, autopct='%1.1f%%')
        ax9.set_title(t('png.dashboard.regime_title'))

    plt.suptitle(t('png.dashboard.title', base_name=base_name), fontsize=16, y=1.02)
    plt.tight_layout()

    out_path = output_dir / f'{base_name}_viz_dashboard.png'
    _save_plot(out_path, 'console.png_dashboard_saved', bbox_inches='tight')
