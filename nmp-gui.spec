# -*- mode: python ; coding: utf-8 -*-

import sys


hidden_imports = ['tomli'] if sys.version_info < (3, 11) else []

a = Analysis(
    ['nmp_client_gui.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

if sys.platform == 'darwin':
    exe = EXE(
        pyz, a.scripts, [],
        name='NMP',
        exclude_binaries=True,
        console=False,
    )
    bundle = COLLECT(
        exe, a.binaries, a.datas,
        name='NMP',
        strip=False,
        upx=False,
    )
    app = BUNDLE(
        bundle,
        name='NMP.app',
        bundle_identifier='com.rainmark.nmp',
        version='0.1.0',
        info_plist={
            'NSPrincipalClass': 'NSApplication',
            'NSHighResolutionCapable': True,
        },
    )
else:
    exe = EXE(
        pyz, a.scripts, a.binaries, a.datas, [],
        name='NMP',
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=False,
        console=False,
    )
