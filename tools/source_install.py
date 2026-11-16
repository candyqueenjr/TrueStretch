"""Last step of install.ps1 (the one-command install without TrueStretch.exe), run with the new venv's Python.

  python tools/source_install.py <tag> [--no-shortcuts]

Copies the launcher next to the install (%LOCALAPPDATA%\\TrueStretch-src\\launcher.pyw), puts a "TrueStretch"
launcher on the Desktop and in the Start menu, and writes install.json - the marker that tells the in-app updater it
may update this install by downloading the next version's source.
"""
import ctypes
import json
import shutil
import sys
import uuid
from ctypes import wintypes
from datetime import datetime, timezone
from pathlib import Path

APP = Path(__file__).resolve().parents[1]          # ...\TrueStretch-src\app (or app.new on a reinstall)
ROOT = APP.parent
FOLDERID_DESKTOP = "{B4BFCC3A-DB2C-424C-B029-7FE99A87C641}"
FOLDERID_PROGRAMS = "{A77F5D77-2E2B-44C3-A6A2-ABA601054A51}"


class GUID(ctypes.Structure):
    _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD), ("Data3", wintypes.WORD),
                ("Data4", ctypes.c_ubyte * 8)]


def known_folder(folder_id):
    """The real Desktop / Start menu folder (also when OneDrive moved the Desktop)."""
    u = uuid.UUID(folder_id)
    g = GUID(u.fields[0], u.fields[1], u.fields[2], (ctypes.c_ubyte * 8)(*u.bytes[8:]))
    out = ctypes.c_wchar_p()
    if ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(g), 0, None, ctypes.byref(out)) != 0:
        return None
    try:
        return Path(out.value)
    finally:
        ctypes.windll.ole32.CoTaskMemFree(out)


def main(argv):
    if not argv:
        print("usage: source_install.py <tag> [--no-shortcuts]")
        return 2
    tag = argv[0]
    launcher = APP / "tools" / "launcher.pyw"
    shutil.copyfile(launcher, ROOT / "launcher.pyw")
    made = []
    if "--no-shortcuts" not in argv:
        for fid, sub in ((FOLDERID_DESKTOP, ""), (FOLDERID_PROGRAMS, "")):
            folder = known_folder(fid)
            if folder and folder.is_dir():
                target = folder / sub / "TrueStretch.pyw"
                shutil.copyfile(launcher, target)
                made.append(str(target))
    (ROOT / "install.json").write_text(json.dumps({
        "kind": "source", "tag": tag, "installed": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "shortcuts": made}, indent=2), encoding="utf-8")
    for m in made:
        print("shortcut:", m)
    print("ok", tag)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
