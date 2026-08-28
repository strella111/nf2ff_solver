# -*- coding: utf-8 -*-
"""Точка входа автономной утилиты «Дальняя зона (расчёт ДН)».

Открывает окно расчёта диаграммы направленности в дальней зоне (NF→FF)
из результатов планарного сканирования (Beam№*.xlsx + scan_params.json).
"""
import os
import sys
from pathlib import Path

import pyqtgraph as pg
from PyQt5 import QtCore, QtWidgets
from loguru import logger

from far_zone import __version__
from far_zone.app_style import apply_app_theme
from far_zone.far_field_dialog import FarFieldWindow
from far_zone.icon_utils import window_icon


def setup_logging():
    """Писать лог в файл рядом с данными пользователя.

    Собранный .exe идёт без консоли (console=False в FarZone.spec), поэтому
    стандартный вывод loguru уходил в никуда: разбираться, почему не открылся
    файл, было не по чему.
    """
    base = os.environ.get('LOCALAPPDATA') or str(Path.home())
    log_dir = Path(base) / 'FarZone' / 'logs'
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        logger.add(log_dir / 'farzone_{time:YYYY-MM-DD}.log',
                   rotation='5 MB', retention='30 days',
                   encoding='utf-8', enqueue=True,
                   backtrace=True, diagnose=False)
        logger.info(f'FarZone {__version__}, лог: {log_dir}')
    except Exception as exc:      # некуда писать — не повод не запускаться
        logger.warning(f'Не удалось включить запись лога в файл: {exc}')


def main():
    QtWidgets.QApplication.setAttribute(QtCore.Qt.AA_EnableHighDpiScaling, True)
    QtWidgets.QApplication.setAttribute(QtCore.Qt.AA_UseHighDpiPixmaps, True)
    app = QtWidgets.QApplication(sys.argv)
    setup_logging()
    apply_app_theme(app)

    # Сглаживание кривых: без него линии ДН заметно ступенчатые на пологих
    # участках. Точек в трассе порядка тысячи — на скорости не сказывается.
    pg.setConfigOptions(antialias=True)

    app.setWindowIcon(window_icon())

    win = FarFieldWindow()
    win.setWindowTitle(f'Дальняя зона (расчёт ДН) v{__version__}')
    win.show()
    sys.exit(app.exec_())


if __name__ == '__main__':
    main()
