#!/usr/bin/env python3
"""Build the Windows executable and the release zip.

    python build.py            # builds AgentChatArchiver.exe
    python build.py v11        # builds AgentChatArchiver-v11.exe

The version is just the name suffix: it is passed to the single spec through
ACA_NAME, so adding a release no longer means copying a spec file.  The zip
matches the existing release layout (executable + README.md) and is written
next to it as AgentChatArchiver-Windows-<version>.zip.
"""

import hashlib
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DIST = ROOT / "dist"


def main(argv):
    version = argv[1] if len(argv) > 1 else ""
    name = f"AgentChatArchiver-{version}" if version else "AgentChatArchiver"
    env = {**os.environ, "ACA_NAME": name}

    subprocess.run(
        [sys.executable, "-m", "PyInstaller", "--noconfirm", "AgentChatArchiver.spec"],
        cwd=ROOT, env=env, check=True,
    )

    exe = DIST / f"{name}.exe"
    if not exe.is_file():
        sys.exit(f"build finished but {exe} is missing")

    zip_name = f"AgentChatArchiver-Windows-{version}.zip" if version else "AgentChatArchiver-Windows.zip"
    archive = ROOT / zip_name
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        z.write(exe, exe.name)
        z.write(ROOT / "README.md", "README.md")

    for path in (exe, archive):
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        print(f"{digest}  {path.relative_to(ROOT)}")
    print(f"\nbuilt {exe.name} ({exe.stat().st_size / 1048576:.1f} MB) and {archive.name}")


if __name__ == "__main__":
    main(sys.argv)
