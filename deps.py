#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Проверка зависимостей и автоустановка (схема взята из animatron.py).

Режимы:
- CLI (запуск с путём до CSV): отсутствующие пакеты только проверяются,
  в консоль печатается точная команда установки, ничего не ставится.
- GUI (запуск без пути): перед действиями недостающие пакеты предлагаются
  к установке диалогом, после согласия пользователя ставятся через pip и
  ПЕРЕПРОВЕРЯЮТСЯ импортом (код возврата pip 0 не гарантирует, что пакет
  импортируется - конфликты версий).
"""

import importlib
import importlib.util
import subprocess
import sys
from typing import Callable, Optional

# Жёсткие зависимости: без них ядро анализа не работает вообще
CORE_PACKAGES: list[str] = ['numpy', 'pandas']

# Формат отчёта (чекбокс GUI) -> import-пакеты, нужные для его генерации.
# Имена pip-пакетов здесь совпадают с import-именами.
FORMAT_PACKAGES: dict[str, list[str]] = {
    'csv':     [],
    'png':     ['matplotlib'],
    'html':    ['plotly', 'jinja2'],
    'pdf':     ['reportlab'],
    'geojson': [],
    'xls':     ['openpyxl'],
}


def pip_install_hint(*packages: str) -> str:
    """Точная команда установки через текущий интерпретатор (не 'python')."""
    return f'"{sys.executable}" -m pip install ' + ' '.join(packages)


class MissingDependencyError(ModuleNotFoundError):
    """Нужного стороннего пакета нет; атрибут .package - имя pip-пакета.

    Наследуется от ModuleNotFoundError, поэтому общие обработчики
    `except ModuleNotFoundError` ловят его автоматически.
    """

    def __init__(self, package: str, message: str):
        super().__init__(message)
        self.package = package


def module_available(name: str) -> bool:
    """True, если модуль найден (без фактического импорта)."""
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def missing_packages(packages: list[str]) -> list[str]:
    """Список пакетов из packages, которых нет в окружении."""
    return [p for p in packages if not module_available(p)]


def require(module_name: str, purpose: str = '') -> object:
    """Импортирует модуль; при отсутствии - MissingDependencyError с командой.

    Использовать вместо прямого `import` для опциональных зависимостей,
    чтобы вызывающий код получал человекочитаемое сообщение вместо голой
    ModuleNotFoundError.
    """
    try:
        return importlib.import_module(module_name)
    except ImportError as exc:
        reason = f' ({purpose})' if purpose else ''
        raise MissingDependencyError(
            module_name,
            f'Не найден пакет {module_name}{reason}. '
            f'Установите командой: {pip_install_hint(module_name)}',
        ) from exc


def install_packages(packages: list[str],
                     log: Optional[Callable[[str], None]] = None) -> tuple[bool, str]:
    """Синхронно ставит пакеты через pip, печатая вывод построчно.

    Вызывать из фонового потока (долгая операция). По возвращении кэши
    поискчиков импорта сброшены. Возвращает (успех, хвост вывода при ошибке).
    """
    writer = log if log is not None else (lambda line: print(line, flush=True))
    cmd = [sys.executable, '-m', 'pip', 'install', *packages]
    writer(f'$ {" ".join(cmd)}')
    tail: list[str] = []
    try:
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1,
        )
        assert proc.stdout is not None
        for line in proc.stdout:
            line = line.rstrip()
            if line:
                writer(line)
                tail.append(line)
                tail = tail[-20:]
        proc.wait()
        ok = proc.returncode == 0
    except OSError as exc:
        writer(f'Не удалось запустить pip: {exc}')
        return False, str(exc)

    importlib.invalidate_caches()
    if not ok:
        return False, '\n'.join(tail)
    return True, ''
