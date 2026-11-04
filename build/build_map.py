#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Модуль генерации HTML-панели карты для единого отчёта OBD-II.

Встраивает интерактивную карту OpenStreetMap (Leaflet.js) с отрезками
из GeoJSON файла, созданного build_geojson.py.
"""

import json
import logging
from pathlib import Path

import sys as _sys
from pathlib import Path as _Path
_root = _Path(__file__).parent.parent
for _d in [str(_root), str(_root / 'build'), str(_root / 'plugins')]:
    if _d not in _sys.path:
        _sys.path.insert(0, _d)

from translation import t

logger = logging.getLogger(__name__)

_SCRIPT_DIR = Path(__file__).parent

try:
    from jinja2 import Environment, FileSystemLoader
    _jinja_env = Environment(
        loader=FileSystemLoader(str(_SCRIPT_DIR)),
        autoescape=False,
        keep_trailing_newline=True,
    )
except ImportError:
    _jinja_env = None  # type: ignore[assignment]
    logger.warning('jinja2 не установлен — карта недоступна. Установите: pip install jinja2')

_MAP_JS = (_SCRIPT_DIR / 'build_map.js').read_text(encoding='utf-8')

# Цветовые стопы для каждого параметра (без меток — они строятся через t() в build_map_panel)
_COLOR_STOPS = {
    'SPEED':        [
        [0,   "#700000"], 
        [20,  "#FF0000"], 
        [40,  "#FFFF00"], 
        [60,  "#B6EB00"], 
        [90,  "#49CC00"], 
        [110, "#00BB00"]
        ],
    'RPM':          [
        [600,  '#2196F3'], 
        [1500, '#4CAF50'], 
        [3000, '#FFC107'], 
        [4000, '#FF9800'], 
        [5000, '#F44336'], 
        [6000, '#9C27B0']
        ],
    'COOLANT_TEMP': [
        [20,  '#2196F3'], 
        [60,  '#4CAF50'], 
        [85,  '#FFC107'], 
        [95,  '#FF9800'], 
        [105, '#F44336'], 
        [110, '#9C27B0']
        ],
    'ENGINE_LOAD':  [
        [0,   '#2196F3'], 
        [20,  '#4CAF50'], 
        [40,  '#FFC107'], 
        [60,  '#FF9800'], 
        [80,  '#F44336'], 
        [100, '#9C27B0']
        ],
    'THROTTLE_POS': [
        [0,   '#2196F3'], 
        [15,  '#4CAF50'], 
        [30,  '#FFC107'], 
        [50,  '#FF9800'], 
        [75,  '#F44336'], 
        [100, '#9C27B0']
        ],
    'MAF':          [
        [0,   '#2196F3'], 
        [10,  '#4CAF50'], 
        [25,  '#FFC107'], 
        [35,  '#FF9800'], 
        [50,  '#F44336'], 
        [70,  '#9C27B0']
        ],
    'KNOCK_RETARD': [
        [0,  '#4CAF50'], 
        [1,  '#FFC107'], 
        [3,  '#FF9800'], 
        [5,  '#F44336'], 
        [10, '#9C27B0']
        ],
}


def build_map_panel(geojson_path: Path) -> str:
    """Строит HTML-панель карты для встраивания в единый отчёт.

    Args:
        geojson_path: Путь к .geojson файлу.

    Returns:
        HTML-строка панели с картой, или пустая строка если файл недоступен.
    """
    if _jinja_env is None:
        return ''

    if not geojson_path or not geojson_path.is_file():
        return ''

    try:
        with open(geojson_path, 'r', encoding='utf-8') as f:
            geojson_data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return ''

    features = geojson_data.get('features', [])
    if not features:
        return ''

    # Строим словари с переведёнными метками (вызывается при каждом запросе, после set_language())
    popup_fields = {
        'TIME':         t('map.popup.TIME'),
        'SPEED':        t('map.popup.SPEED'),
        'RPM':          t('map.popup.RPM'),
        'COOLANT_TEMP': t('map.popup.COOLANT_TEMP'),
        'MAF':          t('map.popup.MAF'),
        'THROTTLE_POS': t('map.popup.THROTTLE_POS'),
        'ENGINE_LOAD':  t('map.popup.ENGINE_LOAD'),
        'LTFT':         t('map.popup.LTFT'),
        'STFT':         t('map.popup.STFT'),
        'KNOCK_RETARD': t('map.popup.KNOCK_RETARD'),
    }
    color_schemes = {
        k: {'label': t(f'map.color_labels.{k}'), 'stops': stops}
        for k, stops in _COLOR_STOPS.items()
    }

    # Вычисляем BBOX (только по LineString-отрезкам, Point-фичи пропускаем)
    lats, lons = [], []
    for feat in features:
        geom = feat.get('geometry', {})
        if geom.get('type') != 'LineString':
            continue
        coords = geom.get('coordinates', [])
        for lon, lat in coords:
            lats.append(lat)
            lons.append(lon)

    if not lats:
        return ''

    min_lat, max_lat = min(lats), max(lats)
    min_lon, max_lon = min(lons), max(lons)

    # Расширяем BBOX на 10%
    lat_pad = max((max_lat - min_lat) * 0.1, 0.002)
    lon_pad = max((max_lon - min_lon) * 0.1, 0.002)
    bbox = [
        [min_lat - lat_pad, min_lon - lon_pad],
        [max_lat + lat_pad, max_lon + lon_pad],
    ]

    # Определяем, какие параметры реально присутствуют в данных
    available_keys = set()
    for feat in features:
        props = feat.get('properties', {})
        for key in color_schemes:
            if f'{key}_mean' in props:
                available_keys.add(key)

    # Фильтруем схемы: только доступные параметры, SPEED первый (по умолчанию)
    ordered_keys = ['SPEED'] + [k for k in color_schemes if k != 'SPEED' and k in available_keys]
    ordered_keys = [k for k in ordered_keys if k in available_keys]

    if not ordered_keys:
        ordered_keys = ['SPEED']

    context = {
        'csp_title':          t('map.csp_warning_title'),
        'csp_body':           t('map.csp_warning_body'),
        'color_select_label': t('map.color_select_label'),
        'color_scheme_options': [(k, color_schemes[k]['label']) for k in ordered_keys],
        'color_schemes_json': json.dumps({k: color_schemes[k] for k in ordered_keys}, ensure_ascii=False),
        'popup_fields_json':  json.dumps(popup_fields, ensure_ascii=False),
        'geojson_json':       json.dumps(geojson_data, ensure_ascii=False),
        'bbox_json':          json.dumps(bbox),
        'route_start_json':   json.dumps(t('map.route_start')),
        'route_end_json':     json.dumps(t('map.route_end')),
        'dtc_increase_json':  json.dumps({
            'title':       t('map.dtc_increase.title'),
            'stall_title': t('map.dtc_increase.stall_title'),
            'count_label': t('map.dtc_increase.count_label'),
            'delta_label': t('map.dtc_increase.delta_label'),
        }, ensure_ascii=False),
        'map_js':             _MAP_JS,
    }

    return _jinja_env.get_template('build_map.j2').render(context)
