# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for Setlist Manager.

Builds a single-file Windows .exe that bundles Python, Tkinter, Pillow and
all needed assets. The end user just runs the installer / .exe.

Build manually with:
    pyinstaller setlist.spec --noconfirm
"""

import os

block_cipher = None

# Optional icon and assets
ICON_PATH = os.path.join("assets", "app.ico")
HAS_ICON = os.path.exists(ICON_PATH)

datas = []
if HAS_ICON:
    datas.append((ICON_PATH, "assets"))


a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="SetlistManager",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # GUI app — no console window
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=ICON_PATH if HAS_ICON else None,
)
