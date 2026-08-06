# -*- coding: utf-8 -*-
"""Колорбар с правкой диапазона: перетаскивание ручек + ввод значений по двойному клику.

Перенесено из основного проекта автоматизации (ui/components/editable_colorbar.py)
без изменений, чтобы шкала ближнего поля вела себя ровно так же, как в режиме
«Измерение лучей АФАР».
"""

from PyQt5 import QtWidgets, QtCore
import pyqtgraph as pg


class EditableColorBarItem(pg.ColorBarItem):
    """ColorBarItem с сигналом двойного клика (для ручного ввода диапазона)."""

    sigDoubleClicked = QtCore.pyqtSignal()

    def mouseDoubleClickEvent(self, ev):
        self.sigDoubleClicked.emit()
        ev.accept()


def prompt_colorbar_range(parent, units, lo, hi, auto_label, auto_checked):
    """Диалог ввода диапазона шкалы.

    Возвращает ``('auto',)`` (выбран авто/по умолчанию), ``('manual', lo, hi)``
    (заданы значения) или ``None`` (отмена).
    """
    dlg = QtWidgets.QDialog(parent)
    dlg.setWindowTitle(f'Диапазон шкалы, {units}')
    form = QtWidgets.QFormLayout(dlg)

    auto_cb = QtWidgets.QCheckBox(auto_label)
    auto_cb.setChecked(auto_checked)
    min_sb = QtWidgets.QDoubleSpinBox()
    min_sb.setRange(-1e6, 1e6)
    min_sb.setDecimals(2)
    min_sb.setValue(float(lo))
    max_sb = QtWidgets.QDoubleSpinBox()
    max_sb.setRange(-1e6, 1e6)
    max_sb.setDecimals(2)
    max_sb.setValue(float(hi))
    form.addRow(auto_cb)
    form.addRow('Минимум:', min_sb)
    form.addRow('Максимум:', max_sb)

    def _sync(_=None):
        enabled = not auto_cb.isChecked()
        min_sb.setEnabled(enabled)
        max_sb.setEnabled(enabled)
    auto_cb.toggled.connect(_sync)
    _sync()

    btns = QtWidgets.QDialogButtonBox(
        QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
    btns.accepted.connect(dlg.accept)
    btns.rejected.connect(dlg.reject)
    form.addRow(btns)

    if dlg.exec_() != QtWidgets.QDialog.Accepted:
        return None
    if auto_cb.isChecked():
        return ('auto',)
    lo2, hi2 = float(min_sb.value()), float(max_sb.value())
    if hi2 - lo2 < 1e-9:
        hi2 = lo2 + 1e-6
    return ('manual', lo2, hi2)
