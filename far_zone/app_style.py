from pathlib import Path
import sys

from .design_tokens import qss_substitutions


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
