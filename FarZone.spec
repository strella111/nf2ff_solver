# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec для сборки FarZone в один .exe.

Сборка:  pyinstaller FarZone.spec
Результат:  dist/FarZone.exe
"""
from PyInstaller.utils.hooks import collect_data_files

# Тема (theme.qss + иконки) и шрифты иконок qtawesome
datas = [('far_zone/styles', 'far_zone/styles')]
datas += collect_data_files('qtawesome')

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
    name='FarZone',
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
