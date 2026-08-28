#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Сборка FarZone в один .exe внутри изолированного venv.

Запуск:
    python build.py              # сборка с текущей версией
    python build.py 1.2.0        # задать версию и собрать
    python build.py 1.2.0 --clean  # + пересоздать venv с нуля

Что делает скрипт:
    1. (опц.) Записывает переданную версию в far_zone/__init__.py.
    2. Создаёт виртуальное окружение .venv (если его ещё нет).
    3. Ставит зависимости из requirements.txt ТОЛЬКО в это окружение
       (глобальный Python не трогается).
    4. Собирает иконку .exe из app.svg (build_icon.py).
    5. Запускает PyInstaller из venv по FarZone.spec.

Результат: dist/FarZone-<версия>.exe
"""
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV_DIR = ROOT / ".venv"
REQUIREMENTS = ROOT / "requirements.txt"
SPEC = ROOT / "FarZone.spec"
INIT_PY = ROOT / "far_zone" / "__init__.py"
_VERSION_RE = re.compile(r"""^__version__\s*=\s*['"]([^'"]+)['"]""", re.MULTILINE)


def venv_python() -> Path:
    """Путь к интерпретатору внутри venv (Windows / POSIX)."""
    if sys.platform == "win32":
        return VENV_DIR / "Scripts" / "python.exe"
    return VENV_DIR / "bin" / "python"


def run(cmd: list[str | Path]) -> None:
    """Запустить команду и упасть с понятной ошибкой при ненулевом коде."""
    printable = " ".join(str(c) for c in cmd)
    print(f"  $ {printable}")
    result = subprocess.run([str(c) for c in cmd], cwd=ROOT)
    if result.returncode != 0:
        sys.exit(f"*** ОШИБКА: команда завершилась с кодом {result.returncode} ***")


def read_version() -> str:
    m = _VERSION_RE.search(INIT_PY.read_text(encoding="utf-8"))
    if not m:
        sys.exit(f"Не найден __version__ в {INIT_PY}")
    return m.group(1)


def set_version(version: str) -> None:
    """Записать новую версию в far_zone/__init__.py."""
    text = INIT_PY.read_text(encoding="utf-8")
    if not _VERSION_RE.search(text):
        sys.exit(f"Не найден __version__ в {INIT_PY}")
    new_text = _VERSION_RE.sub(f"__version__ = '{version}'", text, count=1)
    INIT_PY.write_text(new_text, encoding="utf-8")
    print(f"[*] Версия установлена: {version}")


def ensure_venv(clean: bool) -> None:
    if clean and VENV_DIR.exists():
        print("[*] Удаляю старое окружение .venv ...")
        shutil.rmtree(VENV_DIR)

    if not venv_python().exists():
        print("[1/4] Создаю виртуальное окружение .venv ...")
        run([sys.executable, "-m", "venv", str(VENV_DIR)])
    else:
        print("[1/4] Виртуальное окружение .venv уже существует.")


def install_deps() -> None:
    print("[2/4] Устанавливаю зависимости в .venv ...")
    py = venv_python()
    run([py, "-m", "pip", "install", "--upgrade", "pip"])
    run([py, "-m", "pip", "install", "-r", str(REQUIREMENTS)])


def make_icon() -> None:
    """Собрать build/FarZone.ico из app.svg — иконку самого .exe.

    Не критично для сборки: если Qt в окружении не смог отрисовать SVG, exe
    соберётся с иконкой по умолчанию, а сборка не упадёт.
    """
    script = ROOT / "build_icon.py"
    if not script.exists():
        return
    print("[3/4] Готовлю иконку .exe ...")
    try:
        result = subprocess.run([str(venv_python()), str(script)], cwd=ROOT,
                                timeout=120)
    except subprocess.TimeoutExpired:
        # Страховка: иконка не то, ради чего стоит вешать сборку.
        print("    ! отрисовка иконки не уложилась в 120 с — пропускаю")
        return
    if result.returncode != 0:
        print("    ! иконку собрать не удалось — exe будет с иконкой по умолчанию")


def build() -> None:
    print("[4/4] Сборка PyInstaller ...")
    run([venv_python(), "-m", "PyInstaller", "--noconfirm", "--clean", str(SPEC)])


def main() -> None:
    parser = argparse.ArgumentParser(description="Сборка FarZone в .exe через venv.")
    parser.add_argument(
        "version",
        nargs="?",
        help="версия для сборки, напр. 1.2.0 (по умолчанию берётся из far_zone/__init__.py)",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="пересоздать .venv с нуля перед сборкой",
    )
    args = parser.parse_args()

    if not REQUIREMENTS.exists():
        sys.exit(f"Не найден {REQUIREMENTS}")
    if not SPEC.exists():
        sys.exit(f"Не найден {SPEC}")

    if args.version:
        set_version(args.version)
    version = read_version()
    print(f"[*] Сборка версии {version}")

    ensure_venv(clean=args.clean)
    install_deps()
    make_icon()
    build()

    print(f"\n=== Готово: dist/FarZone-{version}.exe ===")


if __name__ == "__main__":
    main()
