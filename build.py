#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Сборка FarZone в один .exe внутри изолированного venv.

Запуск:
    python build.py            # обычная сборка
    python build.py --clean    # пересоздать venv с нуля

Что делает скрипт:
    1. Создаёт виртуальное окружение .venv (если его ещё нет).
    2. Ставит зависимости из requirements.txt ТОЛЬКО в это окружение
       (глобальный Python не трогается).
    3. Запускает PyInstaller из venv по FarZone.spec.

Результат: dist/FarZone.exe
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV_DIR = ROOT / ".venv"
REQUIREMENTS = ROOT / "requirements.txt"
SPEC = ROOT / "FarZone.spec"


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


def ensure_venv(clean: bool) -> None:
    if clean and VENV_DIR.exists():
        print("[*] Удаляю старое окружение .venv ...")
        shutil.rmtree(VENV_DIR)

    if not venv_python().exists():
        print("[1/3] Создаю виртуальное окружение .venv ...")
        run([sys.executable, "-m", "venv", str(VENV_DIR)])
    else:
        print("[1/3] Виртуальное окружение .venv уже существует.")


def install_deps() -> None:
    print("[2/3] Устанавливаю зависимости в .venv ...")
    py = venv_python()
    run([py, "-m", "pip", "install", "--upgrade", "pip"])
    run([py, "-m", "pip", "install", "-r", str(REQUIREMENTS)])


def build() -> None:
    print("[3/3] Сборка PyInstaller ...")
    run([venv_python(), "-m", "PyInstaller", "--noconfirm", "--clean", str(SPEC)])


def main() -> None:
    parser = argparse.ArgumentParser(description="Сборка FarZone в .exe через venv.")
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

    ensure_venv(clean=args.clean)
    install_deps()
    build()

    print("\n=== Готово: dist/FarZone.exe ===")


if __name__ == "__main__":
    main()
