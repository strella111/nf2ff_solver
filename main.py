# -*- coding: utf-8 -*-
"""Точка входа автономной утилиты «Дальняя зона (расчёт ДН)».

Открывает окно расчёта диаграммы направленности в дальней зоне (NF→FF)
из результатов планарного сканирования (Beam№*.xlsx + scan_params.json).
"""
import sys

from PyQt5 import QtCore, QtWidgets

from far_zone.app_style import apply_app_theme
from far_zone.far_field_dialog import FarFieldDialog


def main():
    QtWidgets.QApplication.setAttribute(QtCore.Qt.AA_EnableHighDpiScaling, True)
    QtWidgets.QApplication.setAttribute(QtCore.Qt.AA_UseHighDpiPixmaps, True)
    app = QtWidgets.QApplication(sys.argv)
    apply_app_theme(app)

    win = FarFieldDialog()
    win.setWindowTitle('Дальняя зона (расчёт ДН)')
    win.show()
    sys.exit(app.exec_())


if __name__ == '__main__':
    main()
