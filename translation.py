#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Модуль локализации для анализа OBD-II данных.

Загружает строки из lang/{code}.json и предоставляет функцию t()
для получения переведённых строк по точечному ключу.
По умолчанию используется русский язык.

Файлы языков: lang/ru.json, lang/en.json, lang/de.json, ...
Новый язык добавляется созданием файла lang/{code}.json.

Использование:
    from translation import t, set_language
    set_language('en')
    print(t('html.tabs.summary'))  # → 'Summary'
    print(t('csv.joker.stalled_reason', rpm=400))  # → 'Engine stalled (RPM < 400)'
"""

import json
import logging
from pathlib import Path

_ROOT = Path(__file__).parent / 'lang'

logger = logging.getLogger(__name__)

_strings: dict = {}
_fallback: dict = {}
_current_lang: str = 'ru'


def _lang_path(code: str) -> Path:
    return _ROOT / f'{code}.json'


def _load_json(path: Path) -> dict:
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def _ensure_fallback() -> None:
    """Загружает русский язык как fallback (один раз)."""
    global _fallback
    if not _fallback:
        _fallback = _load_json(_lang_path('ru'))


def get_language() -> str:
    """Возвращает текущий код языка."""
    return _current_lang


def list_languages() -> list[str]:
    """Возвращает список доступных кодов языков (по наличию файлов lang/*.json)."""
    return sorted(p.stem for p in _ROOT.glob('*.json'))


def set_language(code: str) -> None:
    """Устанавливает язык отчётов.

    Args:
        code: Код языка ('ru', 'en', ...). При отсутствии файла используется 'ru'.
              Доступные языки можно узнать через list_languages().
    """
    global _strings, _current_lang
    _ensure_fallback()
    path = _lang_path(code)
    if not path.exists():
        available = ', '.join(list_languages())
        logger.warning(f'⚠️ Язык "{code}" не найден (доступны: {available}), используется русский')
        _strings = _fallback
        _current_lang = 'ru'
        return
    _strings = _load_json(path)
    _current_lang = code


def _get_dotted(key: str, d: dict) -> str | None:
    """Обходит вложенный словарь по точечному пути."""
    cur: object = d
    for part in key.split('.'):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return None
    return str(cur) if not isinstance(cur, dict) else None


def t(key: str, **kwargs: object) -> str:
    """Возвращает строку по точечному ключу с опциональной подстановкой параметров.

    Поиск: текущий язык → русский fallback → сам ключ как строка.

    Args:
        key: Точечный путь, например 'html.tabs.summary' или 'csv.profile.speed_min'.
        **kwargs: Параметры для format_map (например rpm=400).

    Returns:
        Переведённая строка.

    Examples:
        t('html.tabs.summary')                       → 'Сводка'
        t('csv.joker.stalled_reason', rpm=400)       → 'Двигатель заглох (RPM < 400)'
        t('png.temperatures.coolant_norm', temp=90)  → 'Норма ОЖ (90°C)'
    """
    _ensure_fallback()

    # Ищем в текущем языке, затем в fallback
    val = _get_dotted(key, _strings) or _get_dotted(key, _fallback) or key

    if kwargs:
        try:
            val = val.format_map(kwargs)
        except (KeyError, ValueError):
            pass
    return val
