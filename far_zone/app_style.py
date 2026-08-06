from pathlib import Path
import sys

from PyQt5 import QtGui

from .design_tokens import qss_substitutions


def reserve_bold_width(button):
    """Заложить в ширину кнопки ЖИРНЫЙ текст выбранного состояния.

    Тема делает выбранную кнопку жирной (``QToolButton:checked``,
    ``font-weight: 600`` — в Qt5 это Bold), а размер кнопки посчитан по
    обычному начертанию. Из-за этого текст влезал, пока кнопка не выбрана, и
    обрезался сразу после выбора. Меряем подсказку размера жирным шрифтом и
    фиксируем её как минимальную ширину — тогда размер от состояния не зависит.

    Вызывать после того, как у кнопки заданы текст и иконка.
    """
    normal = button.font()
    bold = QtGui.QFont(normal)
    bold.setBold(True)
    button.setFont(bold)
    width = button.sizeHint().width()
    button.setFont(normal)
    button.setMinimumWidth(width)


def _theme_path_candidates():
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        yield Path(sys._MEIPASS) / "far_zone" / "styles" / "theme.qss"

    yield Path(__file__).resolve().parent / "styles" / "theme.qss"


def apply_app_theme(app):
    for theme_path in _theme_path_candidates():
        if theme_path.exists():
            style_dir = theme_path.parent.as_posix()
            stylesheet = theme_path.read_text(encoding="utf-8")
            stylesheet = stylesheet.replace("${STYLE_DIR}", style_dir)
            for placeholder, value in qss_substitutions().items():
                stylesheet = stylesheet.replace(placeholder, value)
            app.setStyleSheet(stylesheet)
            return theme_path

    return None
