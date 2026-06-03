"""Преобразование ближнего поля в дальнее (NF -> FF).

Порт MATLAB-приложения расчёта лучей АФАР. На вход — планарное амплитудно-
фазовое распределение (ближнее поле); на выходе — сечения диаграммы
направленности в дальней зоне по азимуту и углу места.

Реализация на чистом numpy (без scipy):
- спектр плоских волн — `numpy.fft`;
- интерполяция спектра на нужные углы — БИКУБИЧЕСКАЯ (кубическая свёртка Keys,
  ``_bicubic``), как ``interp2(...,'cubic')`` в MATLAB, но интерполируется
  КОМПЛЕКСНОЕ поле, а модуль берётся в конце (апертура центрируется через
  fftshift -> фаза гладкая -> комплексная интерполяция корректна). ``_bilinear``
  оставлен как запасной;
- ``solve_sections`` считает ТОЛЬКО два сечения через главный лепесток
  (O(n_az + n_el)) вместо полного 2D-поля (O(n_az·n_el)) — это резко снижает
  и время, и расход памяти.

Соглашение по ориентации входа (как в MATLAB): строки ``mag_data`` /
``phase_data`` соответствуют оси X (шаг ``dx``), столбцы — оси Y (шаг ``dy``).
Единицы: ``freq`` — Гц, ``dx``/``dy`` — метры, углы — градусы.
"""

import numpy as np

DEG = np.pi / 180
C_LIGHT = 299_792_458.0  # скорость света, м/с
current_params = dict()


# ----------------------------------------------------------------- numpy-утилиты
def find_peak_indices(y):
    """Индексы локальных максимумов 1D-массива."""
    y = np.asarray(y, dtype=float)
    if y.size < 3:
        return np.empty(0, dtype=int)
    return np.where((y[1:-1] > y[:-2]) & (y[1:-1] >= y[2:]))[0] + 1


def side_lobe_level(section_db):
    """УБЛ относительно главного лепестка (дБ, <0). None если боковых нет."""
    section = np.asarray(section_db, dtype=float)
    peaks = find_peak_indices(section)
    if peaks.size < 2:
        return None
    values = section[peaks]
    main = np.max(values)
    if not np.any(values < main):
        return None
    return float(np.max(values[values < main]) - main)


def _bilinear(x_axis, y_axis, grid, xq, yq):
    """Билинейная интерполяция комплексной ``grid`` (M,N) в точках (xq, yq).

    ``x_axis``/``y_axis`` — возрастающие 1D-оси; ``xq``/``yq`` — массивы любой
    (одинаковой) формы. Точки вне диапазона прижимаются к краю.
    """
    M = x_axis.size
    N = y_axis.size
    ix = np.clip(np.searchsorted(x_axis, xq) - 1, 0, M - 2)
    iy = np.clip(np.searchsorted(y_axis, yq) - 1, 0, N - 2)
    x0 = x_axis[ix]
    x1 = x_axis[ix + 1]
    y0 = y_axis[iy]
    y1 = y_axis[iy + 1]
    tx = np.clip((xq - x0) / (x1 - x0), 0.0, 1.0)
    ty = np.clip((yq - y0) / (y1 - y0), 0.0, 1.0)
    v00 = grid[ix, iy]
    v10 = grid[ix + 1, iy]
    v01 = grid[ix, iy + 1]
    v11 = grid[ix + 1, iy + 1]
    return (v00 * (1 - tx) * (1 - ty) + v10 * tx * (1 - ty)
            + v01 * (1 - tx) * ty + v11 * tx * ty)


def _cubic_weights(t, a=-0.5):
    """Веса ядра кубической свёртки (Keys, a=-0.5) для 4 отсчётов вокруг точки.

    ``t`` — дробная позиция в [0,1) между отсчётами floor и floor+1.
    Возвращает (w[-1], w[0], w[+1], w[+2]); сумма весов = 1.
    """
    t = np.asarray(t, dtype=float)
    # |s| для отсчётов на смещениях -1, 0, +1, +2 относительно floor:
    #   s = 1+t (в [1,2)), t (в [0,1)), 1-t (в [0,1)), 2-t (в [1,2))
    def near(s):   # ветвь |s|<=1: (a+2)|s|^3 - (a+3)|s|^2 + 1
        return (a + 2) * s ** 3 - (a + 3) * s ** 2 + 1

    def far(s):    # ветвь 1<|s|<2: a|s|^3 - 5a|s|^2 + 8a|s| - 4a
        return a * s ** 3 - 5 * a * s ** 2 + 8 * a * s - 4 * a

    return far(1 + t), near(t), near(1 - t), far(2 - t)


def _bicubic(x_axis, y_axis, grid, xq, yq):
    """Бикубическая интерполяция (кубическая свёртка) комплексной ``grid`` (M,N).

    Аналог MATLAB ``interp2(...,'cubic')``: высокий порядок, интерполируется
    КОМПЛЕКСНОЕ поле (модуль берётся вызывающим после). Оси равномерные.
    Точки вне диапазона прижимаются к краю (replicate).
    """
    M = x_axis.size
    N = y_axis.size
    if M < 4 or N < 4:
        return _bilinear(x_axis, y_axis, grid, xq, yq)
    hx = x_axis[1] - x_axis[0]
    hy = y_axis[1] - y_axis[0]
    fx_ = (xq - x_axis[0]) / hx
    fy_ = (yq - y_axis[0]) / hy
    ix = np.floor(fx_).astype(int)
    iy = np.floor(fy_).astype(int)
    tx = fx_ - ix
    ty = fy_ - iy
    wx = _cubic_weights(tx)
    wy = _cubic_weights(ty)

    out = np.zeros(np.broadcast(xq, yq).shape, dtype=complex)
    for ox, wxx in zip((-1, 0, 1, 2), wx):
        xi = np.clip(ix + ox, 0, M - 1)
        for oy, wyy in zip((-1, 0, 1, 2), wy):
            yi = np.clip(iy + oy, 0, N - 1)
            out = out + (wxx * wyy) * grid[xi, yi]
    return out


# ------------------------------------------- кубический B-сплайн (как MATLAB 'spline')
_SPLINE_POLE = np.sqrt(3.0) - 2.0   # ≈ -0.2679


def _bspline_weights(t):
    """Веса кубического B-сплайна для 4 отсчётов (floor-1..floor+2), сумма = 1."""
    t = np.asarray(t, dtype=float)
    t2 = t * t
    t3 = t2 * t
    return ((1 - t) ** 3) / 6.0, (3 * t3 - 6 * t2 + 4) / 6.0, \
           (-3 * t3 + 3 * t2 + 3 * t + 1) / 6.0, t3 / 6.0


def _spline_prefilter1d(c, axis):
    """Префильтр интерполирующего кубического B-сплайна вдоль оси (Thévenaz)."""
    z = _SPLINE_POLE
    lam = (1.0 - z) * (1.0 - 1.0 / z)   # = 6.0
    c = np.moveaxis(c, axis, 0).astype(np.result_type(c.dtype, float), copy=True)
    n = c.shape[0]
    if n < 3:
        return np.moveaxis(c, 0, axis)
    c *= lam
    # причинная инициализация (mirror, усечение по допуску)
    horizon = min(n, int(np.ceil(np.log(1e-9) / np.log(abs(z)))))
    zn = z
    s = c[0].copy()
    for k in range(1, horizon):
        s = s + zn * c[k]
        zn *= z
    c[0] = s
    for k in range(1, n):
        c[k] += z * c[k - 1]
    # антипричинная инициализация
    c[n - 1] = (z / (z * z - 1.0)) * (z * c[n - 2] + c[n - 1])
    for k in range(n - 2, -1, -1):
        c[k] = z * (c[k + 1] - c[k])
    return np.moveaxis(c, 0, axis)


def _spline_coeffs2d(grid):
    """Коэффициенты тензорного кубического B-сплайна (префильтр по обеим осям)."""
    c = _spline_prefilter1d(grid, 0)
    c = _spline_prefilter1d(c, 1)
    return c


def _bspline_eval(x_axis, y_axis, coeffs, xq, yq):
    """Значение кубического B-сплайна по коэффициентам ``coeffs`` в точках (xq, yq).

    Аналог MATLAB ``interp2(...,'spline')`` (граница mirror vs not-a-knot —
    различие только у самых краёв сетки, вдали от рабочей области).
    """
    M, N = coeffs.shape
    if M < 4 or N < 4:
        return _bilinear(x_axis, y_axis, coeffs, xq, yq)
    hx = x_axis[1] - x_axis[0]
    hy = y_axis[1] - y_axis[0]
    fx_ = (xq - x_axis[0]) / hx
    fy_ = (yq - y_axis[0]) / hy
    ix = np.floor(fx_).astype(int)
    iy = np.floor(fy_).astype(int)
    wx = _bspline_weights(fx_ - ix)
    wy = _bspline_weights(fy_ - iy)
    out = np.zeros(np.broadcast(xq, yq).shape, dtype=coeffs.dtype)
    for ox, wxx in zip((-1, 0, 1, 2), wx):
        xi = np.clip(ix + ox, 0, M - 1)
        for oy, wyy in zip((-1, 0, 1, 2), wy):
            yi = np.clip(iy + oy, 0, N - 1)
            out = out + (wxx * wyy) * coeffs[xi, yi]
    return out


def _compute_spectrum(mag_data, phase_data, freq, dx, dy, pad=4):
    """Спектр плоских волн ближнего поля. Возвращает (fx, kx, ky, scale, k0).

    ``pad`` — множитель дополнения нулями над ближайшей степенью двойки
    (число точек БПФ = next_pow2(size) * pad). Больше — плотнее k-сетка и точнее
    интерполяция, но дольше/больше памяти. pad=4 соответствует прежнему поведению.
    """
    mag_data = np.asarray(mag_data, dtype=float)
    phase_data = np.asarray(phase_data, dtype=float)

    ampl = 10 ** (0.05 * mag_data)
    af = ampl * np.exp((phase_data - 180) * DEG * 1j)
    af = np.nan_to_num(af)  # неизмеренные точки -> 0

    k0 = 2 * np.pi * freq / C_LIGHT
    size_m, size_n = af.shape
    MI = int(2 ** np.ceil(np.log2(size_m)) * pad)
    NI = int(2 ** np.ceil(np.log2(size_n)) * pad)
    m = np.arange(-MI / 2, MI / 2, 1)
    n = np.arange(-NI / 2, NI / 2, 1)
    kx = (2 * np.pi * m) / (MI * dx)   # возрастающие (m растёт, dx>0)
    ky = (2 * np.pi * n) / (NI * dy)

    NF_center = np.zeros((MI, NI), dtype=complex)
    start_x = (MI - size_m) // 2
    start_y = (NI - size_n) // 2
    NF_center[start_x:start_x + size_m, start_y:start_y + size_n] = af

    fx = np.fft.ifftshift(np.fft.ifft2(np.fft.fftshift(NF_center)))
    return fx, kx, ky, MI * NI, k0


def _to_db(values, scale):
    with np.errstate(divide='ignore'):
        db = 20 * np.log10(scale * np.abs(values))
    return np.nan_to_num(db, neginf=-300.0, posinf=-300.0)


def solve_sections(mag_data, phase_data, freq, dx, dy, left_az, right_az, d_az,
                   left_el, right_el, d_el, pad=4, interp='cubic', abs_mode='after'):
    """Считает два сечения ДН через главный лепесток (без полного 2D-поля).

    ``pad`` — множитель числа точек БПФ (см. ``_compute_spectrum``).
    ``interp`` — метод интерполяции спектра: 'cubic' (бикубическая свёртка),
    'spline' (кубический B-сплайн, как MATLAB 'spline') или 'linear'.
    ``abs_mode`` — когда брать модуль для АМПЛИТУДЫ:
      - 'after'  — интерполировать КОМПЛЕКСНЫЙ спектр, затем abs (точнее у нулей);
      - 'before' — взять модуль |fx|, затем интерполировать (как MATLAB).
    Фаза всегда считается по комплексной интерполяции (иначе её не получить).

    Returns dict: az_amp/el_amp (дБ), az_phase/el_phase (град), max_val,
    pos_az/pos_el (град), sll_az/sll_el, phase_max.
    """
    fx, kx, ky, scale, k0 = _compute_spectrum(mag_data, phase_data, freq, dx, dy, pad)

    method = str(interp).lower()
    abs_before = str(abs_mode).lower() in ('before', 'до', 'mag', 'magnitude')
    mag = np.abs(fx) if abs_before else None

    # Интерполяторы поля (комплекс) и амплитуды (модуль). Для сплайна коэффициенты
    # префильтруются один раз, для bilinear/bicubic — прямой проход.
    if method.startswith('spl'):
        fx_co = _spline_coeffs2d(fx)
        mag_co = _spline_coeffs2d(mag) if abs_before else None
        fx_eval = lambda xq, yq: _bspline_eval(kx, ky, fx_co, xq, yq)
        mag_eval = (lambda xq, yq: _bspline_eval(kx, ky, mag_co, xq, yq)) if abs_before else None
    else:
        base = _bilinear if method.startswith('lin') else _bicubic
        fx_eval = lambda xq, yq: base(kx, ky, fx, xq, yq)
        mag_eval = (lambda xq, yq: base(kx, ky, mag, xq, yq)) if abs_before else None

    az = np.arange(left_az * DEG, right_az * DEG + d_az * DEG, d_az * DEG)
    el = np.arange(left_el * DEG, right_el * DEG + d_el * DEG, d_el * DEG)
    current_params['az_range'] = az
    current_params['el_range'] = el

    def _kq(az_pts, el_pts):
        return k0 * np.sin(az_pts) * np.cos(el_pts), k0 * np.sin(el_pts)

    def ff_complex(az_pts, el_pts):
        kxq, kyq = _kq(az_pts, el_pts)
        return fx_eval(kxq, kyq)

    def ff_amp(az_pts, el_pts):
        """Амплитуда (модуль) согласно abs_mode."""
        kxq, kyq = _kq(az_pts, el_pts)
        if abs_before:                                   # |fx| -> интерполяция
            return np.abs(mag_eval(kxq, kyq))
        return np.abs(fx_eval(kxq, kyq))                 # интерполяция -> |·|

    # 1) Грубый поиск максимума на разреженной сетке (мало памяти)
    az_c = np.linspace(az[0], az[-1], min(az.size, 161))
    el_c = np.linspace(el[0], el[-1], min(el.size, 161))
    az_cg, el_cg = np.meshgrid(az_c, el_c)
    coarse = ff_amp(az_cg, el_cg)
    r_c, _ = np.unravel_index(int(np.argmax(coarse)), coarse.shape)
    el_fix = el_c[r_c]

    # 2) Уточнение по тонкой сетке итеративно (только вдоль линий)
    col = row = 0
    for _ in range(2):
        col = int(np.argmax(ff_amp(az, np.full_like(az, el_fix))))
        row = int(np.argmax(ff_amp(np.full_like(el, az[col]), el)))
        el_fix = el[row]

    # 3) Финальные согласованные сечения через (az[col], el[row])
    col = int(np.argmax(ff_amp(az, np.full_like(az, el[row]))))
    row = int(np.argmax(ff_amp(np.full_like(el, az[col]), el)))

    az_amp = _to_db(ff_amp(az, np.full_like(az, el[row])), scale)
    el_amp = _to_db(ff_amp(np.full_like(el, az[col]), el), scale)
    # Фаза — всегда по комплексной интерполяции.
    az_cut_c = ff_complex(az, np.full_like(az, el[row]))
    el_cut_c = ff_complex(np.full_like(el, az[col]), el)
    az_phase = np.rad2deg(np.angle(-az_cut_c * 1j))
    el_phase = np.rad2deg(np.angle(-el_cut_c * 1j))

    # Обрезаем нефизичные участки. Спектр определён только в окне k-сетки
    # (|kx| ≤ π/dx, |ky| ≤ π/dy); за ним интерполятор «прижимается» к краю и
    # рисует постоянную «полку». Такие углы помечаем NaN — на графике линия
    # рвётся, оставляя только действительную часть ДН. Граница зависит от
    # частоты (λ=c/f) и шага сканера: sin(θ_max) = λ/(2·d).
    kx_lo, kx_hi = kx[0], kx[-1]
    ky_lo, ky_hi = ky[0], ky[-1]

    def _in_grid(az_pts, el_pts):
        kxq, kyq = _kq(az_pts, el_pts)
        return ((kxq >= kx_lo) & (kxq <= kx_hi)
                & (kyq >= ky_lo) & (kyq <= ky_hi))

    az_valid = _in_grid(az, np.full_like(az, el[row]))
    el_valid = _in_grid(np.full_like(el, az[col]), el)
    az_amp = np.where(az_valid, az_amp, np.nan)
    el_amp = np.where(el_valid, el_amp, np.nan)
    az_phase = np.where(az_valid, az_phase, np.nan)
    el_phase = np.where(el_valid, el_phase, np.nan)

    return {
        'az_amp': az_amp, 'el_amp': el_amp,
        'az_phase': az_phase, 'el_phase': el_phase,
        'max_val': float(az_amp[col]),
        'pos_az': float(np.degrees(az[col])),
        'pos_el': float(np.degrees(el[row])),
        'sll_az': side_lobe_level(az_amp),
        'sll_el': side_lobe_level(el_amp),
        'phase_max': float(-az_phase[col]),
    }


# ----------------------------------------- Полное 2D-поле (опционально, для heatmap)
def solv_far_field(mag_data, phase_data, freq, dx, dy, left_az, right_az, d_az,
                   left_el, right_el, d_el):
    """Полное 2D-поле дальней зоны (n_el, n_az). Дороже по памяти, чем сечения."""
    fx, kx, ky, scale, k0 = _compute_spectrum(mag_data, phase_data, freq, dx, dy)

    az = np.arange(left_az * DEG, right_az * DEG + d_az * DEG, d_az * DEG)
    el = np.arange(left_el * DEG, right_el * DEG + d_el * DEG, d_el * DEG)
    current_params['az_range'] = az
    current_params['el_range'] = el

    az_grid, el_grid = np.meshgrid(az, el)
    kxq = k0 * np.sin(az_grid) * np.cos(el_grid)
    kyq = k0 * np.sin(el_grid)
    val = _bicubic(kx, ky, fx, kxq, kyq)

    f_ampl = _to_db(val, scale)
    f_phase = np.rad2deg(np.angle(-val * 1j))
    return f_ampl, f_phase


def get_sections_far_field(f_ampl, f_phase, is_norm=False):
    """Сечения из полного поля (n_el, n_az). См. solve_sections для быстрого пути."""
    f_ampl = np.asarray(f_ampl)
    f_phase = np.asarray(f_phase)
    f_norm = f_ampl - np.max(f_ampl)
    row, col = np.unravel_index(int(np.argmax(f_ampl)), f_ampl.shape)

    if is_norm:
        az_section_ampl = f_norm[row, :]
        el_section_ampl = f_norm[:, col]
    else:
        az_section_ampl = f_ampl[row, :]
        el_section_ampl = f_ampl[:, col]
    return az_section_ampl, f_phase[row, :], el_section_ampl, f_phase[:, col]
