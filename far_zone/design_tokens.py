# -*- coding: utf-8 -*-
"""Единый источник дизайн-токенов приложения.

Все «брендовые» и семантические цвета, типографика и индикаторы режимов
должны браться отсюда, а не задаваться инлайн в Python или хардкодом в QSS.

Поток использования:
- ``qss_substitutions()`` подставляет токены в ``styles/theme.qss``
  (см. ``app_style.apply_app_theme``);
- ``status_colors`` и ``icon_utils`` читают цвета статусов/иконок отсюда;
- ``main_window`` берёт цвета индикатора режима из ``MODE_COLORS``.

Тема одна (светлая). Нейтральные оттенки интерфейса (границы, поверхности)
остаются литералами внутри theme.qss — они не дублируются в Python и не
определяют бренд. Здесь централизованы только реально разделяемые значения.
"""

# --- Акцент (бренд) ---------------------------------------------------------
# Обновлённая палитра — индиго (свежее прежнего синего #2563eb).
ACCENT = '#4f46e5'          # indigo-600
ACCENT_HOVER = '#4338ca'    # indigo-700
ACCENT_PRESSED = '#3730a3'  # indigo-800
ACCENT_FOCUS = '#818cf8'    # indigo-400

# Производные «мягкие» оттенки акцента — для hover/нажатий/выделения.
# Централизованы здесь, чтобы перекрасить весь UI в один тон из одного места.
ACCENT_SOFT = '#eef2ff'         # indigo-50  — фон hover
ACCENT_SOFT_BORDER = '#a5b4fc'  # indigo-300 — граница hover
ACCENT_SOFT_PRESSED = '#e0e7ff' # indigo-100 — фон нажатия
ACCENT_SELECTION = '#e0e7ff'    # выделение строк таблиц/списков
ACCENT_TEXT = '#3730a3'         # текст выбранных элементов (тёмное индиго)
SELECTION_BG = '#dbe2ff'        # selection-background-color текста

# --- Статусы ----------------------------------------------------------------
# Мягкие фоны (плашки/кнопки подключения) и насыщенные цвета иконок/текста.
STATUS_SURFACE = {
    'ok': '#c8ffc8',
    'warning': '#fff5c8',
    'fail': '#ffc8c8',
    'neutral': '#dcdcdc',
}

STATUS_ICON = {
    'ok': '#047857',
    'warning': '#a16207',
    'fail': '#b91c1c',
    'neutral': '#64748b',
}

# --- Иконки -----------------------------------------------------------------
ICON_DEFAULT = '#334155'
ICON_DISABLED = '#94a3b8'

# --- Типографика ------------------------------------------------------------
# Базовый кегль интерфейса. 10pt вместо прежних 9pt для читаемости на стенде.
FONT_SIZE_BASE = '10pt'

# --- Цвета индикаторов режимов ----------------------------------------------
# Гармонизированы с акцентом #2563eb (палитра уровня 600), вместо разнородных
# Material-цветов. Сохранена исходная логика группировки режимов.
MODE_COLORS = {
    'phase_ma': ACCENT,             # Фазировка МА — акцент (индиго)
    'beam_calb_afar': ACCENT,       # Лучевые КЛБ — акцент (индиго)
    'check_ma': '#059669',          # Проверка МА — зелёный
    'check_stend_ma': '#d97706',    # Стенд МА — янтарный
    'phase_afar': '#7c3aed',        # Фазировка АФАР — фиолетовый
    'beam_pattern': '#e11d48',      # Лучевые диаграммы — розовый
    'check_stend_afar': '#d97706',  # Стенд АФАР — янтарный
}

MODE_INDICATOR_TEXT = '#ffffff'


def qss_substitutions() -> dict:
    """Плейсхолдеры ``${...}`` → значения для подстановки в theme.qss."""
    subs = {
        '${ACCENT}': ACCENT,
        '${ACCENT_HOVER}': ACCENT_HOVER,
        '${ACCENT_PRESSED}': ACCENT_PRESSED,
        '${ACCENT_FOCUS}': ACCENT_FOCUS,
        '${ACCENT_SOFT}': ACCENT_SOFT,
        '${ACCENT_SOFT_BORDER}': ACCENT_SOFT_BORDER,
        '${ACCENT_SOFT_PRESSED}': ACCENT_SOFT_PRESSED,
        '${ACCENT_SELECTION}': ACCENT_SELECTION,
        '${ACCENT_TEXT}': ACCENT_TEXT,
        '${SELECTION_BG}': SELECTION_BG,
        '${FONT_SIZE_BASE}': FONT_SIZE_BASE,
        '${STATUS_OK_SURFACE}': STATUS_SURFACE['ok'],
        '${STATUS_WARNING_SURFACE}': STATUS_SURFACE['warning'],
        '${STATUS_FAIL_SURFACE}': STATUS_SURFACE['fail'],
        '${STATUS_OK_ICON}': STATUS_ICON['ok'],
        '${STATUS_WARNING_ICON}': STATUS_ICON['warning'],
        '${STATUS_FAIL_ICON}': STATUS_ICON['fail'],
        '${MODE_INDICATOR_TEXT}': MODE_INDICATOR_TEXT,
    }
    for mode_key, color in MODE_COLORS.items():
        subs[f'${{MODE_{mode_key.upper()}}}'] = color
    return subs
