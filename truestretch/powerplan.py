"""The active Windows power plan, read and written through powrprof.dll (PowerReadACValueIndex and friends).

Until 2.2.0 the power rows of Optimize Max parsed the text of `powercfg /qh`, looking for the English line
"Current AC Power Setting Index". powercfg translates that line, so on every non-English Windows (Portuguese,
Turkish, Russian, Spanish ...) the rows said "Not in this power plan" and could never be optimized. The API below
returns numbers, in any language. Only the "plugged in" (AC) values of the active plan are touched."""

import ctypes
import uuid
from ctypes import wintypes

# powercfg's aliases (`powercfg /aliases`; the hidden ones from `powercfg /qh`). A raw GUID string is accepted too.
ALIASES = {
    "SUB_PROCESSOR": "54533251-82be-4824-96c1-47b60b740d00",
    "PROCTHROTTLEMIN": "893dee8e-2bef-41e0-89c6-b55d0929964c",
    "PERFBOOSTMODE": "be337238-0d82-4146-a960-4f3749d470c7",
    "CPMINCORES": "0cc5b647-c1df-4637-891a-dec35c318583",
    "SUB_PCIEXPRESS": "501a4d13-42af-4429-9fd1-a8218c268e20",
    "ASPM": "ee12f906-d277-404b-b6da-e5fa1a576df5",
}

ERROR_SUCCESS, ERROR_FILE_NOT_FOUND, ERROR_ACCESS_DENIED = 0, 2, 5


class GUID(ctypes.Structure):
    _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD), ("Data3", wintypes.WORD),
                ("Data4", ctypes.c_ubyte * 8)]

    @classmethod
    def of(cls, value):
        return cls.from_buffer_copy(as_uuid(value).bytes_le)

    def uuid(self):
        return uuid.UUID(bytes_le=bytes(self))


def as_uuid(value):
    """A powercfg alias, a GUID string or a uuid.UUID → uuid.UUID."""
    if isinstance(value, uuid.UUID):
        return value
    text = ALIASES.get(str(value).upper(), str(value))
    return uuid.UUID(text)


try:
    powrprof = ctypes.WinDLL("powrprof", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    powrprof.PowerGetActiveScheme.argtypes = [wintypes.HKEY, ctypes.POINTER(ctypes.POINTER(GUID))]
    powrprof.PowerGetActiveScheme.restype = wintypes.DWORD
    for _fn in (powrprof.PowerReadACValueIndex, powrprof.PowerReadDCValueIndex):
        _fn.argtypes = [wintypes.HKEY, ctypes.POINTER(GUID), ctypes.POINTER(GUID), ctypes.POINTER(GUID),
                        ctypes.POINTER(wintypes.DWORD)]
        _fn.restype = wintypes.DWORD
    powrprof.PowerWriteACValueIndex.argtypes = [wintypes.HKEY, ctypes.POINTER(GUID), ctypes.POINTER(GUID),
                                                ctypes.POINTER(GUID), wintypes.DWORD]
    powrprof.PowerWriteACValueIndex.restype = wintypes.DWORD
    powrprof.PowerSetActiveScheme.argtypes = [wintypes.HKEY, ctypes.POINTER(GUID)]
    powrprof.PowerSetActiveScheme.restype = wintypes.DWORD
    kernel32.LocalFree.argtypes = [wintypes.HLOCAL]
    kernel32.LocalFree.restype = wintypes.HLOCAL
except (OSError, AttributeError):          # not Windows (docs builds, linting): every call below reports None
    powrprof = None


def active_scheme():
    """uuid.UUID of the active power plan, or None if Windows won't say."""
    if powrprof is None:
        return None
    ptr = ctypes.POINTER(GUID)()
    if powrprof.PowerGetActiveScheme(None, ctypes.byref(ptr)) != ERROR_SUCCESS or not ptr:
        return None
    try:
        return ptr.contents.uuid()
    finally:
        kernel32.LocalFree(ctypes.cast(ptr, wintypes.HLOCAL))


def _read(fn, sub, setting, scheme=None):
    scheme = scheme or active_scheme()
    if powrprof is None or scheme is None:
        return None
    value = wintypes.DWORD()
    rc = fn(None, ctypes.byref(GUID.of(scheme)), ctypes.byref(GUID.of(sub)), ctypes.byref(GUID.of(setting)),
            ctypes.byref(value))
    return value.value if rc == ERROR_SUCCESS else None


def read_ac(sub, setting, scheme=None):
    """The "plugged in" index of one setting in the active plan, or None when the plan doesn't have it
    (ERROR_FILE_NOT_FOUND - e.g. the Wi-Fi group on a PC without Wi-Fi)."""
    return _read(powrprof.PowerReadACValueIndex if powrprof else None, sub, setting, scheme)


def read_dc(sub, setting, scheme=None):
    """The "on battery" index (read only; TrueStretch never changes battery values)."""
    return _read(powrprof.PowerReadDCValueIndex if powrprof else None, sub, setting, scheme)


def write_ac(sub, setting, value, scheme=None):
    """Sets the "plugged in" index and makes the plan re-read it (what `powercfg /setacvalueindex` +
    `powercfg /setactive SCHEME_CURRENT` did). Raises OSError with the Windows error code."""
    if powrprof is None:
        raise OSError("powrprof is not available on this system")
    scheme = scheme or active_scheme()
    if scheme is None:
        raise OSError("Windows reported no active power plan")
    scheme_guid = GUID.of(scheme)
    rc = powrprof.PowerWriteACValueIndex(None, ctypes.byref(scheme_guid), ctypes.byref(GUID.of(sub)),
                                         ctypes.byref(GUID.of(setting)), int(value))
    if rc != ERROR_SUCCESS:
        raise OSError(rc, "Windows refused to change the power plan"
                      + (" (administrator permission needed)" if rc == ERROR_ACCESS_DENIED else f" (error {rc})"))
    rc = powrprof.PowerSetActiveScheme(None, ctypes.byref(scheme_guid))
    if rc != ERROR_SUCCESS:
        raise OSError(rc, f"The power plan was changed but couldn't be re-applied (error {rc})")
