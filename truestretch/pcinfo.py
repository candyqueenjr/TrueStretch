"""Reads everything useful about the player's PC: processor, memory, graphics cards and drivers,
power, Windows gaming settings, anti-cheat. Read-only; every probe fails soft."""

import ctypes
import os
import re
import shutil
import subprocess
import winreg
from ctypes import wintypes
from dataclasses import dataclass, field
from datetime import date, datetime

from .display import clean_name
from .system import reg_get, windows_version

GPU_CLASS_KEY = r"SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}"
POWER_KEY = r"SYSTEM\CurrentControlSet\Control\Power\User\PowerSchemes"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

POWER_MODES = {  # Windows 10/11 "Power mode" slider
    "961cc777-2547-4f9d-8174-7d86181b8a7a": "Best power efficiency",
    "00000000-0000-0000-0000-000000000000": "Balanced",
    "3af9b8d9-7c97-431d-ad78-34a8bfea439f": "Better performance",
    "ded574b5-45a0-4f42-8737-46345c09c238": "Best performance",
}
POWER_PLANS = {
    "a1841308-3541-4fab-bc81-f71556f20b4a": "Power saver",
    "381b4222-f694-41f0-9685-ff5bb260df2e": "Balanced",
    "8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c": "High performance",
    "e9a42b02-d5df-448d-aa00-03f14749eb61": "Ultimate performance",
}


@dataclass
class Gpu:
    name: str
    vendor: str
    driver_version: str
    driver_date: date = None
    vram_gb: float = None

    @property
    def driver_age_days(self):
        return (date.today() - self.driver_date).days if self.driver_date else None

    @property
    def friendly_driver(self):
        """NVIDIA shows drivers as e.g. 616.92, not 32.0.16.1692."""
        if self.vendor == "nvidia":
            digits = self.driver_version.replace(".", "")
            if len(digits) >= 5:
                tail = digits[-5:]
                return f"{tail[:3]}.{tail[3:]}"
        return self.driver_version


@dataclass
class PcInfo:
    windows: str = ""
    cpu: str = ""
    cores: int = 0
    ram_gb: float = 0
    gpus: list = field(default_factory=list)
    laptop: bool = False
    on_battery: bool = False
    battery_percent: int = None
    power_plan: str = None
    power_mode: str = None
    game_mode: bool = True
    hags: bool = None              # hardware-accelerated GPU scheduling; None = Windows default
    vanguard_installed: bool = False
    vanguard_running: bool = False
    scanned_at: datetime = None

    @property
    def hybrid_graphics(self):
        vendors = {g.vendor for g in self.gpus}
        return "intel" in vendors and len(vendors) > 1 or len(self.gpus) > 1 and self.laptop


def _vendor(name):
    from .display import gpu_vendor
    return gpu_vendor(name)


class MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [("dwLength", wintypes.DWORD), ("dwMemoryLoad", wintypes.DWORD),
                ("ullTotalPhys", ctypes.c_uint64), ("ullAvailPhys", ctypes.c_uint64),
                ("ullTotalPageFile", ctypes.c_uint64), ("ullAvailPageFile", ctypes.c_uint64),
                ("ullTotalVirtual", ctypes.c_uint64), ("ullAvailVirtual", ctypes.c_uint64),
                ("ullAvailExtendedVirtual", ctypes.c_uint64)]


class SYSTEM_POWER_STATUS(ctypes.Structure):
    _fields_ = [("ACLineStatus", ctypes.c_ubyte), ("BatteryFlag", ctypes.c_ubyte),
                ("BatteryLifePercent", ctypes.c_ubyte), ("SystemStatusFlag", ctypes.c_ubyte),
                ("BatteryLifeTime", wintypes.DWORD), ("BatteryFullLifeTime", wintypes.DWORD)]


def ram_gb():
    status = MEMORYSTATUSEX()
    status.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
    if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        return round(status.ullTotalPhys / 1024 ** 3, 1)
    return 0


def power_status():
    """(laptop, on_battery, percent)"""
    s = SYSTEM_POWER_STATUS()
    if not ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(s)):
        return False, False, None
    has_battery = s.BatteryFlag not in (128, 255)
    percent = s.BatteryLifePercent if s.BatteryLifePercent <= 100 else None
    return has_battery, has_battery and s.ACLineStatus == 0, percent


def gpus():
    found = []
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, GPU_CLASS_KEY) as root:
            for i in range(winreg.QueryInfoKey(root)[0]):
                sub = winreg.EnumKey(root, i)
                try:
                    with winreg.OpenKey(root, sub) as key:
                        name = clean_name(winreg.QueryValueEx(key, "DriverDesc")[0])
                        values = {}
                        for v in ("DriverVersion", "DriverDate", "HardwareInformation.qwMemorySize",
                                  "HardwareInformation.MemorySize"):
                            try:
                                values[v] = winreg.QueryValueEx(key, v)[0]
                            except OSError:
                                pass
                except OSError:
                    continue
                if not name or "basic" in name.lower() or any(g.name == name for g in found):
                    continue
                drv_date = None
                m = re.match(r"(\d+)-(\d+)-(\d{4})", str(values.get("DriverDate", "")))
                if m:
                    try:
                        drv_date = date(int(m.group(3)), int(m.group(1)), int(m.group(2)))
                    except ValueError:
                        pass
                vram = values.get("HardwareInformation.qwMemorySize")
                if not isinstance(vram, int):
                    mem = values.get("HardwareInformation.MemorySize")
                    vram = mem if isinstance(mem, int) else None
                found.append(Gpu(name, _vendor(name), str(values.get("DriverVersion", "unknown")), drv_date,
                                 round(vram / 1024 ** 3, 1) if vram and vram > 256 * 1024 ** 2 else None))
    except OSError:
        pass
    order = {"nvidia": 0, "amd": 1, "intel": 2}
    found.sort(key=lambda g: order.get(g.vendor, 3))
    return found


def _service_running(name):
    try:
        out = subprocess.run(["sc.exe", "query", name], capture_output=True, text=True,
                             creationflags=NO_WINDOW, timeout=5).stdout
    except (OSError, subprocess.TimeoutExpired):
        return None
    if "1060" in out or "does not exist" in out.lower():
        return None
    return "RUNNING" in out


def scan():
    info = PcInfo(windows=windows_version(), scanned_at=datetime.now())
    info.cpu = clean_name(reg_get(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0",
                                  "ProcessorNameString", ""))
    info.cores = os.cpu_count() or 0
    info.ram_gb = ram_gb()
    info.gpus = gpus()
    info.laptop, info.on_battery, info.battery_percent = power_status()

    plan = reg_get(winreg.HKEY_LOCAL_MACHINE, POWER_KEY, "ActivePowerScheme")
    info.power_plan = POWER_PLANS.get((plan or "").lower(), "Custom plan" if plan else None)
    overlay = reg_get(winreg.HKEY_LOCAL_MACHINE, POWER_KEY,
                      "ActiveOverlayDcPowerScheme" if info.on_battery else "ActiveOverlayAcPowerScheme")
    info.power_mode = POWER_MODES.get((overlay or "").lower()) if overlay is not None else None

    info.game_mode = reg_get(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\GameBar", "AutoGameModeEnabled", 1) != 0
    hags = reg_get(winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\GraphicsDrivers", "HwSchMode")
    info.hags = None if hags is None else hags == 2

    vgk = _service_running("vgk")
    info.vanguard_installed = vgk is not None or os.path.isfile(r"C:\Program Files\Riot Vanguard\vgc.exe")
    info.vanguard_running = bool(vgk)
    return info


def disk_free_gb(path):
    try:
        return round(shutil.disk_usage(path).free / 1024 ** 3, 1)
    except OSError:
        return None


DRIVER_PAGES = {
    "nvidia": "https://www.nvidia.com/en-us/geforce/drivers/",
    "amd": "https://www.amd.com/en/support/download/drivers.html",
    "intel": "https://www.intel.com/content/www/us/en/support/detect.html",
}
