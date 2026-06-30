# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['morphix_ui\\main_window.py'],
    pathex=[],
    binaries=[('ffmpeg_binaries\\bin\\ffmpeg.exe', 'ffmpeg'), ('ffmpeg_binaries\\bin\\ffprobe.exe', 'ffmpeg')],
    datas=[('morphix_core', 'morphix_core')],
    hiddenimports=['morphix_core.core', 'morphix_core.cli', 'ffmpeg'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='Morphix_UI',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
