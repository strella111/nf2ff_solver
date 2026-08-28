# -*- coding: utf-8 -*-
"""Проверка набора иконок (styles/glyphs) — без Qt.

Смысл: имя иконки задаётся строкой, и опечатка раньше всплывала бы только
глазами на запущенном окне. Тест обходит вызовы app_icon/set_button_icon в
исходниках и требует, чтобы для каждого имени нашёлся файл глифа.
"""

import os
import re
import sys
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from far_zone.icon_utils import ICON_ALIASES

ROOT = Path(__file__).resolve().parent.parent
GLYPHS = ROOT / 'far_zone' / 'styles' / 'glyphs'
SOURCES = sorted((ROOT / 'far_zone').glob('*.py')) + [ROOT / 'main.py']

# Все формы, которыми в проекте задаётся иконка:
#   app_icon('name'), _icon_btn('name', ...), _view_button('name', ...)
#   set_button_icon(btn, 'name'), _set_primary(btn, 'name', ...)
_FIRST_ARG = ('app_icon', '_icon_btn', '_view_button', '_nav_button')
_SECOND_ARG = ('set_button_icon', '_set_primary')
_USE_RE = re.compile(
    r"""(?:(?:%s)\(\s*|(?:%s)\(\s*[^,]+,\s*)['"]([a-z0-9\-]+)['"]"""
    % ('|'.join(_FIRST_ARG), '|'.join(_SECOND_ARG)))


def used_icon_names():
    names = set()
    for path in SOURCES:
        names |= set(_USE_RE.findall(path.read_text(encoding='utf-8')))
    return names


class GlyphSetTests(unittest.TestCase):
    def test_every_used_name_has_a_glyph(self):
        """Имя иконки из кода должно существовать файлом — иначе пустая кнопка."""
        missing = sorted(n for n in used_icon_names()
                         if not (GLYPHS / f'{n}.svg').exists())
        self.assertEqual(missing, [], f'нет глифов: {missing}')

    def test_used_names_are_actually_found(self):
        """Страховка от того, что регулярка перестала что-либо находить.

        На момент написания в интерфейсе ровно 20 имён иконок.
        """
        self.assertGreaterEqual(len(used_icon_names()), 20)

    def test_view_buttons_and_tools_are_covered(self):
        """Ключевые инструменты не должны молча уехать в запасной qtawesome."""
        for name in ('cursor-v', 'cursor-h', 'max-global', 'max-local',
                     'normalize', 'autoscale', 'aspect', 'near-field',
                     'far-field', 'app'):
            self.assertTrue((GLYPHS / f'{name}.svg').exists(), name)

    def test_fallback_alias_exists_for_every_glyph(self):
        """У каждого глифа есть шрифтовой запасной вариант (кроме иконки окна)."""
        for svg in GLYPHS.glob('*.svg'):
            if svg.stem == 'app':      # иконка приложения своя, замены нет
                continue
            self.assertIn(svg.stem, ICON_ALIASES, svg.stem)


class GlyphFileTests(unittest.TestCase):
    def test_files_are_valid_svg_with_viewbox(self):
        for svg in sorted(GLYPHS.glob('*.svg')):
            with self.subTest(glyph=svg.stem):
                root = ET.fromstring(svg.read_text(encoding='utf-8'))
                self.assertTrue(root.tag.endswith('svg'))
                box = [float(v) for v in root.get('viewBox').split()]
                self.assertEqual(box[:2], [0.0, 0.0])
                self.assertEqual(box[2], box[3], 'иконка должна быть квадратной')

    def test_interface_glyphs_are_recolorable(self):
        """Без currentColor иконка не перекрасится под состояние кнопки."""
        for svg in sorted(GLYPHS.glob('*.svg')):
            if svg.stem == 'app':      # у иконки приложения цвета свои
                continue
            with self.subTest(glyph=svg.stem):
                self.assertIn('currentColor', svg.read_text(encoding='utf-8'))

    def test_app_icon_has_no_placeholder(self):
        """Иконка приложения должна быть самодостаточной по цвету."""
        text = (GLYPHS / 'app.svg').read_text(encoding='utf-8')
        self.assertNotIn('currentColor', text)


if __name__ == '__main__':
    unittest.main()
