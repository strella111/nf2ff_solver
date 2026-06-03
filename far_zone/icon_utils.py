# -*- coding: utf-8 -*-
from PyQt5 import QtCore, QtGui
import qtawesome as qta

from .design_tokens import ICON_DEFAULT, ICON_DISABLED


ICON_ALIASES = {
    'add': 'fa5s.plus',
    'apply': 'fa5s.sliders-h',
    'back': 'fa5s.chevron-left',
    'check-all': 'fa5s.check-double',
    'clear': 'fa5s.times',
    'copy': 'fa5s.copy',
    'connect': 'fa5s.plug',
    'collapse-down': 'fa5s.chevron-down',
    'collapse-up': 'fa5s.chevron-up',
    'disconnect': 'fa5s.unlink',
    'filter': 'fa5s.filter',
    'folder-open': 'fa5s.folder-open',
    'forward': 'fa5s.chevron-right',
    'module': 'fa5s.microchip',
    'move': 'fa5s.location-arrow',
    'pause': 'fa5s.pause',
    'play': 'fa5s.play',
    'plots': 'fa5s.chart-area',
    'power': 'fa5s.power-off',
    'results': 'fa5s.table',
    'remove': 'fa5s.minus',
    'save': 'fa5s.save',
    'settings': 'fa5s.sliders-h',
    'spinner': 'fa5s.spinner',
    'stop': 'fa5s.stop',
    'sync': 'fa5s.clock',
    'analyzer': 'fa5s.chart-line',
    'trash': 'fa5s.trash-alt',
    'cursor-v': 'fa5s.grip-lines-vertical',
    'cursor-h': 'fa5s.grip-lines',
    'autoscale': 'fa5s.expand-arrows-alt',
    'normalize': 'fa5s.wave-square',
    'csv': 'fa5s.file-csv',
    'png': 'fa5s.image',
    'max-global': 'fa5s.mountain',
    'max-local': 'fa5s.search-plus',
}


def app_icon(name, color=ICON_DEFAULT, disabled_color=ICON_DISABLED) -> QtGui.QIcon:
    icon_name = ICON_ALIASES.get(name, name)
    return qta.icon(icon_name, color=color, color_disabled=disabled_color)


def set_button_icon(button, name, size=16, color=ICON_DEFAULT) -> None:
    icon = app_icon(name, color=color)
    button.setIcon(icon)
    button.setIconSize(QtCore.QSize(size, size))
