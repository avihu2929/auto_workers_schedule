# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec: one-dir, windowed GUI, config.yaml bundled as data.
# Build:  pyinstaller schedule.spec

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[('config.yaml', '.')],
    hiddenimports=[],
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='schedule',
    debug=False,
    strip=False,
    upx=False,
    console=False,
    icon=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name='schedule',
)
