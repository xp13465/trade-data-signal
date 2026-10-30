# sensenova-proxy.spec - PyInstaller 打包配置(打成单文件 exe)
# 用法:在 Windows 机器上跑 build-exe.bat(mac/linux 不能交叉编译)
# key 不进 exe:运行时读旁边 keys.txt
# -*- mode: python ; coding: utf-8 -*-

block_cipher = None

a = Analysis(
    ['sensenova-rotate-proxy.py'],
    pathex=[],
    binaries=[],
    datas=[],
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
    name='sensenova-proxy',
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
