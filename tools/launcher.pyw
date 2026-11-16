"""TrueStretch launcher for the one-command install (no TrueStretch.exe).

Windows' Smart App Control blocks programs that aren't code-signed, and TrueStretch.exe isn't signed yet. Python
and Qt are signed, so TrueStretch can run from its open-source code instead. install.ps1 sets this up in
%LOCALAPPDATA%\\TrueStretch-src:

    venv\\          Python environment with PySide6 (signed by the Python Software Foundation and The Qt Company)
    app\\           the TrueStretch source of the installed version
    app.new\\       a downloaded update, waiting to replace app\\ at the next start
    launcher.pyw   this file (a copy also sits on the Desktop and in the Start menu)

This file only uses the standard library, so any Python can run it (double-click uses the Python launcher).
"""
import os
import shutil
import subprocess
import sys

ROOT = os.environ.get("TRUESTRETCH_SRC_ROOT") or os.path.join(os.environ.get("LOCALAPPDATA", ""), "TrueStretch-src")


def wait_for_pid(pid, seconds=20):
    import ctypes
    handle = ctypes.windll.kernel32.OpenProcess(0x00100000, False, pid)      # SYNCHRONIZE
    if handle:
        ctypes.windll.kernel32.WaitForSingleObject(handle, int(seconds * 1000))
        ctypes.windll.kernel32.CloseHandle(handle)


def apply_pending_update(root=ROOT):
    """app.new -> app (the old version goes to app.old). Returns True if an update was put in place."""
    app, new, old = (os.path.join(root, n) for n in ("app", "app.new", "app.old"))
    if not os.path.isfile(os.path.join(new, "main.py")):
        return False
    shutil.rmtree(old, ignore_errors=True)
    try:
        if os.path.isdir(app):
            os.replace(app, old)
        os.replace(new, app)
    except OSError:
        if not os.path.isdir(app) and os.path.isdir(old):      # put the working version back
            os.replace(old, app)
        return False
    shutil.rmtree(old, ignore_errors=True)
    return True


def ensure_qt(root=ROOT):
    """After an update: if the new version pins a different PySide6, install it into the venv (rare)."""
    import re
    req = os.path.join(root, "app", "requirements.txt")
    try:
        with open(req, encoding="utf-8") as f:
            m = re.search(r"^PySide6(?:-Essentials)?==([\w.]+)", f.read(), re.M)
    except OSError:
        return
    if not m:
        return
    site = os.path.join(root, "venv", "Lib", "site-packages")
    want = f"pyside6_essentials-{m.group(1)}.dist-info"
    try:
        have = {n.lower() for n in os.listdir(site)}
    except OSError:
        return
    if want in have:
        return
    python = os.path.join(root, "venv", "Scripts", "python.exe")
    subprocess.run([python, "-m", "pip", "install", "--quiet", "--disable-pip-version-check",
                    f"PySide6-Essentials=={m.group(1)}"], creationflags=0x08000000)     # CREATE_NO_WINDOW


def command(root=ROOT, extra=()):
    pythonw = os.path.join(root, "venv", "Scripts", "pythonw.exe")
    return [pythonw, os.path.join(root, "app", "main.py"), *extra]


def main(argv):
    args = list(argv)
    if "--wait-pid" in args:                     # restarted by an update: let the old version quit first
        i = args.index("--wait-pid")
        wait_for_pid(int(args[i + 1]))
        del args[i:i + 2]
    updated = apply_pending_update()
    if updated:
        ensure_qt()
        if "--updated" not in args:
            args.append("--updated")
    cmd = command(extra=args)
    if not os.path.isfile(cmd[0]) or not os.path.isfile(cmd[1]):
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, "TrueStretch isn't fully installed. Run the install command from "
                                         "https://candyqueenjr.github.io/TrueStretch/ again.", "TrueStretch", 0x10)
        return 1
    subprocess.Popen(cmd, cwd=os.path.dirname(cmd[1]), close_fds=True)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
