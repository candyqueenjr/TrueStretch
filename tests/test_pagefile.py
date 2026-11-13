r"""Optimize Max "Page file": Windows keeps the list of page files in HKLM\...\Memory Management -> PagingFiles
(REG_MULTI_SZ). The check only offers a change when the page file is switched off, and the change and its undo are
administrator command lines. Tested here without administrator rights: the same command lines are run, through
cmd.exe exactly like the app runs them, against a scratch key under HKCU that is removed at the end, and the raw
registry bytes are compared (apply -> Windows' default; undo -> byte-identical to before)."""
import ctypes
import json
import os
import subprocess
import sys
import tempfile
import winreg
from ctypes import wintypes
from types import SimpleNamespace

os.environ["APPDATA"] = tempfile.mkdtemp(prefix="ts-page-")
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))

from truestretch import optimizer as opt                 # noqa: E402
from truestretch import optimizer_more as more           # noqa: E402
from truestretch import pagefile as pf                   # noqa: E402

fails = []


def check(c, t):
    print(("PASS " if c else "FAIL ") + t)
    c or fails.append(t)


# ---- reading the list (pure) --------------------------------------------------------------------------------------
check(pf.status([pf.AUTO]) == pf.MANAGED, "?:\\pagefile.sys -> managed by Windows")
check(pf.status([]) == pf.OFF, "empty list -> off")
check(pf.status(None) is None, "missing value -> unknown (no row)")
check(pf.status([r"C:\pagefile.sys 0 0"]) == pf.MANAGED, "C:\\pagefile.sys 0 0 -> managed size")
check(pf.status([r"C:\pagefile.sys"]) == pf.MANAGED, "no sizes -> managed size")
check(pf.status([r"C:\pagefile.sys 4096 8192"]) == pf.CUSTOM, "fixed sizes -> custom")
check(pf.status([r"C:\pagefile.sys 4096 8192", r"D:\pagefile.sys 0 0"]) == pf.MANAGED, "one managed drive -> managed")
check(pf.status([""]) is None and pf.status([" "]) is None, "blank entries -> unknown, never 'off'")
check(pf.status(['C:\\page"file.sys & calc']) is None, "entry with shell characters -> unknown")
check(pf.status(["C:\\pagefile.sys 10%TEMP%"]) is None, "entry with % -> unknown")
check(pf.parse([r"C:\pagefile.sys 4096 8192"]) == [("C:\\pagefile.sys", 4096, 8192)], "parse sizes")
check(pf.parse([r"D:\my files\pagefile.sys 16 32"]) == [("D:\\my files\\pagefile.sys", 16, 32)], "parse path with a space")
check(pf.custom_max_mb([r"C:\pagefile.sys 4096 8192", r"D:\pagefile.sys 1024 2048"]) == 10240, "custom maximum adds up")
check(pf.restorable(None) and pf.restorable([]) and pf.restorable([pf.AUTO]) and not pf.restorable([""]),
      "restorable: missing, empty and normal lists only")
try:
    pf.undo_cmds(['x" & calc'])
    check(False, "undo refuses a list it can't write safely")
except ValueError:
    check(True, "undo refuses a list it can't write safely")
live = pf.live_mb()
check(live is None or live >= 0, f"live page file size readable ({live} MB)")

# ---- the row ------------------------------------------------------------------------------------------------------
pc16, pc32 = SimpleNamespace(ram_gb=15.8), SimpleNamespace(ram_gb=31.9)
i = more.page_file_item(pc16, entries=[], live_mb=0)
check(i.state == opt.IMPROVE and i.current == "Off" and i.can_apply and i.admin and i.restart and i.level == 2,
      "off -> can be fixed, administrator + restart, medium on 16 GB")
check(i._admin_cmds == pf.apply_cmds() and i._snapshot() == [], "off -> apply command + snapshot of the empty list")
check(more.page_file_item(pc32, entries=[], live_mb=0).level == 1, "off on 32 GB -> low")
check(more.page_file_item(pc16, entries=[], live_mb=20000).current == "Off from the next restart",
      "switched off but still in use until the restart")
i = more.page_file_item(pc16, entries=[pf.AUTO], live_mb=20000)
check(i.state == opt.DONE and i.current == "Managed by Windows" and not i.can_apply, "managed -> done, nothing to apply")
check(i._admin_undo([]) == pf.undo_cmds([]), "a done row can still undo an earlier change")
i = more.page_file_item(pc16, entries=[pf.AUTO], live_mb=0)
check(i.state == opt.DONE and "next restart" in i.current, "switched on, not restarted yet -> says so")
i = more.page_file_item(pc16, entries=[r"C:\pagefile.sys 4096 8192"], live_mb=8192)
check(i.state == opt.DONE and i.current == "Custom size (up to 8 GB)" and not i.can_apply, "custom size -> left alone")
check(more.page_file_item(pc16, entries=None, live_mb=0) is None, "unknown -> no row")
check(more.page_file_item(pc16, entries=[""], live_mb=0) is None, "blank entry -> no row")
real = more.page_file_item(pc16)
check(real is None or real.id == "page_file", f"real PC: {real.current if real else 'no row'}")
check(all(pf.KEY in c and "HKLM" in c for c in pf.apply_cmds() + pf.undo_cmds([]) + pf.undo_cmds(None)),
      "the real command lines only touch the page-file value under HKLM")

# ---- the command lines, for real, on a scratch key ------------------------------------------------------------
SCRATCH = r"Software\TrueStretch-test-pagefile\Memory Management"
adv = ctypes.WinDLL("advapi32", use_last_error=True)
adv.RegQueryValueExW.argtypes = [wintypes.HANDLE, wintypes.LPCWSTR, ctypes.c_void_p, ctypes.POINTER(wintypes.DWORD),
                                 ctypes.c_void_p, ctypes.POINTER(wintypes.DWORD)]


def raw():
    """(type, bytes) of the scratch value, or None if it doesn't exist."""
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, SCRATCH) as k:
        kind, size = wintypes.DWORD(), wintypes.DWORD(0)
        if adv.RegQueryValueExW(int(k), pf.VALUE, None, ctypes.byref(kind), None, ctypes.byref(size)):
            return None
        buf = ctypes.create_string_buffer(max(size.value, 1))
        adv.RegQueryValueExW(int(k), pf.VALUE, None, ctypes.byref(kind), buf, ctypes.byref(size))
        return kind.value, buf.raw[:size.value]


def run(cmds):          # the same shape optimizer.run_elevated() uses: cmd.exe /c "a & b"
    return subprocess.run('cmd.exe /c "' + " & ".join(cmds) + '"', capture_output=True).returncode


def put(entries):
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, SCRATCH, 0, winreg.KEY_SET_VALUE) as k:
        if entries is None:
            try:
                winreg.DeleteValue(k, pf.VALUE)
            except OSError:
                pass
        else:
            winreg.SetValueEx(k, pf.VALUE, 0, winreg.REG_MULTI_SZ, entries)


try:
    put([pf.AUTO])
    default = raw()
    for name, before in [("off (empty list)", []), ("value missing", None), ("managed", [pf.AUTO]),
                         ("custom, two drives", [r"C:\pagefile.sys 4096 8192", r"D:\pagefile.sys 0 0"]),
                         ("path with a space", [r"D:\my files\pagefile.sys 16 32"])]:
        put(before)
        original = raw()
        saved = json.loads(json.dumps(pf.read(winreg.HKEY_CURRENT_USER, SCRATCH)))      # like the undo file
        check(saved == before, f"{name}: read back as {saved!r}")
        code = run(pf.apply_cmds(SCRATCH, "HKCU") + ["ver >nul"])                      # chained like a real batch
        check(code == 0 and raw() == default, f"{name}: apply -> Windows' default, byte for byte")
        check(pf.status(pf.read(winreg.HKEY_CURRENT_USER, SCRATCH)) == pf.MANAGED, f"{name}: re-read says managed")
        code = run(pf.undo_cmds(saved, SCRATCH, "HKCU"))
        check(code == 0 and raw() == original, f"{name}: undo -> byte-identical to before")
finally:
    for key in (SCRATCH, SCRATCH.rsplit("\\", 1)[0]):
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, key)
        except OSError:
            pass
try:
    winreg.CloseKey(winreg.OpenKey(winreg.HKEY_CURRENT_USER, SCRATCH.rsplit("\\", 1)[0]))
    check(False, "scratch key removed")
except OSError:
    check(True, "scratch key removed")

print("\nALL PASSED" if not fails else f"\n{len(fails)} FAILED: {fails}")
sys.exit(1 if fails else 0)
