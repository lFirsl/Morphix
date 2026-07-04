# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['morphix_ui\\main_window.py'],
    pathex=[],
    binaries=[('ffmpeg_binaries\\bin\\ffmpeg.exe', 'ffmpeg'), ('ffmpeg_binaries\\bin\\ffprobe.exe', 'ffmpeg')],
    datas=[('morphix_core', 'morphix_core'), ('morphix_ui', 'morphix_ui')],
    hiddenimports=['morphix_core.core', 'morphix_core.cli', 'morphix_core.config', 'morphix_core.gpu_detection', 'morphix_ui.widgets', 'morphix_ui.dialogs', 'morphix_ui.compression_worker', 'morphix_ui.time_utils', 'morphix_ui.validation_chain', 'morphix_ui.tabs', 'morphix_ui.tabs.base', 'morphix_ui.tabs.target_tab', 'morphix_ui.tabs.trim_tab', 'morphix_ui.tabs.advanced_tab', 'ffmpeg'],
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
