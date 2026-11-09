# Build on Windows 10/11 x64 with: pyinstaller --clean MustacomAqua.spec
from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules

root = Path(SPECPATH)
datas = [(str(root/'assets'), 'assets'), (str(root/'help'), 'help')]
hiddenimports = collect_submodules('openpyxl') + collect_submodules('cryptography')

a = Analysis(
    ['run.py'], pathex=[str(root)], binaries=[], datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[], hooksconfig={}, runtime_hooks=[],
    excludes=['PySide6.QtWebEngineCore','PySide6.QtWebEngineWidgets','PySide6.QtQml','PySide6.QtQuick3D','tkinter'],
    noarchive=False, optimize=1,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [], exclude_binaries=True,
    name='MustacomAquaGestionPro', debug=False, bootloader_ignore_signals=False,
    strip=False, upx=False, console=False, disable_windowed_traceback=False,
    argv_emulation=False, target_arch=None, codesign_identity=None, entitlements_file=None,
    icon=str(root/'assets'/'app.ico'), version=str(root/'installer'/'version_info.txt'),
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, upx_exclude=[], name='MustacomAquaGestionPro')
