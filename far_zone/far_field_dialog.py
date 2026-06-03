# -*- coding: utf-8 -*-
"""Утилита расчёта диаграммы направленности в дальней зоне (NF -> FF).

Вход — папка с результатами режима «Измерение лучей АФАР» (Beam№*.xlsx +
scan_params.json) ЛИБО отдельный файл измерения (кнопка «Открыть файл»). После
открытия вызывается окно параметров (диапазоны, шаг, dx/dy, выбор лучей и частот).
В режиме одиночного файла роль «луча» играет имя файла, а dx/dy задаются вручную.
Выбранные лучи/частоты считаются в фоне, результаты кэшируются — переключение
мгновенное.

Амплитуда и фаза показываются НА ОДНОМ графике: 4 трассы (Az/El × амплитуда/
фаза), две оси Y — слева амплитуда (дБ), справа фаза (°). Любую трассу можно
скрыть тумблером. Поддержка: значение при наведении, перетаскиваемые линии-
маркеры V/H со значениями на пересечении, наложение трасс, нормировка (только
амплитуда), поиск максимумов (только амплитуда), экспорт PNG/CSV.

Единицы шага сканера — сантиметры (как в MATLAB): dx/dy [см] -> метры (×1e-2).
"""

import os
import csv

import numpy as np
import pyqtgraph as pg
import pyqtgraph.exporters  # noqa: F401  (регистрирует pg.exporters)
from PyQt5 import QtCore, QtGui, QtWidgets
from loguru import logger

from .nf2ff_solver import solve_sections, find_peak_indices, side_lobe_level
from .beam_loader import load_beam_pattern_results, load_single_beam_file, BeamFileFormatError
from .beam_mapping import beam_to_angles
from .icon_utils import set_button_icon, app_icon
from .design_tokens import ACCENT, STATUS_ICON

AZ_COLOR = ACCENT
EL_COLOR = '#059669'
PHASE_AZ_COLOR = STATUS_ICON['fail']   # красный
PHASE_EL_COLOR = '#d97706'             # янтарный
MASK_COLOR = '#dc2626'                 # линия маски УБЛ
MARKER_V_COLOR = '#111827'             # обычный вертикальный маркер
MARKER_H_COLOR = '#7c3aed'             # обычный горизонтальный маркер
PEAK_COLOR = '#db2777'                 # маркер поиска максимума (магнитится к пикам)
MARKER_WIDTH = 1.8                     # толщина линии маркеров (была 1)
PEAK_WIDTH = 2.4                       # маркер-максимум чуть толще обычных
DEG = np.pi / 180
OVERLAY_COLORS = ['#7c3aed', '#0891b2', '#d97706', '#475467', '#e11d48', '#059669', '#2563eb']
STEP_TO_M = 1e-2  # шаг сканера: см -> метры


def angle_axis(left, right, step):
    """Сетка углов (град) — той же формулой, что и солвер (совпадает по длине)."""
    return np.degrees(np.arange(left * DEG, right * DEG + step * DEG, step * DEG))


# ============================================================ Окно параметров
class FarFieldParamsDialog(QtWidgets.QDialog):
    """Параметры пересчёта + выбор лучей и частот."""

    def __init__(self, beams, freqs, defaults=None, single_file=False, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Параметры пересчёта')
        self.setMinimumWidth(560)
        defaults = defaults or {}
        self._single_file = single_file

        root = QtWidgets.QVBoxLayout(self)
        root.setSpacing(10)

        params_group = QtWidgets.QGroupBox('Параметры расчёта')
        grid = QtWidgets.QGridLayout(params_group)
        self.az_from = self._dspin(-90, 90, defaults.get('az_from', -5), ' °')
        self.az_to = self._dspin(-90, 90, defaults.get('az_to', 5), ' °')
        self.az_step = self._dspin(0.001, 5, defaults.get('az_step', 0.05), ' °', 3)
        self.el_from = self._dspin(-90, 90, defaults.get('el_from', -20), ' °')
        self.el_to = self._dspin(-90, 90, defaults.get('el_to', 20), ' °')
        self.el_step = self._dspin(0.001, 5, defaults.get('el_step', 0.05), ' °', 3)
        self.dx_spin = self._dspin(0.01, 1000, defaults.get('dx', 1.0), ' см', 3)
        self.dy_spin = self._dspin(0.01, 1000, defaults.get('dy', 1.0), ' см', 3)

        self.fft_combo = QtWidgets.QComboBox()
        for text, val in (('×2 (быстро)', 2), ('×4', 4), ('×8', 8), ('×16 (точно)', 16)):
            self.fft_combo.addItem(text, val)
        self.fft_combo.setToolTip(
            'Дополнение нулями перед БПФ (число точек = ближайшая степень 2 × множитель).\n'
            'Больше — плотнее сетка и точнее интерполяция, но дольше и больше памяти.')
        pad_idx = self.fft_combo.findData(int(defaults.get('pad', 4)))
        self.fft_combo.setCurrentIndex(pad_idx if pad_idx >= 0 else 1)

        self.interp_combo = QtWidgets.QComboBox()
        self.interp_combo.addItem('Бикубическая', 'cubic')
        self.interp_combo.addItem('Кубический сплайн', 'spline')
        self.interp_combo.addItem('Билинейная', 'linear')
        self.interp_combo.setToolTip(
            'Метод интерполяции спектра на углы.\n'
            '• Кубический сплайн — как interp2(...,\'spline\') в MATLAB (точнее всего);\n'
            '• Бикубическая — кубическая свёртка (interp2 \'cubic\'), близко к сплайну;\n'
            '• Билинейная — быстрее/грубее.')
        i_idx = self.interp_combo.findData(str(defaults.get('interp', 'cubic')))
        self.interp_combo.setCurrentIndex(i_idx if i_idx >= 0 else 0)

        self.abs_combo = QtWidgets.QComboBox()
        self.abs_combo.addItem('После (комплекс → |·|)', 'after')
        self.abs_combo.addItem('До (модуль |fx| → интерп.)', 'before')
        self.abs_combo.setToolTip(
            'Когда брать модуль амплитуды:\n'
            '• После — интерполируется комплексный спектр, затем модуль '
            '(точнее у нулей, наш метод);\n'
            '• До — модуль берётся до интерполяции (как в MATLAB).\n'
            'Фаза всегда считается по комплексу.')
        a_idx = self.abs_combo.findData(str(defaults.get('abs_mode', 'after')))
        self.abs_combo.setCurrentIndex(a_idx if a_idx >= 0 else 0)

        grid.addWidget(QtWidgets.QLabel('Az:'), 0, 0)
        grid.addWidget(self._labeled('от', self.az_from), 0, 1)
        grid.addWidget(self._labeled('до', self.az_to), 0, 2)
        grid.addWidget(self._labeled('шаг', self.az_step), 0, 3)
        grid.addWidget(QtWidgets.QLabel('El:'), 1, 0)
        grid.addWidget(self._labeled('от', self.el_from), 1, 1)
        grid.addWidget(self._labeled('до', self.el_to), 1, 2)
        grid.addWidget(self._labeled('шаг', self.el_step), 1, 3)
        grid.addWidget(self._labeled('Шаг X (dx)', self.dx_spin), 2, 1)
        grid.addWidget(self._labeled('Шаг Y (dy)', self.dy_spin), 2, 2)
        grid.addWidget(self._labeled('Точек БПФ', self.fft_combo), 2, 3)
        grid.addWidget(self._labeled('Интерполяция', self.interp_combo), 3, 1)
        grid.addWidget(self._labeled('Модуль (abs)', self.abs_combo), 3, 2, 1, 2)
        root.addWidget(params_group)

        lists_row = QtWidgets.QHBoxLayout()
        if single_file:
            beams_group, self.beams_list = self._build_check_list('Файл', beams, lambda b: str(b))
        else:
            beams_group, self.beams_list = self._build_check_list('Лучи', beams, lambda b: f'Луч {b}')
        freqs_group, self.freqs_list = self._build_check_list('Частоты', freqs, lambda f: f'{f:g} МГц')
        lists_row.addWidget(beams_group)
        lists_row.addWidget(freqs_group)
        root.addLayout(lists_row)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        buttons.button(QtWidgets.QDialogButtonBox.Ok).setText('Рассчитать')
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    @staticmethod
    def _dspin(lo, hi, val, suffix='', decimals=2):
        spin = QtWidgets.QDoubleSpinBox()
        spin.setRange(lo, hi)
        spin.setDecimals(decimals)
        spin.setValue(val)
        if suffix:
            spin.setSuffix(suffix)
        return spin

    @staticmethod
    def _labeled(text, widget):
        box = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(box)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)
        lbl = QtWidgets.QLabel(text)
        lbl.setStyleSheet('color: #667085; font-size: 8pt;')
        lay.addWidget(lbl)
        lay.addWidget(widget)
        return box

    def _build_check_list(self, title, items, fmt):
        group = QtWidgets.QGroupBox(title)
        layout = QtWidgets.QVBoxLayout(group)
        lst = QtWidgets.QListWidget()
        lst.setSelectionMode(QtWidgets.QAbstractItemView.NoSelection)
        for value in items:
            item = QtWidgets.QListWidgetItem(fmt(value))
            item.setFlags(item.flags() | QtCore.Qt.ItemIsUserCheckable)
            item.setCheckState(QtCore.Qt.Checked)
            item.setData(QtCore.Qt.UserRole, value)
            lst.addItem(item)
        layout.addWidget(lst)

        btn_row = QtWidgets.QHBoxLayout()
        for text, action in (('Все', QtCore.Qt.Checked), ('Снять', QtCore.Qt.Unchecked), ('Инверт.', None)):
            btn = QtWidgets.QPushButton(text)
            if action is None:
                btn.clicked.connect(lambda _, w=lst: self._invert(w))
            else:
                btn.clicked.connect(lambda _, w=lst, s=action: self._set_all(w, s))
            btn_row.addWidget(btn)
        layout.addLayout(btn_row)
        return group, lst

    @staticmethod
    def _set_all(lst, state):
        for i in range(lst.count()):
            lst.item(i).setCheckState(state)

    @staticmethod
    def _invert(lst):
        for i in range(lst.count()):
            item = lst.item(i)
            item.setCheckState(QtCore.Qt.Unchecked if item.checkState() == QtCore.Qt.Checked else QtCore.Qt.Checked)

    @staticmethod
    def _checked_values(lst):
        return [lst.item(i).data(QtCore.Qt.UserRole)
                for i in range(lst.count()) if lst.item(i).checkState() == QtCore.Qt.Checked]

    def selected_beams(self):
        return self._checked_values(self.beams_list)

    def selected_freqs(self):
        return self._checked_values(self.freqs_list)

    def params(self):
        return {
            'az_from': self.az_from.value(), 'az_to': self.az_to.value(), 'az_step': self.az_step.value(),
            'el_from': self.el_from.value(), 'el_to': self.el_to.value(), 'el_step': self.el_step.value(),
            'dx': self.dx_spin.value(), 'dy': self.dy_spin.value(),
            'pad': int(self.fft_combo.currentData()),
            'interp': str(self.interp_combo.currentData()),
            'abs_mode': str(self.abs_combo.currentData()),
        }

    def accept(self):
        if self.az_from.value() >= self.az_to.value() or self.el_from.value() >= self.el_to.value():
            QtWidgets.QMessageBox.warning(self, 'Проверьте диапазоны', '«от» должно быть меньше «до» по Az и El.')
            return
        if not self.selected_beams():
            if self._single_file:
                QtWidgets.QMessageBox.warning(self, 'Нет файла', 'Отметьте файл для пересчёта.')
            else:
                QtWidgets.QMessageBox.warning(self, 'Нет лучей', 'Выберите хотя бы один луч.')
            return
        if not self.selected_freqs():
            QtWidgets.QMessageBox.warning(self, 'Нет частот', 'Выберите хотя бы одну частоту.')
            return
        super().accept()


# ================================================================ Фоновый счёт
class _FarFieldWorker(QtCore.QObject):
    progress = QtCore.pyqtSignal(int, int, str)
    finished = QtCore.pyqtSignal(dict)
    failed = QtCore.pyqtSignal(str)
    done = QtCore.pyqtSignal()

    def __init__(self, data, tasks, params):
        super().__init__()
        self.data = data
        self.tasks = tasks
        self.p = params
        self._stop = False

    def stop(self):
        self._stop = True

    @QtCore.pyqtSlot()
    def run(self):
        cache = {}
        total = len(self.tasks)
        try:
            for i, (beam, freq) in enumerate(self.tasks, 1):
                if self._stop:
                    break
                entry = self._compute_one(beam, freq)
                if entry is not None:
                    cache[(beam, freq)] = entry
                self.progress.emit(i, total, f'Луч {beam}, {freq:g} МГц')
            self.finished.emit(cache)
        except Exception as exc:
            logger.error(f'Ошибка фонового расчёта дальней зоны: {exc}', exc_info=True)
            self.failed.emit(str(exc))
        finally:
            self.done.emit()

    def _compute_one(self, beam, freq):
        fd = self.data.get(beam, {}).get(freq)
        if not fd:
            return None
        amp = np.asarray(fd['amp'], dtype=float).T      # (y,x) -> (x,y)
        phase = np.asarray(fd['phase'], dtype=float).T
        if np.all(np.isnan(amp)):
            return None
        p = self.p
        return solve_sections(
            amp, phase, freq * 1e6, p['dx'] * STEP_TO_M, p['dy'] * STEP_TO_M,
            p['az_from'], p['az_to'], p['az_step'],
            p['el_from'], p['el_to'], p['el_step'],
            p.get('pad', 4), p.get('interp', 'cubic'), p.get('abs_mode', 'after'),
        )


# ============================================================ Панель графика
class FarFieldPlotPanel(QtWidgets.QWidget):
    """График с двумя осями Y: слева амплитуда (дБ), справа фаза (°).

    trace_defs: список (name, color, axis), axis ∈ {'L','R'} — левая/правая ось.
    Левые трассы считаются амплитудными (к ним применяются нормировка и поиск
    максимумов). Линии-маркеры (верт./гориз.) показывают значения пересечения с
    трассами: ПКМ по линии — удалить, двойной клик — ввести точное значение.
    """

    def __init__(self, trace_defs, left_unit='дБ', left_range=(-60, 0),
                 right_unit='°', right_range=(-200, 200), parent=None):
        super().__init__(parent)
        self._trace_defs = list(trace_defs)
        self._left_unit = left_unit
        self._right_unit = right_unit
        self._left_range = left_range
        self._right_range = right_range

        self._label_font = QtGui.QFont()
        self._label_font.setPointSize(10)
        self._label_font.setBold(True)

        self._normalize = True
        self._cursors = []      # [{line, kind, dotsL, dotsR, labelsL, labelsR}]
        self._overlays = []     # [[curve, vb, name]]
        self._hover_text = ''
        self._cursor_text = ''
        self._overlay_count = 0
        self._vis_btns = {}
        self._peak_cursor = None
        self._mask_line = None
        self._mask_db = None

        root = QtWidgets.QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)
        root.addWidget(self._build_tools(), 0)

        plot_area = QtWidgets.QVBoxLayout()
        plot_area.setContentsMargins(0, 0, 0, 0)
        plot_area.setSpacing(2)
        plot_area.addLayout(self._build_plane_bar())

        self._build_plot(left_unit, left_range, right_unit, right_range)
        plot_area.addWidget(self.plot, 1)

        self.readout = QtWidgets.QLabel(' ')
        self.readout.setObjectName('ffReadout')
        self.readout.setMinimumHeight(16)
        plot_area.addWidget(self.readout)
        root.addLayout(plot_area, 1)

        self._build_traces(trace_defs)
        self._build_hover()

        self._proxy = pg.SignalProxy(self.plot.scene().sigMouseMoved, rateLimit=60, slot=self._on_mouse_move)
        self.plot.scene().sigMouseClicked.connect(self._on_scene_click)

    # ------------------------------------------------------------- построение
    def _build_plot(self, left_unit, left_range, right_unit, right_range):
        self.plot = pg.PlotWidget()
        self.plot.setBackground('#fbfcff')
        pi = self.plot.getPlotItem()
        self._pi = pi
        pi.setTitle('Дальняя зона: амплитуда (дБ) · фаза (°)', color='#1f2937', size='11pt')
        pi.showGrid(x=True, y=True, alpha=0.22)
        pi.setMenuEnabled(False)
        pi.setLabel('bottom', 'Угол, °')
        pi.setLabel('left', left_unit)
        self.vbL = pi.vb
        self.vbL.setYRange(*left_range)

        # Вторая ось Y (фаза) — отдельный ViewBox, связанный по X.
        self.vbR = pg.ViewBox()
        pi.showAxis('right')
        pi.scene().addItem(self.vbR)
        pi.getAxis('right').linkToView(self.vbR)
        self.vbR.setXLink(pi)
        self.vbR.setMouseEnabled(x=False, y=False)
        ax_r = pi.getAxis('right')
        ax_r.setLabel(right_unit, color=PHASE_EL_COLOR)
        ax_r.setTextPen(pg.mkPen(PHASE_EL_COLOR))
        self.vbR.setYRange(*right_range)

        self.vbL.sigResized.connect(self._sync_views)
        QtCore.QTimer.singleShot(0, self._sync_views)

        self.legend = pi.addLegend(offset=(-12, 8))

    def _sync_views(self):
        self.vbR.setGeometry(self.vbL.sceneBoundingRect())
        self.vbR.linkedViewChanged(self.vbL, self.vbR.XAxis)

    def _build_traces(self, trace_defs):
        self._traces = []
        for name, color, axis in trace_defs:
            curve = pg.PlotDataItem([], [], pen=pg.mkPen(color, width=2.4), name=name)
            vb = self.vbL if axis == 'L' else self.vbR
            vb.addItem(curve)
            self.legend.addItem(curve, name)
            self._traces.append({
                'name': name, 'color': color, 'axis': axis, 'amp': axis == 'L',
                'unit': self._left_unit if axis == 'L' else self._right_unit,
                'curve': curve, 'vb': vb, 'visible': True,
                'x': np.array([]), 'y_raw': np.array([]), 'max_val': 0.0,
            })

    def _build_hover(self):
        self._hover = {}
        for key, vb in (('L', self.vbL), ('R', self.vbR)):
            dot = pg.ScatterPlotItem(size=11, brush=pg.mkBrush('#111827'), pen=pg.mkPen('w', width=1.5))
            dot.setZValue(50)
            vb.addItem(dot, ignoreBounds=True)
            lab = pg.TextItem(color='#111827', anchor=(0, 1))
            lab.setZValue(51)
            vb.addItem(lab, ignoreBounds=True)
            lab.hide()
            self._hover[key] = {'dot': dot, 'lab': lab}
        self.vline = pg.InfiniteLine(angle=90, movable=False,
                                     pen=pg.mkPen('#c7d0dc', style=QtCore.Qt.DashLine))
        self.vline.hide()
        self.plot.addItem(self.vline, ignoreBounds=True)

    # --------------------------------------------------- инструменты (слева)
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
        """Компактная вертикальная панель иконок-инструментов."""
        panel = QtWidgets.QWidget()
        panel.setFixedWidth(40)
        col = QtWidgets.QVBoxLayout(panel)
        col.setContentsMargins(2, 2, 2, 2)
        col.setSpacing(4)

        col.addWidget(self._icon_btn('cursor-h', 'Добавить горизонтальный маркер (по амплитуде)', self._add_hcursor, shortcut='H'))
        col.addWidget(self._icon_btn('cursor-v', 'Добавить вертикальный маркер', self._add_vcursor, shortcut='V'))
        col.addWidget(self._icon_btn('max-global', 'Маркер максимума (отдельный цвет): в главный максимум амплитуды.\n'
                                                   'Перетаскивание маркера притягивается к ближайшему максимуму', self._marker_to_max, shortcut='M'))
        col.addWidget(self._icon_btn('max-local', 'Маркер максимума: следующий локальный максимум по кругу.\n'
                                                  'Перетаскивание маркера притягивается к ближайшему максимуму', self._next_local_max, shortcut='Shift+M'))
        col.addWidget(self._icon_btn('autoscale', 'Автомасштаб по данным', self.autoscale, shortcut='A'))
        self.norm_btn = self._icon_btn('normalize', 'Нормировка амплитуды к максимуму (дБ)', self._toggle_norm, checkable=True, shortcut='N')
        self.norm_btn.setChecked(self._normalize)
        col.addWidget(self.norm_btn)
        col.addSpacing(8)
        col.addWidget(self._icon_btn('csv', 'Экспорт данных в CSV', self._export_csv))
        col.addWidget(self._icon_btn('png', 'Экспорт графика в PNG', self._export_png))
        col.addStretch(1)
        return panel

    def _build_plane_bar(self):
        """Тумблеры видимости трасс — в правом верхнем углу над графиком."""
        bar = QtWidgets.QHBoxLayout()
        bar.setContentsMargins(0, 0, 4, 0)
        bar.setSpacing(4)
        bar.addStretch(1)
        bar.addWidget(QtWidgets.QLabel('Трассы:'))
        for name, color, _axis in self._trace_defs:
            btn = QtWidgets.QToolButton()
            btn.setText(name)
            btn.setCheckable(True)
            btn.setChecked(True)
            btn.setToolTip(f'Показать/скрыть «{name}»')
            btn.setStyleSheet(f'QToolButton:checked {{ color: {color}; font-weight: 600; }}')
            btn.clicked.connect(lambda _=False, n=name: self._toggle_trace(n))
            bar.addWidget(btn)
            self._vis_btns[name] = btn
        return bar

    # --------------------------------------------------------------- данные
    def _disp(self, trace):
        if trace['amp'] and self._normalize:
            return trace['y_raw'] - trace['max_val']
        return trace['y_raw']

    def _visible_traces(self):
        return [t for t in self._traces if t['visible'] and t['x'].size]

    def _visible_amp_traces(self):
        return [t for t in self._traces if t['visible'] and t['amp'] and t['x'].size]

    def _toggle_trace(self, name):
        btn = self._vis_btns.get(name)
        for trace in self._traces:
            if trace['name'] == name:
                trace['visible'] = btn.isChecked() if btn else True
                if trace['visible'] and trace['x'].size:
                    trace['curve'].setData(trace['x'], self._disp(trace))
                    trace['curve'].show()
                else:
                    trace['curve'].hide()
        self._update_intersections()

    def set_data(self, traces_data):
        """traces_data: список (x, y_raw, max_val) в порядке trace_defs."""
        for trace, (x, y_raw, max_val) in zip(self._traces, traces_data):
            trace['x'] = np.asarray(x, dtype=float)
            trace['y_raw'] = np.asarray(y_raw, dtype=float)
            trace['max_val'] = float(max_val)
            if trace['x'].size and trace['visible']:
                trace['curve'].setData(trace['x'], self._disp(trace))
                trace['curve'].show()
            else:
                trace['curve'].setData([], [])
        self._refresh_mask()
        self._update_intersections()

    def clear_data(self):
        self.set_data([(np.array([]), np.array([]), 0.0) for _ in self._traces])

    def hold_current(self, label):
        self._overlay_count += 1
        color = OVERLAY_COLORS[(self._overlay_count - 1) % len(OVERLAY_COLORS)]
        for trace in self._traces:
            if trace['x'].size == 0:
                continue
            name = f'{label} · {trace["name"]}'
            curve = pg.PlotDataItem(trace['x'].copy(), self._disp(trace).copy(),
                                    pen=pg.mkPen(color, width=1, style=QtCore.Qt.DotLine), name=name)
            trace['vb'].addItem(curve)
            self.legend.addItem(curve, name)
            self._overlays.append([curve, trace['vb'], name])

    def clear_overlays(self):
        for curve, vb, name in self._overlays:
            vb.removeItem(curve)
            try:
                self.legend.removeItem(name)
            except Exception:
                pass
        self._overlays = []

    # ---------------------------------------------------------- управление
    def autoscale(self):
        self._pi.enableAutoRange(x=True)
        self.vbL.enableAutoRange(y=True)
        self.vbR.enableAutoRange(y=True)

    def reset_view(self):
        self._pi.enableAutoRange(x=True)
        self.vbL.setYRange(*self._left_range)
        self.vbR.setYRange(*self._right_range)

    def _toggle_norm(self):
        self._normalize = self.norm_btn.isChecked()
        for trace in self._traces:
            if trace['amp'] and trace['x'].size and trace['visible']:
                trace['curve'].setData(trace['x'], self._disp(trace))
        self._refresh_mask()
        self._update_intersections()

    # ----------------------------------------------------- маска УБЛ
    def set_sll_mask(self, db_below):
        """Включить маску (db_below — предел в дБ от максимума, <0) или None — выкл."""
        self._mask_db = db_below
        self._refresh_mask()

    def _mask_level(self):
        amps = self._visible_amp_traces()
        if not amps or self._mask_db is None:
            return None
        top = max(float(np.max(self._disp(t))) for t in amps)
        return top + self._mask_db

    def _refresh_mask(self):
        level = self._mask_level()
        if level is None:
            if self._mask_line is not None:
                self.plot.removeItem(self._mask_line)
                self._mask_line = None
            return
        if self._mask_line is None:
            self._mask_line = pg.InfiniteLine(
                angle=0, movable=False,
                pen=pg.mkPen(MASK_COLOR, width=1.6, style=QtCore.Qt.DashDotLine),
                label='Маска УБЛ', labelOpts={'position': 0.04, 'color': MASK_COLOR})
            self._mask_line.setZValue(5)
            self.plot.addItem(self._mask_line)
        self._mask_line.setValue(level)

    # ------------------------------------------------------------ курсоры
    @staticmethod
    def _crossings(x, y, level):
        """Точки пересечения ломаной (x, y) с горизонтальным уровнем (интерп.)."""
        x = np.asarray(x, dtype=float)
        y = np.asarray(y, dtype=float)
        d = y - level
        res = []
        for i in range(d.size - 1):
            d0, d1 = d[i], d[i + 1]
            if d0 == 0.0:
                res.append(float(x[i]))
            if (d0 < 0 < d1) or (d1 < 0 < d0):
                t = d0 / (d0 - d1)
                res.append(float(x[i] + t * (x[i + 1] - x[i])))
        if d.size and d[-1] == 0.0:
            res.append(float(x[-1]))
        return res

    def _make_dots(self, vb, color):
        dots = pg.ScatterPlotItem(size=10, symbol='o',
                                  brush=pg.mkBrush(color), pen=pg.mkPen('w', width=1))
        dots.setZValue(40)
        vb.addItem(dots, ignoreBounds=True)
        return dots

    def _new_cursor_record(self, line, kind, peak=False):
        if peak:
            color = PEAK_COLOR
        else:
            color = MARKER_V_COLOR if kind == 'v' else MARKER_H_COLOR
        return {
            'line': line, 'kind': kind, 'peak': peak,
            'dotsL': self._make_dots(self.vbL, color),
            'dotsR': self._make_dots(self.vbR, color),
            'labelsL': [], 'labelsR': [],
        }

    def _make_vcursor(self, x, peak=False):
        color = PEAK_COLOR if peak else MARKER_V_COLOR
        width = PEAK_WIDTH if peak else MARKER_WIDTH
        line = pg.InfiniteLine(pos=x, angle=90, movable=True,
                               pen=pg.mkPen(color, width=width, style=QtCore.Qt.DashLine),
                               label='{value:0.2f}°', labelOpts={'position': 0.97, 'color': color})
        line.sigPositionChanged.connect(self._update_intersections)
        if peak:
            # Маркер поиска максимума «магнитится» к локальным максимумам при сдвиге.
            line.sigDragged.connect(self._snap_peak_to_nearest)
        self.plot.addItem(line)
        cur = self._new_cursor_record(line, 'v', peak=peak)
        self._cursors.append(cur)
        return cur

    def _add_vcursor(self):
        x0 = 0.0
        vis = self._visible_traces()
        if vis:
            x0 = float(vis[0]['x'][vis[0]['x'].size // 2])
        self._make_vcursor(x0)
        self._update_intersections()

    def _add_hcursor(self):
        y0 = -3.0
        vis = self._visible_amp_traces()
        if vis:
            y0 = float(np.max(self._disp(vis[0]))) - 3.0
        line = pg.InfiniteLine(pos=y0, angle=0, movable=True,
                               pen=pg.mkPen(MARKER_H_COLOR, width=MARKER_WIDTH, style=QtCore.Qt.DashLine),
                               label='{value:0.2f}', labelOpts={'position': 0.95, 'color': MARKER_H_COLOR})
        line.sigPositionChanged.connect(self._update_intersections)
        self.plot.addItem(line)
        self._cursors.append(self._new_cursor_record(line, 'h'))
        self._update_intersections()

    # ---------------------------------------------------- поиск максимумов
    # Только по амплитудным (левым) трассам. Чтобы искать в одной плоскости —
    # скройте вторую амплитудную трассу тумблером справа сверху.
    def _peak_vcursor(self, x):
        if self._peak_cursor is None or self._peak_cursor not in self._cursors:
            self._peak_cursor = self._make_vcursor(x, peak=True)
        else:
            self._peak_cursor['line'].setValue(x)
        self._update_intersections()

    def _local_max_angles(self):
        """Отсортированные углы (°) всех локальных максимумов видимых амплитуд."""
        angles = []
        for trace in self._visible_amp_traces():
            for p in find_peak_indices(self._disp(trace)):
                angles.append(float(trace['x'][p]))
        if not angles:
            return []
        return sorted(set(round(a, 6) for a in angles))

    def _snap_peak_to_nearest(self):
        """Притянуть маркер-максимум к ближайшему локальному максимуму (магнит)."""
        if self._peak_cursor is None or self._peak_cursor not in self._cursors:
            return
        angles = self._local_max_angles()
        if not angles:
            return
        x = float(self._peak_cursor['line'].value())
        nearest = min(angles, key=lambda a: abs(a - x))
        if abs(nearest - x) > 1e-9:
            self._peak_cursor['line'].setValue(nearest)

    def _peak_cursor_x(self):
        if self._peak_cursor is not None and self._peak_cursor in self._cursors:
            return float(self._peak_cursor['line'].value())
        return -np.inf

    def _marker_to_max(self):
        best_x, best_y = None, None
        for trace in self._visible_amp_traces():
            disp = self._disp(trace)
            i = int(np.argmax(disp))
            if best_y is None or disp[i] > best_y:
                best_y, best_x = float(disp[i]), float(trace['x'][i])
        if best_x is not None:
            self._peak_vcursor(best_x)

    def _next_local_max(self):
        angles = self._local_max_angles()
        if not angles:
            return
        cur_x = self._peak_cursor_x()
        nxt = [a for a in angles if a > cur_x + 1e-6]
        self._peak_vcursor(nxt[0] if nxt else angles[0])

    # -------------------------------------- удаление/правка линий (ПКМ / 2×клик)
    def _remove_cursor(self, cur):
        self.plot.removeItem(cur['line'])
        self.vbL.removeItem(cur['dotsL'])
        self.vbR.removeItem(cur['dotsR'])
        for lab in cur['labelsL']:
            self.vbL.removeItem(lab)
        for lab in cur['labelsR']:
            self.vbR.removeItem(lab)
        if cur in self._cursors:
            self._cursors.remove(cur)
        if cur is self._peak_cursor:
            self._peak_cursor = None
        self._update_intersections()

    def _cursor_near(self, scene_pos, thresh_px=8):
        mp = self.vbL.mapSceneToView(scene_pos)
        try:
            xpix, ypix = self.vbL.viewPixelSize()
        except Exception:
            return None
        best, best_d = None, thresh_px
        for cur in self._cursors:
            v = float(cur['line'].value())
            d = abs(mp.x() - v) / xpix if cur['kind'] == 'v' else abs(mp.y() - v) / ypix
            if d < best_d:
                best_d, best = d, cur
        return best

    def _on_scene_click(self, ev):
        try:
            cur = self._cursor_near(ev.scenePos())
            if cur is not None:
                if ev.button() == QtCore.Qt.RightButton:
                    self._remove_cursor(cur)
                    ev.accept()
                elif ev.button() == QtCore.Qt.LeftButton and ev.double():
                    self._edit_cursor(cur)
                    ev.accept()
                return
            # Клик не по линии: двойной ЛКМ по полю графика — автомасштаб.
            if (ev.button() == QtCore.Qt.LeftButton and ev.double()
                    and self.plot.sceneBoundingRect().contains(ev.scenePos())):
                self.autoscale()
                ev.accept()
        except Exception:
            logger.exception('Ошибка обработки клика по графику')

    def _edit_cursor(self, cur):
        line = cur['line']
        if cur['kind'] == 'v':
            title, label = 'Вертикальный маркер', 'Угол, °:'
        else:
            title, label = 'Горизонтальный маркер', f'Уровень, {self._left_unit}:'
        val, ok = QtWidgets.QInputDialog.getDouble(self, title, label, float(line.value()),
                                                   -1.0e9, 1.0e9, 3)
        if ok:
            line.setValue(val)

    def _v_points(self, x0):
        out = []
        for trace in self._visible_traces():
            y = float(np.interp(x0, trace['x'], self._disp(trace)))
            out.append({'x': x0, 'y': y, 'axis': trace['axis'], 'color': trace['color'],
                        'label': f'{y:.2f} {trace["unit"]}', 'summary': f"{trace['name']}={y:.2f}"})
        return out

    def _h_points(self, level):
        out = []
        for trace in self._visible_amp_traces():
            disp = self._disp(trace)
            xs = self._crossings(trace['x'], disp, level)
            if xs:
                for xv in xs:
                    out.append({'x': xv, 'y': level, 'axis': 'L',
                                'color': trace['color'], 'label': f'{xv:.2f}°'})
                summ = ", ".join(f"{v:.2f}°" for v in xs)
                if len(xs) >= 2:
                    summ += f" (Δ={max(xs) - min(xs):.2f}°)"
                out[-1]['summary'] = f"{trace['name']}: {summ}"
            else:
                i = int(np.argmin(np.abs(disp - level)))
                out.append({'x': float(trace['x'][i]), 'y': float(disp[i]), 'axis': 'L',
                            'color': trace['color'], 'label': f'≈{trace["x"][i]:.2f}°',
                            'summary': f"{trace['name']}: ≈{trace['x'][i]:.2f}° (нет пересеч.)"})
        return out

    def _sync_labels(self, store, points, vb):
        while len(store) < len(points):
            # Крупный шрифт + компактная непрозрачная плашка, чтобы цифры
            # читались и не сливались с линией.
            t = pg.TextItem(anchor=(0.5, 1.4),
                            fill=pg.mkBrush(255, 255, 255, 230),
                            border=pg.mkPen('#cbd5e1'))
            t.setFont(self._label_font)
            t.setZValue(41)
            vb.addItem(t, ignoreBounds=True)
            store.append(t)
        for i, lab in enumerate(store):
            if i < len(points):
                p = points[i]
                lab.setText(p['label'])
                lab.setColor(p['color'])
                lab.setPos(p['x'], p['y'])
                lab.show()
            else:
                lab.hide()

    def _render_intersection(self, cur, points):
        left = [p for p in points if p['axis'] == 'L']
        right = [p for p in points if p['axis'] == 'R']
        cur['dotsL'].setData([p['x'] for p in left], [p['y'] for p in left])
        cur['dotsR'].setData([p['x'] for p in right], [p['y'] for p in right])
        self._sync_labels(cur['labelsL'], left, self.vbL)
        self._sync_labels(cur['labelsR'], right, self.vbR)
        return [p['summary'] for p in points if 'summary' in p]

    def _update_intersections(self):
        parts = []
        for cur in self._cursors:
            val = float(cur['line'].value())
            points = self._v_points(val) if cur['kind'] == 'v' else self._h_points(val)
            summ = self._render_intersection(cur, points)
            tag = 'Верт.' if cur['kind'] == 'v' else 'Гориз.'
            if summ:
                parts.append(f"{tag} {val:.2f}: " + "; ".join(summ))
        self._cursor_text = "   |   ".join(parts)
        self._update_readout()

    def clear_annotations(self):
        for cur in list(self._cursors):
            self._remove_cursor(cur)
        self._cursors = []
        self._cursor_text = ''
        self._update_readout()

    # ------------------------------------------------- наведение (значение точки)
    def _nearest_point(self, scene_pos):
        """Ближайшая точка среди видимых трасс (пиксельное расстояние по своей оси)."""
        best, best_d = None, None
        for ti, trace in enumerate(self._traces):
            if not trace['visible'] or trace['x'].size == 0:
                continue
            vb = trace['vb']
            mp = vb.mapSceneToView(scene_pos)
            try:
                xpix, ypix = vb.viewPixelSize()
            except Exception:
                continue
            if xpix == 0 or ypix == 0:
                continue
            disp = self._disp(trace)
            d = ((trace['x'] - mp.x()) / xpix) ** 2 + ((disp - mp.y()) / ypix) ** 2
            i = int(np.argmin(d))
            if best_d is None or d[i] < best_d:
                best_d, best = float(d[i]), (ti, i)
        return best

    def _point_text(self, trace, xv, yv):
        return f'{trace["name"]}: {xv:.2f}°  {yv:.2f} {trace["unit"]}'

    def _hide_hover(self):
        for h in self._hover.values():
            h['dot'].setData([], [])
            h['lab'].hide()
        self.vline.hide()
        self._hover_text = ''

    def _on_mouse_move(self, evt):
        try:
            pos = evt[0]
            if not self.plot.sceneBoundingRect().contains(pos):
                self._hide_hover()
                self._update_readout()
                return
            hit = self._nearest_point(pos)
            if hit is None:
                return
            ti, idx = hit
            trace = self._traces[ti]
            xv = float(trace['x'][idx])
            yv = float(self._disp(trace)[idx])
            for key, h in self._hover.items():
                if key == trace['axis']:
                    h['dot'].setData([xv], [yv])
                    h['dot'].setBrush(pg.mkBrush(trace['color']))
                    h['lab'].setText(self._point_text(trace, xv, yv))
                    h['lab'].setColor(trace['color'])
                    h['lab'].setPos(xv, yv)
                    h['lab'].show()
                else:
                    h['dot'].setData([], [])
                    h['lab'].hide()
            self.vline.setPos(xv)
            self.vline.show()
            self._hover_text = self._point_text(trace, xv, yv)
            self._update_readout()
        except Exception:
            pass

    def _update_readout(self):
        parts = []
        if self._hover_text:
            parts.append('▶ ' + self._hover_text)
        if self._cursor_text:
            parts.append(self._cursor_text)
        self.readout.setText('      '.join(parts) if parts else ' ')

    # ------------------------------------------------------------ экспорт
    def _export_png(self):
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, 'Сохранить график', 'far_field.png', 'PNG (*.png)')
        if not path:
            return
        try:
            pg.exporters.ImageExporter(self._pi).export(path)
            logger.info(f'График сохранён: {path}')
        except Exception as exc:
            logger.error(f'Ошибка экспорта PNG: {exc}')
            QtWidgets.QMessageBox.critical(self, 'Ошибка экспорта', str(exc))

    def _export_csv(self):
        if not any(t['x'].size for t in self._traces):
            return
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, 'Сохранить данные', 'far_field.csv', 'CSV (*.csv)')
        if not path:
            return
        try:
            with open(path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f, delimiter=';')
                for trace in self._traces:
                    if trace['x'].size == 0:
                        continue
                    writer.writerow([f'{trace["name"]} угол, °'] + [f'{v:.4f}' for v in trace['x']])
                    writer.writerow([f'{trace["name"]}, {trace["unit"]}'] + [f'{v:.4f}' for v in self._disp(trace)])
            logger.info(f'Данные сохранены: {path}')
        except Exception as exc:
            logger.error(f'Ошибка экспорта CSV: {exc}')
            QtWidgets.QMessageBox.critical(self, 'Ошибка экспорта', str(exc))


# ==================================================================== Окно
class FarFieldDialog(QtWidgets.QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Дальняя зона (расчёт ДН)')
        self.setWindowFlags(
            self.windowFlags()
            | QtCore.Qt.WindowMaximizeButtonHint
            | QtCore.Qt.WindowMinimizeButtonHint
            | QtCore.Qt.WindowSystemMenuHint
        )
        self.setSizeGripEnabled(True)
        self.setMinimumSize(1080, 700)
        self.resize(1300, 820)
        self.setAcceptDrops(True)

        self._result = None
        self._folder = None
        self._single_file_mode = False
        self._beams = []
        self._freqs = []
        self._computed_beams = []
        self._computed_freqs = []
        self._cache = {}
        self._params = self._load_saved_params()
        self._default_step = (1.0, 1.0)
        self._az_deg = None
        self._el_deg = None
        self._updating = False
        self._thread = None
        self._worker = None

        self._build_ui()
        self._restore_window_state()

    # ------------------------------------------------ запоминание параметров
    @staticmethod
    def _settings():
        return QtCore.QSettings('FarZone', 'FarField')

    _PARAM_KEYS = ('az_from', 'az_to', 'az_step', 'el_from', 'el_to', 'el_step', 'dx', 'dy')

    def _load_saved_params(self):
        """Прочитать последние введённые параметры пересчёта (между сессиями)."""
        s = self._settings()
        s.beginGroup('far_field/params')
        params = {}
        try:
            for k in self._PARAM_KEYS:
                v = s.value(k)
                if v is not None:
                    params[k] = float(v)
            pad = s.value('pad')
            if pad is not None:
                params['pad'] = int(pad)
            for k in ('interp', 'abs_mode'):
                v = s.value(k)
                if v is not None:
                    params[k] = str(v)
        finally:
            s.endGroup()
        return params or None

    def _save_params(self, params):
        if not params:
            return
        s = self._settings()
        s.beginGroup('far_field/params')
        try:
            for k in self._PARAM_KEYS:
                if k in params:
                    s.setValue(k, float(params[k]))
            if 'pad' in params:
                s.setValue('pad', int(params['pad']))
            for k in ('interp', 'abs_mode'):
                if k in params:
                    s.setValue(k, str(params[k]))
        finally:
            s.endGroup()
        s.sync()

    # ----------------------------------- запоминание окна и последней папки
    def _restore_window_state(self):
        geo = self._settings().value('far_field/geometry')
        if geo is not None:
            try:
                self.restoreGeometry(geo)
            except Exception:
                pass

    def _save_window_state(self):
        self._settings().setValue('far_field/geometry', self.saveGeometry())

    def _last_folder(self):
        return self._settings().value('far_field/last_folder', '') or ''

    def _set_last_folder(self, folder):
        self._settings().setValue('far_field/last_folder', folder)

    def _build_ui(self):
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)
        root.addLayout(self._build_top_bar())
        body = QtWidgets.QHBoxLayout()
        body.setSpacing(10)
        body.addWidget(self._build_left_panel(), 0)
        body.addWidget(self._build_plots(), 1)
        root.addLayout(body, 1)
        root.addLayout(self._build_progress_bar())

    def _build_top_bar(self):
        bar = QtWidgets.QHBoxLayout()
        bar.setSpacing(8)

        self.open_btn = QtWidgets.QPushButton('Открыть папку')
        set_button_icon(self.open_btn, 'folder-open')
        self.open_btn.setToolTip('Выбрать папку с результатами сканирования лучей (Beam№*.xlsx)')
        self.open_btn.clicked.connect(self.open_folder)
        bar.addWidget(self.open_btn)

        self.open_file_btn = QtWidgets.QPushButton('Открыть файл')
        set_button_icon(self.open_file_btn, 'file-open')
        self.open_file_btn.setToolTip('Открыть отдельный файл измерения для пересчёта '
                                      '(имя любое — важен формат внутри); '
                                      'шаг dx/dy и др. задаются вручную')
        self.open_file_btn.clicked.connect(self.open_file)
        bar.addWidget(self.open_file_btn)

        self.params_btn = QtWidgets.QPushButton('Параметры…')
        set_button_icon(self.params_btn, 'settings')
        self.params_btn.setToolTip('Изменить параметры пересчёта и набор лучей/частот')
        self.params_btn.clicked.connect(self.open_params)
        self.params_btn.setEnabled(False)
        bar.addWidget(self.params_btn)

        self.folder_label = QtWidgets.QLabel('Папка не выбрана')
        self.folder_label.setObjectName('ffFolderLabel')
        bar.addWidget(self.folder_label, 1)

        self.hold_btn = QtWidgets.QPushButton('Закрепить')
        set_button_icon(self.hold_btn, 'pin')
        self.hold_btn.setToolTip('Закрепить текущие трассы для сравнения')
        self.hold_btn.clicked.connect(self._hold_traces)
        self.hold_btn.setEnabled(False)
        bar.addWidget(self.hold_btn)

        self.clear_overlays_btn = QtWidgets.QPushButton('Очистить нал.')
        set_button_icon(self.clear_overlays_btn, 'eraser')
        self.clear_overlays_btn.setToolTip('Убрать закреплённые трассы')
        self.clear_overlays_btn.clicked.connect(self._clear_overlays)
        self.clear_overlays_btn.setEnabled(False)
        bar.addWidget(self.clear_overlays_btn)

        self.beam_kind_label = QtWidgets.QLabel('Луч:')
        bar.addWidget(self.beam_kind_label)
        self.beam_prev_btn = self._nav_button('back', 'Предыдущий луч  [←]', self._beam_prev,
                                              QtGui.QKeySequence(QtCore.Qt.Key_Left))
        bar.addWidget(self.beam_prev_btn)
        self.beam_combo = QtWidgets.QComboBox()
        self.beam_combo.setMinimumWidth(90)
        self.beam_combo.currentIndexChanged.connect(self._on_selection_changed)
        bar.addWidget(self.beam_combo)
        self.beam_next_btn = self._nav_button('forward', 'Следующий луч  [→]', self._beam_next,
                                              QtGui.QKeySequence(QtCore.Qt.Key_Right))
        bar.addWidget(self.beam_next_btn)

        bar.addSpacing(12)
        bar.addWidget(QtWidgets.QLabel('Частота:'))
        self.freq_prev_btn = self._nav_button('back', 'Предыдущая частота  [PgUp]', self._freq_prev,
                                              QtGui.QKeySequence(QtCore.Qt.Key_PageUp))
        bar.addWidget(self.freq_prev_btn)
        self.freq_combo = QtWidgets.QComboBox()
        self.freq_combo.setMinimumWidth(110)
        self.freq_combo.currentIndexChanged.connect(self._on_selection_changed)
        bar.addWidget(self.freq_combo)
        self.freq_next_btn = self._nav_button('forward', 'Следующая частота  [PgDn]', self._freq_next,
                                              QtGui.QKeySequence(QtCore.Qt.Key_PageDown))
        bar.addWidget(self.freq_next_btn)
        return bar

    def _nav_button(self, icon, tooltip, slot, shortcut=None):
        btn = QtWidgets.QToolButton()
        btn.setProperty('navButton', True)
        set_button_icon(btn, icon, size=14)
        if shortcut is not None:
            btn.setShortcut(shortcut)
        btn.setToolTip(tooltip)
        btn.clicked.connect(slot)
        return btn

    def _build_progress_bar(self):
        row = QtWidgets.QHBoxLayout()
        self.progress = QtWidgets.QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setTextVisible(True)
        self.progress.setVisible(False)
        row.addWidget(self.progress, 1)
        self.cancel_btn = QtWidgets.QPushButton('Отмена')
        set_button_icon(self.cancel_btn, 'stop')
        self.cancel_btn.clicked.connect(self._cancel_compute)
        self.cancel_btn.setVisible(False)
        row.addWidget(self.cancel_btn)
        return row

    def _build_left_panel(self):
        panel = QtWidgets.QWidget()
        panel.setFixedWidth(300)
        layout = QtWidgets.QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        metrics_group = QtWidgets.QGroupBox('Результаты')
        m = QtWidgets.QFormLayout(metrics_group)
        m.setContentsMargins(12, 12, 12, 12)
        self.lbl_max = self._metric()
        self.lbl_pos_az = self._metric()
        self.lbl_pos_el = self._metric()
        self.lbl_sll_az = self._metric()
        self.lbl_sll_el = self._metric()
        self.lbl_bw_az = self._metric()
        self.lbl_bw_el = self._metric()
        self.lbl_phase_max = self._metric()
        self.lbl_set_angle = self._metric()
        m.addRow('Максимум, дБ:', self.lbl_max)
        m.addRow('Положение Az, °:', self.lbl_pos_az)
        m.addRow('Положение El, °:', self.lbl_pos_el)
        m.addRow('Ширина ДН Az (−3дБ), °:', self.lbl_bw_az)
        m.addRow('Ширина ДН El (−3дБ), °:', self.lbl_bw_el)
        m.addRow('УБЛ Az, дБ:', self.lbl_sll_az)
        m.addRow('УБЛ El, дБ:', self.lbl_sll_el)
        m.addRow('Фаза в макс., °:', self.lbl_phase_max)
        m.addRow('Задан. (α/β), °:', self.lbl_set_angle)
        layout.addWidget(metrics_group)

        mask_group = QtWidgets.QGroupBox('Маска УБЛ')
        mg = QtWidgets.QGridLayout(mask_group)
        mg.setContentsMargins(12, 10, 12, 10)
        self.mask_check = QtWidgets.QCheckBox('Показать маску')
        self.mask_check.setToolTip('Предел уровня боковых лепестков относительно главного максимума')
        self.mask_check.toggled.connect(self._update_mask)
        self.mask_spin = QtWidgets.QDoubleSpinBox()
        self.mask_spin.setRange(-60, -1)
        self.mask_spin.setDecimals(1)
        self.mask_spin.setSingleStep(1.0)
        self.mask_spin.setValue(-20.0)
        self.mask_spin.setSuffix(' дБ')
        self.mask_spin.valueChanged.connect(self._update_mask)
        self.mask_result = QtWidgets.QLabel('—')
        self.mask_result.setWordWrap(True)
        mg.addWidget(self.mask_check, 0, 0, 1, 2)
        mg.addWidget(QtWidgets.QLabel('Предел:'), 1, 0)
        mg.addWidget(self.mask_spin, 1, 1)
        mg.addWidget(self.mask_result, 2, 0, 1, 2)
        layout.addWidget(mask_group)

        layout.addStretch(1)

        self.export_table_btn = QtWidgets.QPushButton('Экспорт таблицы метрик…')
        set_button_icon(self.export_table_btn, 'export')
        self.export_table_btn.setToolTip('Сохранить метрики всех рассчитанных лучей и частот в Excel или CSV')
        self.export_table_btn.clicked.connect(self._export_metrics_table)
        self.export_table_btn.setEnabled(False)
        layout.addWidget(self.export_table_btn)
        return panel

    def _build_plots(self):
        self.plot_panel = FarFieldPlotPanel([
            ('Az ампл.', AZ_COLOR, 'L'),
            ('El ампл.', EL_COLOR, 'L'),
            ('Az фаза', PHASE_AZ_COLOR, 'R'),
            ('El фаза', PHASE_EL_COLOR, 'R'),
        ])
        self.panels = [self.plot_panel]
        return self.plot_panel

    @staticmethod
    def _metric():
        lbl = QtWidgets.QLabel('—')
        lbl.setProperty('metricValue', True)
        lbl.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        return lbl

    # --------------------------------------------------------------- Поток
    def _busy_warn(self):
        if self._worker is not None:
            QtWidgets.QMessageBox.information(self, 'Идёт расчёт',
                                             'Дождитесь окончания текущего расчёта или отмените его.')
            return True
        return False

    def open_folder(self):
        folder = QtWidgets.QFileDialog.getExistingDirectory(
            self, 'Выберите папку с результатами сканирования лучей', self._last_folder())
        if not folder:
            return
        self._load_folder(folder)

    def open_file(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, 'Выберите файл для пересчёта',
            self._last_folder(), 'Все файлы (*);;Файлы измерений (*.xlsx)')
        if not path:
            return
        self._load_file(path)

    # ------------------------------------------------------- Drag-and-drop
    @staticmethod
    def _dropped_target(mime):
        """Вернуть ('dir', path) для папки или ('file', path) для любого файла.

        Любой файл принимаем — корректность формата проверит загрузчик.
        """
        for url in mime.urls():
            if url.isLocalFile():
                path = url.toLocalFile()
                if os.path.isdir(path):
                    return 'dir', path
                if os.path.isfile(path):
                    return 'file', path
        return None

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls() and self._dropped_target(event.mimeData()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        target = self._dropped_target(event.mimeData()) if event.mimeData().hasUrls() else None
        if not target:
            event.ignore()
            return
        event.acceptProposedAction()
        kind, path = target
        if kind == 'dir':
            self._load_folder(path)
        else:
            self._load_file(path)

    def _load_folder(self, folder):
        if self._busy_warn():
            return
        result = load_beam_pattern_results(folder)
        if not result or not result.get('data'):
            QtWidgets.QMessageBox.warning(self, 'Ошибка', 'Не удалось загрузить данные из выбранной папки.')
            return
        self._set_last_folder(folder)
        try:
            step = (float(result.get('step_x', 1.0)), float(result.get('step_y', 1.0)))
        except (TypeError, ValueError):
            step = (1.0, 1.0)
        self._apply_result(result, folder, single_file=False, scan_step=step)

    def _load_file(self, path):
        if self._busy_warn():
            return
        try:
            result = load_single_beam_file(path)
        except BeamFileFormatError as exc:
            QtWidgets.QMessageBox.warning(
                self, 'Неподходящий файл',
                f'{os.path.basename(path)}\n\n{exc}')
            return
        except Exception as exc:
            logger.error(f'Ошибка чтения файла {path}: {exc}', exc_info=True)
            QtWidgets.QMessageBox.critical(
                self, 'Ошибка', f'Не удалось прочитать файл:\n{exc}')
            return
        self._set_last_folder(os.path.dirname(path))
        self._apply_result(result, path, single_file=True, scan_step=None)

    def _apply_result(self, result, source, single_file, scan_step):
        """Применить загруженный набор данных (папка или одиночный файл)."""
        self._result = result
        self._folder = source
        self._single_file_mode = single_file
        self._beams = sorted(result['data'].keys())
        self._freqs = list(result.get('freq_list') or [])
        if not self._freqs and self._beams:
            self._freqs = sorted(result['data'][self._beams[0]].keys())

        self.folder_label.setText(os.path.basename(source.rstrip('/\\')) or source)
        self.folder_label.setToolTip(source)
        self.beam_kind_label.setText('Файл:' if single_file else 'Луч:')
        self.params_btn.setEnabled(True)

        if self._params is None:
            self._params = {}
        if single_file:
            # Шаг сканера неизвестен — dx/dy вводятся вручную (берём прошлые или 1.0).
            self._default_step = (float(self._params.get('dx', 1.0)),
                                  float(self._params.get('dy', 1.0)))
        else:
            # Запомненные диапазоны/шаги/БПФ сохраняем, но dx/dy берём из шага скана.
            self._default_step = scan_step
            self._params['dx'], self._params['dy'] = self._default_step

        kind = 'файл' if single_file else 'лучей'
        logger.info(f'Загружено {kind}: {len(self._beams)}, частот: {len(self._freqs)} из {source}')
        self.open_params()

    def open_params(self):
        if self._result is None:
            return
        defaults = dict(self._params) if self._params else {}
        defaults.setdefault('dx', self._default_step[0])
        defaults.setdefault('dy', self._default_step[1])
        dlg = FarFieldParamsDialog(self._beams, self._freqs, defaults=defaults,
                                   single_file=self._single_file_mode, parent=self)
        if dlg.exec_() != QtWidgets.QDialog.Accepted:
            return
        self._params = dlg.params()
        self._save_params(self._params)
        self._az_deg = angle_axis(self._params['az_from'], self._params['az_to'], self._params['az_step'])
        self._el_deg = angle_axis(self._params['el_from'], self._params['el_to'], self._params['el_step'])
        tasks = [(b, f) for b in dlg.selected_beams() for f in dlg.selected_freqs()]
        self._start_compute(tasks)

    def _start_compute(self, tasks):
        if not tasks:
            return
        self._set_busy(True)
        self.progress.setRange(0, len(tasks))
        self.progress.setValue(0)

        self._thread = QtCore.QThread()
        self._worker = _FarFieldWorker(self._result['data'], tasks, self._params)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_compute_finished)
        self._worker.failed.connect(self._on_compute_failed)
        # Удаляем объекты ТОЛЬКО после полной остановки потока (thread.finished),
        # иначе "QThread: Destroyed while thread is still running".
        self._worker.done.connect(self._thread.quit)
        self._thread.finished.connect(self._on_thread_finished)
        self._thread.start()

    @QtCore.pyqtSlot()
    def _on_thread_finished(self):
        if self._worker is not None:
            self._worker.deleteLater()
        if self._thread is not None:
            self._thread.deleteLater()
        self._worker = None
        self._thread = None

    @QtCore.pyqtSlot(int, int, str)
    def _on_progress(self, done, total, msg):
        self.progress.setValue(done)
        self.progress.setFormat(f'{msg}  ({done}/{total})')

    @QtCore.pyqtSlot(dict)
    def _on_compute_finished(self, cache):
        try:
            self._cache = cache
            self._set_busy(False)
            if not cache:
                QtWidgets.QMessageBox.information(self, 'Нет результатов',
                                                  'Ни один выбранный луч/частота не содержит данных.')
                return
            beams = sorted({b for b, _ in cache.keys()})
            freqs = sorted({f for _, f in cache.keys()})
            self._updating = True
            self.beam_combo.clear()
            self.beam_combo.addItems([str(b) for b in beams])
            self.freq_combo.clear()
            self.freq_combo.addItems([f'{f:g}' for f in freqs])
            self._computed_beams = beams
            self._computed_freqs = freqs
            self._updating = False
            self.hold_btn.setEnabled(True)
            self.clear_overlays_btn.setEnabled(True)
            self.export_table_btn.setEnabled(True)
            self._display_current()
        except Exception:
            logger.exception('Ошибка при отображении результатов расчёта дальней зоны')

    @QtCore.pyqtSlot(str)
    def _on_compute_failed(self, message):
        self._set_busy(False)
        QtWidgets.QMessageBox.critical(self, 'Ошибка расчёта', message)

    def _cancel_compute(self):
        if self._worker is not None:
            self._worker.stop()
            self.cancel_btn.setEnabled(False)

    def _set_busy(self, busy):
        self.progress.setVisible(busy)
        self.cancel_btn.setVisible(busy)
        self.cancel_btn.setEnabled(busy)
        self.open_btn.setEnabled(not busy)
        self.open_file_btn.setEnabled(not busy)
        self.params_btn.setEnabled(not busy and self._result is not None)
        for w in (self.beam_combo, self.freq_combo, self.beam_prev_btn,
                  self.beam_next_btn, self.freq_prev_btn, self.freq_next_btn):
            w.setEnabled(not busy)

    # --------------------------------------------------------- Навигация
    def _on_selection_changed(self, _index=None):
        if self._updating:
            return
        self._display_current()

    def _beam_prev(self):
        self._step_combo(self.beam_combo, -1)

    def _beam_next(self):
        self._step_combo(self.beam_combo, +1)

    def _freq_prev(self):
        self._step_combo(self.freq_combo, -1)

    def _freq_next(self):
        self._step_combo(self.freq_combo, +1)

    @staticmethod
    def _step_combo(combo, delta):
        new_index = combo.currentIndex() + delta
        if 0 <= new_index < combo.count():
            combo.setCurrentIndex(new_index)

    def _current_beam_freq(self):
        b_idx = self.beam_combo.currentIndex()
        f_idx = self.freq_combo.currentIndex()
        if b_idx < 0 or f_idx < 0:
            return None, None
        return self._computed_beams[b_idx], self._computed_freqs[f_idx]

    def _current_label(self):
        beam, freq = self._current_beam_freq()
        if beam is None:
            return ''
        prefix = '' if self._single_file_mode else 'Луч '
        return f'{prefix}{beam} / {freq:g} МГц'

    # ----------------------------------------------------------- Отрисовка
    def _display_current(self):
        beam, freq = self._current_beam_freq()
        if beam is None or freq is None:
            return
        entry = self._cache.get((beam, freq))
        if entry is None:
            self.plot_panel.clear_data()
            for lbl in (self.lbl_max, self.lbl_pos_az, self.lbl_pos_el, self.lbl_sll_az,
                        self.lbl_sll_el, self.lbl_bw_az, self.lbl_bw_el,
                        self.lbl_phase_max, self.lbl_set_angle):
                lbl.setText('—')
            self._update_mask()
            return
        self.plot_panel.set_data([
            (self._az_deg, entry['az_amp'], entry['max_val']),
            (self._el_deg, entry['el_amp'], entry['max_val']),
            (self._az_deg, entry['az_phase'], 0.0),
            (self._el_deg, entry['el_phase'], 0.0),
        ])
        self._update_metrics(beam, entry)
        self._update_mask()

    def _update_mask(self, *_):
        """Маска УБЛ: линия предела на графике + вердикт годен/не годен."""
        if not self.mask_check.isChecked():
            self.plot_panel.set_sll_mask(None)
            self.mask_result.setText('—')
            self.mask_result.setStyleSheet('')
            return
        db = self.mask_spin.value()
        self.plot_panel.set_sll_mask(db)
        beam, freq = self._current_beam_freq()
        entry = self._cache.get((beam, freq)) if beam is not None else None
        if entry is None:
            self.mask_result.setText('нет данных')
            self.mask_result.setStyleSheet('color:#667085;')
            return
        worst = None
        for arr in (entry['az_amp'], entry['el_amp']):
            sll = side_lobe_level(arr)
            if sll is not None:
                worst = sll if worst is None else max(worst, sll)
        if worst is None:
            self.mask_result.setText('боковых нет — годен')
            self.mask_result.setStyleSheet(f'color:{STATUS_ICON["ok"]}; font-weight:600;')
            return
        ok = worst <= db
        color = STATUS_ICON['ok'] if ok else STATUS_ICON['fail']
        verdict = 'ГОДЕН' if ok else 'НЕ ГОДЕН'
        self.mask_result.setText(f'{verdict}\nхудший УБЛ {worst:.1f} дБ (предел {db:.0f})')
        self.mask_result.setStyleSheet(f'color:{color}; font-weight:600;')

    @staticmethod
    def _beamwidth(x, amp):
        """Ширина главного лепестка по уровню −3 дБ (линейная интерполяция краёв)."""
        x = np.asarray(x, dtype=float)
        amp = np.asarray(amp, dtype=float)
        if amp.size < 3:
            return None
        peak = int(np.argmax(amp))
        level = amp[peak] - 3.0

        def edge(rng):
            prev = peak
            for i in rng:
                if (amp[i] - level) * (amp[prev] - level) <= 0 and amp[i] != amp[prev]:
                    t = (level - amp[prev]) / (amp[i] - amp[prev])
                    return x[prev] + t * (x[i] - x[prev])
                prev = i
            return None

        left = edge(range(peak - 1, -1, -1))
        right = edge(range(peak + 1, amp.size))
        if left is None or right is None:
            return None
        return abs(right - left)

    def _update_metrics(self, beam, entry):
        self.lbl_max.setText(f"{entry['max_val']:.2f}")
        self.lbl_pos_az.setText(f"{entry['pos_az']:.3f}")
        self.lbl_pos_el.setText(f"{entry['pos_el']:.3f}")
        bw_az = self._beamwidth(self._az_deg, entry['az_amp'])
        bw_el = self._beamwidth(self._el_deg, entry['el_amp'])
        self.lbl_bw_az.setText('—' if bw_az is None else f"{bw_az:.3f}")
        self.lbl_bw_el.setText('—' if bw_el is None else f"{bw_el:.3f}")
        self.lbl_sll_az.setText('—' if entry['sll_az'] is None else f"{entry['sll_az']:.2f}")
        self.lbl_sll_el.setText('—' if entry['sll_el'] is None else f"{entry['sll_el']:.2f}")
        self.lbl_phase_max.setText(f"{entry['phase_max']:.2f}")
        try:
            mapping = beam_to_angles(int(beam))
            self.lbl_set_angle.setText(f'α={mapping.alpha:g} / β={mapping.beta:g}')
        except Exception:
            self.lbl_set_angle.setText('—')

    # ----------------------------------------------------------- Наложение
    def _hold_traces(self):
        label = self._current_label()
        if not label:
            return
        for p in self.panels:
            p.hold_current(label)

    def _clear_overlays(self):
        for p in self.panels:
            p.clear_overlays()

    # ------------------------------------------------ Пакетный экспорт метрик
    _METRICS_HEADERS = [
        'Луч', 'Частота, МГц', 'Максимум, дБ', 'Положение Az, °', 'Положение El, °',
        'Ширина Az (−3дБ), °', 'Ширина El (−3дБ), °', 'УБЛ Az, дБ', 'УБЛ El, дБ',
        'Фаза в макс., °', 'Задан. α, °', 'Задан. β, °',
    ]

    def _metrics_rows(self):
        """Строки таблицы метрик по всем рассчитанным (луч, частота)."""
        rows = []
        for beam, freq in sorted(self._cache.keys()):
            e = self._cache[(beam, freq)]
            bw_az = self._beamwidth(self._az_deg, e['az_amp'])
            bw_el = self._beamwidth(self._el_deg, e['el_amp'])
            try:
                mp = beam_to_angles(int(beam))
                alpha, beta = mp.alpha, mp.beta
            except Exception:
                alpha = beta = None
            rows.append([
                beam, freq, round(e['max_val'], 2),
                round(e['pos_az'], 3), round(e['pos_el'], 3),
                None if bw_az is None else round(bw_az, 3),
                None if bw_el is None else round(bw_el, 3),
                None if e['sll_az'] is None else round(e['sll_az'], 2),
                None if e['sll_el'] is None else round(e['sll_el'], 2),
                round(e['phase_max'], 2), alpha, beta,
            ])
        return rows

    def _export_metrics_table(self):
        if not self._cache:
            return
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, 'Сохранить таблицу метрик', 'far_field_metrics.xlsx',
            'Excel (*.xlsx);;CSV (*.csv)')
        if not path:
            return
        rows = self._metrics_rows()
        try:
            if path.lower().endswith('.csv'):
                self._write_metrics_csv(path, self._METRICS_HEADERS, rows)
            else:
                self._write_metrics_xlsx(path, self._METRICS_HEADERS, rows)
            logger.info(f'Таблица метрик сохранена: {path} ({len(rows)} строк)')
            QtWidgets.QMessageBox.information(self, 'Готово',
                                             f'Сохранено строк: {len(rows)}\n{path}')
        except Exception as exc:
            logger.error(f'Ошибка экспорта таблицы метрик: {exc}', exc_info=True)
            QtWidgets.QMessageBox.critical(self, 'Ошибка экспорта', str(exc))

    @staticmethod
    def _write_metrics_csv(path, headers, rows):
        with open(path, 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.writer(f, delimiter=';')
            writer.writerow(headers)
            for r in rows:
                writer.writerow(['' if v is None else v for v in r])

    @staticmethod
    def _write_metrics_xlsx(path, headers, rows):
        from openpyxl import Workbook
        from openpyxl.styles import Font
        from openpyxl.utils import get_column_letter
        wb = Workbook()
        ws = wb.active
        ws.title = 'Метрики'
        ws.append(headers)
        for cell in ws[1]:
            cell.font = Font(bold=True)
        for r in rows:
            ws.append(r)
        for i, h in enumerate(headers, 1):
            ws.column_dimensions[get_column_letter(i)].width = max(12, len(h) + 2)
        ws.freeze_panes = 'A2'
        wb.save(path)

    # ------------------------------------------------------------- Закрытие
    def closeEvent(self, event):
        self._save_window_state()
        if self._worker is not None:
            self._worker.stop()
        if self._thread is not None:
            self._thread.quit()
            self._thread.wait(2000)
        super().closeEvent(event)
