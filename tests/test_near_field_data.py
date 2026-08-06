# -*- coding: utf-8 -*-
"""Проверка подготовки ближнего поля к отрисовке (near_field_data, без Qt)."""

import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from far_zone.near_field_data import (PHASE_LEVELS, auto_levels, axis_layout,
                                      axis_points, expand_span, field_image,
                                      field_stats, measured_bounds, prepare_maps)


class FieldImageTests(unittest.TestCase):
    def test_transposes_measurement_to_image(self):
        """В файле [y][x], в картинке — [x][y]: путать оси нельзя."""
        values = [[1.0, 2.0, 3.0],      # y=0
                  [4.0, 5.0, 6.0]]      # y=1
        img = field_image(values)
        self.assertEqual(img.shape, (3, 2))     # (x, y)
        self.assertEqual(img[0, 0], 1.0)        # x=0, y=0
        self.assertEqual(img[2, 0], 3.0)        # x=2, y=0
        self.assertEqual(img[0, 1], 4.0)        # x=0, y=1

    def test_flips_axes_on_request(self):
        values = [[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]]
        flipped_x = field_image(values, flip_x=True)
        self.assertEqual(flipped_x[0, 0], 3.0)
        flipped_y = field_image(values, flip_y=True)
        self.assertEqual(flipped_y[0, 0], 4.0)

    def test_rejects_non_2d(self):
        with self.assertRaises(ValueError):
            field_image([1.0, 2.0, 3.0])


class AxisLayoutTests(unittest.TestCase):
    def test_uses_scan_coordinates_in_cm(self):
        """Координаты из scan_params.json: края расширены на полшага."""
        start, size, reverse = axis_layout([10.0, 12.0, 14.0, 16.0], 4, step=99.0)
        self.assertAlmostEqual(start, 9.0)       # 10 - 2/2
        self.assertAlmostEqual(size, 8.0)        # (16-10) + 2
        self.assertFalse(reverse)

    def test_descending_coordinates_request_flip(self):
        start, size, reverse = axis_layout([16.0, 14.0, 12.0, 10.0], 4, step=99.0)
        self.assertTrue(reverse, 'скан справа налево — картинку надо развернуть')
        self.assertAlmostEqual(start, 9.0)
        self.assertAlmostEqual(size, 8.0)

    def test_point_numbers_are_not_centimetres(self):
        """0,1,2,… — это номера точек (нет scan_params.json), ось идёт по шагу."""
        start, size, reverse = axis_layout([0, 1, 2, 3], 4, step=2.5)
        self.assertAlmostEqual(start, -1.25)
        self.assertAlmostEqual(size, 10.0)       # 4 точки × 2.5 см
        self.assertFalse(reverse)

    def test_falls_back_to_step_without_coordinates(self):
        start, size, _ = axis_layout(None, 3, step=4.0)
        self.assertAlmostEqual(start, -2.0)
        self.assertAlmostEqual(size, 12.0)

    def test_length_mismatch_falls_back_to_step(self):
        start, size, _ = axis_layout([0.0, 5.0], 3, step=1.0)
        self.assertAlmostEqual(start, -0.5)
        self.assertAlmostEqual(size, 3.0)

    def test_single_point_and_zero_step_survive(self):
        self.assertEqual(axis_layout([], 0, step=1.0), (0.0, 0.0, False))
        start, size, _ = axis_layout([7.0], 1, step=0.0)
        self.assertAlmostEqual(size, 1.0, msg='нулевой шаг не должен схлопнуть ось')

    def test_axis_points_are_cell_centres(self):
        pts = axis_points([10.0, 12.0, 14.0], 3, step=99.0)
        np.testing.assert_allclose(pts, [10.0, 12.0, 14.0])
        pts = axis_points(None, 3, step=2.0)
        np.testing.assert_allclose(pts, [0.0, 2.0, 4.0])


class PrepareMapsTests(unittest.TestCase):
    def test_geometry_matches_data(self):
        amp = [[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]]      # 2 по Y, 3 по X
        phase = [[0.0, 10.0, 20.0], [30.0, 40.0, 50.0]]
        maps = prepare_maps(amp, phase, [0.0, 2.0, 4.0], [0.0, 3.0], dx=2.0, dy=3.0)
        self.assertEqual(maps['amp'].shape, (3, 2))
        self.assertEqual(maps['phase'].shape, (3, 2))
        x0, y0, w, h = maps['rect']
        self.assertAlmostEqual(x0, -1.0)
        self.assertAlmostEqual(w, 6.0)
        self.assertAlmostEqual(y0, -1.5)
        self.assertAlmostEqual(h, 6.0)

    def test_phase_of_wrong_shape_becomes_nan(self):
        maps = prepare_maps([[1.0, 2.0]], [[1.0, 2.0, 3.0]], None, None, 1.0, 1.0)
        self.assertTrue(np.all(np.isnan(maps['phase'])))

    def test_flip_applies_to_both_maps(self):
        amp = [[1.0, 2.0]]
        phase = [[10.0, 20.0]]
        maps = prepare_maps(amp, phase, [5.0, 0.0], [0.0], dx=5.0, dy=1.0)
        self.assertEqual(maps['amp'][0, 0], 2.0)
        self.assertEqual(maps['phase'][0, 0], 20.0)


class LevelsTests(unittest.TestCase):
    def test_levels_are_plain_min_max_of_measured(self):
        """Как в скане лучей: без «пола» и нормировки — что измерено, то и в шкале."""
        img = np.array([[0.0, -5.0], [-8.0, np.nan]])
        lo, hi = auto_levels(img)
        self.assertAlmostEqual(lo, -8.0)
        self.assertAlmostEqual(hi, 0.0)

    def test_single_deep_dip_is_not_clipped(self):
        img = np.array([[0.0, -5.0], [-200.0, -3.0]])
        lo, hi = auto_levels(img)
        self.assertAlmostEqual(lo, -200.0)
        self.assertAlmostEqual(hi, 0.0)

    def test_flat_and_empty_fields_do_not_break(self):
        lo, hi = auto_levels(np.full((2, 2), -7.0))
        self.assertLess(lo, hi, 'у ровного поля шкала не должна схлопнуться')
        lo, hi = auto_levels(np.full((2, 2), np.nan))
        self.assertLess(lo, hi)

    def test_phase_levels_are_full_circle(self):
        self.assertEqual(PHASE_LEVELS, (-180.0, 180.0))


class MeasuredBoundsTests(unittest.TestCase):
    """Подгон масштаба по двойному клику — как на карте скана."""

    X = np.array([0.0, 2.0, 4.0, 6.0, 8.0, 10.0])   # шаг 2 см
    Y = np.array([0.0, 3.0, 6.0, 9.0])              # шаг 3 см

    def test_fits_to_measured_part_only(self):
        amp = np.full((6, 4), np.nan)       # (x, y)
        amp[1:5, 0:3] = -5.0                # измерены X=2..8, Y=0..6
        x0, x1, y0, y1 = measured_bounds(amp, self.X, self.Y)
        self.assertAlmostEqual(x0, 1.0)     # 2 - шаг/2
        self.assertAlmostEqual(x1, 9.0)     # 8 + шаг/2
        self.assertAlmostEqual(y0, -1.5)
        self.assertAlmostEqual(y1, 7.5)

    def test_single_column_is_widened(self):
        """Измерен один столбец — вид не должен схлопнуться в полоску."""
        amp = np.full((6, 4), np.nan)
        amp[2, :] = -5.0
        x0, x1, _y0, _y1 = measured_bounds(amp, self.X, self.Y)
        self.assertAlmostEqual(x1 - x0, 6.0, msg='минимум три клетки по X')
        self.assertAlmostEqual((x0 + x1) / 2, 4.0, msg='центр на измеренном столбце')

    def test_empty_field_shows_whole_aperture(self):
        amp = np.full((6, 4), np.nan)
        x0, x1, y0, y1 = measured_bounds(amp, self.X, self.Y)
        self.assertAlmostEqual(x0, -1.0)
        self.assertAlmostEqual(x1, 11.0)
        self.assertAlmostEqual(y0, -1.5)
        self.assertAlmostEqual(y1, 10.5)

    def test_no_axes_means_nothing_to_show(self):
        self.assertIsNone(measured_bounds(np.empty((0, 0)), np.empty(0), np.empty(0)))

    def test_expand_span_adds_padding_and_minimum(self):
        self.assertEqual(expand_span(0.0, 10.0, 3.0, 1.0), (-1.0, 11.0))
        lo, hi = expand_span(5.0, 5.0, 6.0, 0.5)
        self.assertAlmostEqual(hi - lo, 6.0)
        self.assertAlmostEqual((lo + hi) / 2, 5.0)


class StatsTests(unittest.TestCase):
    def test_reports_maximum_with_coordinates(self):
        amp = np.array([[-10.0, -6.0], [-3.0, -20.0]])   # (x, y)
        phase = np.array([[0.0, 45.0], [-90.0, 180.0]])
        x_pts = np.array([0.0, 5.0])
        y_pts = np.array([0.0, 4.0])
        stats = field_stats(amp, phase, x_pts, y_pts)
        self.assertAlmostEqual(stats['max_db'], -3.0)
        self.assertAlmostEqual(stats['max_x'], 5.0)
        self.assertAlmostEqual(stats['max_y'], 0.0)
        self.assertAlmostEqual(stats['dynamic_db'], 17.0)
        self.assertAlmostEqual(stats['phase_span'], 270.0)
        self.assertEqual((stats['measured'], stats['total']), (4, 4))
        self.assertAlmostEqual(stats['size_x'], 5.0)
        self.assertAlmostEqual(stats['size_y'], 4.0)
        self.assertEqual((stats['n_x'], stats['n_y']), (2, 2))

    def test_counts_unmeasured_points(self):
        amp = np.array([[np.nan, -6.0], [-3.0, np.nan]])
        phase = np.full((2, 2), np.nan)
        stats = field_stats(amp, phase, np.array([0.0, 1.0]), np.array([0.0, 1.0]))
        self.assertEqual(stats['measured'], 2)
        self.assertEqual(stats['total'], 4)
        self.assertAlmostEqual(stats['max_db'], -3.0)
        self.assertIsNone(stats['phase_span'], 'фазы нет — размах не выдумываем')

    def test_empty_field_returns_none(self):
        amp = np.full((2, 2), np.nan)
        stats = field_stats(amp, amp, np.array([0.0, 1.0]), np.array([0.0, 1.0]))
        self.assertIsNone(stats['max_db'])
        self.assertIsNone(stats['dynamic_db'])
        self.assertEqual(stats['measured'], 0)


if __name__ == '__main__':
    unittest.main()
