# -*- mode: python ; coding: utf-8 -*-

import os

tool_dir = SPECPATH

a = Analysis(
    [os.path.join(tool_dir, "pico_image_gui.py")],
    pathex=[tool_dir],
    binaries=[],
    datas=[],
    hiddenimports=["PIL._tkinter_finder"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["numpy", "PIL.AvifImagePlugin"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="PicoImageTool",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
)
