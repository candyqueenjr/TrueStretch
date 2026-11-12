"""NVIDIA driver scaling through NVAPI (nvapi64.dll, installed with every NVIDIA driver).

Windows' own "stretched" request can be overruled by the NVIDIA Control Panel setting
(Adjust desktop size and position > Scaling mode / Perform scaling on / Override). This module reads and
sets that driver setting directly: NV_SCALING_GPU_SCALING_TO_NATIVE = "Full-screen" + "Perform scaling on GPU".
"""

import ctypes
from dataclasses import dataclass

NVAPI_OK = 0
ID_INITIALIZE = 0x0150E828
ID_GET_DISPLAY_CONFIG = 0x11ABCCF8
ID_SET_DISPLAY_CONFIG = 0x5D8CF8DE
ID_GET_ERROR_MESSAGE = 0x6C2D048C
ID_GET_TIMING = 0x175167E9
ID_TRY_CUSTOM_DISPLAY = 0x1F7DB630
ID_SAVE_CUSTOM_DISPLAY = 0x49882876
ID_REVERT_CUSTOM_TRIAL = 0xCBBD40F0
SAVE_TO_PERSISTENCE = 0x1
FORCE_MODE_ENUMERATION = 0x4
TIMING_CVT_RB = 6        # CVT reduced blanking - what NVIDIA Control Panel uses for LCD custom resolutions

SCALING_NAMES = {
    0: "Default", 1: "Full-screen (balanced)", 2: "Full-screen on GPU", 3: "No scaling (centered) on GPU",
    5: "Aspect ratio on GPU", 6: "Aspect ratio (balanced)", 7: "No scaling (balanced)", 8: "Integer scaling",
}
FULL_SCREEN_GPU = 2
STRETCHING = {1, 2}


class NV_TIMINGEXT(ctypes.Structure):
    _fields_ = [("flag", ctypes.c_uint32), ("rr", ctypes.c_uint16), ("rrx1k", ctypes.c_uint32),
                ("aspect", ctypes.c_uint32), ("rep", ctypes.c_uint16), ("status", ctypes.c_uint32),
                ("name", ctypes.c_uint8 * 40)]


class NV_TIMING(ctypes.Structure):
    _fields_ = [("HVisible", ctypes.c_uint16), ("HBorder", ctypes.c_uint16), ("HFrontPorch", ctypes.c_uint16),
                ("HSyncWidth", ctypes.c_uint16), ("HTotal", ctypes.c_uint16), ("HSyncPol", ctypes.c_uint8),
                ("VVisible", ctypes.c_uint16), ("VBorder", ctypes.c_uint16), ("VFrontPorch", ctypes.c_uint16),
                ("VSyncWidth", ctypes.c_uint16), ("VTotal", ctypes.c_uint16), ("VSyncPol", ctypes.c_uint8),
                ("interlaced", ctypes.c_uint16), ("pclk", ctypes.c_uint32), ("etc", NV_TIMINGEXT)]


class TIMING_FLAG(ctypes.Structure):
    # isInterlaced:4 + reserved:12 | union{tvFormat:8, ceaId:8, nvPsfId:8} | scaling:8 - MSVC gives the anonymous
    # union its own 32-bit unit, so this is 3 x uint32.
    _fields_ = [("bits", ctypes.c_uint32), ("format", ctypes.c_uint32), ("scaling", ctypes.c_uint32)]


class TIMING_INPUT(ctypes.Structure):
    _fields_ = [("version", ctypes.c_uint32), ("width", ctypes.c_uint32), ("height", ctypes.c_uint32),
                ("rr", ctypes.c_float), ("flag", TIMING_FLAG), ("type", ctypes.c_uint32)]


class CUSTOM_DISPLAY(ctypes.Structure):
    _fields_ = [("version", ctypes.c_uint32), ("width", ctypes.c_uint32), ("height", ctypes.c_uint32),
                ("depth", ctypes.c_uint32), ("colorFormat", ctypes.c_uint32),
                ("srcX", ctypes.c_float), ("srcY", ctypes.c_float), ("srcW", ctypes.c_float), ("srcH", ctypes.c_float),
                ("xRatio", ctypes.c_float), ("yRatio", ctypes.c_float), ("timing", NV_TIMING),
                ("flags", ctypes.c_uint32)]


class ADVANCED_TARGET_INFO(ctypes.Structure):
    _fields_ = [("version", ctypes.c_uint32), ("rotation", ctypes.c_uint32), ("scaling", ctypes.c_uint32),
                ("refreshRate1K", ctypes.c_uint32), ("flags", ctypes.c_uint32), ("connector", ctypes.c_uint32),
                ("tvFormat", ctypes.c_uint32), ("timingOverride", ctypes.c_uint32), ("timing", NV_TIMING)]


class PATH_TARGET_INFO(ctypes.Structure):
    _fields_ = [("displayId", ctypes.c_uint32), ("details", ctypes.POINTER(ADVANCED_TARGET_INFO)),
                ("targetId", ctypes.c_uint32)]


class SOURCE_MODE_INFO(ctypes.Structure):
    _fields_ = [("width", ctypes.c_uint32), ("height", ctypes.c_uint32), ("colorDepth", ctypes.c_uint32),
                ("colorFormat", ctypes.c_uint32), ("x", ctypes.c_int32), ("y", ctypes.c_int32),
                ("spanningOrientation", ctypes.c_uint32), ("flags", ctypes.c_uint32)]


class PATH_INFO(ctypes.Structure):
    _fields_ = [("version", ctypes.c_uint32), ("sourceId", ctypes.c_uint32), ("targetInfoCount", ctypes.c_uint32),
                ("targetInfo", ctypes.POINTER(PATH_TARGET_INFO)), ("sourceModeInfo", ctypes.POINTER(SOURCE_MODE_INFO)),
                ("flags", ctypes.c_uint32), ("pOSAdapterID", ctypes.c_void_p)]


def _ver(struct, v):
    return ctypes.sizeof(struct) | (v << 16)


@dataclass
class NvTarget:
    display_id: int
    width: int
    height: int
    x: int
    y: int
    scaling: int

    @property
    def scaling_name(self):
        return SCALING_NAMES.get(self.scaling, f"mode {self.scaling}")

    @property
    def stretches(self):
        return self.scaling in STRETCHING


class NvApi:
    def __init__(self):
        dll = ctypes.CDLL("nvapi64.dll")             # raises OSError on PCs without an NVIDIA driver
        query = dll.nvapi_QueryInterface
        query.restype = ctypes.c_void_p
        query.argtypes = [ctypes.c_uint32]

        def fn(fid, *args):
            ptr = query(fid)
            if not ptr:
                raise OSError(f"NVAPI function {fid:#x} not available")
            return ctypes.CFUNCTYPE(ctypes.c_int, *args)(ptr)

        self._init = fn(ID_INITIALIZE)
        self._get = fn(ID_GET_DISPLAY_CONFIG, ctypes.POINTER(ctypes.c_uint32), ctypes.POINTER(PATH_INFO))
        self._set = fn(ID_SET_DISPLAY_CONFIG, ctypes.c_uint32, ctypes.POINTER(PATH_INFO), ctypes.c_uint32)
        self._timing = fn(ID_GET_TIMING, ctypes.c_uint32, ctypes.POINTER(TIMING_INPUT), ctypes.POINTER(NV_TIMING))
        self._try = fn(ID_TRY_CUSTOM_DISPLAY, ctypes.POINTER(ctypes.c_uint32), ctypes.c_uint32,
                       ctypes.POINTER(CUSTOM_DISPLAY))
        self._save = fn(ID_SAVE_CUSTOM_DISPLAY, ctypes.POINTER(ctypes.c_uint32), ctypes.c_uint32, ctypes.c_uint32,
                        ctypes.c_uint32)
        self._revert = fn(ID_REVERT_CUSTOM_TRIAL, ctypes.POINTER(ctypes.c_uint32), ctypes.c_uint32)
        rc = self._init()
        if rc != NVAPI_OK:
            raise OSError(f"NVAPI couldn't start (error {rc})")

    def _read(self):
        count = ctypes.c_uint32(0)
        rc = self._get(ctypes.byref(count), None)
        if rc != NVAPI_OK:
            raise OSError(f"NvAPI_DISP_GetDisplayConfig failed ({rc})")
        paths = (PATH_INFO * count.value)()
        for p in paths:
            p.version = _ver(PATH_INFO, 2)
        rc = self._get(ctypes.byref(count), paths)
        if rc != NVAPI_OK:
            raise OSError(f"NvAPI_DISP_GetDisplayConfig (pass 2) failed ({rc})")
        keep = []
        for p in paths:
            targets = (PATH_TARGET_INFO * max(1, p.targetInfoCount))()
            for t in targets:
                details = ADVANCED_TARGET_INFO()
                details.version = _ver(ADVANCED_TARGET_INFO, 1)
                keep.append(details)
                t.details = ctypes.pointer(details)
            source = SOURCE_MODE_INFO()
            keep += [targets, source]
            p.targetInfo = ctypes.cast(targets, ctypes.POINTER(PATH_TARGET_INFO))
            p.sourceModeInfo = ctypes.pointer(source)
        rc = self._get(ctypes.byref(count), paths)
        if rc != NVAPI_OK:
            raise OSError(f"NvAPI_DISP_GetDisplayConfig (pass 3) failed ({rc})")
        return count.value, paths, keep

    def targets(self):
        _, paths, _keep = self._read()
        found = []
        for p in paths:
            s = p.sourceModeInfo.contents
            for i in range(p.targetInfoCount):
                t = p.targetInfo[i]
                found.append(NvTarget(t.displayId, s.width, s.height, s.x, s.y, t.details.contents.scaling))
        return found

    def set_scaling(self, scaling, x=None, y=None, flags=SAVE_TO_PERSISTENCE | FORCE_MODE_ENUMERATION):
        """Set the scaling mode for the screen whose desktop starts at (x, y) - or every NVIDIA screen.
        FORCE_MODE_ENUMERATION also makes Windows re-read the mode list (new custom resolutions appear)."""
        count, paths, _keep = self._read()
        changed = 0
        for p in paths:
            s = p.sourceModeInfo.contents
            if x is not None and (s.x, s.y) != (x, y):
                continue
            for i in range(p.targetInfoCount):
                p.targetInfo[i].details.contents.scaling = scaling
                changed += 1
        if not changed:
            return False
        rc = self._set(count, paths, flags)
        if rc != NVAPI_OK:
            raise OSError(f"NvAPI_DISP_SetDisplayConfig failed ({rc})")
        return True


    def add_custom_resolution(self, display_id, width, height, hz):
        """Same as NVIDIA Control Panel > Change resolution > Customize > Create Custom Resolution > Test > Save.
        The screen switches to the new mode for a moment while the driver tests it."""
        tin = TIMING_INPUT(version=_ver(TIMING_INPUT, 1), width=width, height=height, rr=float(hz),
                           type=TIMING_CVT_RB)
        timing = NV_TIMING()
        rc = self._timing(display_id, ctypes.byref(tin), ctypes.byref(timing))
        if rc != NVAPI_OK:
            raise OSError(f"NVIDIA couldn't calculate a timing for {width} x {height} @ {hz} Hz (error {rc})")
        custom = CUSTOM_DISPLAY(version=_ver(CUSTOM_DISPLAY, 1), width=width, height=height, depth=32,
                                srcX=0.0, srcY=0.0, srcW=1.0, srcH=1.0, xRatio=1.0, yRatio=1.0, timing=timing)
        ids = (ctypes.c_uint32 * 1)(display_id)
        rc = self._try(ids, 1, ctypes.byref(custom))
        if rc != NVAPI_OK:
            self._revert(ids, 1)
            raise OSError(f"NVIDIA rejected {width} x {height} @ {hz} Hz (error {rc})")
        rc = self._save(ids, 1, 1, 1)
        if rc != NVAPI_OK:
            self._revert(ids, 1)
            raise OSError(f"NVIDIA couldn't save {width} x {height} @ {hz} Hz (error {rc})")
        return True

    def display_id_at(self, x, y):
        for t in self.targets():
            if (t.x, t.y) == (x, y):
                return t.display_id
        return None


def available():
    try:
        NvApi()
        return True
    except OSError:
        return False
