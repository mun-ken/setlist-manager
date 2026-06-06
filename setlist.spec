# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for Setlist Manager.

Bygger en --ONEDIR distribution (ikke onefile!) der lægger alle DLL'er
permanent i installations-mappen. Det giver:

  * Ingen 'Failed to load Python DLL'-fejl. --onefile udpakker python312.dll
    til %TEMP%/_MEIxxxxx ved hver start, og Windows Defender / antivirus
    holder ofte en lock på filen mens de scanner den → LoadLibrary fejler.
    Med --onedir scannes DLL'erne ÉN gang ved install og ligger så stille
    bagefter.
  * Hurtigere opstart (ingen extraction)
  * Færre antivirus-falske-alarmer (UPX er også slået fra — UPX-pakkede
    .exe'er er en MASSIV trigger for AV-heuristik)

End-user mærker intet — Inno Setup installer alle filerne pænt i
Program Files, og brugeren dobbeltklikker bare "Setlist Manager"
genvejen som peger på SetlistManager.exe i den mappe.

Build manually with:
    pyinstaller setlist.spec --noconfirm
"""

import os
from PyInstaller.utils.hooks import collect_all

block_cipher = None

# Optional icon and assets
ICON_PATH = os.path.join("assets", "app.ico")
HAS_ICON = os.path.exists(ICON_PATH)

datas = []
binaries = []
hidden_imports = ["certifi"]

if HAS_ICON:
    datas.append((ICON_PATH, "assets"))

# Inkluder certifi's CA-bundle så auto-update kan validere GitHub's SSL-cert
# (PyInstaller bundles på Windows mangler ellers ofte CA-certifikater).
try:
    import certifi
    datas.append((certifi.where(), "certifi"))
except ImportError:
    pass

# === NDI binding ===
# ndi-python's wheel inkluderer Processing.NDI.Lib.x64.dll på Windows.
# Vi bruger collect_all() til at sørge for at PyInstaller pakker BÅDE
# .pyd extension-modulet OG den medfølgende DLL ind i dist-mappen.
# Resultat: brugeren skal IKKE selv installere NDI Tools separat —
# alt fungerer ud af kassen så snart de har installeret Setlist Manager.
try:
    import NDIlib  # noqa: F401
    ndi_datas, ndi_binaries, ndi_hidden = collect_all("NDIlib")
    datas.extend(ndi_datas)
    binaries.extend(ndi_binaries)
    hidden_imports.extend(ndi_hidden)
    hidden_imports.append("NDIlib")
    print(f"[setlist.spec] NDIlib bundles: {len(ndi_binaries)} binaries, "
          f"{len(ndi_datas)} datas")
except (ImportError, OSError) as _e:
    # NDI Runtime ikke installeret på build-maskinen — fortsæt uden NDI.
    # End-userens app vil så vise venlig fejlbesked hvis de prøver NDI-features.
    print(f"[setlist.spec] NDIlib NOT bundled (import failed: {_e})")

# numpy er en hård dependency for NDI (vi bruger den til BGRA-conversion).
# Den er normalt allerede inkluderet, men vi tilføjer den eksplicit for at
# være sikre.
try:
    import numpy  # noqa: F401
    hidden_imports.append("numpy")
except ImportError:
    pass


a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hidden_imports,
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

# --- ONEDIR mode ---
# EXE indeholder KUN bootloader + scripts (ikke binaries/zipfiles/datas).
# Disse pakkes i COLLECT() til dist/SetlistManager/ mappen.
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,   # ← VIGTIGT for onedir mode
    name="SetlistManager",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,               # ← UPX disabled (antivirus trigger)
    console=False,           # GUI app — no console window
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=ICON_PATH if HAS_ICON else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,               # ← UPX disabled på alle DLL'er
    upx_exclude=[],
    name="SetlistManager",   # → dist/SetlistManager/
)
