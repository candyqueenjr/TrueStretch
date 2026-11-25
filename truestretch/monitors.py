"""Monitor devices in Device Manager. The 2026 true-stretched method disables them: Windows then stops
applying the monitor's own driver limits, which removes black bars and un-greys VALORANT's "Fill" option.
Reading needs no special rights; disabling / re-enabling asks for administrator permission (UAC)."""

import ctypes
import subprocess
import sys
import uuid
from ctypes import wintypes
from dataclasses import dataclass

from .readcache import memo
from .system import run_elevated

MONITOR_CLASS = uuid.UUID("4d36e96e-e325-11ce-bfc1-08002be10318")
DIGCF_PRESENT = 0x2
SPDRP_DEVICEDESC = 0x0
SPDRP_FRIENDLYNAME = 0xC
CM_PROB_DISABLED = 22
DN_HAS_PROBLEM = 0x400
INVALID_HANDLE = ctypes.c_void_p(-1).value


class GUID(ctypes.Structure):
    _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD), ("Data3", wintypes.WORD),
                ("Data4", ctypes.c_ubyte * 8)]


class SP_DEVINFO_DATA(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("ClassGuid", GUID), ("DevInst", wintypes.DWORD),
                ("Reserved", ctypes.c_void_p)]


setupapi = ctypes.WinDLL("setupapi")
cfgmgr32 = ctypes.WinDLL("cfgmgr32")
setupapi.SetupDiGetClassDevsW.argtypes = [ctypes.POINTER(GUID), wintypes.LPCWSTR, wintypes.HWND, wintypes.DWORD]
setupapi.SetupDiGetClassDevsW.restype = ctypes.c_void_p
setupapi.SetupDiEnumDeviceInfo.argtypes = [ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(SP_DEVINFO_DATA)]
setupapi.SetupDiGetDeviceInstanceIdW.argtypes = [ctypes.c_void_p, ctypes.POINTER(SP_DEVINFO_DATA), wintypes.LPWSTR,
                                                 wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
setupapi.SetupDiGetDeviceRegistryPropertyW.argtypes = [ctypes.c_void_p, ctypes.POINTER(SP_DEVINFO_DATA),
                                                       wintypes.DWORD, ctypes.POINTER(wintypes.DWORD),
                                                       ctypes.c_void_p, wintypes.DWORD,
                                                       ctypes.POINTER(wintypes.DWORD)]
setupapi.SetupDiDestroyDeviceInfoList.argtypes = [ctypes.c_void_p]
cfgmgr32.CM_Get_DevNode_Status.argtypes = [ctypes.POINTER(wintypes.ULONG), ctypes.POINTER(wintypes.ULONG),
                                           wintypes.DWORD, wintypes.ULONG]


@dataclass
class MonitorDevice:
    instance_id: str          # DISPLAY\SAM707F\5&2f1b...&UID4352
    description: str          # "Generic PnP Monitor"
    disabled: bool

    def matches(self, monitor):
        """Is this Device Manager entry the given displayconfig.Monitor? Uses the device path when the entry is
        enabled, otherwise the connector id (UID) that Windows puts at the end of the instance id."""
        if monitor.device_path:
            path = monitor.device_path.upper().lstrip("\\?").split("#{")[0].replace("#", "\\")
            if path == self.instance_id.upper():
                return True
        return bool(monitor.target_id) and self.instance_id.upper().endswith(f"UID{monitor.target_id}")


def device_for(monitor, devices=None):
    for dev in devices if devices is not None else list_monitor_devices():
        if dev.matches(monitor):
            return dev
    return None


def _prop(handle, data, prop):
    buf = ctypes.create_unicode_buffer(512)
    if setupapi.SetupDiGetDeviceRegistryPropertyW(handle, ctypes.byref(data), prop, None, buf,
                                                  ctypes.sizeof(buf), None):
        return buf.value
    return ""


def list_monitor_devices():
    """Every monitor in Device Manager (cached inside a UI refresh, see readcache)."""
    return memo("monitor_devices", _list_monitor_devices)


def _list_monitor_devices():
    guid = GUID.from_buffer_copy(MONITOR_CLASS.bytes_le)
    handle = setupapi.SetupDiGetClassDevsW(ctypes.byref(guid), None, None, DIGCF_PRESENT)
    if not handle or handle == INVALID_HANDLE:
        return []
    found = []
    try:
        i = 0
        while True:
            data = SP_DEVINFO_DATA()
            data.cbSize = ctypes.sizeof(SP_DEVINFO_DATA)
            if not setupapi.SetupDiEnumDeviceInfo(handle, i, ctypes.byref(data)):
                break
            i += 1
            buf = ctypes.create_unicode_buffer(512)
            if not setupapi.SetupDiGetDeviceInstanceIdW(handle, ctypes.byref(data), buf, 512, None):
                continue
            status, problem = wintypes.ULONG(), wintypes.ULONG()
            disabled = False
            if cfgmgr32.CM_Get_DevNode_Status(ctypes.byref(status), ctypes.byref(problem), data.DevInst, 0) == 0:
                disabled = bool(status.value & DN_HAS_PROBLEM) and problem.value == CM_PROB_DISABLED
            desc = _prop(handle, data, SPDRP_FRIENDLYNAME) or _prop(handle, data, SPDRP_DEVICEDESC) or "Monitor"
            found.append(MonitorDevice(buf.value, desc, disabled))
    finally:
        setupapi.SetupDiDestroyDeviceInfoList(handle)
    return found


def pnputil_supported():
    return sys.getwindowsversion().build >= 19041   # pnputil /disable-device arrived in Windows 10 2004


def set_enabled(instance_ids, enabled, hwnd=None):
    """Disable or enable monitor devices through pnputil, with one administrator prompt.
    Returns the exit code (0 ok, 3010 = works after restart). Raises PermissionError if UAC was declined."""
    verb = "/enable-device" if enabled else "/disable-device"
    return run_elevated([f'pnputil {verb} "{iid}"' for iid in instance_ids], hwnd, timeout=120, what="pnputil")


def open_device_manager():
    subprocess.Popen(["mmc.exe", "devmgmt.msc"])
