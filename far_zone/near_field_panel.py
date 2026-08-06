# -*- coding: utf-8 -*-
"""Панель ближнего поля: 2D-карта амплитуды ИЛИ фазы по апертуре.

Показывается одна карта, переключатель сверху выбирает величину. Логика
подготовки данных — в near_field_data (без Qt), здесь только отрисовка.
"""

import csv

import numpy as np
import pyqtgraph as pg
import pyqtgraph.exporters  # noqa: F401  (регистрирует pg.exporters)
from PyQt5 import QtCore, QtGui, QtWidgets
from loguru import logger

from .icon_utils import app_icon
from .near_field_data import (DEFAULT_FLOOR_DB, PHASE_LEVELS, amp_display,
                              amp_levels, axis_points, field_stats, prepare_maps)

AMP_CMAP = 'viridis'
PHASE_CMAP = 'CET-C6'                  # циклическая: стык −180/+180 без ложного разрыва
HOLE_COLOR = (203, 213, 225, 255)      # точки без измерения — серым, а не «минус бесконечность»


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
        self._mode = 'amp'          # 'amp' | 'phase'
        self._normalize = True
        self._floor_db = DEFAULT_FLOOR_DB
        self._label = ''

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

        col.addWidget(self._icon_btn('autoscale', 'Показать всю апертуру', self.autoscale))
        self.aspect_btn = self._icon_btn(
            'aspect', 'Равный масштаб по X и Y (апертура без искажений).\n'
                      'Выключите, чтобы растянуть картинку на всё окно',
            self._toggle_aspect, checkable=True)
        self.aspect_btn.setChecked(True)
        col.addWidget(self.aspect_btn)
        self.norm_btn = self._icon_btn(
            'normalize', 'Нормировка амплитуды к максимуму (0 дБ)',
            self._toggle_norm, checkable=True)
        self.norm_btn.setChecked(self._normalize)
        col.addWidget(self.norm_btn)
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
        for mode, text, tip in (
            ('amp', 'Амплитуда', 'Амплитуда ближнего поля, дБ'),
            ('phase', 'Фаза', 'Фаза ближнего поля, градусы'),
        ):
            btn = QtWidgets.QToolButton()
            btn.setText(text)
            btn.setCheckable(True)
            btn.setToolTip(tip)
            btn.setChecked(mode == self._mode)
            btn.clicked.connect(lambda _=False, m=mode: self.set_mode(m))
            self._mode_group.addButton(btn)
            bar.addWidget(btn)
            setattr(self, f'_{mode}_btn', btn)
        return bar

    def _build_plot(self):
        self.plot = pg.PlotWidget()
        self.plot.setBackground('#fbfcff')
        pi = self.plot.getPlotItem()
        self._pi = pi
        pi.showGrid(x=True, y=True, alpha=0.15)
        pi.setMenuEnabled(False)
        pi.getAxis('bottom').setLabel('X, см')
        pi.getAxis('left').setLabel('Y, см')
        pi.setAspectLocked(True)
        pi.setTitle('Ближнее поле', color='#1f2937', size='11pt')

        # axisOrder='col-major' — первая ось массива горизонтальная (см. near_field_data).
        self._img = pg.ImageItem()
        self._img.setOpts(axisOrder='col-major')
        pi.addItem(self._img)

        # Отдельным слоем — неизмеренные точки: иначе NaN уедет в «самый низкий» цвет.
        self._holes = pg.ImageItem()
        self._holes.setOpts(axisOrder='col-major')
        self._holes.setZValue(10)
        pi.addItem(self._holes)

        self._cbar = pg.ColorBarItem(colorMap=pg.colormap.get(AMP_CMAP),
                                     label='дБ', interactive=True)
        self._cbar.setImageItem(self._img, insert_in=pi)

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
            self.autoscale()
        return field_stats(self._amp, self._phase, self._x_pts, self._y_pts)

    def clear_data(self):
        self._amp = None
        self._phase = None
        self._img.clear()
        self._holes.clear()
        self.readout.setText(' ')
        self._pi.setTitle('Ближнее поле', color='#1f2937', size='11pt')

    def set_mode(self, mode):
        """Переключить величину: 'amp' (дБ) или 'phase' (°)."""
        mode = 'phase' if str(mode) == 'phase' else 'amp'
        self._mode = mode
        self._amp_btn.setChecked(mode == 'amp')
        self._phase_btn.setChecked(mode == 'phase')
        self.norm_btn.setEnabled(mode == 'amp')
        self._refresh()

    def _current_image(self):
        """Картинка, пределы шкалы, палитра и единицы для текущего режима."""
        if self._mode == 'phase':
            return self._phase, PHASE_LEVELS, pg.colormap.get(PHASE_CMAP), '°'
        img = amp_display(self._amp, self._normalize)
        return img, amp_levels(img, self._floor_db), pg.colormap.get(AMP_CMAP), 'дБ'

    def _refresh(self):
        if self._amp is None:
            return
        img, levels, cmap, unit = self._current_image()
        self._img.setImage(img, autoLevels=False, levels=levels)
        self._img.setRect(QtCore.QRectF(*self._rect))
        self._cbar.setColorMap(cmap)
        self._cbar.setLevels(values=levels)
        self._cbar.setLabel('left', unit)
        self._refresh_holes(img)

        kind = 'фаза, °' if self._mode == 'phase' else (
            'амплитуда, дБ (норм.)' if self._normalize else 'амплитуда, дБ')
        title = f'Ближнее поле · {kind}'
        if self._label:
            title = f'{title} · {self._label}'
        self._pi.setTitle(title, color='#1f2937', size='11pt')

    def _refresh_holes(self, img):
        """Точки без измерения — отдельным слоем поверх карты."""
        mask = ~np.isfinite(np.asarray(img, dtype=float))
        if not mask.any():
            self._holes.clear()
            return
        rgba = np.zeros(mask.shape + (4,), dtype=np.ubyte)
        rgba[mask] = HOLE_COLOR
        self._holes.setImage(rgba, autoLevels=False)
        self._holes.setRect(QtCore.QRectF(*self._rect))

    # ------------------------------------------------------------- управление
    def autoscale(self):
        self._pi.enableAutoRange(x=True, y=True)

    def _toggle_aspect(self):
        self._pi.setAspectLocked(self.aspect_btn.isChecked())
        self.autoscale()

    def _toggle_norm(self):
        self._normalize = self.norm_btn.isChecked()
        self._refresh()

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
        if self._amp is None:
            return
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, 'Сохранить карту', 'near_field.csv', 'CSV (*.csv)')
        if not path:
            return
        img, _levels, _cmap, unit = self._current_image()
        try:
            with open(path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f, delimiter=';')
                writer.writerow([f'Y \\ X, см ({unit})']
                                + [f'{v:.3f}' for v in self._x_pts])
                for iy in range(img.shape[1]):
                    row = ['' if not np.isfinite(v) else f'{v:.4f}' for v in img[:, iy]]
                    writer.writerow([f'{self._y_pts[iy]:.3f}'] + row)
            logger.info(f'Карта ближнего поля сохранена: {path}')
        except Exception as exc:
            logger.error(f'Ошибка экспорта CSV: {exc}')
            QtWidgets.QMessageBox.critical(self, 'Ошибка экспорта', str(exc))
