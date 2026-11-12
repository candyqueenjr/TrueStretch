"""Windows accessibility keyboard shortcuts - Sticky Keys (press Shift 5 times), Filter Keys (hold the right Shift key
8 seconds) and Toggle Keys (hold Num Lock 5 seconds) - read and changed through SystemParametersInfo, the same way
Settings > Accessibility > Keyboard does it. Only the *shortcut* is ever touched, never the feature itself.

Flags and SPI codes are from winuser.h: STICKYKEYS / FILTERKEYS / TOGGLEKEYS and SPI_GET/SET{STICKY,FILTER,TOGGLE}KEYS.
The live state (what the shortcut does right now) comes from SystemParametersInfo; Windows also keeps a copy in
HKCU\\Control Panel\\Accessibility\\<feature>\\Flags that it loads at sign-in, so both are read, set and restored."""

import ctypes
import winreg
from ctypes import wintypes

SPIF_UPDATEINIFILE, SPIF_SENDCHANGE = 0x1, 0x2
ON, HOTKEY = 0x1, 0x4            # SKF_STICKYKEYSON / FKF_FILTERKEYSON / TKF_TOGGLEKEYSON and *_HOTKEYACTIVE
REG_ROOT = r"Control Panel\Accessibility"


class _Flags(ctypes.Structure):          # STICKYKEYS and TOGGLEKEYS
    _fields_ = [("cbSize", wintypes.UINT), ("dwFlags", wintypes.DWORD)]


class _FilterKeys(ctypes.Structure):     # FILTERKEYS
    _fields_ = [("cbSize", wintypes.UINT), ("dwFlags", wintypes.DWORD), ("iWaitMSec", wintypes.DWORD),
                ("iDelayMSec", wintypes.DWORD), ("iRepeatMSec", wintypes.DWORD), ("iBounceMSec", wintypes.DWORD)]


class Feature:
    def __init__(self, fid, title, shortcut, spi_get, spi_set, struct, reg_key):
        self.id, self.title, self.shortcut = fid, title, shortcut
        self.spi_get, self.spi_set, self.struct = spi_get, spi_set, struct
        self.reg_key = REG_ROOT + "\\" + reg_key


FEATURES = [
    Feature("sticky", "Sticky Keys", "Shift × 5", 0x3A, 0x3B, _Flags, "StickyKeys"),
    Feature("filter", "Filter Keys", "hold right Shift 8 s", 0x32, 0x33, _FilterKeys, "Keyboard Response"),
    Feature("toggle", "Toggle Keys", "hold Num Lock 5 s", 0x34, 0x35, _Flags, "ToggleKeys"),
]


def _spi(action, struct, flags=0):
    size = ctypes.sizeof(struct)
    struct.cbSize = size
    if not ctypes.windll.user32.SystemParametersInfoW(action, size, ctypes.byref(struct), flags):
        raise OSError(f"SystemParametersInfo({action:#x}) failed (error {ctypes.GetLastError()})")


def read(feature):
    """The live settings structure (all members filled in by Windows)."""
    s = feature.struct()
    _spi(feature.spi_get, s)
    return s


def fields(struct):
    return {name: int(getattr(struct, name)) for name, _ in struct._fields_ if name != "cbSize"}


def write(feature, values):
    """Set the live settings from {member: value} and ask Windows to keep them for the next sign-in too."""
    s = feature.struct()
    for name, value in values.items():
        if name != "cbSize":
            setattr(s, name, int(value))
    _spi(feature.spi_set, s, SPIF_UPDATEINIFILE | SPIF_SENDCHANGE)


def registry_values(feature):
    """Every value under the feature's registry key: {name: [value, kind]} (empty if the key doesn't exist)."""
    out = {}
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, feature.reg_key) as k:
            i = 0
            while True:
                try:
                    name, value, kind = winreg.EnumValue(k, i)
                except OSError:
                    break
                out[name] = [value.hex() if isinstance(value, bytes) else value, kind]   # JSON-safe for the undo file
                i += 1
    except OSError:
        pass
    return out


def registry_flags(feature):
    """The dwFlags Windows will load at the next sign-in, or None if it isn't stored."""
    raw = registry_values(feature).get("Flags")
    try:
        return int(str(raw[0]).strip()) if raw else None
    except ValueError:
        return None


def set_registry_values(feature, values):
    """Make the registry key hold exactly these values (others are removed)."""
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, feature.reg_key, 0, winreg.KEY_ALL_ACCESS) as k:
        for name in list(registry_values(feature)):
            if name not in values:
                winreg.DeleteValue(k, name)
        for name, (value, kind) in values.items():
            if kind == winreg.REG_BINARY and isinstance(value, str):
                value = bytes.fromhex(value)
            winreg.SetValueEx(k, name, 0, kind, value)


def hotkey_active(feature):
    """(live, stored): whether the shortcut works right now, and whether it comes back at the next sign-in."""
    live = bool(read(feature).dwFlags & HOTKEY)
    stored = registry_flags(feature)
    return live, (live if stored is None else bool(stored & HOTKEY))


def feature_on(feature):
    return bool(read(feature).dwFlags & ON)


def snapshot(feature):
    return {"live": fields(read(feature)), "registry": registry_values(feature)}


def restore(feature, data):
    """Put back exactly what snapshot() saw: the live state first (that also rewrites the registry), then the
    registry values byte for byte."""
    write(feature, data["live"])
    set_registry_values(feature, {n: (v[0], v[1]) for n, v in data["registry"].items()})


def set_hotkey(feature, active):
    """Turn only the shortcut on or off; every other flag and timing value stays as it is."""
    values = fields(read(feature))
    values["dwFlags"] = (values["dwFlags"] | HOTKEY) if active else (values["dwFlags"] & ~HOTKEY)
    write(feature, values)
    # Windows normally stores the new flags itself (SPIF_UPDATEINIFILE); make sure, so the change survives sign-in.
    if registry_flags(feature) != values["dwFlags"]:
        reg = registry_values(feature)
        reg["Flags"] = [str(values["dwFlags"]), winreg.REG_SZ]
        set_registry_values(feature, {n: (v[0], v[1]) for n, v in reg.items()})
