# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['Morphix.py'],
    pathex=[],
    binaries=[('ffmpeg_binaries\\bin\\ffmpeg.exe', 'ffmpeg'), ('ffmpeg_binaries\\bin\\ffprobe.exe', 'ffmpeg')],
    datas=[],
    hiddenimports=['ffmpeg'],
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
    name='Morphix_CLI',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
