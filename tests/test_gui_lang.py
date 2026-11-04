#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Тесты языкового конфига GUI: автоопределение, чтение/запись gui_config.json.

Модуль gui тянет tkinter — в средах без него (например, slim-контейнер)
тесты пропускаются целиком через importorskip.
"""

import json

import pytest

pytest.importorskip('tkinter')

import gui  # noqa: E402


def test_detect_system_language_supported():
    assert gui.detect_system_language() in gui.GUI_LANGS


def test_load_language_missing_file(tmp_path):
    assert gui.load_language(tmp_path / 'absent.json') is None


def test_load_language_broken_json(tmp_path):
    p = tmp_path / 'gui_config.json'
    p.write_text('{это не json', encoding='utf-8')
    assert gui.load_language(p) is None


def test_load_language_unknown_code(tmp_path):
    p = tmp_path / 'gui_config.json'
    p.write_text('{"language": "xx"}', encoding='utf-8')
    assert gui.load_language(p) is None


def test_load_language_no_key(tmp_path):
    p = tmp_path / 'gui_config.json'
    p.write_text('{"other": 1}', encoding='utf-8')
    assert gui.load_language(p) is None


def test_save_load_roundtrip(tmp_path):
    p = tmp_path / 'gui_config.json'
    for code in sorted(gui.GUI_LANGS):
        gui.save_language(code, p)
        assert gui.load_language(p) == code
    data = json.loads(p.read_text(encoding='utf-8'))
    assert set(data) == {'language'}


def test_save_language_unwritable_path_no_raise(tmp_path):
    bad = tmp_path / 'no' / 'such' / 'dir' / 'gui_config.json'
    gui.save_language('ru', bad)  # не должен бросать


def test_gui_keys_complete():
    """Для каждого ключа gui.* из переключателя — перевод в en и de (не только ru-fallback)."""
    from translation import _lang_path, _load_json, list_languages

    def flat(d, prefix=''):
        out = set()
        for k, v in d.items():
            if isinstance(v, dict):
                out |= flat(v, f'{prefix}.{k}' if prefix else k)
            else:
                out.add(f'{prefix}.{k}' if prefix else k)
        return out

    base = flat(_load_json(_lang_path('ru')).get('gui', {}))
    assert base, 'секция gui пуста'
    for code in ('en', 'de'):
        assert code in list_languages()
        got = flat(_load_json(_lang_path(code)).get('gui', {}))
        assert base <= got, f'{code}: missing {sorted(base - got)}'
