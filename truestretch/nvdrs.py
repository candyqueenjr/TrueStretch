"""NVIDIA driver profile settings (what NVIDIA Control Panel > Manage 3D settings > Program settings changes), through
NVAPI's DRS functions. Only VALORANT's own program profile is changed - never the global profile. IDs and values are
from NVIDIA's public nvapi.h / NvApiDriverSettings.h."""

import ctypes
from ctypes import POINTER, byref, c_int, c_uint16, c_uint32, c_uint8, c_void_p

NVAPI_OK = 0
SETTING_NOT_FOUND = -160
PROFILE_NOT_FOUND = -163
EXECUTABLE_NOT_FOUND = -166

PREFERRED_PSTATE = 0x1057EB71            # Power management mode
PSTATE_PREFER_MAX, PSTATE_OPTIMAL = 0x1, 0x5
QUALITY_ENHANCEMENTS = 0x00CE2691        # Texture filtering - Quality
TEXTURE_HIGH_PERFORMANCE, TEXTURE_QUALITY = 0x14, 0x0
VSYNCMODE = 0x00A879CF                   # Vertical sync
VSYNC_FORCE_OFF, VSYNC_APP = 0x08416747, 0x60925292

LOCATION_NAMES = {0: "VALORANT's profile", 1: "global profile", 2: "base profile", 3: "driver default"}
UString = c_uint16 * 2048


class _Binary(ctypes.Structure):
    _fields_ = [("valueLength", c_uint32), ("valueData", c_uint8 * 4096)]


class _Value(ctypes.Union):
    # Drivers accept the 12,320-byte NVDRS_SETTING_V1 (no 64-bit member, 4-byte packing); the newer header's
    # QWORD member makes it 12,328 bytes, which drivers reject with NVAPI_INCOMPATIBLE_STRUCT_VERSION.
    _pack_ = 4
    _fields_ = [("u32", c_uint32), ("binary", _Binary), ("wsz", UString)]


class SETTING(ctypes.Structure):
    _pack_ = 4
    _fields_ = [("version", c_uint32), ("settingName", UString), ("settingId", c_uint32), ("settingType", c_uint32),
                ("settingLocation", c_uint32), ("isCurrentPredefined", c_uint32), ("isPredefinedValid", c_uint32),
                ("predefined", _Value), ("current", _Value)]


class APPLICATION(ctypes.Structure):          # NVDRS_APPLICATION_V1
    _fields_ = [("version", c_uint32), ("isPredefined", c_uint32), ("appName", UString),
                ("userFriendlyName", UString), ("launcher", UString)]


class PROFILE(ctypes.Structure):              # NVDRS_PROFILE_V1
    _fields_ = [("version", c_uint32), ("profileName", UString), ("gpuSupport", c_uint32), ("isPredefined", c_uint32),
                ("numOfApps", c_uint32), ("numOfSettings", c_uint32)]


def _ver(struct, v=1):
    return ctypes.sizeof(struct) | (v << 16)


def _ustr(text):
    buf = UString()
    for i, ch in enumerate(text[:2047]):
        buf[i] = ord(ch)
    return buf


class DrsError(OSError):
    pass


class Drs:
    """One session: `with Drs() as d: d.get(...)`. Raises DrsError/OSError without an NVIDIA driver."""

    def __init__(self):
        dll = ctypes.CDLL("nvapi64.dll")
        query = dll.nvapi_QueryInterface
        query.restype = c_void_p
        query.argtypes = [c_uint32]

        def fn(fid, *args):
            ptr = query(fid)
            if not ptr:
                raise DrsError(f"NVAPI function {fid:#x} not available")
            return ctypes.CFUNCTYPE(c_int, *args)(ptr)

        fn(0x0150E828)()                                          # NvAPI_Initialize
        self._create = fn(0x0694D52E, POINTER(c_void_p))
        self._destroy = fn(0xDAD9CFF8, c_void_p)
        self._load = fn(0x375DBD6B, c_void_p)
        self._save = fn(0xFCBC7E14, c_void_p)
        self._find_app = fn(0xEEE566B2, c_void_p, POINTER(UString), POINTER(c_void_p), POINTER(APPLICATION))
        self._find_profile = fn(0x7E4A9A0B, c_void_p, POINTER(UString), POINTER(c_void_p))
        self._create_profile = fn(0xCC176068, c_void_p, POINTER(PROFILE), POINTER(c_void_p))
        self._create_app = fn(0x4347A9DE, c_void_p, c_void_p, POINTER(APPLICATION))
        self._get = fn(0x73BF8338, c_void_p, c_void_p, c_uint32, POINTER(SETTING))
        self._set = fn(0x577DD202, c_void_p, c_void_p, POINTER(SETTING))
        self._delete = fn(0xE4A26362, c_void_p, c_void_p, c_uint32)
        self.session = c_void_p()
        self._check(self._create(byref(self.session)), "CreateSession")
        self._check(self._load(self.session), "LoadSettings")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def close(self):
        if self.session:
            self._destroy(self.session)
            self.session = c_void_p()

    @staticmethod
    def _check(status, what):
        if status != NVAPI_OK:
            raise DrsError(f"NVIDIA {what} failed ({status})", status)

    def app_profile(self, exe_name, create_as=None):
        """The profile VALORANT's .exe belongs to. With create_as, makes one if the driver has none."""
        app = APPLICATION()
        app.version = _ver(APPLICATION)
        handle = c_void_p()
        name = _ustr(exe_name)
        status = self._find_app(self.session, byref(name), byref(handle), byref(app))
        if status == NVAPI_OK:
            return handle
        if status != EXECUTABLE_NOT_FOUND or not create_as:
            self._check(status, "FindApplicationByName")
        pname = _ustr(create_as)
        status = self._find_profile(self.session, byref(pname), byref(handle))
        if status == PROFILE_NOT_FOUND:
            prof = PROFILE()
            prof.version = _ver(PROFILE)
            prof.profileName = pname
            self._check(self._create_profile(self.session, byref(prof), byref(handle)), "CreateProfile")
        else:
            self._check(status, "FindProfileByName")
        new_app = APPLICATION()
        new_app.version = _ver(APPLICATION)
        new_app.appName = _ustr(exe_name)
        new_app.userFriendlyName = _ustr(create_as)
        self._check(self._create_app(self.session, handle, byref(new_app)), "CreateApplication")
        return handle

    def get(self, profile, setting_id):
        """(value, location) - location 0 means it's set on this profile itself. None if the driver has no value."""
        s = SETTING()
        s.version = _ver(SETTING)
        status = self._get(self.session, profile, setting_id, byref(s))
        if status == SETTING_NOT_FOUND:
            return None, None
        self._check(status, "GetSetting")
        return s.current.u32, s.settingLocation

    def set(self, profile, setting_id, value):
        s = SETTING()
        s.version = _ver(SETTING)
        s.settingId = setting_id
        s.settingType = 0                           # NVDRS_DWORD_TYPE
        s.current.u32 = value
        self._check(self._set(self.session, profile, byref(s)), "SetSetting")

    def delete(self, profile, setting_id):
        status = self._delete(self.session, profile, setting_id)
        if status not in (NVAPI_OK, SETTING_NOT_FOUND):
            self._check(status, "DeleteProfileSetting")

    def save(self):
        self._check(self._save(self.session), "SaveSettings")
