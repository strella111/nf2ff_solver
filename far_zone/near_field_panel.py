# -*- coding: utf-8 -*-
"""Панель ближнего поля: 2D-карта амплитуды ИЛИ фазы по апертуре.

Показывается одна карта, переключатель сверху выбирает величину. Отрисовка и
работа мышью сделаны как в режиме «Измерение лучей АФАР» основного проекта:
палитра turbo, свободный масштаб (ЛКМ — сдвиг, ПКМ — масштаб по двум осям,
колесо — зум), двойной клик по карте подгоняет вид под измеренные точки,
шкала правится перетаскиванием ручек или вводом значений по двойному клику.

Подготовка данных — в near_field_data (без Qt), здесь только отрисовка.
"""

import csv

import numpy as np
import pyqtgraph as pg
import pyqtgraph.exporters  # noqa: F401  (регистрирует pg.exporters)
from PyQt5 import QtCore, QtGui, QtWidgets
from loguru import logger

from .editable_colorbar import EditableColorBarItem, prompt_colorbar_range
from .icon_utils import app_icon
from .near_field_data import (PHASE_LEVELS, auto_levels, axis_points,
                              field_stats, measured_bounds, prepare_maps)

# Палитра как в скане лучей: синий→…→красный, максимум красный. Одна и та же
# для амплитуды и фазы — чтобы карты читались одинаково.
FIELD_CMAP = 'turbo'

MODES = {
    'amp': {'title': 'Амплитуда (2D)', 'units': 'дБ'},
    'phase': {'title': 'Фаза (2D)', 'units': 'град'},
}


class NearFieldPanel(QtWidgets.QWidget):
    """Карта ближнего поля одного луча на одной частоте.

    set_field() принимает данные как они лежат в файле (``[y][x]``) и
    возвращает сводку (field_stats) — её показывает окно в панели метрик.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._amp = None            # картинка (x, y), дБ
        self._phase = None          # картинка (x, y), градусы
        self._rect = (0.0, 0.0, 1.0, 1.0)
        self._x_pts = np.empty(0)
        self._y_pts = np.empty(0)
        self._mode = 'amp'
        self._label = ''

        # Режим шкал: амплитуда по данным, фаза — фиксированные -180..180
        # (как в скане лучей).
        self._auto = {'amp': True, 'phase': False}
        self._levels = {'amp': None, 'phase': PHASE_LEVELS}
        self._updating_levels = False

        root = QtWidgets.QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)
        root.addWidget(self._build_tools(), 0)

        area = QtWidgets.QVBoxLayout()
        area.setContentsMargins(0, 0, 0, 0)
        area.setSpacing(2)
        area.addLayout(self._build_mode_bar())
        self._build_plot()
        area.addWidget(self.plot, 1)

        self.readout = QtWidgets.QLabel(' ')
        self.readout.setObjectName('ffReadout')
        self.readout.setMinimumHeight(16)
        area.addWidget(self.readout)
        root.addLayout(area, 1)

        self._proxy = pg.SignalProxy(self.plot.scene().sigMouseMoved,
                                     rateLimit=60, slot=self._on_mouse_move)
        self.plot.scene().sigMouseClicked.connect(self._on_scene_click)

    # ------------------------------------------------------------- построение
    def _icon_btn(self, icon, tip, slot, checkable=False, shortcut=None):
        btn = QtWidgets.QToolButton()
        btn.setProperty('plotTool', True)
        btn.setIcon(app_icon(icon))
        btn.setIconSize(QtCore.QSize(18, 18))
        if shortcut:
            btn.setShortcut(QtGui.QKeySequence(shortcut))
            tip = f'{tip}  [{shortcut}]'
        btn.setToolTip(tip)
        btn.setCheckable(checkable)
        btn.setAutoRaise(True)
        btn.setFixedSize(32, 32)
        btn.clicked.connect(slot)
        return btn

    def _build_tools(self):
        panel = QtWidgets.QWidget()
        panel.setFixedWidth(40)
        col = QtWidgets.QVBoxLayout(panel)
        col.setContentsMargins(2, 2, 2, 2)
        col.setSpacing(4)

        col.addWidget(self._icon_btn(
            'autoscale', 'Подогнать масштаб под измеренные точки.\n'
                         'То же самое — двойной клик по карте',
            self.fit_to_data))
        self.aspect_btn = self._icon_btn(
            'aspect', 'Равный масштаб по X и Y (апертура без искажений).\n'
                      'Пока включён, ПКМ тянет обе оси вместе',
            self._toggle_aspect, checkable=True)
        col.addWidget(self.aspect_btn)
        col.addSpacing(8)
        col.addWidget(self._icon_btn('csv', 'Экспорт текущей карты в CSV', self._export_csv))
        col.addWidget(self._icon_btn('png', 'Экспорт картинки в PNG', self._export_png))
        col.addStretch(1)
        return panel

    def _build_mode_bar(self):
        """Переключатель величины: амплитуда или фаза."""
        bar = QtWidgets.QHBoxLayout()
        bar.setContentsMargins(0, 0, 4, 0)
        bar.setSpacing(4)
        bar.addStretch(1)
        bar.addWidget(QtWidgets.QLabel('Показать:'))

        self._mode_group = QtWidgets.QButtonGroup(self)
        self._mode_group.setExclusive(True)
        for mode in ('amp', 'phase'):
            text = 'Амплитуда' if mode == 'amp' else 'Фаза'
            btn = QtWidgets.QToolButton()
            btn.setText(text)
            btn.setCheckable(True)
            btn.setToolTip(f'{MODES[mode]["title"]}, {MODES[mode]["units"]}')
            btn.setChecked(mode == self._mode)
            btn.clicked.connect(lambda _=False, m=mode: self.set_mode(m))
            self._mode_group.addButton(btn)
            bar.addWidget(btn)
            setattr(self, f'_{mode}_btn', btn)
        return bar

    def _build_plot(self):
        self.plot = pg.PlotWidget(title=MODES['amp']['title'])
        self.plot.setBackground('w')
        self.plot.showGrid(x=True, y=True, alpha=0.3)
        self.plot.setLabel('left', 'Y (см)')
        self.plot.setLabel('bottom', 'X (см)')
        self._pi = self.plot.getPlotItem()
        # Масштаб не заперт и меню включено — мышь работает как в скане лучей:
        # ЛКМ тянет вид, ПКМ меняет масштаб по обеим осям, колесо зумит.

        # axisOrder='col-major' — первая ось массива горизонтальная (см. near_field_data).
        # NaN (непромеренные точки) pyqtgraph рисует прозрачными сам.
        self._img = pg.ImageItem()
        self._img.setOpts(axisOrder='col-major')
        self._pi.addItem(self._img)

        # Перекрестие под курсором — как на карте скана.
        cross_pen = pg.mkPen('k', width=1, style=QtCore.Qt.DashLine)
        self._vline = pg.InfiniteLine(angle=90, movable=False, pen=cross_pen)
        self._hline = pg.InfiniteLine(angle=0, movable=False, pen=cross_pen)
        self._pi.addItem(self._vline, ignoreBounds=True)
        self._pi.addItem(self._hline, ignoreBounds=True)

        self._cbar = EditableColorBarItem(colorMap=pg.colormap.get(FIELD_CMAP),
                                          label=MODES['amp']['units'])
        self._cbar.setImageItem(self._img, insert_in=self._pi)
        self._cbar.sigDoubleClicked.connect(self._edit_colorbar)
        self._cbar.sigLevelsChanged.connect(self._on_user_levels)

    # ------------------------------------------------------------------ данные
    def set_field(self, amp, phase, x_list, y_list, dx, dy, label=''):
        """Показать поле; amp/phase — массивы ``[y][x]`` как в файле.

        Возвращает сводку (near_field_data.field_stats) для панели метрик.
        """
        maps = prepare_maps(amp, phase, x_list, y_list, dx, dy)
        same_geometry = (self._amp is not None
                         and np.allclose(self._rect, maps['rect'])
                         and self._amp.shape == maps['amp'].shape)
        self._amp = maps['amp']
        self._phase = maps['phase']
        self._rect = maps['rect']
        n_x, n_y = self._amp.shape
        self._x_pts = axis_points(x_list, n_x, dx)
        self._y_pts = axis_points(y_list, n_y, dy)
        self._label = label
        self._refresh()
        if not same_geometry:
            # Апертура та же — сохраняем масштаб, иначе зум слетал бы на каждом луче.
            self.fit_to_data()
        return field_stats(self._amp, self._phase, self._x_pts, self._y_pts)

    def clear_data(self):
        self._amp = None
        self._phase = None
        self._img.clear()
        self.readout.setText(' ')
        self._pi.setTitle(MODES[self._mode]['title'])

    def set_mode(self, mode):
        """Переключить величину: 'amp' (дБ) или 'phase' (град)."""
        mode = 'phase' if str(mode) == 'phase' else 'amp'
        self._mode = mode
        self._amp_btn.setChecked(mode == 'amp')
        self._phase_btn.setChecked(mode == 'phase')
        self._cbar.setLabel('left', MODES[mode]['units'])
        self._refresh()

    def _current_data(self):
        return self._phase if self._mode == 'phase' else self._amp

    def _refresh(self):
        img = self._current_data()
        if img is None:
            return
        mode = self._mode
        if self._auto[mode] or self._levels[mode] is None:
            self._levels[mode] = auto_levels(img)

        self._img.setImage(img, autoLevels=False)
        self._img.setRect(QtCore.QRectF(*self._rect))
        self._set_levels(*self._levels[mode])

        title = MODES[mode]['title']
        if self._label:
            title = f'{title} — {self._label}'
        self._pi.setTitle(title)

    # -------------------------------------------------------------- шкала
    def _set_levels(self, lo, hi):
        """Задать уровни, не переводя шкалу в ручной режим."""
        self._updating_levels = True
        try:
            self._cbar.setLevels((lo, hi))
        finally:
            self._updating_levels = False

    def _on_user_levels(self, *_args):
        """Перетаскивание ручек на шкале → переход в ручной режим."""
        if self._updating_levels:
            return
        self._auto[self._mode] = False
        self._levels[self._mode] = tuple(self._cbar.levels())

    def _edit_colorbar(self):
        """Диалог ввода диапазона шкалы (двойной клик по колорбару)."""
        mode = self._mode
        lo, hi = self._cbar.levels()
        res = prompt_colorbar_range(self, MODES[mode]['units'], lo, hi,
                                    'Автомасштаб по данным', self._auto[mode])
        if res is None:
            return
        if res[0] == 'auto':
            self._auto[mode] = True
            self._levels[mode] = None
            self._refresh()
            return
        _, lo2, hi2 = res
        self._auto[mode] = False
        self._levels[mode] = (lo2, hi2)
        self._set_levels(lo2, hi2)

    # ------------------------------------------------------------- управление
    def fit_to_data(self):
        """Подогнать масштаб под измеренные точки."""
        if self._amp is None:
            return
        bounds = measured_bounds(self._amp, self._x_pts, self._y_pts)
        if bounds is None:
            return
        x0, x1, y0, y1 = bounds
        self.plot.setRange(xRange=(x0, x1), yRange=(y0, y1), padding=0.02)

    def _toggle_aspect(self):
        self._pi.setAspectLocked(self.aspect_btn.isChecked())
        self.fit_to_data()

    def _on_scene_click(self, event):
        """Двойной клик по карте — подогнать масштаб под измеренные точки."""
        if not event.double():
            return
        view_box = self._pi.getViewBox()
        # Клики по шкале и полям графика обрабатывает не этот метод.
        if not view_box.sceneBoundingRect().contains(event.scenePos()):
            return
        event.accept()
        self.fit_to_data()

    # ----------------------------------------------------------------- курсор
    def _on_mouse_move(self, evt):
        if self._amp is None or not self._pi.sceneBoundingRect().contains(evt[0]):
            self.readout.setText(' ')
            return
        point = self._pi.vb.mapSceneToView(evt[0])
        ix, iy = self._nearest_cell(point.x(), point.y())
        if ix is None:
            self.readout.setText(' ')
            return
        self._vline.setPos(float(self._x_pts[ix]))
        self._hline.setPos(float(self._y_pts[iy]))
        amp = self._amp[ix, iy]
        phase = self._phase[ix, iy]
        amp_txt = '—' if not np.isfinite(amp) else f'{amp:.2f} дБ'
        phase_txt = '—' if not np.isfinite(phase) else f'{phase:.1f}°'
        self.readout.setText(
            f'X = {self._x_pts[ix]:.2f} см    Y = {self._y_pts[iy]:.2f} см    '
            f'амплитуда {amp_txt}    фаза {phase_txt}')

    def _nearest_cell(self, x, y):
        """Индексы ближайшей точки скана или (None, None) вне апертуры."""
        x0, y0, width, height = self._rect
        if not (x0 <= x <= x0 + width and y0 <= y <= y0 + height):
            return None, None
        if self._x_pts.size == 0 or self._y_pts.size == 0:
            return None, None
        return (int(np.abs(self._x_pts - x).argmin()),
                int(np.abs(self._y_pts - y).argmin()))

    # ---------------------------------------------------------------- экспорт
    def _export_png(self):
        if self._amp is None:
            return
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, 'Сохранить картинку', 'near_field.png', 'PNG (*.png)')
        if not path:
            return
        try:
            pg.exporters.ImageExporter(self._pi).export(path)
            logger.info(f'Картинка ближнего поля сохранена: {path}')
        except Exception as exc:
            logger.error(f'Ошибка экспорта PNG: {exc}')
            QtWidgets.QMessageBox.critical(self, 'Ошибка экспорта', str(exc))

    def _export_csv(self):
        img = self._current_data()
        if img is None:
            return
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, 'Сохранить карту', 'near_field.csv', 'CSV (*.csv)')
        if not path:
            return
        units = MODES[self._mode]['units']
        try:
            with open(path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f, delimiter=';')
                writer.writerow([f'Y \\ X, см ({units})']
                                + [f'{v:.3f}' for v in self._x_pts])
                for iy in range(img.shape[1]):
                    row = ['' if not np.isfinite(v) else f'{v:.4f}' for v in img[:, iy]]
                    writer.writerow([f'{self._y_pts[iy]:.3f}'] + row)
            logger.info(f'Карта ближнего поля сохранена: {path}')
        except Exception as exc:
            logger.error(f'Ошибка экспорта CSV: {exc}')
            QtWidgets.QMessageBox.critical(self, 'Ошибка экспорта', str(exc))
