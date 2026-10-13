# -*- mode: python ; coding: utf-8 -*-
# One spec for every release. The executable name — and therefore the version —
# comes from ACA_NAME, so there is no per-version copy to keep in sync.
# Use build.py, which sets it and also packages the release zip.

import os

name = os.environ.get("ACA_NAME") or "AgentChatArchiver"

a = Analysis(
    ['agent_chat_archiver.py'],
    pathex=[], binaries=[],
    # The window icon is read at run time through resource_path(), which looks
    # in sys._MEIPASS when frozen, so it has to travel with the executable.
    datas=[('assets/icon.ico', 'assets'), ('assets/icon.png', 'assets')],
    hiddenimports=[], hookspath=[],
    hooksconfig={}, runtime_hooks=[], excludes=[], noarchive=False, optimize=0,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, a.binaries, a.datas, [], name=name,
    icon='assets/icon.ico',
    debug=False, bootloader_ignore_signals=False, strip=False, upx=True,
    upx_exclude=[], runtime_tmpdir=None, console=False,
    disable_windowed_traceback=False, argv_emulation=False, target_arch=None,
    codesign_identity=None, entitlements_file=None,
)
