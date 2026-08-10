# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[('utils', 'utils'), ('widgets', 'widgets'), ('theme.py', '.'), ('queue_manager.py', '.'), ('downloader.py', '.'), ('qt_app.py', '.')],
    hiddenimports=['yt_dlp', 'PySide6.QtCore', 'PySide6.QtWidgets', 'PySide6.QtGui'],
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
    [],
    exclude_binaries=True,
    name='YoutubeDownloader',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='YoutubeDownloader',
)
app = BUNDLE(
    coll,
    name='YoutubeDownloader.app',
    icon=None,
    bundle_identifier=None,
)
