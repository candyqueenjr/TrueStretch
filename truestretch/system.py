"""Windows helpers: running processes, registry, drives, startup entry, opening things."""

import ctypes
import os
import platform
import subprocess
import sys
import winreg
from ctypes import wintypes
from pathlib import Path

from . import APP_NAME
from .paths import is_frozen

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.c_size_t),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", wintypes.LONG),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", wintypes.WCHAR * 260),
    ]


TH32CS_SNAPPROCESS = 0x2
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
kernel32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
kernel32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def running_processes():
    """Lower-case exe names of every running process."""
    names = set()
    snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if not snap or snap == INVALID_HANDLE_VALUE:
        return names
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        ok = kernel32.Process32FirstW(snap, ctypes.byref(entry))
        while ok:
            names.add(entry.szExeFile.lower())
            ok = kernel32.Process32NextW(snap, ctypes.byref(entry))
    finally:
        kernel32.CloseHandle(snap)
    return names


def fixed_drives():
    """Local hard drives, e.g. ['C:\\', 'D:\\']."""
    mask = kernel32.GetLogicalDrives()
    drives = []
    for i in range(26):
        if mask & (1 << i):
            root = f"{chr(65 + i)}:\\"
            if kernel32.GetDriveTypeW(root) == 3:  # DRIVE_FIXED
                drives.append(root)
    return drives


def reg_get(root, path, name, default=None):
    try:
        with winreg.OpenKey(root, path) as key:
            return winreg.QueryValueEx(key, name)[0]
    except OSError:
        return default


def reg_set(root, path, name, value):
    with winreg.CreateKeyEx(root, path, 0, winreg.KEY_SET_VALUE) as key:
        winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)


def reg_delete(root, path, name):
    try:
        with winreg.OpenKey(root, path, 0, winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, name)
    except FileNotFoundError:
        pass


def flags_with(raw, name, value):
    """Windows keeps some per-app graphics settings as one string of "Name=Value;" pairs (DirectX
    UserGpuPreferences: GpuPreference, AutoHDREnable, AppStatus, SwapEffectUpgradeEnable ...). Returns that string
    with `name` set to `value` (value None removes it) and every other pair kept exactly as Windows wrote it.
    Returns "" when nothing is left."""
    pairs = [p for p in (raw or "").split(";") if p.strip()]
    kept = [p for p in pairs if p.split("=", 1)[0].strip().lower() != name.lower()]
    if value is not None:
        kept.append(f"{name}={value}")
    return ";".join(kept) + ";" if kept else ""


def flag_value(raw, name):
    """The value of one "Name=Value" pair in such a string, or None if it isn't there."""
    for p in (raw or "").split(";"):
        k, _, v = p.partition("=")
        if k.strip().lower() == name.lower():
            return v.strip()
    return None


def launch_command(*extra):
    """Command line that starts this app (packaged .exe or source)."""
    if is_frozen():
        # A one-file .exe runs from a temporary unpack folder; relaunch the real TrueStretch.exe instead.
        original = Path(sys.argv[0])
        exe = original if original.suffix.lower() == ".exe" and original.is_file() else Path(sys.executable)
        return [str(exe), *extra]
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    main = Path(__file__).resolve().parent.parent / "main.py"
    return [str(pythonw if pythonw.exists() else sys.executable), str(main), *extra]


def startup_enabled():
    return reg_get(winreg.HKEY_CURRENT_USER, RUN_KEY, APP_NAME) is not None


def set_startup(enabled):
    if enabled:
        reg_set(winreg.HKEY_CURRENT_USER, RUN_KEY, APP_NAME, subprocess.list2cmdline(launch_command("--minimized")))
    else:
        reg_delete(winreg.HKEY_CURRENT_USER, RUN_KEY, APP_NAME)


def windows_version():
    build = sys.getwindowsversion().build
    name = "Windows 11" if build >= 22000 else f"Windows {platform.release()}"
    return f"{name} (build {build})"


def system_prefers_dark():
    value = reg_get(winreg.HKEY_CURRENT_USER,
                    r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize", "AppsUseLightTheme", 1)
    return value == 0


def open_path(path):
    path = Path(path)
    if not path.exists() and path.suffix == "":
        path.mkdir(parents=True, exist_ok=True)
    os.startfile(path)


def reveal_file(path):
    subprocess.Popen(["explorer.exe", "/select,", str(path)])


def open_uri(uri):
    os.startfile(uri)


def open_store_app(app_id):
    subprocess.Popen(["explorer.exe", f"shell:AppsFolder\\{app_id}"])


def store_app_family(package_name):
    """PackageFamilyName of an installed Store app (it differs between PCs), or None."""
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command", f"(Get-AppxPackage -Name '{package_name}').PackageFamilyName"],
            capture_output=True, text=True, timeout=15, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        family = out.stdout.strip().splitlines()
        return family[0].strip() if family else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def open_installed_store_app(package_name, app_id):
    """Open a Store app by package name, looking up this PC's real app id. Raises FileNotFoundError."""
    family = store_app_family(package_name)
    if not family:
        raise FileNotFoundError(f"{package_name} isn't installed on this PC.")
    open_store_app(f"{family}!{app_id}")


def set_dark_title_bar(hwnd, dark):
    try:
        value = ctypes.c_int(1 if dark else 0)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(wintypes.HWND(hwnd), 20, ctypes.byref(value), ctypes.sizeof(value))
    except (AttributeError, OSError):
        pass
