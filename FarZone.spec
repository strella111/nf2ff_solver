# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec для сборки FarZone в один .exe.

Сборка:  pyinstaller FarZone.spec
Результат:  dist/FarZone.exe
"""
import os
import pathlib

from PyInstaller.utils.hooks import collect_data_files

from far_zone import __version__


def _fix_qt_paths_with_cyrillic():
    """Починить пути Qt, если проект лежит в каталоге с кириллицей.

    Qt5 отдаёт свои каталоги через QLibraryInfo, конвертируя их однобайтовой
    кодировкой, и русские буквы превращаются в «?» («...\\ЛО1\\...» ->
    «...\\??1\\...»). PyInstaller 6.x на таком пути падает:
    «Qt plugin directory ... does not exist!». Python при этом видит путь
    правильно, поэтому чиним по реальному расположению пакета PyQt5.

    На обычном (латинском) пути функция ничего не делает.
    """
    try:
        import PyQt5
        from PyInstaller.utils.hooks.qt import pyqt5_library_info
    except ImportError:
        return

    location = pyqt5_library_info.location
    reported = (location or {}).get('PrefixPath')
    real = (pathlib.Path(PyQt5.__file__).parent / 'Qt5').as_posix()
    if not reported or os.path.isdir(reported) or not os.path.isdir(real):
        return  # путь корректен или чинить нечем — не вмешиваемся

    for key, value in list(location.items()):
        if isinstance(value, str) and value.startswith(reported):
            location[key] = real + value[len(reported):]

    # qt_lib_dir кэшируется ВМЕСТЕ с location, до этой правки, и остаётся битым.
    # Именно по нему проверяются зависимости плагинов: с несуществующим путём
    # проверку не проходит ни один, и exe собирается БЕЗ platforms/qwindows.dll
    # (молча — только в debug-логе), после чего не запускается вообще.
    lib_dir = pathlib.Path(pyqt5_library_info.qt_lib_dir).as_posix()
    if lib_dir.startswith(reported):
        pyqt5_library_info.qt_lib_dir = pathlib.Path(real + lib_dir[len(reported):]).resolve()

    # qt_inside_package тоже считался по битому пути и получился False, хотя Qt
    # лежит внутри пакета PyQt5 (колесо с PyPI) — от этого зависит раскладка
    # плагинов в собранном exe.
    package = pathlib.Path(pyqt5_library_info.package_location)
    prefix = pathlib.Path(location['PrefixPath']).resolve()
    pyqt5_library_info.qt_inside_package = (package == prefix or package in prefix.parents)
    print(f'[FarZone.spec] путь Qt исправлен (кириллица в пути): {reported} -> {real}')


_fix_qt_paths_with_cyrillic()

# Тема (theme.qss + глифы интерфейса) и шрифты иконок qtawesome
datas = [('far_zone/styles', 'far_zone/styles')]
datas += collect_data_files('qtawesome')

# Иконка самого exe: готовится build_icon.py из far_zone/styles/glyphs/app.svg.
# Если её нет (собирали не через build.py) — exe получит иконку по умолчанию.
_icon_file = pathlib.Path(SPECPATH) / 'build' / 'FarZone.ico'
exe_icon = str(_icon_file) if _icon_file.exists() else None

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=['pyqtgraph.exporters'],
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name=f'FarZone-{__version__}',
    icon=exe_icon,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
