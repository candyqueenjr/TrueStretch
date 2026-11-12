"""AMD graphics through the AMD Display Library (atiadlxx.dll, installed with every Radeon driver): add a custom
resolution and set scaling to Full panel - what AMD Software (Adrenalin) does by hand.
Raises OSError when the library or the screen isn't there."""

import ctypes
from ctypes import POINTER, byref, c_char, c_int, c_void_p

from .paths import log

ADL_OK = 0
ADL_MAX_PATH = 256
DISPLAY_CONNECTED, DISPLAY_MAPPED = 0x1, 0x2
MODE_SUPPORTED = 1 << 0


class _AdapterInfo(ctypes.Structure):
    _fields_ = [("iSize", c_int), ("iAdapterIndex", c_int), ("strUDID", c_char * ADL_MAX_PATH),
                ("iBusNumber", c_int), ("iDeviceNumber", c_int), ("iFunctionNumber", c_int), ("iVendorID", c_int),
                ("strAdapterName", c_char * ADL_MAX_PATH), ("strDisplayName", c_char * ADL_MAX_PATH),
                ("iPresent", c_int), ("iExist", c_int), ("strDriverPath", c_char * ADL_MAX_PATH),
                ("strDriverPathExt", c_char * ADL_MAX_PATH), ("strPNPString", c_char * ADL_MAX_PATH),
                ("iOSDisplayIndex", c_int)]


class _DisplayID(ctypes.Structure):
    _fields_ = [("iDisplayLogicalIndex", c_int), ("iDisplayPhysicalIndex", c_int),
                ("iDisplayLogicalAdapterIndex", c_int), ("iDisplayPhysicalAdapterIndex", c_int)]


class _DisplayInfo(ctypes.Structure):
    _fields_ = [("displayID", _DisplayID), ("iDisplayControllerIndex", c_int),
                ("strDisplayName", c_char * ADL_MAX_PATH), ("strDisplayManufacturerName", c_char * ADL_MAX_PATH),
                ("iDisplayType", c_int), ("iDisplayOutputType", c_int), ("iDisplayConnector", c_int),
                ("iDisplayInfoMask", c_int), ("iDisplayInfoValue", c_int)]


class _CustomMode(ctypes.Structure):
    _fields_ = [("iFlags", c_int), ("iModeWidth", c_int), ("iModeHeight", c_int), ("iBaseModeWidth", c_int),
                ("iBaseModeHeight", c_int), ("iRefreshRate", c_int)]


_MALLOC = ctypes.CFUNCTYPE(c_void_p, c_int)
_keep = []                                     # the allocator must outlive every ADL call


@_MALLOC
def _adl_malloc(size):
    buf = ctypes.create_string_buffer(size)
    _keep.append(buf)
    return ctypes.addressof(buf)


class AmdDisplay:
    def __init__(self, adapter, display, device):
        self.adapter, self.display, self.device = adapter, display, device

    def __repr__(self):
        return f"AmdDisplay({self.device}, adapter={self.adapter}, display={self.display})"


class AmdApi:
    def __init__(self):
        dll = None
        for name in ("atiadlxx.dll", "atiadlxy.dll"):
            try:
                dll = ctypes.CDLL(name)
                break
            except OSError:
                continue
        if dll is None:
            raise OSError("AMD Display Library isn't installed (no Radeon driver)")
        self.dll = dll
        self._call("ADL_Main_Control_Create", _adl_malloc, 1)

    def _call(self, name, *args):
        fn = getattr(self.dll, name, None)
        if fn is None:
            raise OSError(f"{name} isn't in this AMD driver")
        fn.restype = c_int
        result = fn(*args)
        if result != ADL_OK and result != 1:            # 1 = ADL_OK_WARNING
            raise OSError(f"{name} failed ({result})", result)
        return result

    def close(self):
        try:
            self.dll.ADL_Main_Control_Destroy()
        except Exception:
            pass

    def displays(self):
        count = c_int(0)
        self._call("ADL_Adapter_NumberOfAdapters_Get", byref(count))
        if count.value <= 0:
            return []
        infos = (_AdapterInfo * count.value)()
        for info in infos:
            info.iSize = ctypes.sizeof(_AdapterInfo)
        self._call("ADL_Adapter_AdapterInfo_Get", infos, ctypes.sizeof(infos))
        found, seen = [], set()
        for info in infos:
            device = info.strDisplayName.decode(errors="ignore")
            if not info.iPresent or not device:
                continue
            num, ptr = c_int(0), POINTER(_DisplayInfo)()
            try:
                self._call("ADL_Display_DisplayInfo_Get", info.iAdapterIndex, byref(num), byref(ptr), 0)
            except OSError:
                continue
            for i in range(num.value):
                d = ptr[i]
                wanted = DISPLAY_CONNECTED | DISPLAY_MAPPED
                if (d.iDisplayInfoValue & wanted) != wanted:
                    continue
                if d.displayID.iDisplayLogicalAdapterIndex != info.iAdapterIndex:
                    continue
                key = (info.iAdapterIndex, d.displayID.iDisplayLogicalIndex)
                if key not in seen:
                    seen.add(key)
                    found.append(AmdDisplay(info.iAdapterIndex, d.displayID.iDisplayLogicalIndex, device))
        return found

    def display_for(self, device):
        return next((d for d in self.displays() if d.device.lower() == (device or "").lower()), None)

    def custom_modes(self, disp):
        n = c_int(0)
        self._call("ADL_Display_CustomizedModeListNum_Get", disp.adapter, disp.display, byref(n))
        if n.value <= 0:
            return []
        modes = (_CustomMode * n.value)()
        self._call("ADL_Display_CustomizedModeList_Get", disp.adapter, disp.display, modes, ctypes.sizeof(modes))
        return [(m.iModeWidth, m.iModeHeight, m.iRefreshRate) for m in modes]

    def add_custom_mode(self, disp, width, height, hz, base_width, base_height):
        """Adds width x height, scaled by the GPU from the screen's own base mode. True when added."""
        if any((w, h) == (width, height) for w, h, _ in self.custom_modes(disp)):
            return False
        mode = _CustomMode(MODE_SUPPORTED, width, height, base_width, base_height, int(hz))
        valid = c_int(0)
        try:
            self._call("ADL_Display_CustomizedMode_Validate", disp.adapter, disp.display, mode, byref(valid))
        except OSError:
            valid.value = 1                                  # older drivers: just try
        if not valid.value:
            raise OSError(f"the AMD driver won't accept {width} x {height}")
        self._call("ADL_Display_CustomizedMode_Add", disp.adapter, disp.display, mode)
        log.info("AMD: custom resolution %sx%s@%s added", width, height, hz)
        return True

    def full_panel(self, disp):
        """Scaling mode = Full panel (stretch, no black bars)."""
        changed = False
        for name, value in (("ADL_Display_PreservedAspectRatio_Set", 0), ("ADL_Display_ImageExpansion_Set", 1)):
            try:
                self._call(name, disp.adapter, disp.display, value)
                changed = True
            except OSError as exc:
                log.info("AMD: %s", exc)
        return changed
