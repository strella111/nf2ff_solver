# -*- coding: utf-8 -*-
"""Иконки приложения.

Основной источник — собственный набор SVG в ``styles/glyphs``: одна сетка
24×24, одна толщина штриха и метафоры под задачи именно этой утилиты
(маркеры на графике, поиск максимумов, нормировка к пику, сечение ДН).
Готовые шрифтовые наборы такого не дают: приходилось мешать FontAwesome с
Material, а «нормировка» и «локальный максимум» оказывались двумя похожими
волнами.

Цвет подставляется при отрисовке: в файлах стоит ``currentColor``, а
``app_icon`` заменяет его на нужный. Отсюда же берутся отдельные цвета для
выключенного и нажатого состояний — иконка на checkable-кнопке загорается
акцентом, а не остаётся серой.

Если глифа нет, имя уходит в ``qtawesome`` по таблице ``ICON_ALIASES``
(запасной путь; сам по себе набор SVG самодостаточен).
"""
import math
import sys
from pathlib import Path

from PyQt5 import QtCore, QtGui, QtSvg

from .design_tokens import (ICON_DEFAULT, ICON_DISABLED, ICON_RENDER_SIZES,
                            ICON_SM)

try:
    import qtawesome as qta
except ImportError:      # запасной путь недоступен — работаем на своих SVG
    qta = None


# Запасные соответствия для имён, которых нет в styles/glyphs.
ICON_ALIASES = {
    'add': 'fa5s.plus',
    'apply': 'fa5s.sliders-h',
    'back': 'fa5s.chevron-left',
    'clear': 'fa5s.times',
    'copy': 'fa5s.copy',
    'export': 'fa5s.file-export',
    'file-open': 'fa5s.file-import',
    'filter': 'fa5s.filter',
    'folder-open': 'fa5s.folder-open',
    'forward': 'fa5s.chevron-right',
    'pin': 'fa5s.thumbtack',
    'play': 'fa5s.play',
    'remove': 'fa5s.minus',
    'save': 'fa5s.save',
    'settings': 'fa5s.sliders-h',
    'stop': 'fa5s.stop',
    'trash': 'fa5s.trash-alt',
    'eraser': 'fa5s.eraser',
    'csv': 'fa5s.file-csv',
    'png': 'fa5s.image',
    'recalc': 'fa5s.calculator',
    'normalize': 'fa5s.wave-square',
    'autoscale': 'fa5s.expand-arrows-alt',
    'aspect': 'mdi6.aspect-ratio',
    'cursor-v': 'fa5s.ruler-vertical',
    'cursor-h': 'fa5s.ruler-horizontal',
    'clear-markers': 'fa5s.times-circle',
    'max-global': 'mdi6.summit',
    'max-local': 'mdi6.sine-wave',
    'near-field': 'mdi6.grid',
    'far-field': 'fa5s.chart-line',
}

_SOURCE_CACHE = {}   # имя -> текст SVG либо None
_ICON_CACHE = {}     # (имя, цвета) -> QIcon


def _glyph_dirs():
    """Где искать глифы: сначала распакованный exe, потом исходники."""
    if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
        yield Path(sys._MEIPASS) / 'far_zone' / 'styles' / 'glyphs'
    yield Path(__file__).resolve().parent / 'styles' / 'glyphs'


def _glyph_source(name):
    if name not in _SOURCE_CACHE:
        text = None
        for folder in _glyph_dirs():
            candidate = folder / f'{name}.svg'
            if candidate.exists():
                text = candidate.read_text(encoding='utf-8')
                break
        _SOURCE_CACHE[name] = text
    return _SOURCE_CACHE[name]


def _device_ratio():
    """Во сколько раз растить растр под экран (HiDPI). До создания app — 1."""
    app = QtGui.QGuiApplication.instance()
    try:
        ratio = float(app.devicePixelRatio()) if app is not None else 1.0
    except Exception:
        ratio = 1.0
    return float(max(1, math.ceil(ratio)))


def _pixmap(source, color, size, ratio):
    """Отрисовать SVG в pixmap нужного цвета и логического размера."""
    data = QtCore.QByteArray(source.replace('currentColor', color).encode('utf-8'))
    renderer = QtSvg.QSvgRenderer(data)
    side = max(1, int(round(size * ratio)))
    pixmap = QtGui.QPixmap(side, side)
    pixmap.fill(QtCore.Qt.transparent)
    painter = QtGui.QPainter(pixmap)
    painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
    renderer.render(painter)
    painter.end()
    pixmap.setDevicePixelRatio(ratio)
    return pixmap


def app_icon(name, color=ICON_DEFAULT, disabled_color=ICON_DISABLED,
             color_on=None) -> QtGui.QIcon:
    """Иконка по имени.

    ``color_on`` — цвет для нажатого состояния checkable-кнопки; без него
    нажатая кнопка отличалась только фоном, и было не видно, что режим включён.
    """
    key = (name, color, disabled_color, color_on)
    icon = _ICON_CACHE.get(key)
    if icon is not None:
        return icon

    source = _glyph_source(name)
    if source is None:
        if qta is None:
            return QtGui.QIcon()
        icon = qta.icon(ICON_ALIASES.get(name, name), color=color,
                        color_disabled=disabled_color)
    else:
        ratio = _device_ratio()
        icon = QtGui.QIcon()
        for size in ICON_RENDER_SIZES:
            normal = _pixmap(source, color, size, ratio)
            disabled = _pixmap(source, disabled_color, size, ratio)
            checked = (_pixmap(source, color_on, size, ratio)
                       if color_on else normal)
            icon.addPixmap(normal, QtGui.QIcon.Normal, QtGui.QIcon.Off)
            icon.addPixmap(disabled, QtGui.QIcon.Disabled, QtGui.QIcon.Off)
            icon.addPixmap(checked, QtGui.QIcon.Normal, QtGui.QIcon.On)
            icon.addPixmap(disabled, QtGui.QIcon.Disabled, QtGui.QIcon.On)

    _ICON_CACHE[key] = icon
    return icon


def set_button_icon(button, name, size=ICON_SM, color=ICON_DEFAULT,
                    color_on=None) -> None:
    button.setIcon(app_icon(name, color=color, color_on=color_on))
    button.setIconSize(QtCore.QSize(size, size))


WINDOW_ICON_SIZES = (16, 24, 32, 48, 64, 128, 256)


def window_icon() -> QtGui.QIcon:
    """Иконка приложения (окно, панель задач, Alt+Tab).

    Отдельно от app_icon: нужны крупные размеры и собственные цвета глифа —
    подстановка currentColor тут не работает и не нужна.
    """
    source = _glyph_source('app')
    if source is None:
        return QtGui.QIcon()
    icon = QtGui.QIcon()
    for size in WINDOW_ICON_SIZES:
        pixmap = QtGui.QPixmap(size, size)
        pixmap.fill(QtCore.Qt.transparent)
        painter = QtGui.QPainter(pixmap)
        painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
        QtSvg.QSvgRenderer(QtCore.QByteArray(source.encode('utf-8'))).render(painter)
        painter.end()
        icon.addPixmap(pixmap)
    return icon
