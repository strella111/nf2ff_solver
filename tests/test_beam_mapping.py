# -*- coding: utf-8 -*-
"""Проверка порядка перебора лучей (beam_mapping, без Qt)."""

import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from far_zone.beam_mapping import (BEAM_ORDER_AZIMUTH, BEAM_ORDER_ELEVATION,
                                   BEAM_ORDER_NUMBER, BETA_LEVELS, TOTAL_BEAMS,
                                   beam_to_angles, group_beams, order_beams)


def beam_of(alpha_index, beta_index):
    """Номер луча по индексам в сетке — та же формула, что у нумерации."""
    return alpha_index * BETA_LEVELS + beta_index + 1


class GroupBeamsTests(unittest.TestCase):
    # Три азимута × два угла места, номера перемешаны — порядок задаёт функция.
    GRID = [beam_of(a, b) for a in (0, 5, 9) for b in (3, 40)]

    def test_azimuth_groups_all_elevations_at_one_azimuth(self):
        groups = group_beams(self.GRID, BEAM_ORDER_AZIMUTH)
        self.assertEqual(len(groups), 3)                    # три азимута
        for lead, beams in groups:
            alphas = {beam_to_angles(b).alpha for b in beams}
            self.assertEqual(alphas, {lead})                # внутри группы α один
            betas = [beam_to_angles(b).beta for b in beams]
            self.assertEqual(betas, sorted(betas))          # β по возрастанию
        self.assertEqual([lead for lead, _ in groups],
                         sorted(lead for lead, _ in groups))

    def test_elevation_groups_all_azimuths_at_one_elevation(self):
        groups = group_beams(self.GRID, BEAM_ORDER_ELEVATION)
        self.assertEqual(len(groups), 2)                    # два угла места
        for lead, beams in groups:
            betas = {beam_to_angles(b).beta for b in beams}
            self.assertEqual(betas, {lead})
            alphas = [beam_to_angles(b).alpha for b in beams]
            self.assertEqual(alphas, sorted(alphas))

    def test_number_order_is_one_group(self):
        groups = group_beams(self.GRID, BEAM_ORDER_NUMBER)
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0][1], sorted(self.GRID))

    def test_orders_are_permutations_of_the_same_beams(self):
        """Ни один луч не теряется и не дублируется при смене порядка."""
        for order in (BEAM_ORDER_NUMBER, BEAM_ORDER_AZIMUTH, BEAM_ORDER_ELEVATION):
            self.assertEqual(sorted(order_beams(self.GRID, order)), sorted(self.GRID))

    def test_number_order_already_groups_by_azimuth(self):
        """Нумерация идёт растром, поэтому «по номеру» = «по азимуту»."""
        self.assertEqual(order_beams(self.GRID, BEAM_ORDER_NUMBER),
                         order_beams(self.GRID, BEAM_ORDER_AZIMUTH))

    def test_azimuth_and_elevation_orders_differ(self):
        self.assertNotEqual(order_beams(self.GRID, BEAM_ORDER_AZIMUTH),
                            order_beams(self.GRID, BEAM_ORDER_ELEVATION))

    def test_sparse_set_needs_no_full_grid(self):
        """В окне лежат только измеренные лучи — дырки в сетке не мешают."""
        beams = [beam_of(2, 7), beam_of(2, 100), beam_of(30, 7)]
        groups = group_beams(beams, BEAM_ORDER_ELEVATION)
        self.assertEqual([(lead, len(g)) for lead, g in groups],
                         [(beam_to_angles(beam_of(0, 7)).beta, 2),
                          (beam_to_angles(beam_of(0, 100)).beta, 1)])


class UnknownBeamTests(unittest.TestCase):
    """Лучи без углов (одиночный файл, номер вне сетки) не должны теряться."""

    def test_names_go_last_but_survive(self):
        beams = ['Измерение_1', beam_of(4, 4), beam_of(1, 1)]
        for order in (BEAM_ORDER_NUMBER, BEAM_ORDER_AZIMUTH, BEAM_ORDER_ELEVATION):
            ordered = order_beams(beams, order)
            self.assertEqual(sorted(map(str, ordered)), sorted(map(str, beams)))
            self.assertEqual(ordered[-1], 'Измерение_1')

    def test_out_of_range_number_treated_as_unknown(self):
        ordered = order_beams([TOTAL_BEAMS + 1, 5], BEAM_ORDER_AZIMUTH)
        self.assertEqual(ordered, [5, TOTAL_BEAMS + 1])

    def test_empty_input(self):
        self.assertEqual(group_beams([], BEAM_ORDER_AZIMUTH), [])
        self.assertEqual(order_beams([], BEAM_ORDER_AZIMUTH), [])


if __name__ == '__main__':
    unittest.main()
