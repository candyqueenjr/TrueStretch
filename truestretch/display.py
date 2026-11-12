"""Monitors, their resolutions, and switching between them (user32)."""

import ctypes
import re
import winreg
from ctypes import wintypes
from dataclasses import dataclass


class DEVMODEW(ctypes.Structure):
    _fields_ = [
        ("dmDeviceName", wintypes.WCHAR * 32),
        ("dmSpecVersion", wintypes.WORD),
        ("dmDriverVersion", wintypes.WORD),
        ("dmSize", wintypes.WORD),
        ("dmDriverExtra", wintypes.WORD),
        ("dmFields", wintypes.DWORD),
        ("dmPositionX", wintypes.LONG),
        ("dmPositionY", wintypes.LONG),
        ("dmDisplayOrientation", wintypes.DWORD),
        ("dmDisplayFixedOutput", wintypes.DWORD),
        ("dmColor", ctypes.c_short),
        ("dmDuplex", ctypes.c_short),
        ("dmYResolution", ctypes.c_short),
        ("dmTTOption", ctypes.c_short),
        ("dmCollate", ctypes.c_short),
        ("dmFormName", wintypes.WCHAR * 32),
        ("dmLogPixels", wintypes.WORD),
        ("dmBitsPerPel", wintypes.DWORD),
        ("dmPelsWidth", wintypes.DWORD),
        ("dmPelsHeight", wintypes.DWORD),
        ("dmDisplayFlags", wintypes.DWORD),
        ("dmDisplayFrequency", wintypes.DWORD),
        ("dmICMMethod", wintypes.DWORD),
        ("dmICMIntent", wintypes.DWORD),
        ("dmMediaType", wintypes.DWORD),
        ("dmDitherType", wintypes.DWORD),
        ("dmReserved1", wintypes.DWORD),
        ("dmReserved2", wintypes.DWORD),
        ("dmPanningWidth", wintypes.DWORD),
        ("dmPanningHeight", wintypes.DWORD),
    ]


class DISPLAY_DEVICEW(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("DeviceName", wintypes.WCHAR * 32),
        ("DeviceString", wintypes.WCHAR * 128),
        ("StateFlags", wintypes.DWORD),
        ("DeviceID", wintypes.WCHAR * 128),
        ("DeviceKey", wintypes.WCHAR * 128),
    ]


ENUM_CURRENT_SETTINGS = 0xFFFFFFFF
DM_PELSWIDTH = 0x00080000
DM_PELSHEIGHT = 0x00100000
DM_DISPLAYFREQUENCY = 0x00400000
CDS_UPDATEREGISTRY = 0x01
CDS_TEST = 0x02
DISPLAY_DEVICE_ATTACHED_TO_DESKTOP = 0x01
DISPLAY_DEVICE_PRIMARY_DEVICE = 0x04
DISP_ERRORS = {
    -1: "the display driver failed",
    -2: "this mode isn't supported by the display",
    -3: "Windows couldn't save the setting",
    -4: "invalid flags",
    -5: "invalid parameters",
    -6: "invalid dual-view setup",
}
GPU_CLASS_KEY = r"SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}"

user32 = ctypes.WinDLL("user32")
user32.EnumDisplaySettingsW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(DEVMODEW)]
user32.EnumDisplaySettingsW.restype = wintypes.BOOL
user32.EnumDisplayDevicesW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(DISPLAY_DEVICEW), wintypes.DWORD]
user32.EnumDisplayDevicesW.restype = wintypes.BOOL
user32.ChangeDisplaySettingsExW.argtypes = [
    wintypes.LPCWSTR, ctypes.POINTER(DEVMODEW), wintypes.HWND, wintypes.DWORD, wintypes.LPVOID,
]
user32.ChangeDisplaySettingsExW.restype = ctypes.c_long


class DisplayError(RuntimeError):
    pass


@dataclass(frozen=True)
class Mode:
    width: int
    height: int
    hz: int

    @property
    def size(self):
        return self.width, self.height

    def __str__(self):
        return f"{self.width} \u00d7 {self.height} @ {self.hz} Hz"

    def to_list(self):
        return [self.width, self.height, self.hz]

    @classmethod
    def from_list(cls, value):
        try:
            w, h, hz = (int(v) for v in value)
            return cls(w, h, hz)
        except (TypeError, ValueError):
            return None


@dataclass(frozen=True)
class Display:
    device: str      # \\.\DISPLAY1
    gpu: str         # name of the graphics card driving it
    primary: bool
    number: int      # 1-based, as Windows numbers them
    name: str = ""           # the monitor's own name, e.g. "LF27T35"
    connection: str = ""     # HDMI, DisplayPort, Built-in screen...
    built_in: bool = False
    native: tuple = None     # the panel's real resolution

    @property
    def vendor(self):
        return gpu_vendor(self.gpu)

    @property
    def title(self):
        """Short human name: 'LF27T35 (HDMI)' or 'Built-in screen'."""
        if not self.name:
            return f"Display {self.number}"
        if self.built_in or self.connection in ("", "Other") or self.name == self.connection:
            return self.name
        return f"{self.name} ({self.connection})"

    @property
    def label(self):
        suffix = ", main" if self.primary else ""
        return f"{self.title} \u2014 Display {self.number}{suffix}"


def clean_name(name):
    """'Intel(R) UHD Graphics' -> 'Intel UHD Graphics'."""
    return re.sub(r"\s+", " ", re.sub(r"\((R|TM|C)\)", "", name or "", flags=re.I)).strip()


def gpu_vendor(name):
    lowered = (name or "").lower()
    for vendor, keys in (("nvidia", ("nvidia", "geforce", "rtx", "gtx", "quadro")),
                         ("amd", ("amd", "radeon", "ati ")),
                         ("intel", ("intel", "iris", "uhd graphics", "arc"))):
        if any(k in lowered for k in keys):
            return vendor
    return "other"


def _devmode():
    dm = DEVMODEW()
    dm.dmSize = ctypes.sizeof(DEVMODEW)
    return dm


def list_displays():
    """Monitors attached to the desktop, main display first."""
    try:
        from .displayconfig import monitors
        named = {m.device: m for m in monitors()}
    except (OSError, AttributeError, ValueError):
        named = {}
    displays = []
    i = 0
    while True:
        dd = DISPLAY_DEVICEW()
        dd.cb = ctypes.sizeof(DISPLAY_DEVICEW)
        if not user32.EnumDisplayDevicesW(None, i, ctypes.byref(dd), 0):
            break
        i += 1
        if not dd.StateFlags & DISPLAY_DEVICE_ATTACHED_TO_DESKTOP:
            continue
        digits = "".join(c for c in dd.DeviceName if c.isdigit())
        mon = named.get(dd.DeviceName)
        displays.append(Display(
            device=dd.DeviceName,
            gpu=clean_name(dd.DeviceString) or "Unknown graphics",
            primary=bool(dd.StateFlags & DISPLAY_DEVICE_PRIMARY_DEVICE),
            number=int(digits) if digits else len(displays) + 1,
            name=mon.name if mon else "",
            connection=mon.connection if mon else "",
            built_in=mon.built_in if mon else False,
            native=mon.native if mon and mon.native[0] else None,
        ))
    displays.sort(key=lambda d: (not d.primary, d.number))
    return displays


def monitor_ref(target):
    """(monitor device id, index) the way games list monitors: 'MONITOR\\SAM707F\\{...}\\0004' and the screen's
    position in Windows' display order. None if Windows exposes no monitor (e.g. its driver is disabled)."""
    if target is None:
        return None
    dd = DISPLAY_DEVICEW()
    dd.cb = ctypes.sizeof(DISPLAY_DEVICEW)
    if not user32.EnumDisplayDevicesW(target.device, 0, ctypes.byref(dd), 0) or not dd.DeviceID:
        return None
    order = [d.device for d in sorted(list_displays(), key=lambda d: d.number)]
    return dd.DeviceID, order.index(target.device) if target.device in order else 0


def find_display(device=None):
    """The display with this device name, or the main display."""
    displays = list_displays()
    for d in displays:
        if device and d.device == device:
            return d
    return displays[0] if displays else None


def current_mode(device=None):
    dm = _devmode()
    if not user32.EnumDisplaySettingsW(device, ENUM_CURRENT_SETTINGS, ctypes.byref(dm)):
        return None
    return Mode(dm.dmPelsWidth, dm.dmPelsHeight, dm.dmDisplayFrequency)


def available_modes(device=None):
    """Every mode the driver offers for this display, biggest first, highest refresh first."""
    modes = set()
    i = 0
    while True:
        dm = _devmode()
        if not user32.EnumDisplaySettingsW(device, i, ctypes.byref(dm)):
            break
        i += 1
        if dm.dmBitsPerPel and dm.dmBitsPerPel < 32:
            continue
        modes.add(Mode(dm.dmPelsWidth, dm.dmPelsHeight, dm.dmDisplayFrequency))
    return sorted(modes, key=lambda m: (m.width * m.height, m.width, m.hz), reverse=True)


def sizes(modes):
    seen = []
    for m in modes:
        if m.size not in seen:
            seen.append(m.size)
    return seen


def refresh_rates(modes, width, height):
    return sorted({m.hz for m in modes if m.size == (width, height)}, reverse=True)


def mode_accepted(mode, device=None):
    """True if the driver would switch to this mode - also custom resolutions Windows doesn't list
    (with the monitor driver disabled, NVIDIA accepts sizes that never appear in the mode list)."""
    dm = _devmode()
    dm.dmPelsWidth, dm.dmPelsHeight, dm.dmDisplayFrequency = mode.width, mode.height, mode.hz
    dm.dmFields = DM_PELSWIDTH | DM_PELSHEIGHT | DM_DISPLAYFREQUENCY
    return user32.ChangeDisplaySettingsExW(device, ctypes.byref(dm), None, CDS_TEST, None) == 0


def desktop_position(device=None):
    """(x, y) of this screen's top-left corner on the Windows desktop."""
    dm = _devmode()
    if not user32.EnumDisplaySettingsW(device, ENUM_CURRENT_SETTINGS, ctypes.byref(dm)):
        return None
    return dm.dmPositionX, dm.dmPositionY


def set_mode(mode, device=None, persist=True):
    """Switch a display to this mode. persist=False changes it only until the next switch or reboot, so a crash
    can never leave the PC stretched. Raises DisplayError."""
    dm = _devmode()
    dm.dmPelsWidth, dm.dmPelsHeight, dm.dmDisplayFrequency = mode.width, mode.height, mode.hz
    dm.dmFields = DM_PELSWIDTH | DM_PELSHEIGHT | DM_DISPLAYFREQUENCY
    for flags in (CDS_TEST, CDS_UPDATEREGISTRY if persist else 0):
        rc = user32.ChangeDisplaySettingsExW(device, ctypes.byref(dm), None, flags, None)
        if rc not in (0, 1):
            raise DisplayError(f"Windows couldn't switch to {mode}: {DISP_ERRORS.get(rc, f'error {rc}')}.")


def installed_gpus():
    """Every graphics adapter installed, from the driver registry."""
    names = []
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, GPU_CLASS_KEY) as root:
            for i in range(winreg.QueryInfoKey(root)[0]):
                sub = winreg.EnumKey(root, i)
                try:
                    with winreg.OpenKey(root, sub) as key:
                        name = clean_name(winreg.QueryValueEx(key, "DriverDesc")[0])
                except OSError:
                    continue
                if name and name not in names and "basic" not in name.lower():
                    names.append(name)
    except OSError:
        pass
    return names
