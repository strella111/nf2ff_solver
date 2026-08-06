# -*- coding: utf-8 -*-
"""Подготовка ближнего поля к отрисовке в 2D — чистый numpy, без Qt.

Измерение хранится как ``[y][x]`` (строки — Y, столбцы — X, см. beam_loader),
а pyqtgraph считает ПЕРВУЮ ось картинки горизонтальной. Здесь собрано всё, что
нужно для перевода одного в другое: транспозиция, геометрия осей в сантиметрах
и пределы цветовой шкалы. Вынесено из виджета, чтобы проверялось без Qt.

Единицы: координаты и шаги — сантиметры (как в scan_params.json), амплитуда —
дБ, фаза — градусы.
"""

import numpy as np

PHASE_LEVELS = (-180.0, 180.0)


def field_image(values, flip_x=False, flip_y=False):
    """Измерение ``(y, x)`` -> картинка ``(x, y)`` для ImageItem.

    flip_x/flip_y разворачивают данные, если координаты скана идут по убыванию
    (иначе картинка окажется зеркальной относительно осей).
    """
    arr = np.asarray(values, dtype=float)
    if arr.ndim != 2:
        raise ValueError('ожидался двумерный массив измерения (y, x)')
    img = arr.T
    if flip_x:
        img = img[::-1, :]
    if flip_y:
        img = img[:, ::-1]
    return np.ascontiguousarray(img)


def _is_index_range(pts):
    """True для 0, 1, 2, … — это НОМЕРА точек, а не сантиметры.

    Так координаты подставляет beam_loader, когда scan_params.json нет
    (одиночный файл): тогда ось надо строить по шагу dx/dy из параметров.
    """
    return bool(pts) and all(p == i for i, p in enumerate(pts))


def axis_layout(coords, count, step):
    """Геометрия оси картинки: ``(начало_см, размер_см, развернуть_ли)``.

    ``coords`` — координаты точек скана из scan_params.json; если их нет или
    длина не совпала с числом точек, ось строится от нуля с шагом ``step``
    (режим одиночного файла, где dx/dy задаёт пользователь).

    Точки — ЦЕНТРЫ ячеек, поэтому края расширены на полшага: иначе крайние
    отсчёты оказались бы половинками на границе картинки.
    """
    count = int(count)
    if count <= 0:
        return 0.0, 0.0, False

    try:
        pts = [float(c) for c in (coords or [])]
    except (TypeError, ValueError):
        pts = []

    use_coords = len(pts) == count and not _is_index_range(pts)
    reverse = use_coords and count > 1 and pts[0] > pts[-1]
    lo, hi = (min(pts), max(pts)) if use_coords else (0.0, 0.0)

    if count > 1 and hi > lo:
        cell = (hi - lo) / (count - 1)
    else:
        cell = abs(float(step or 0.0)) or 1.0
        hi = lo + cell * (count - 1)
    return lo - cell / 2.0, (hi - lo) + cell, reverse


def axis_points(coords, count, step):
    """Координаты центров точек оси (см), всегда по возрастанию."""
    start, size, _reverse = axis_layout(coords, count, step)
    count = int(count)
    if count <= 0:
        return np.empty(0, dtype=float)
    cell = size / count
    return start + cell * (np.arange(count, dtype=float) + 0.5)


def prepare_maps(amp, phase, x_list, y_list, dx, dy):
    """Картинки амплитуды и фазы ``(x, y)`` + прямоугольник ``(x0, y0, w, h)``."""
    amp_arr = np.asarray(amp, dtype=float)
    if amp_arr.ndim != 2:
        raise ValueError('ожидался двумерный массив амплитуды (y, x)')
    n_y, n_x = amp_arr.shape

    x0, width, flip_x = axis_layout(x_list, n_x, dx)
    y0, height, flip_y = axis_layout(y_list, n_y, dy)

    phase_arr = np.asarray(phase, dtype=float)
    if phase_arr.shape != amp_arr.shape:
        phase_arr = np.full_like(amp_arr, np.nan)

    return {
        'amp': field_image(amp_arr, flip_x, flip_y),
        'phase': field_image(phase_arr, flip_x, flip_y),
        'rect': (x0, y0, width, height),
    }


def auto_levels(img):
    """Пределы шкалы по данным: ``(min, max)`` измеренных точек.

    Так же, как в «Измерении лучей АФАР»: без «пола» и нормировки — что
    измерено, то и в шкале. Вырожденный случай (все значения равны) немного
    раздвигается, иначе шкала схлопывается.
    """
    img = np.asarray(img, dtype=float)
    finite = img[np.isfinite(img)]
    if finite.size == 0:
        return 0.0, 1.0
    lo, hi = float(finite.min()), float(finite.max())
    if hi - lo < 1e-9:
        hi = lo + 1e-6
    return lo, hi


def expand_span(lo, hi, min_span, pad):
    """Расширить отрезок до минимальной ширины и добавить поля по краям."""
    lo, hi = lo - pad, hi + pad
    if hi - lo < min_span:
        center = (lo + hi) / 2
        lo, hi = center - min_span / 2, center + min_span / 2
    return lo, hi


def measured_bounds(amp_img, x_pts, y_pts):
    """Границы измеренных точек ``(x0, x1, y0, y1)`` для подгонки масштаба.

    ``amp_img`` — картинка ``(x, y)``. Если измеренных точек нет, берётся вся
    апертура. Вырожденный отрезок (измерена одна строка/столбец) раздвигается
    до трёх клеток: иначе pyqtgraph получает пустой диапазон и карта нечитаема.
    Возвращает None, если показывать нечего.
    """
    amp_img = np.asarray(amp_img, dtype=float)
    x_pts = np.asarray(x_pts, dtype=float)
    y_pts = np.asarray(y_pts, dtype=float)
    if x_pts.size == 0 or y_pts.size == 0:
        return None

    dx = float(x_pts[1] - x_pts[0]) if x_pts.size > 1 else 1.0
    dy = float(y_pts[1] - y_pts[0]) if y_pts.size > 1 else 1.0
    x0, x1 = float(x_pts.min()), float(x_pts.max())
    y0, y1 = float(y_pts.min()), float(y_pts.max())

    if amp_img.size:
        measured = np.isfinite(amp_img)
        if measured.any():
            cols = np.where(np.any(measured, axis=1))[0]   # какие X измерены
            rows = np.where(np.any(measured, axis=0))[0]   # какие Y измерены
            x0, x1 = float(x_pts[cols[0]]), float(x_pts[cols[-1]])
            y0, y1 = float(y_pts[rows[0]]), float(y_pts[rows[-1]])

    x0, x1 = expand_span(x0, x1, abs(dx) * 3, abs(dx) / 2)
    y0, y1 = expand_span(y0, y1, abs(dy) * 3, abs(dy) / 2)
    return x0, x1, y0, y1


def field_stats(amp_img, phase_img, x_pts, y_pts):
    """Сводка по ближнему полю для панели метрик.

    На вход — уже подготовленные картинки ``(x, y)`` и координаты точек.
    Значения, которых нет (пустое поле), возвращаются как None.
    """
    amp_img = np.asarray(amp_img, dtype=float)
    phase_img = np.asarray(phase_img, dtype=float)
    x_pts = np.asarray(x_pts, dtype=float)
    y_pts = np.asarray(y_pts, dtype=float)

    stats = {
        'n_x': int(amp_img.shape[0]) if amp_img.ndim == 2 else 0,
        'n_y': int(amp_img.shape[1]) if amp_img.ndim == 2 else 0,
        'total': int(amp_img.size),
        'measured': 0,
        'max_db': None, 'max_x': None, 'max_y': None,
        'dynamic_db': None, 'phase_span': None,
        'size_x': None, 'size_y': None,
    }

    finite = np.isfinite(amp_img)
    stats['measured'] = int(finite.sum())
    if finite.any():
        ix, iy = np.unravel_index(
            int(np.argmax(np.where(finite, amp_img, -np.inf))), amp_img.shape)
        values = amp_img[finite]
        stats['max_db'] = float(amp_img[ix, iy])
        stats['dynamic_db'] = float(values.max() - values.min())
        if ix < x_pts.size:
            stats['max_x'] = float(x_pts[ix])
        if iy < y_pts.size:
            stats['max_y'] = float(y_pts[iy])

    ph_finite = np.isfinite(phase_img)
    if ph_finite.any():
        ph = phase_img[ph_finite]
        stats['phase_span'] = float(ph.max() - ph.min())

    if x_pts.size > 1:
        stats['size_x'] = float(abs(x_pts[-1] - x_pts[0]))
    if y_pts.size > 1:
        stats['size_y'] = float(abs(y_pts[-1] - y_pts[0]))
    return stats
