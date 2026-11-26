"""Game Color: stronger, more vivid colours on the game's screen - only while the game is the window in front.

What NVIDIA Control Panel calls "Digital vibrance" and AMD Software calls "Saturation", set through the graphics
driver (NVAPI / AMD Display Library - the same calls those panels make). Nothing touches the game: it is a
setting of the screen, applied when VALORANT comes to the front and put back the moment you alt-tab, close the
game or quit TrueStretch. The level that was there before is written to color.json first, so a crash, a
power cut or a killed TrueStretch can always be undone (the guard process and the next start both do that).
"""

import ctypes
import json
import os
from ctypes import wintypes
from dataclasses import dataclass

from .paths import DATA_DIR, atomic_write_text, log

COLOR_FILE = DATA_DIR / "color.json"

# Strength presets: how far towards the driver's maximum the colour goes (0 = the screen's normal look).
LEVELS = [("light", "Light", 30), ("medium", "Medium", 50), ("strong", "Strong", 70), ("max", "Max", 100)]
LEVEL_PERCENT = {key: pct for key, _, pct in LEVELS}


class ColorError(OSError):
    pass


@dataclass
class Screen:
    backend: str          # "nvidia" | "amd"
    key: str              # how the backend finds this screen again (NVIDIA display name, AMD adapter/display)
    device: str           # Windows device name, \\.\DISPLAYn
    level: int            # the driver's current value
    default: int          # the driver's normal value (NVIDIA 50 %, AMD saturation 100)
    minimum: int
    maximum: int

    @property
    def vendor(self):
        return {"nvidia": "NVIDIA", "amd": "AMD"}.get(self.backend, self.backend)

    @property
    def setting(self):
        return {"nvidia": "digital vibrance", "amd": "saturation"}.get(self.backend, "colour")

    def target(self, percent):
        """Driver value for a strength: 0 % = normal, 100 % = the driver's maximum."""
        percent = max(0, min(100, int(percent)))
        return int(round(self.default + (self.maximum - self.default) * percent / 100))

    def shown(self, value):
        """The value the way the vendor's own panel shows it."""
        return f"{value} %" if self.backend == "nvidia" else str(value)


# ---- NVIDIA (NVAPI) ------------------------------------------------------------------------------------------

NVAPI_OK = 0
NVAPI_END_ENUMERATION = -7
ID_INITIALIZE = 0x0150E828
ID_ENUM_DISPLAY_HANDLE = 0x9ABDD40D
ID_DISPLAY_NAME = 0x22A78B05
ID_GET_DVC_INFO_EX = 0x0E45002D
ID_SET_DVC_LEVEL_EX = 0x4A82C2B1


class NV_DISPLAY_DVC_INFO_EX(ctypes.Structure):
    _fields_ = [("version", ctypes.c_uint32), ("currentLevel", ctypes.c_int32), ("minLevel", ctypes.c_int32),
                ("maxLevel", ctypes.c_int32), ("defaultLevel", ctypes.c_int32)]


def _dvc(level=0):
    return NV_DISPLAY_DVC_INFO_EX(version=ctypes.sizeof(NV_DISPLAY_DVC_INFO_EX) | (1 << 16), currentLevel=level)


class NvidiaColor:
    name = "nvidia"

    def __init__(self):
        dll = ctypes.CDLL("nvapi64.dll")             # OSError on PCs without an NVIDIA driver
        query = dll.nvapi_QueryInterface
        query.restype = ctypes.c_void_p
        query.argtypes = [ctypes.c_uint32]

        def fn(fid, *args):
            ptr = query(fid)
            if not ptr:
                raise ColorError(f"NVAPI function {fid:#x} isn't in this NVIDIA driver")
            return ctypes.CFUNCTYPE(ctypes.c_int, *args)(ptr)

        init = fn(ID_INITIALIZE)
        self._enum = fn(ID_ENUM_DISPLAY_HANDLE, ctypes.c_uint32, ctypes.POINTER(ctypes.c_void_p))
        self._name = fn(ID_DISPLAY_NAME, ctypes.c_void_p, ctypes.c_char * 64)
        self._get = fn(ID_GET_DVC_INFO_EX, ctypes.c_void_p, ctypes.c_uint32, ctypes.POINTER(NV_DISPLAY_DVC_INFO_EX))
        self._set = fn(ID_SET_DVC_LEVEL_EX, ctypes.c_void_p, ctypes.c_uint32, ctypes.POINTER(NV_DISPLAY_DVC_INFO_EX))
        rc = init()
        if rc != NVAPI_OK:
            raise ColorError(f"NVAPI couldn't start (error {rc})")

    def _handles(self):
        """(Windows device name, NVAPI display handle) for every screen wired to the NVIDIA chip. Handles can change
        after a mode switch, so they are looked up again for every call."""
        found = []
        for i in range(16):
            handle = ctypes.c_void_p()
            rc = self._enum(i, ctypes.byref(handle))
            if rc == NVAPI_END_ENUMERATION or rc != NVAPI_OK:
                break
            buf = (ctypes.c_char * 64)()
            if self._name(handle, buf) == NVAPI_OK:
                found.append((buf.value.decode(errors="ignore"), handle))
        return found

    def screens(self):
        out = []
        for device, handle in self._handles():
            info = _dvc()
            if self._get(handle, 0, ctypes.byref(info)) != NVAPI_OK:
                continue
            out.append(Screen("nvidia", device, device, info.currentLevel, info.defaultLevel, info.minLevel,
                              info.maxLevel))
        return out

    def set_level(self, key, level):
        for device, handle in self._handles():
            if device.lower() == key.lower():
                rc = self._set(handle, 0, ctypes.byref(_dvc(int(level))))
                if rc != NVAPI_OK:
                    raise ColorError(f"NVIDIA refused digital vibrance {level} % (error {rc})")
                return
        raise ColorError(f"{key} isn't connected to the NVIDIA graphics any more")


# ---- AMD (ADL) -----------------------------------------------------------------------------------------------

ADL_DISPLAY_COLOR_SATURATION = 1 << 2


class AmdColor:
    name = "amd"

    def __init__(self):
        from .amd import AmdApi
        self.api = AmdApi()                          # OSError on PCs without a Radeon driver

    def _get(self, adapter, disp):
        cur, default, lo, hi, step = (ctypes.c_int() for _ in range(5))
        self.api._call("ADL_Display_Color_Get", adapter, disp, ADL_DISPLAY_COLOR_SATURATION, ctypes.byref(cur),
                       ctypes.byref(default), ctypes.byref(lo), ctypes.byref(hi), ctypes.byref(step))
        return cur.value, default.value, lo.value, hi.value

    def screens(self):
        out = []
        for d in self.api.displays():
            try:
                cur, default, lo, hi = self._get(d.adapter, d.display)
            except OSError as exc:
                log.info("AMD saturation unavailable on %s: %s", d.device, exc)
                continue
            if hi > lo:
                out.append(Screen("amd", f"{d.adapter}:{d.display}", d.device, cur, default, lo, hi))
        return out

    def set_level(self, key, level):
        adapter, disp = (int(x) for x in key.split(":"))
        self.api._call("ADL_Display_Color_Set", adapter, disp, ADL_DISPLAY_COLOR_SATURATION, int(level))


BACKENDS = (NvidiaColor, AmdColor)


def backend(name):
    for cls in BACKENDS:
        if cls.name == name:
            return cls()
    raise ColorError(f"unknown colour backend {name}")


def find_screen(device):
    """The Screen for a Windows device name, or (None, reason in words)."""
    reasons = []
    for cls in BACKENDS:
        try:
            api = cls()
            screens = api.screens()
        except OSError as exc:
            reasons.append(str(exc))
            continue
        for s in screens:
            if not device or s.device.lower() == device.lower():
                return api, s, None
    return None, None, ("This screen is connected to graphics that don't offer a colour boost (Game Color works "
                        "with NVIDIA and AMD graphics; on laptops the built-in screen often runs on the Intel "
                        "chip).")


# ---- which window is in front --------------------------------------------------------------------------------

_user32 = ctypes.WinDLL("user32", use_last_error=True)
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_user32.GetForegroundWindow.restype = wintypes.HWND
_user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
_kernel32.OpenProcess.restype = wintypes.HANDLE
_kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
_kernel32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
                                                 ctypes.POINTER(wintypes.DWORD)]
_kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_front_cache = {}


def foreground_exe():
    """Lower-case exe name of the window in front, or None (desktop, lock screen, no access)."""
    hwnd = _user32.GetForegroundWindow()
    if not hwnd:
        return None
    pid = wintypes.DWORD()
    _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    if not pid.value:
        return None
    cached = _front_cache.get(hwnd)
    if cached and cached[0] == pid.value:
        return cached[1]
    name = None
    handle = _kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
    if handle:
        try:
            buf = ctypes.create_unicode_buffer(32768)
            size = wintypes.DWORD(len(buf))
            if _kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
                name = os.path.basename(buf.value).lower()
        finally:
            _kernel32.CloseHandle(handle)
    if len(_front_cache) > 64:
        _front_cache.clear()
    _front_cache[hwnd] = (pid.value, name)
    return name


# ---- the saved "before" level --------------------------------------------------------------------------------

def read_saved():
    try:
        data = json.loads(COLOR_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as exc:
        log.warning("color.json unreadable: %s", exc)
        return {}


def write_saved(data):
    atomic_write_text(COLOR_FILE, json.dumps(data, indent=2))


def clear_saved():
    try:
        COLOR_FILE.unlink()
    except FileNotFoundError:
        pass


def restore_saved(only_owner=None, make=backend):
    """Put back the level stored in color.json. only_owner: only when that process applied it (the guard).
    Returns True when something was restored. The file is removed only once the restore worked."""
    data = read_saved()
    if not data.get("backend"):
        return False
    if only_owner is not None and int(data.get("owner") or 0) != int(only_owner):
        return False
    try:
        make(data["backend"]).set_level(data["key"], int(data["previous"]))
    except (OSError, KeyError, ValueError) as exc:
        log.warning("Couldn't put the colour back on %s: %s", data.get("device"), exc)
        return False
    clear_saved()
    log.info("Game Color: %s back to %s", data.get("device"), data.get("previous"))
    return True


class GameColor:
    """Turns the colour boost on while the game window is in front and off otherwise. tick() is called from the
    engine's half-second poll; every driver call is skipped when nothing changed."""

    def __init__(self, find=find_screen, make=backend, front=foreground_exe):
        self._find, self._make, self._front = find, make, front
        self.applied = None           # dict like color.json while the boost is on
        self.failed = None            # (device, reason) after an error: don't retry every half second
        self.preview_until = 0.0

    def recover(self):
        """At start: a boost left behind by a crash or power cut goes back to the stored level."""
        return restore_saved(make=self._make)

    def tick(self, enabled, percent, device, game_exes, now=None):
        """Returns a sentence when Game Color just stopped working (shown once), else None."""
        want = bool(enabled) and self._front() in game_exes
        if now is not None and now < self.preview_until:
            want = True
        if want and self.failed and self.failed[0] == device:
            want = False
        try:
            if not want:
                self.off()
            elif self.applied and self.applied["device"].lower() == (device or "").lower():
                target = self._target_for(percent)
                if target != self.applied["target"]:
                    self._make(self.applied["backend"]).set_level(self.applied["key"], target)
                    self.applied.update(target=target, percent=percent)
                    write_saved(self.applied)
            else:
                self.off()
                self.on(percent, device)
        except OSError as exc:
            self.failed = (device, str(exc))
            log.warning("Game Color stopped: %s", exc)
            self.off()
            return str(exc)
        return None

    def preview(self, now, seconds=4.0):
        self.failed = None
        self.preview_until = now + seconds

    def _target_for(self, percent):
        a = self.applied
        return int(round(a["default"] + (a["maximum"] - a["default"]) * max(0, min(100, int(percent))) / 100))

    def on(self, percent, device):
        api, screen, reason = self._find(device)
        if not screen:
            raise ColorError(reason)
        target = screen.target(percent)
        previous = screen.level
        saved = read_saved()                        # a restore that failed earlier: the true original is there
        if saved.get("backend") == screen.backend and saved.get("key") == screen.key and "previous" in saved:
            previous = int(saved["previous"])
        self.applied = {"backend": screen.backend, "key": screen.key, "device": screen.device,
                        "previous": previous, "default": screen.default, "maximum": screen.maximum,
                        "target": target, "percent": percent, "owner": os.getpid()}
        write_saved(self.applied)                   # the way back is on disk before anything changes
        api.set_level(screen.key, target)
        log.info("Game Color on: %s %s %s -> %s", screen.device, screen.setting, screen.level, target)

    def off(self):
        if not self.applied:
            return False
        a, self.applied = self.applied, None
        try:
            self._make(a["backend"]).set_level(a["key"], a["previous"])
            clear_saved()
            log.info("Game Color off: %s back to %s", a["device"], a["previous"])
        except OSError as exc:
            log.warning("Couldn't put the colour back on %s: %s (kept in color.json for the next try)",
                        a["device"], exc)
            return False
        return True
