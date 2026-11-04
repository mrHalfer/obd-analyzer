#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GUI для анализатора OBD-II (запускается analyze_obd.py без пути до CSV).

Отличие от CLI: недостающие пакеты предлагаются к установке диалогом и
ставятся через pip после согласия пользователя (схема из animatron.py);
перепроверка импортом после установки обязательна. Все долгие действия
выполняются в фоновом потоке, вывод — в текстовое поле окна.

Язык интерфейса: при первом запуске определяется по языку системы
(ru → русский, иначе английский), переключается в окне (Русский/English)
и сохраняется в gui_config.json рядом с программой (файл в .gitignore).
Язык отчётов следует языку интерфейса. Все строки GUI — через t('gui.*').

Запуск GUI напрямую:  python gui.py
"""

import importlib
import json
import logging
import os
import queue
import sys
import threading
import traceback
from pathlib import Path
from typing import Optional

import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk

_ROOT = Path(__file__).parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import deps
from translation import get_language, set_language, t

# Локальный конфиг GUI (язык и пр.) — НЕ коммитится, см. .gitignore
CONFIG_PATH = _ROOT / 'gui_config.json'
# Языки, доступные в переключателе интерфейса (нативные названия не переводятся)
GUI_LANGS: dict = {'ru': 'Русский', 'en': 'English'}

# Форматы отчётов: ключи совпадают с deps.FORMAT_PACKAGES, подпись — t('gui.fmt.<ключ>')
FORMAT_KEYS = ['csv', 'png', 'html', 'pdf', 'geojson', 'xls']


def detect_system_language() -> str:
    """Код языка интерфейса по системе: 'ru' для русской локали, иначе 'en'."""
    if sys.platform == 'win32':
        try:
            import ctypes
            lang_id = ctypes.windll.kernel32.GetUserDefaultUILanguage()
            return 'ru' if (lang_id & 0x3FF) == 0x19 else 'en'  # 0x19 = Russian
        except Exception:
            pass
    for var in ('LANGUAGE', 'LC_ALL', 'LC_MESSAGES', 'LANG'):
        if os.environ.get(var, '').lower().startswith('ru'):
            return 'ru'
    return 'en'


def load_language(config_path: Optional[Path] = None) -> Optional[str]:
    """Сохранённый язык из конфига; None, если конфиг отсутствует/битый/неизвестный код."""
    path = Path(config_path) if config_path else CONFIG_PATH
    try:
        with open(path, encoding='utf-8') as f:
            code = json.load(f).get('language')
    except (OSError, ValueError):
        return None
    return code if code in GUI_LANGS else None


def save_language(code: str, config_path: Optional[Path] = None) -> None:
    """Пишет выбранный язык в конфиг; при недоступности диска молча продолжает работу."""
    path = Path(config_path) if config_path else CONFIG_PATH
    try:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump({'language': code}, f, ensure_ascii=False, indent=2)
    except OSError:
        pass


class _QueueLogHandler(logging.Handler):
    """Перенаправляет записи logging в очередь GUI (печатает поток окна)."""

    def __init__(self, app: 'ObdApp'):
        super().__init__(level=logging.INFO)
        self.app = app
        self.setFormatter(logging.Formatter('%(message)s'))

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.app.log(self.format(record))
        except Exception:
            pass


class ObdApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.q: 'queue.Queue' = queue.Queue()
        self._running = False
        self._tr: list = []  # [(widget, ключ t())] — перетекстичиваются при смене языка

        root.geometry('880x600')
        root.minsize(700, 480)

        pad = {'padx': 8, 'pady': 4}

        # --- Папки ---
        top = ttk.Frame(root)
        top.pack(fill='x', **pad)
        self.in_var = tk.StringVar()
        self.out_var = tk.StringVar()
        self._reg(ttk.Label(top), 'gui.in_folder').grid(row=0, column=0, sticky='w')
        ttk.Entry(top, textvariable=self.in_var).grid(row=0, column=1, sticky='ew', padx=6)
        self._reg(ttk.Button(top, command=lambda: self._browse(self.in_var)),
                  'gui.browse').grid(row=0, column=2)
        self._reg(ttk.Label(top), 'gui.out_folder').grid(row=1, column=0, sticky='w')
        ttk.Entry(top, textvariable=self.out_var).grid(row=1, column=1, sticky='ew', padx=6)
        self._reg(ttk.Button(top, command=lambda: self._browse(self.out_var)),
                  'gui.browse').grid(row=1, column=2)
        self._reg(ttk.Label(top, foreground='#666'), 'gui.out_hint') \
            .grid(row=2, column=1, sticky='w', padx=6)
        top.columnconfigure(1, weight=1)

        # --- Форматы отчётов ---
        self.fmt_frame = ttk.LabelFrame(root)
        self._reg(self.fmt_frame, 'gui.formats').pack(fill='x', **pad)
        self.fmt_vars: dict[str, tk.BooleanVar] = {}
        for i, key in enumerate(FORMAT_KEYS):
            var = tk.BooleanVar(value=(key != 'xls'))
            self.fmt_vars[key] = var
            self._reg(ttk.Checkbutton(self.fmt_frame, variable=var),
                      f'gui.fmt.{key}').grid(row=0, column=i, padx=8, pady=4)

        # --- Кнопки запуска + переключатель языка ---
        btns = ttk.Frame(root)
        btns.pack(fill='x', **pad)
        self.btn_all = self._reg(ttk.Button(btns, command=lambda: self._start('all')),
                                 'gui.btn_all')
        self.btn_new = self._reg(ttk.Button(btns, command=lambda: self._start('new')),
                                 'gui.btn_new')
        self.btn_cmp = self._reg(ttk.Button(btns, command=lambda: self._start('compare')),
                                 'gui.btn_cmp')
        self.btn_all.pack(side='left', padx=4)
        self.btn_new.pack(side='left', padx=4)
        self.btn_cmp.pack(side='left', padx=4)

        self.lang_var = tk.StringVar(value=GUI_LANGS.get(get_language(), GUI_LANGS['en']))
        self._reg(ttk.Label(btns), 'gui.language').pack(side='right', padx=(0, 4))
        self.lang_menu = ttk.OptionMenu(btns, self.lang_var, self.lang_var.get(),
                                        *GUI_LANGS.values(), command=self._on_language)
        self.lang_menu.pack(side='right')

        # --- Лог ---
        self.text = scrolledtext.ScrolledText(root, state='disabled', wrap='word',
                                              font=('Consolas', 9))
        self.text.pack(fill='both', expand=True, **pad)

        # --- Статус-бар ---
        self.status = tk.StringVar(value=t('gui.status_ready'))
        ttk.Label(root, textvariable=self.status, relief='sunken', anchor='w') \
            .pack(fill='x', side='bottom')

        self._retranslate()  # устанавливает title и тексты всех self._tr

        # logging модулей (после импорта analyze_obd) — в окно
        handler = _QueueLogHandler(self)
        handler.setLevel(logging.INFO)
        logging.getLogger().addHandler(handler)

        root.protocol('WM_DELETE_WINDOW', self._on_close)
        root.after(80, self._poll)

    # ==================== Язык интерфейса ====================

    def _reg(self, widget, key: str):
        """Подписывает widget переводом t(key) и регистрирует для перетекстинга."""
        widget.configure(text=t(key))
        self._tr.append((widget, key))
        return widget

    def _on_language(self, native: str) -> None:
        """Выбор в OptionMenu: сохранить, применить, перетекстичить окно."""
        code = next((c for c, n in GUI_LANGS.items() if n == native), 'en')
        if code == get_language():
            return
        save_language(code)
        set_language(code)
        self._retranslate()

    def _retranslate(self) -> None:
        self.root.title(t('gui.title'))
        for widget, key in self._tr:
            widget.configure(text=t(key))
        self.status.set(t('gui.status_running') if self._running else t('gui.status_ready'))

    # ==================== Вспомогательное (потокобезопасное) ====================

    def log(self, line: str) -> None:
        """Пишет строку в лог окна (безопасно из любого потока)."""
        self.q.put(('log', str(line)))

    def _ask(self, title: str, message: str) -> bool:
        """Вопрос YES/NO из рабочего потока; ответ даёт поток окна."""
        ev = threading.Event()
        box: dict = {}
        self.q.put(('ask', title, message, ev, box))
        ev.wait()
        return bool(box.get('ok'))

    def _post(self, fn) -> None:
        """Выполняет fn в потоке окна."""
        self.q.put(('call', fn))

    def _browse(self, var: tk.StringVar) -> None:
        start = var.get() or None
        chosen = filedialog.askdirectory(title=t('gui.select_folder'), initialdir=start)
        if chosen:
            var.set(str(Path(chosen)))

    def _checked_formats(self, restrict: Optional[set[str]] = None) -> set[str]:
        sel = {k for k, v in self.fmt_vars.items() if v.get()}
        return sel if restrict is None else sel & restrict

    # ==================== Зависимости ====================

    def _ensure_packages(self, packages: list[str]) -> tuple[list[str], bool]:
        """Возвращает (неустановленные пакеты, что что-то удалось поставить).

        Диалог согласия показывается в потоке окна; установка идёт pip-ом с
        потоковым логом; после — ПЕРЕПРОВЕРКА импортом (pip 0 != импортируется).
        """
        missing = deps.missing_packages(sorted(set(packages)))
        if not missing:
            return [], False
        text = t('gui.packages_text', packages=', '.join(missing),
                 cmd=deps.pip_install_hint(*missing))
        if not self._ask(t('gui.packages_title'), text):
            self.log(t('gui.install_declined', cmd=deps.pip_install_hint(*missing)))
            return missing, False
        self.log(t('gui.installing', packages=', '.join(missing)))
        ok, tail = deps.install_packages(missing, log=self.log)
        still = deps.missing_packages(missing)
        if still:
            self.log(t('gui.install_failed', packages=', '.join(still)))
            if tail:
                self.log(tail)
        elif not ok:
            self.log(t('gui.install_error'))
        else:
            self.log(t('gui.install_done'))
        return still, bool(ok and not still)

    @staticmethod
    def _formats_without_deps(fmts: set[str], still: list[str]) -> set[str]:
        """Форматы, чьи пакеты точно установлены (сбоившие — вычёркиваются)."""
        still_set = set(still)
        return {f for f in fmts
                if not any(p in still_set for p in deps.FORMAT_PACKAGES.get(f, []))}

    # ==================== Запуск действий ====================

    def _start(self, mode: str) -> None:
        if self._running:
            return
        if not self.in_var.get().strip() and not self.out_var.get().strip():
            messagebox.showerror(t('gui.folders_title'), t('gui.folders_text'),
                                 parent=self.root)
            return
        self._running = True
        self.status.set(t('gui.status_running'))
        threading.Thread(target=self._worker, args=(mode,), daemon=True).start()

    def _worker(self, mode: str) -> None:
        try:
            self._run_mode(mode)
        except Exception:
            self.log(t('gui.error_prefix') + traceback.format_exc())
        finally:
            self._running = False
            self._post(lambda: self.status.set(t('gui.status_ready')))

    def _run_mode(self, mode: str) -> None:
        in_dir_s = self.in_var.get().strip().strip('"')
        out_dir_s = self.out_var.get().strip().strip('"')

        if mode == 'compare':
            work_dir = Path(out_dir_s or in_dir_s)
            if not work_dir.is_dir():
                self.log(t('gui.compare_hint'))
                return
            fmts = self._checked_formats({'png', 'html', 'pdf', 'xls'})
        else:
            in_dir = Path(in_dir_s)
            if not in_dir.is_dir():
                self.log(t('gui.no_in_folder', path=in_dir_s))
                return
            work_dir = Path(out_dir_s) if out_dir_s else in_dir
            fmts = self._checked_formats()

        # Зависимости: ядерные + пакеты выбранных форматов
        pkgs: list[str] = list(deps.CORE_PACKAGES)
        for f in sorted(fmts):
            pkgs += deps.FORMAT_PACKAGES.get(f, [])
        still, installed_something = self._ensure_packages(pkgs)
        if deps.missing_packages(deps.CORE_PACKAGES):
            self.log(t('gui.core_missing', cmd=deps.pip_install_hint(*deps.CORE_PACKAGES)))
            return
        fmts = self._formats_without_deps(fmts, still)
        if still:
            # Визуально снять чекбоксы форматов, оставшихся без пакетов
            lost = {f for f in deps.FORMAT_PACKAGES if f in self.fmt_vars
                    and any(p in still for p in deps.FORMAT_PACKAGES[f])}

            def uncheck(lost=lost):
                for key in lost:
                    self.fmt_vars[key].set(False)
            self._post(uncheck)

        # Импорт оркестратора — после того как пакеты на месте. Если что-то
        # доустановили позже первого импорта — перезагрузить модуль, чтобы
        # его защищённые импорты (build_png и т.п.) подхватили новинки.
        ao = sys.modules.get('analyze_obd')
        if ao is not None and installed_something:
            ao = importlib.reload(ao)
        elif ao is None:
            ao = importlib.import_module('analyze_obd')
        ao.set_language(get_language())

        if mode == 'compare':
            self._compare(ao, work_dir, fmts)
            return

        csv_files = ao.find_csv_files(in_dir)
        if not csv_files:
            self.log(t('gui.csv_not_found', path=in_dir))
            return
        self.log(t('gui.csv_found', count=len(csv_files)))

        ok_count = 0
        for f in csv_files:
            if mode == 'new' and (work_dir / f'{f.stem}_metrics.csv').exists():
                self.log(t('gui.skip_exists', file=f.name))
                ok_count += 1
                continue
            if ao.process_file(
                f,
                no_csv='csv' not in fmts,
                no_png='png' not in fmts,
                no_plot='html' not in fmts,
                no_html='html' not in fmts,
                no_pdf='pdf' not in fmts,
                no_geojson='geojson' not in fmts,
                no_map='geojson' not in fmts,
                output_dir=work_dir,
            ):
                ok_count += 1
        self.log(t('gui.processed', ok=ok_count, total=len(csv_files)))

        if len(list(work_dir.glob('*_metrics.csv'))) >= 2:
            self._compare(ao, work_dir, fmts)

    def _compare(self, ao, directory: Path, fmts: set[str]) -> None:
        ao._run_compare(directory,
                        no_png='png' not in fmts,
                        no_html='html' not in fmts,
                        no_pdf='pdf' not in fmts,
                        no_xls='xls' not in fmts)

    # ==================== Поток окна ====================

    def _poll(self) -> None:
        try:
            while True:
                item = self.q.get_nowait()
                kind = item[0]
                if kind == 'log':
                    self._append(item[1])
                elif kind == 'ask':
                    _, title, msg, ev, box = item
                    box['ok'] = messagebox.askyesno(title, msg, parent=self.root)
                    ev.set()
                elif kind == 'call':
                    item[1]()
        except queue.Empty:
            pass
        for b in (self.btn_all, self.btn_new, self.btn_cmp):
            if self._running:
                b.state(['disabled'])
            else:
                b.state(['!disabled'])
        self.root.after(80, self._poll)

    def _append(self, text: str) -> None:
        self.text.configure(state='normal')
        self.text.insert('end', text + '\n')
        self.text.see('end')
        self.text.configure(state='disabled')

    def _on_close(self) -> None:
        if self._running and not messagebox.askyesno(
                t('gui.close_title'), t('gui.close_text'), parent=self.root):
            return
        self.root.destroy()


def run_gui(root: Optional[tk.Tk] = None) -> int:
    """Запускает GUI; возвращает код выхода процесса (для analyze_obd.py)."""
    own = root is None
    set_language(load_language() or detect_system_language())
    if own:
        root = tk.Tk()
    ObdApp(root)
    if own:
        root.mainloop()
    return 0


if __name__ == '__main__':
    sys.exit(run_gui())
