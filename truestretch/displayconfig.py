"""Windows Connecting-and-Configuring-Displays (CCD) API: real monitor names, how they're connected,
their native resolution, and the GPU scaling mode (centered / keep aspect / stretched)."""

import ctypes
from ctypes import wintypes
from dataclasses import dataclass


class LUID(ctypes.Structure):
    _fields_ = [("LowPart", wintypes.DWORD), ("HighPart", wintypes.LONG)]


class RATIONAL(ctypes.Structure):
    _fields_ = [("Numerator", ctypes.c_uint32), ("Denominator", ctypes.c_uint32)]


class REGION2D(ctypes.Structure):
    _fields_ = [("cx", ctypes.c_uint32), ("cy", ctypes.c_uint32)]


class VIDEO_SIGNAL_INFO(ctypes.Structure):
    _fields_ = [("pixelRate", ctypes.c_uint64), ("hSyncFreq", RATIONAL), ("vSyncFreq", RATIONAL),
                ("activeSize", REGION2D), ("totalSize", REGION2D), ("videoStandard", ctypes.c_uint32),
                ("scanLineOrdering", ctypes.c_uint32)]


class PATH_SOURCE_INFO(ctypes.Structure):
    _fields_ = [("adapterId", LUID), ("id", ctypes.c_uint32), ("modeInfoIdx", ctypes.c_uint32),
                ("statusFlags", ctypes.c_uint32)]


class PATH_TARGET_INFO(ctypes.Structure):
    _fields_ = [("adapterId", LUID), ("id", ctypes.c_uint32), ("modeInfoIdx", ctypes.c_uint32),
                ("outputTechnology", ctypes.c_uint32), ("rotation", ctypes.c_uint32),
                ("scaling", ctypes.c_uint32), ("refreshRate", RATIONAL), ("scanLineOrdering", ctypes.c_uint32),
                ("targetAvailable", wintypes.BOOL), ("statusFlags", ctypes.c_uint32)]


class PATH_INFO(ctypes.Structure):
    _fields_ = [("sourceInfo", PATH_SOURCE_INFO), ("targetInfo", PATH_TARGET_INFO), ("flags", ctypes.c_uint32)]


class MODE_INFO(ctypes.Structure):
    _fields_ = [("infoType", ctypes.c_uint32), ("id", ctypes.c_uint32), ("adapterId", LUID),
                ("data", ctypes.c_uint64 * 6)]


class DEVICE_INFO_HEADER(ctypes.Structure):
    _fields_ = [("type", ctypes.c_uint32), ("size", ctypes.c_uint32), ("adapterId", LUID), ("id", ctypes.c_uint32)]


class SOURCE_DEVICE_NAME(ctypes.Structure):
    _fields_ = [("header", DEVICE_INFO_HEADER), ("viewGdiDeviceName", wintypes.WCHAR * 32)]


class TARGET_DEVICE_NAME(ctypes.Structure):
    _fields_ = [("header", DEVICE_INFO_HEADER), ("flags", ctypes.c_uint32), ("outputTechnology", ctypes.c_uint32),
                ("edidManufactureId", ctypes.c_uint16), ("edidProductCodeId", ctypes.c_uint16),
                ("connectorInstance", ctypes.c_uint32), ("monitorFriendlyDeviceName", wintypes.WCHAR * 64),
                ("monitorDevicePath", wintypes.WCHAR * 128)]


class TARGET_PREFERRED_MODE(ctypes.Structure):
    _fields_ = [("header", DEVICE_INFO_HEADER), ("width", ctypes.c_uint32), ("height", ctypes.c_uint32),
                ("targetMode", VIDEO_SIGNAL_INFO)]


QDC_ONLY_ACTIVE_PATHS = 0x2
GET_SOURCE_NAME, GET_TARGET_NAME, GET_TARGET_PREFERRED_MODE = 1, 2, 3
SDC_USE_SUPPLIED_DISPLAY_CONFIG = 0x20
SDC_VALIDATE = 0x40
SDC_APPLY = 0x80
SDC_SAVE_TO_DATABASE = 0x200
SDC_ALLOW_CHANGES = 0x400

SCALING_NAMES = {1: "None (identity)", 2: "Centered (black bars)", 3: "Stretched (full screen)",
                 4: "Keep aspect ratio (black bars)", 5: "Custom", 128: "Driver default"}
SCALING_STRETCHED = 3
CONNECTIONS = {0: "VGA", 4: "DVI", 5: "HDMI", 6: "Built-in screen", 10: "DisplayPort", 11: "Built-in screen",
               13: "Built-in screen", 15: "Wireless (Miracast)", 16: "USB / dock", 17: "Virtual",
               0x80000000: "Built-in screen"}
BUILT_IN = {6, 11, 13, 0x80000000}

user32 = ctypes.WinDLL("user32")
user32.GetDisplayConfigBufferSizes.argtypes = [ctypes.c_uint32, ctypes.POINTER(ctypes.c_uint32),
                                               ctypes.POINTER(ctypes.c_uint32)]
user32.GetDisplayConfigBufferSizes.restype = ctypes.c_long
user32.QueryDisplayConfig.argtypes = [ctypes.c_uint32, ctypes.POINTER(ctypes.c_uint32), ctypes.POINTER(PATH_INFO),
                                      ctypes.POINTER(ctypes.c_uint32), ctypes.POINTER(MODE_INFO), ctypes.c_void_p]
user32.QueryDisplayConfig.restype = ctypes.c_long
user32.SetDisplayConfig.argtypes = [ctypes.c_uint32, ctypes.POINTER(PATH_INFO), ctypes.c_uint32,
                                    ctypes.POINTER(MODE_INFO), ctypes.c_uint32]
user32.SetDisplayConfig.restype = ctypes.c_long
user32.DisplayConfigGetDeviceInfo.argtypes = [ctypes.c_void_p]
user32.DisplayConfigGetDeviceInfo.restype = ctypes.c_long


@dataclass
class Monitor:
    device: str              # \\.\DISPLAY1 - matches display.Display.device
    name: str                # "LG 27GL850", "Built-in screen" ...
    connection: str
    built_in: bool
    native: tuple            # (width, height) the panel really has
    native_hz: float
    scaling: int             # SCALING_* value currently set for this screen
    device_path: str = ""    # \\?\DISPLAY#SAM707F#... - links to the monitor's Device Manager entry
    target_id: int = 0       # matches "UID<n>" in the Device Manager instance id, even when that entry is disabled

    @property
    def scaling_name(self):
        return SCALING_NAMES.get(self.scaling, f"Unknown ({self.scaling})")

    @property
    def stretches(self):
        return self.scaling == SCALING_STRETCHED


def _query():
    for _ in range(3):
        n_paths, n_modes = ctypes.c_uint32(), ctypes.c_uint32()
        if user32.GetDisplayConfigBufferSizes(QDC_ONLY_ACTIVE_PATHS, ctypes.byref(n_paths), ctypes.byref(n_modes)):
            return [], [], 0, 0
        paths = (PATH_INFO * n_paths.value)()
        modes = (MODE_INFO * n_modes.value)()
        rc = user32.QueryDisplayConfig(QDC_ONLY_ACTIVE_PATHS, ctypes.byref(n_paths), paths, ctypes.byref(n_modes),
                                       modes, None)
        if rc == 0:
            return paths, modes, n_paths.value, n_modes.value
        if rc != 122:  # ERROR_INSUFFICIENT_BUFFER: the setup changed between calls, try again
            break
    return [], [], 0, 0


def _info(struct, kind, adapter, target_id):
    struct.header.type = kind
    struct.header.size = ctypes.sizeof(struct)
    struct.header.adapterId = adapter
    struct.header.id = target_id
    return user32.DisplayConfigGetDeviceInfo(ctypes.byref(struct)) == 0


def monitors():
    """Every active monitor with its real name and settings. Empty list if Windows won't say."""
    paths, _, count, _ = _query()
    found = []
    for i in range(count):
        path = paths[i]
        src = SOURCE_DEVICE_NAME()
        if not _info(src, GET_SOURCE_NAME, path.sourceInfo.adapterId, path.sourceInfo.id):
            continue
        tgt = TARGET_DEVICE_NAME()
        _info(tgt, GET_TARGET_NAME, path.targetInfo.adapterId, path.targetInfo.id)
        pref = TARGET_PREFERRED_MODE()
        _info(pref, GET_TARGET_PREFERRED_MODE, path.targetInfo.adapterId, path.targetInfo.id)
        tech = path.targetInfo.outputTechnology
        built_in = tech in BUILT_IN
        name = tgt.monitorFriendlyDeviceName.strip() or ("Built-in screen" if built_in else "Monitor")
        vs = pref.targetMode.vSyncFreq
        found.append(Monitor(
            device=src.viewGdiDeviceName, name=name, connection=CONNECTIONS.get(tech, "Other"),
            built_in=built_in, native=(pref.width, pref.height),
            native_hz=round(vs.Numerator / vs.Denominator, 1) if vs.Denominator else 0.0,
            scaling=path.targetInfo.scaling, device_path=tgt.monitorDevicePath, target_id=path.targetInfo.id))
    return found


def monitor_for(device):
    for m in monitors():
        if m.device == device:
            return m
    return None


def set_scaling(device, scaling, apply=True):
    """Ask Windows / the graphics driver to use this scaling mode for one screen.
    With apply=False it only checks the driver would accept it. Returns True on success."""
    paths, modes, n_paths, n_modes = _query()
    changed = False
    for i in range(n_paths):
        src = SOURCE_DEVICE_NAME()
        if _info(src, GET_SOURCE_NAME, paths[i].sourceInfo.adapterId, paths[i].sourceInfo.id) \
                and src.viewGdiDeviceName == device:
            paths[i].targetInfo.scaling = scaling
            changed = True
    if not changed:
        return False
    flags = SDC_USE_SUPPLIED_DISPLAY_CONFIG | (SDC_APPLY | SDC_SAVE_TO_DATABASE | SDC_ALLOW_CHANGES if apply
                                               else SDC_VALIDATE)
    return user32.SetDisplayConfig(n_paths, paths, n_modes, modes, flags) == 0
