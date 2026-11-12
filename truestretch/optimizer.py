"""Optimize Max: scans everything on this PC that affects VALORANT's FPS and input delay, lists every change
separately with what it is now, what it should be and why, applies only what the player picks, checks that each
change actually stuck, and can undo every one of them (the original value is kept the first time).

Only real, reversible settings are included - no "FPS boost" placebo, no security settings, no network hacks."""

import ctypes
import json
import os
import subprocess
import winreg
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from . import display, pcinfo
from .inifile import IniFile, set_read_only
from .paths import DATA_DIR, log
from .system import flag_value, flags_with, reg_delete, reg_get, reg_set, running_processes

UNDO_FILE = DATA_DIR / "optimizer-undo.json"
GAME_EXE = "VALORANT-Win64-Shipping.exe"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

DONE, IMPROVE, INFO, UNAVAILABLE, IN_GAME, OPTIONAL = ("done", "improve", "info", "unavailable", "in_game",
                                                      "optional")
GROUPS = ["Windows", "Windows power", "Graphics card", "VALORANT files", "Startup apps", "Background & overlays",
          "Network", "Mouse", "Inside VALORANT", "Inside AMD Software", "Inside Intel Graphics", "Your PC"]


@dataclass
class Item:
    id: str
    group: str
    title: str
    why: str
    current: str
    target: str
    state: str
    impact: str = ""                  # what it improves: "More FPS", "Lower input delay", ...
    level: int = 1                    # 3 high, 2 medium, 1 low
    note: str = ""                    # caveats: restart, admin, game must be closed
    admin: bool = False
    restart: bool = False
    debug: list = field(default_factory=list)       # technical details for the diagnostics view
    link: str = ""                    # for info items that point somewhere (driver download)
    blocked: str = ""                 # why it can't be applied right now
    _apply: object = None             # callable() - does the change
    _snapshot: object = None          # callable() -> json-able undo data
    _restore: object = None           # callable(data) - puts the original back
    _admin_cmds: list = field(default_factory=list)            # for admin items: cmd lines to run elevated
    _admin_undo: object = None        # callable(data) -> cmd lines

    @property
    def can_apply(self):
        return bool(self.state in (IMPROVE, OPTIONAL) and not self.blocked and (self._apply or self._admin_cmds))


# ---- helpers ---------------------------------------------------------------------------------------------

HKCU, HKLM = winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE
ROOT_NAMES = {HKCU: "HKCU", HKLM: "HKLM"}


def _reg(root, key, name, default=None):
    return reg_get(root, key, name, default)


def _reg_dword(root, key, name, value):
    with winreg.CreateKeyEx(root, key, 0, winreg.KEY_SET_VALUE) as k:
        winreg.SetValueEx(k, name, 0, winreg.REG_DWORD, int(value))


def _reg_snapshot(root, key, *names):
    out = {}
    for n in names:
        try:
            with winreg.OpenKey(root, key) as k:
                value, kind = winreg.QueryValueEx(k, n)
            out[n] = [value, kind]
        except OSError:
            out[n] = None
    return out


def _reg_restore(root, key, data):
    for n, saved in data.items():
        if saved is None:
            reg_delete(root, key, n)
        else:
            with winreg.CreateKeyEx(root, key, 0, winreg.KEY_SET_VALUE) as k:
                winreg.SetValueEx(k, n, 0, saved[1], saved[0])


def _dbg(root, key, name, value):
    return f"{ROOT_NAMES[root]}\\{key} → {name} = {value!r}"


def run_elevated(commands, hwnd=None):
    """Runs cmd lines with one administrator prompt. Returns the exit code; PermissionError if declined."""
    from .monitors import SHELLEXECUTEINFOW
    from ctypes import wintypes
    info = SHELLEXECUTEINFOW()
    info.cbSize = ctypes.sizeof(SHELLEXECUTEINFOW)
    info.fMask = 0x40 | 0x400
    info.hwnd = hwnd
    info.lpVerb = "runas"
    info.lpFile = "cmd.exe"
    info.lpParameters = '/c "' + " & ".join(commands) + '"'
    info.nShow = 0
    if not ctypes.windll.shell32.ShellExecuteExW(ctypes.byref(info)):
        err = ctypes.GetLastError()
        if err == 1223:
            raise PermissionError("Administrator permission was declined.")
        raise OSError(f"Couldn't start the administrator command (error {err}).")
    ctypes.windll.kernel32.WaitForSingleObject(info.hProcess, 60_000)
    code = wintypes.DWORD()
    ctypes.windll.kernel32.GetExitCodeProcess(info.hProcess, ctypes.byref(code))
    ctypes.windll.kernel32.CloseHandle(info.hProcess)
    return code.value


# ---- Windows ---------------------------------------------------------------------------------------------

def _game_mode():
    key, name = r"Software\Microsoft\GameBar", "AutoGameModeEnabled"
    raw = _reg(HKCU, key, name)
    on = raw is None or raw != 0
    return Item("game_mode", "Windows", "Game Mode", "Windows gives the game priority over background work (updates, "
                "indexing) and avoids starting driver installs while you play.",
                "On" if on else "Off", "On", DONE if on else IMPROVE, "Steadier FPS", 2,
                debug=[_dbg(HKCU, key, name, raw)],
                _apply=lambda: _reg_dword(HKCU, key, name, 1),
                _snapshot=lambda: _reg_snapshot(HKCU, key, name),
                _restore=lambda d: _reg_restore(HKCU, key, d))


def _game_dvr():
    k1, n1 = r"System\GameConfigStore", "GameDVR_Enabled"
    k2, n2 = r"Software\Microsoft\Windows\CurrentVersion\GameDVR", "AppCaptureEnabled"
    v1, v2 = _reg(HKCU, k1, n1), _reg(HKCU, k2, n2)
    on = (v1 is None or v1 != 0) or (v2 is not None and v2 != 0)

    def apply():
        _reg_dword(HKCU, k1, n1, 0)
        _reg_dword(HKCU, k2, n2, 0)

    return Item("game_dvr", "Windows", "Xbox Game Bar background recording",
                "Game Bar can keep recording the last minutes of gameplay in the background. That costs FPS and adds "
                "a little delay. Screenshots with Win+Alt+PrtScn keep working.",
                "On" if on else "Off", "Off", IMPROVE if on else DONE, "More FPS", 2,
                debug=[_dbg(HKCU, k1, n1, v1), _dbg(HKCU, k2, n2, v2)], _apply=apply,
                _snapshot=lambda: {"a": _reg_snapshot(HKCU, k1, n1), "b": _reg_snapshot(HKCU, k2, n2)},
                _restore=lambda d: (_reg_restore(HKCU, k1, d["a"]), _reg_restore(HKCU, k2, d["b"])))


class GUID(ctypes.Structure):
    _fields_ = [("Data1", ctypes.c_uint32), ("Data2", ctypes.c_uint16), ("Data3", ctypes.c_uint16),
                ("Data4", ctypes.c_uint8 * 8)]

    @classmethod
    def parse(cls, text):
        import uuid
        u = uuid.UUID(text)
        g = cls(u.fields[0], u.fields[1], u.fields[2])
        for i, b in enumerate(u.bytes[8:]):
            g.Data4[i] = b
        return g

    def __str__(self):
        import uuid
        return str(uuid.UUID(bytes_le=bytes(self)))


BEST_PERFORMANCE = "ded574b5-45a0-4f42-8737-46345c09c238"


def _overlay_get():
    g = GUID()
    if ctypes.windll.powrprof.PowerGetActualOverlayScheme(ctypes.byref(g)) != 0:
        raise OSError("power mode unavailable")
    return str(g)


def _overlay_set(text):
    fn = ctypes.windll.powrprof.PowerSetActiveOverlayScheme
    fn.argtypes = [GUID]
    if fn(GUID.parse(text)) != 0:
        raise OSError("Windows didn't accept the power mode")


def _power(pc):
    plan = (pc.power_plan or "")
    if plan in ("High performance", "Ultimate performance"):
        return Item("power", "Windows", "Power mode", "Windows runs the processor and graphics at full speed instead of "
                    "saving power.", plan, "Best performance", DONE, "More FPS", 3, debug=[f"power plan: {plan}"])
    try:
        current = _overlay_get()
    except (OSError, AttributeError) as exc:
        return Item("power", "Windows", "Power mode", "Windows runs at full speed instead of saving power.",
                    plan or "Unknown", "Best performance", UNAVAILABLE, "More FPS", 3,
                    note="This version of Windows has no power mode slider.", debug=[str(exc)])
    name = pcinfo.POWER_MODES.get(current.lower(), current)
    ok = current.lower() == BEST_PERFORMANCE
    return Item("power", "Windows", "Power mode", "Windows runs the processor and graphics card at full speed "
                "instead of saving power. The biggest single FPS gain on most laptops.",
                name, "Best performance", DONE if ok else IMPROVE, "More FPS", 3,
                note="Applies to the current power source (plugged in or battery).",
                debug=[f"plan: {plan}", f"power mode overlay: {name}"],
                _apply=lambda: _overlay_set(BEST_PERFORMANCE), _snapshot=lambda: current,
                _restore=lambda d: _overlay_set(d))


def _hags(pc):
    key, name = r"SYSTEM\CurrentControlSet\Control\GraphicsDrivers", "HwSchMode"
    raw = _reg(HKLM, key, name)
    if raw is None:
        return Item("hags", "Windows", "Hardware-accelerated GPU scheduling", "Lets the graphics card manage its own "
                    "memory, which lowers delay.", "Not supported", "On", UNAVAILABLE, "Lower input delay", 2,
                    note="Your graphics driver or Windows version doesn't offer it.", debug=[_dbg(HKLM, key, name, raw)])
    on = raw == 2
    cmd = f'reg add "HKLM\\{key}" /v {name} /t REG_DWORD /d 2 /f'
    return Item("hags", "Windows", "Hardware-accelerated GPU scheduling",
                "Lets the graphics card schedule its own work instead of Windows doing it, which lowers delay and "
                "helps NVIDIA Reflex.", "On" if on else "Off", "On", DONE if on else IMPROVE, "Lower input delay", 2,
                note="Needs administrator permission and a restart.", admin=True, restart=True,
                debug=[_dbg(HKLM, key, name, raw)], _admin_cmds=[cmd], _snapshot=lambda: raw,
                _admin_undo=lambda d: [f'reg add "HKLM\\{key}" /v {name} /t REG_DWORD /d {int(d or 1)} /f'])


def _windowed_opt():
    import sys
    key, name = r"Software\Microsoft\DirectX\UserGpuPreferences", "DirectXUserGlobalSettings"
    if sys.getwindowsversion().build < 22000:
        return Item("flip_model", "Windows", "Optimizations for windowed games", "", "Windows 10", "On", UNAVAILABLE,
                    "Lower input delay", 2, note="Windows 11 only.")
    raw = _reg(HKCU, key, name, "") or ""
    on = flag_value(raw, "SwapEffectUpgradeEnable") == "1"

    def apply():        # the other global flags in the string (VRROptimizeEnable, AutoHDREnable ...) are kept
        reg_set(HKCU, key, name, flags_with(_reg(HKCU, key, name, "") or "", "SwapEffectUpgradeEnable", "1"))

    return Item("flip_model", "Windows", "Optimizations for windowed games",
                "TrueStretch runs VALORANT in Windowed fullscreen. This Windows 11 setting gives windowed games the same "
                "low delay as exclusive fullscreen.", "On" if on else "Off", "On", DONE if on else IMPROVE,
                "Lower input delay", 3, debug=[_dbg(HKCU, key, name, raw)], _apply=apply,
                _snapshot=lambda: _reg_snapshot(HKCU, key, name), _restore=lambda d: _reg_restore(HKCU, key, d))


def _gpu_pref(engine, pc):
    info = engine.info.get("valorant")
    exe = str(info.game_exe) if info and info.game_exe else None
    key = r"Software\Microsoft\DirectX\UserGpuPreferences"
    if len(pc.gpus) < 2:
        return Item("gpu_pref", "Windows", "VALORANT on the fast graphics card", "", "One graphics card",
                    "High performance", DONE, "More FPS", 3, note="Only matters on PCs with two graphics chips.")
    if not exe:
        return Item("gpu_pref", "Windows", "VALORANT on the fast graphics card", "", "VALORANT not found",
                    "High performance", UNAVAILABLE, "More FPS", 3)
    raw = _reg(HKCU, key, exe, "") or ""
    pref = flag_value(raw, "GpuPreference")
    on = pref == "2"
    current = {"2": "High performance", "1": "Power saving", "0": "Let Windows decide"}.get(pref, "Let Windows decide")

    def apply():        # Windows keeps its own flags in the same string (AutoHDREnable, AppStatus): keep them
        reg_set(HKCU, key, exe, flags_with(_reg(HKCU, key, exe, "") or "", "GpuPreference", "2"))

    return Item("gpu_pref", "Windows", "VALORANT on the fast graphics card",
                "Your PC has two graphics chips. This makes Windows always run VALORANT on the powerful one.",
                current, "High performance", DONE if on else IMPROVE,
                "More FPS", 3, debug=[_dbg(HKCU, key, exe, raw)],
                _apply=apply,
                _snapshot=lambda: _reg_snapshot(HKCU, key, exe), _restore=lambda d: _reg_restore(HKCU, key, d))


def _key_written(root, key):
    """When a registry key was last written (local time), or None."""
    try:
        with winreg.OpenKey(root, key) as k:
            ticks = winreg.QueryInfoKey(k)[2]                    # 100 ns since 1601-01-01 UTC
        return datetime.fromtimestamp((ticks - 116444736000000000) / 1e7)
    except (OSError, OverflowError, ValueError):
        return None


def _render_gpu(engine, log_path=None):
    """Read-only proof for laptops: which graphics chip VALORANT really got at its last start (from the game log)."""
    from . import rendergpu
    from .games.valorant import LOG_DIR
    info = rendergpu.last_start(log_path or LOG_DIR / "ShooterGame.log")
    kind = rendergpu.verdict(info)
    if not kind:
        return None
    chosen, fast = info["chosen"], info["fast"]
    when = f" ({info['started']:%d %b %H:%M})" if info["started"] else ""
    debug = [f"ShooterGame.log{when}: " + "; ".join(f"{a['index']}. {a['name']} {a['mb']} MB 0x{a['vendor']:04x}"
                                                    for a in info["adapters"]), f"chosen: {chosen['name']}"]
    title = "Graphics chip VALORANT used"
    if kind == "fast":
        return Item("render_gpu", "Windows", title, f"VALORANT's own log from its last start{when} confirms it ran on "
                    "your powerful graphics chip.", chosen["name"], "The fast chip", DONE, "More FPS", 3, debug=debug)
    if kind == "basic":
        return Item("render_gpu", "Windows", title, f"At its last start{when} VALORANT ran on Windows' basic display "
                    "driver - no graphics driver was in use, so FPS is very low. This usually means the graphics "
                    "driver is missing or crashed; reinstalling it or restarting the PC fixes it.",
                    chosen["name"], fast["name"] if fast else "Your graphics card", INFO, "More FPS", 3, debug=debug)
    exe = (engine.info.get("valorant").game_exe if engine.info.get("valorant") else None)
    key = r"Software\Microsoft\DirectX\UserGpuPreferences"
    pref = flag_value(_reg(HKCU, key, str(exe), "") or "", "GpuPreference") if exe else None
    written = _key_written(HKCU, key)
    if pref != "2":
        note = "“VALORANT on the fast graphics card” fixes this from the next time VALORANT starts."
    elif info["started"] and written and written > info["started"]:
        note = "The fast graphics card was set after that start - it is used from the next time VALORANT starts."
    else:
        note = ("VALORANT is already set to the fast graphics card, but the laptop gave it the built-in chip. Some "
                "laptops have a graphics mode switch in the manufacturer's app (Eco / iGPU only / Optimus).")
    return Item("render_gpu", "Windows", title, f"At its last start{when} VALORANT ran on the built-in graphics chip, "
                f"not on {fast['name']}. That costs a lot of FPS.", chosen["name"], fast["name"], INFO, "More FPS", 3,
                note=note, debug=debug)


def _fps_cap(engine):
    """The in-game 'Limit FPS Always' cap of the last signed-in account (float), or None when off/unknown."""
    try:
        from . import riotsettings as rs
        targets = [t for t in engine.selected_targets("valorant") if not t.is_default]
        main = next((t for t in targets if t.last_signed_in), targets[0] if targets else None)
        if not main:
            return None
        values = rs.read(rs.riot_settings_path(main.path), rs.FPS_KEYS)
        if not rs._bool(values.get(rs.FPS_KEYS[0])):
            return None
        return rs._num(values.get(rs.FPS_KEYS[1]))
    except Exception:                                # only refines the verdict; never worth failing the row
        return None


def _match_perf(engine, log_dir=None):
    """Read-only: how VALORANT really ran in the last match - average FPS, what limits it (graphics card, processor or
    the FPS cap), stutters and memory - from the game's own per-round statistics in its log."""
    from . import matchperf
    from .games.valorant import LOG_DIR
    info = matchperf.latest(log_dir or LOG_DIR)
    if not info:
        return None
    fps = info["fps"]
    kind = matchperf.limit(info, _fps_cap(engine))
    try:
        native = engine.native_mode("valorant")
        hz = native.hz if native else None
    except Exception:
        hz = None
    when = f" ({info['ended']:%d %b %H:%M})" if info["ended"] else ""
    busy = info["gpu_busy"]
    why = [f"VALORANT's own statistics for your last match{when}: {fps:.0f} FPS on average over {info['rounds']} "
           f"round{'s' if info['rounds'] != 1 else ''}."]
    if busy is not None and kind != "cap":
        why.append(f"The graphics card was busy {busy * 100:.0f}% of each frame.")
    why.append({"gpu": "Your graphics card sets the FPS: lower graphics quality (Material, Texture, Detail) and the "
                       "stretched resolution give the most extra frames.",
                "cpu": "Your processor sets the FPS, not the graphics card - lowering graphics quality adds little. "
                       "Power settings, startup apps and background programs above matter most.",
                "both": "Processor and graphics card are both close to their limit.",
                "cap": "Your in-game FPS limit sets the FPS."}.get(kind, ""))
    notes = []
    slow = info["slow_share"]
    if slow is not None and slow >= 0.01:
        notes.append(f"{slow * 100:.0f}% of frames were slower than 60 FPS - those are the stutters you feel.")
    if info["memory"] is not None and info["memory"] >= 90:
        notes.append(f"Windows memory was {info['memory']:.0f}% full during the match - close browsers and launchers "
                     "before playing.")
    if info["hitches"]:
        notes.append(f"{info['hitches']} shader stutter(s): the first match after a game or driver update is "
                     "normal, they go away.")
    debug = [f"{info['file']}: {info['rounds']} rounds, {info['minutes']:.1f} min, {fps:.1f} FPS, gpu busy "
             f"{busy if busy is None else round(busy, 3)}, slow {slow if slow is None else round(slow, 4)}, memory "
             f"{info['memory']}, hitches {info['hitches']}, limit {kind}"]
    return Item("match_perf", "Your PC", f"Your last match: {fps:.0f} FPS average", " ".join(w for w in why if w),
                f"{fps:.0f} FPS", f"{hz}+ FPS" if hz else "—", INFO, "More FPS", 2, note=" ".join(notes),
                debug=debug)


def _refresh(engine):
    gid = "valorant"
    d = engine.display_for(gid)
    native = engine.native_mode(gid)
    cur = display.current_mode(d.device if d else None)
    if not d or not native or not cur:
        return None
    stretched = engine.is_stretched(gid)
    best = native.hz
    ok = cur.hz >= best or stretched
    return Item("refresh", "Windows", f"Refresh rate of {d.title}",
                "Your screen can show more pictures per second than Windows is sending it. Higher refresh = smoother "
                "and shows enemies sooner.", f"{cur.hz} Hz", f"{best} Hz", DONE if ok else IMPROVE, "Smoother picture", 3,
                debug=[f"device {d.device}: current {cur}, best native {native}"],
                _apply=lambda: display.set_mode(display.Mode(cur.width, cur.height, best), d.device),
                _snapshot=lambda: cur.to_list(),
                _restore=lambda data: display.set_mode(display.Mode.from_list(data), d.device))


def _pointer():
    key = r"Control Panel\Mouse"
    speed, t1, t2 = (_reg(HKCU, key, n) for n in ("MouseSpeed", "MouseThreshold1", "MouseThreshold2"))
    on = str(speed) != "0"

    def apply():
        for n in ("MouseSpeed", "MouseThreshold1", "MouseThreshold2"):
            reg_set(HKCU, key, n, "0")
        arr = (ctypes.c_int * 3)(0, 0, 0)
        ctypes.windll.user32.SystemParametersInfoW(0x0004, 0, arr, 0x01 | 0x02)   # SPI_SETMOUSE, update + notify

    def restore(data):
        _reg_restore(HKCU, key, data)
        vals = [int((data.get(n) or ["0"])[0]) for n in ("MouseThreshold1", "MouseThreshold2", "MouseSpeed")]
        arr = (ctypes.c_int * 3)(*vals)
        ctypes.windll.user32.SystemParametersInfoW(0x0004, 0, arr, 0x01 | 0x02)

    return Item("pointer", "Mouse", "Enhance pointer precision (mouse acceleration)",
                "Makes the cursor move further when you move the mouse faster. VALORANT uses raw input in matches, so "
                "this mostly keeps your menus and desktop aim consistent with your in-game aim.",
                "On" if on else "Off", "Off", IMPROVE if on else DONE, "Consistent aim", 1,
                debug=[_dbg(HKCU, key, "MouseSpeed", speed), _dbg(HKCU, key, "MouseThreshold1", t1),
                       _dbg(HKCU, key, "MouseThreshold2", t2)], _apply=apply,
                _snapshot=lambda: _reg_snapshot(HKCU, key, "MouseSpeed", "MouseThreshold1", "MouseThreshold2"),
                _restore=restore)


# ---- NVIDIA driver (VALORANT's program profile only) ------------------------------------------------------

def _nvidia_items(pc):
    if not any(g.vendor == "nvidia" for g in pc.gpus):
        vendor = next((g.vendor for g in pc.gpus), "")
        return [Item("gpu_driver_profile", "Graphics card", "Graphics driver settings for VALORANT",
                     "", "—", "—", UNAVAILABLE, "", 1,
                     note=f"Driver profile tuning is available for NVIDIA cards ({vendor.upper() or 'your card'} uses "
                          "the in-game settings below).")]
    from . import nvdrs
    specs = [
        ("nv_power", "Power management mode", nvdrs.PREFERRED_PSTATE, nvdrs.PSTATE_PREFER_MAX,
         {1: "Prefer maximum performance", 5: "Normal", 0: "Adaptive"}, "Keeps the graphics card at full clock speed in "
         "VALORANT instead of slowing down between frames - steadier FPS, fewer drops.", "Steadier FPS", 3),
        ("nv_texture", "Texture filtering - Quality", nvdrs.QUALITY_ENHANCEMENTS, nvdrs.TEXTURE_HIGH_PERFORMANCE,
         {0x14: "High performance", 0xA: "Performance", 0: "Quality", 0xFFFFFFF6: "High quality"},
         "Uses faster texture filtering. You won't see a difference in VALORANT; the graphics card does less work.",
         "More FPS", 1),
        ("nv_vsync", "Vertical sync", nvdrs.VSYNCMODE, nvdrs.VSYNC_FORCE_OFF,
         {nvdrs.VSYNC_FORCE_OFF: "Off", nvdrs.VSYNC_APP: "Use the game's setting", 0x47814940: "On"},
         "VSync waits for the screen before showing each frame, which adds input delay. Forced off for VALORANT.",
         "Lower input delay", 3),
    ]
    from .optimizer_more import nvidia_extra_specs
    specs += nvidia_extra_specs()[0]
    items = []
    try:
        with nvdrs.Drs() as d:
            profile = d.app_profile(GAME_EXE, create_as="VALORANT (TrueStretch)")
            for iid, title, sid, want, names, why, impact, level in specs:
                value, loc = d.get(profile, sid)
                cur = names.get(value, "Driver default" if value is None else hex(value))
                if value is not None and loc not in (0, None):
                    cur += f" (from the {nvdrs.LOCATION_NAMES.get(loc, 'driver')})"

                def apply(sid=sid, want=want):
                    with nvdrs.Drs() as s:
                        p = s.app_profile(GAME_EXE, create_as="VALORANT (TrueStretch)")
                        s.set(p, sid, want)
                        s.save()

                def snapshot(sid=sid):
                    with nvdrs.Drs() as s:
                        v, location = s.get(s.app_profile(GAME_EXE, create_as="VALORANT (TrueStretch)"), sid)
                    return {"value": v if location == 0 else None}

                def restore(data, sid=sid):
                    with nvdrs.Drs() as s:
                        p = s.app_profile(GAME_EXE, create_as="VALORANT (TrueStretch)")
                        if data.get("value") is None:
                            s.delete(p, sid)
                        else:
                            s.set(p, sid, data["value"])
                        s.save()

                items.append(Item(iid, "Graphics card", f"NVIDIA: {title}", why, cur, names[want],
                                  DONE if value == want else IMPROVE, impact, level,
                                  note="Only VALORANT's program profile is changed; other games are untouched.",
                                  debug=[f"NVAPI DRS setting {sid:#010x} = {value if value is None else hex(value)}, "
                                         f"location {loc}"],
                                  _apply=apply, _snapshot=snapshot, _restore=restore))
    except OSError as exc:
        items.append(Item("nv_error", "Graphics card", "NVIDIA driver settings", "", "Couldn't read", "—", UNAVAILABLE,
                          note=f"The NVIDIA driver didn't answer ({exc}). Updating the driver usually fixes this.",
                          debug=[repr(exc)]))
    return items


# ---- VALORANT settings files ---------------------------------------------------------------------------

SG = [  # (key, title, why, level) - Unreal Engine scalability groups VALORANT keeps in GameUserSettings.ini
    ("sg.ShadowQuality", "Shadow quality", "Shadows are one of the most expensive things to draw.", 3),
    ("sg.EffectsQuality", "Effects quality", "Ability and smoke effects. Low keeps them clear and cheap.", 2),
    ("sg.PostProcessQuality", "Post-processing quality", "Screen-wide effects like bloom - extra work, no advantage.", 2),
    ("sg.TextureQuality", "Texture quality", "Lower texture detail; matters most on cards with little memory.", 1),
    ("sg.ShadingQuality", "Shading quality", "How detailed surfaces and materials are lit.", 2),
    ("sg.AntiAliasingQuality", "Anti-aliasing quality", "Edge smoothing work done every frame.", 1),
    ("sg.ViewDistanceQuality", "View distance", "How much detail far-away objects keep.", 1),
    ("sg.FoliageQuality", "Foliage quality", "Plants and small scenery details.", 1),
]
QUALITY_NAMES = {"0": "Low", "1": "Medium", "2": "High", "3": "Epic"}


def _valorant_items(engine):
    game = engine.games.get("valorant")
    info = engine.info.get("valorant")
    if not game or not info or not info.installed:
        return []
    targets = [t for t in engine.selected_targets("valorant") if t.path.exists()]
    if not targets:
        return [Item("val_files", "VALORANT files", "VALORANT graphics settings", "", "No settings yet", "—",
                     UNAVAILABLE, note="Play VALORANT once; then these can be optimized.")]
    running = engine.running.get("valorant")
    blocked = "Close VALORANT first — it saves its own settings when it closes." if running else ""
    from .games.valorant import SECTION
    items = []
    main = next((t for t in targets if t.last_signed_in), targets[0])    # stable: not "last file written"

    def writer(section, values):
        def apply():
            for t in targets:
                _write_ini(game, engine, t, section, values)
        return apply

    def snap(section, keys):
        def snapshot():          # every account file AND the copies HP OMEN AI keeps, so Undo restores all of them
            files = [t.path for t in targets] + [c for t in targets for c in game.optimizer_copies(t)]
            return {str(f): {k: IniFile(f).get(section, keys).get(k) for k in keys} for f in files}
        return snapshot

    def restore(section):
        def _restore(data):
            for path, values in data.items():
                p = Path(path)
                if p.exists():
                    set_read_only(p, False)
                    ini = IniFile(p)
                    present = {k: v for k, v in values.items() if v is not None}
                    missing = [k for k, v in values.items() if v is None]
                    if present:
                        ini.set(section, present)
                    if missing:                      # the key didn't exist before: remove it again
                        ini.remove(section, missing)
                    ini.save()
        return _restore

    def per_account(section, key):
        """{target: raw value} for every account, and the label shown: the last signed-in account's value, plus how
        many other accounts differ."""
        values = {str(t.path): IniFile(t.path).get(section, [key]).get(key) for t in targets}
        names = {str(t.path): engine.target_name("valorant", t) for t in targets}
        return values, [f"{names[p]}: {key} = {v!r}" for p, v in values.items()]

    def shown(values, names):
        raw = values.get(str(main.path))
        text = names.get(raw, raw) if raw is not None else "Not set"
        others = {v for p, v in values.items() if p != str(main.path) and v is not None and v != raw}
        return text + (" (other accounts differ)" if others else "")

    values, dbg = per_account(SECTION, "bUseVSync")
    any_on = any((v or "False").lower() == "true" for v in values.values())
    items.append(Item("val_vsync", "VALORANT files", "VSync in VALORANT", "Waits for the screen before every frame - "
                      "adds input delay. Competitive players keep it off.",
                      shown({t: ("On" if (v or "False").lower() == "true" else "Off") for t, v in values.items()}, {}),
                      "Off", IMPROVE if any_on else DONE, "Lower input delay", 3, blocked=blocked,
                      note=f"All {len(targets)} account(s) on this PC.", debug=dbg,
                      _apply=writer(SECTION, {"bUseVSync": "False"}), _snapshot=snap(SECTION, ["bUseVSync"]),
                      _restore=restore(SECTION)))
    for key, title, why, level in SG:
        values, dbg = per_account("ScalabilityGroups", key)
        if all(v is None for v in values.values()):
            continue
        all_low = all(v in (None, "0") for v in values.values())
        items.append(Item(f"val_{key}", "VALORANT files", title, why + " Set to Low for maximum FPS.",
                          shown(values, QUALITY_NAMES), "Low", DONE if all_low else IMPROVE, "More FPS", level,
                          blocked=blocked, note=f"All {len(targets)} account(s) on this PC.", debug=dbg,
                          _apply=writer("ScalabilityGroups", {key: "0"}),
                          _snapshot=snap("ScalabilityGroups", [key]), _restore=restore("ScalabilityGroups")))
    from .optimizer_more import MORE_VALORANT
    for section, key, title, want, names, why, impact, level in MORE_VALORANT:
        values, dbg = per_account(section, key)
        if all(v is None for v in values.values()):
            continue
        ok = all(v in (None, want) for v in values.values())
        items.append(Item(f"val_{key}", "VALORANT files", title, why, shown(values, names), names.get(want, want),
                          DONE if ok else IMPROVE, impact, level, blocked=blocked,
                          note=f"All {len(targets)} account(s) on this PC.", debug=dbg,
                          _apply=writer(section, {key: want}), _snapshot=snap(section, [key]),
                          _restore=restore(section)))
    return items


def _write_ini(game, engine, target, section, values):
    set_read_only(target.path, False)
    engine.backups.create(game.id, target.key, target.label, target.path)
    ini = IniFile(target.path)
    ini.set(section, values)
    ini.save()
    for i, copy in enumerate(game.optimizer_copies(target)):     # HP OMEN AI keeps its own copy and restores it
        try:
            set_read_only(copy, False)
            c = IniFile(copy)
            c.set(section, values)
            c.save()
        except OSError:
            pass


def _in_game_items(engine):
    """Settings VALORANT keeps in the Riot account (Video > Graphics Quality, FPS limit): read from the last signed-in
    account's RiotUserSettings.ini and shown with the exact place to change them - only the game can change them."""
    from .riotsettings import ingame_items, riot_settings_path
    targets = [t for t in engine.selected_targets("valorant") if not t.is_default and t.path.parent.parent.is_dir()]
    if not targets:
        return ingame_items(None)
    main = next((t for t in targets if t.last_signed_in), targets[0])
    native = engine.native_mode("valorant")
    return ingame_items(riot_settings_path(main.path), native.hz if native else None,
                        engine.target_name("valorant", main))


# ---- informational checks ------------------------------------------------------------------------------

def _info_items(engine, pc):
    items = []
    if pc.laptop and pc.on_battery:
        items.append(Item("battery", "Your PC", "Laptop is on battery", "On battery, Windows and the graphics card "
                          "limit performance a lot.", "Battery", "Plugged in", INFO, "More FPS", 3,
                          note="Plug the charger in while you play."))
    for g in pc.gpus:
        days = g.driver_age_days
        if days and days > 180:
            items.append(Item(f"driver_{g.vendor}", "Your PC", f"{g.name}: graphics driver is {days // 30} months old",
                              "New drivers often bring VALORANT performance fixes.", g.friendly_driver, "Latest",
                              INFO, "More FPS", 2, link=pcinfo.DRIVER_PAGES.get(g.vendor, "")))
    try:
        hvci = reg_get(HKLM, r"SYSTEM\CurrentControlSet\Control\DeviceGuard\Scenarios\HypervisorEnforcedCodeIntegrity",
                       "Enabled")
    except OSError:
        hvci = None
    if hvci == 1:
        items.append(Item("hvci", "Your PC", "Memory integrity is on", "This Windows security feature costs a few "
                          "percent of FPS. TrueStretch never changes security settings - it's your choice.",
                          "On", "Your choice", INFO, "Few % FPS", 1,
                          debug=["HKLM\\...\\HypervisorEnforcedCodeIntegrity → Enabled = 1"]))
    info = engine.info.get("valorant")
    if info and info.install_dir:
        free = pcinfo.disk_free_gb(str(info.install_dir))
        if free is not None and free < 15:
            items.append(Item("disk", "Your PC", f"Only {free:.0f} GB free on VALORANT's drive", "Updates need space "
                              "and a nearly full drive slows loading.", f"{free:.0f} GB", "15 GB or more", INFO,
                              "Faster loading", 1))
    if pc.ram_gb and pc.ram_gb < 8:
        items.append(Item("ram", "Your PC", f"{pc.ram_gb:.0f} GB memory", "VALORANT runs best with 8 GB or more. "
                          "Close browsers and launchers while playing.", f"{pc.ram_gb:.0f} GB", "8 GB+", INFO, "", 2))
    return items


# ---- the optimizer -------------------------------------------------------------------------------------

class Optimizer:
    def __init__(self, engine):
        self.engine = engine
        self.items = []
        self.scanned_at = None
        self.history = []                  # (time, text) of every change, for the diagnostics view

    # undo store ------------------------------------------------------------
    def _undo_data(self):
        try:
            return json.loads(UNDO_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _save_undo(self, data):
        UNDO_FILE.parent.mkdir(parents=True, exist_ok=True)
        UNDO_FILE.write_text(json.dumps(data, indent=1, default=str), encoding="utf-8")

    def changed_ids(self):
        return set(self._undo_data())

    # scanning --------------------------------------------------------------
    def steps(self, pc):
        """[(label, callable)] - every check, in the order the scan runs them (shown live in the UI)."""
        from . import optimizer_more as more
        e = self.engine
        d = e.display_for("valorant")
        vendor = d.vendor if d else ""
        return [
            ("Windows power mode", lambda: _power(pc)),
            ("Power plan: processor, USB, PCI Express, Wi-Fi", lambda: more.power_items(pc)),
            ("Game Mode", _game_mode),
            ("Xbox Game Bar recording", _game_dvr),
            ("GPU scheduling", lambda: _hags(pc)),
            ("Windowed game optimizations", _windowed_opt),
            ("Graphics card preference", lambda: _gpu_pref(e, pc)),
            ("Graphics chip VALORANT used", lambda: _render_gpu(e)),
            ("Screen refresh rate", lambda: _refresh(e)),
            ("Transparency effects", more.transparency_item),
            ("Pending Windows restart", more.pending_restart_item),
            ("Mouse acceleration", _pointer),
            ("Keyboard shortcut pop-ups (Sticky, Filter, Toggle Keys)", more.accessibility_hotkey_items),
            ("NVIDIA driver profile", lambda: _nvidia_items(pc)),
            ("VALORANT settings files", lambda: _valorant_items(e)),
            ("Startup apps", more.startup_items),
            ("Overlays", more.overlay_items),
            ("Programs using lots of memory", more.memory_hog_items),
            ("Memory speed and channels", more.memory_items),
            ("Drive VALORANT is installed on", lambda: more.storage_item(e)),
            ("Network connection", more.network_item),
            ("Graphics drivers, battery, memory integrity", lambda: _info_items(e, pc)),
            ("Your last match (VALORANT's own statistics)", lambda: _match_perf(e)),
            ("Settings inside VALORANT", lambda: _in_game_items(e)),
            ("Graphics panel settings", lambda: more.panel_items(vendor) if vendor in ("amd", "intel") else []),
        ]

    def scan(self, progress=None):
        """Runs every check. progress(index, total, label) is called before each one."""
        pc = self.engine.pc if getattr(self.engine, "pc", None) else pcinfo.scan()
        steps = self.steps(pc)
        items = []
        for n, (label, fn) in enumerate(steps):
            if progress:
                progress(n, len(steps), label)
            try:
                result = fn()
            except Exception as exc:                 # one broken check must never hide the others
                log.exception("Optimizer check '%s' failed", label)
                result = Item(f"error_{n}", "Your PC", f"Check failed: {label}", "", "Error", "—", UNAVAILABLE,
                              note=str(exc), debug=[repr(exc)])
            if result is None:
                continue
            items.extend(result if isinstance(result, list) else [result])
        if progress:
            progress(len(steps), len(steps), "Done")
        self.items = items
        self.scanned_at = datetime.now()
        return items

    def score(self):
        """0-100: how much of what TrueStretch can optimize automatically already is (weighted by impact)."""
        auto = [i for i in self.items if i.state in (DONE, IMPROVE) and (i._apply or i._admin_cmds or
                                                                          i.state == DONE)
                and not i.group.startswith("Inside")]        # in-game / panel settings: shown, not ours to change
        total = sum(i.level for i in auto)
        return round(100 * sum(i.level for i in auto if i.state == DONE) / total) if total else 100

    def get(self, iid):
        return next((i for i in self.items if i.id == iid), None)

    def _record(self, text):
        self.history.append((datetime.now(), text))
        log.info("Optimizer: %s", text)

    # applying --------------------------------------------------------------
    def apply(self, ids, hwnd=None):
        """Apply the chosen items. Returns [(item, ok, message)]. Each change is verified by scanning again."""
        chosen = [self.get(i) for i in ids]
        chosen = [i for i in chosen if i and i.can_apply]
        undo = self._undo_data()
        results = []
        admin = [i for i in chosen if i._admin_cmds]
        for item in [i for i in chosen if not i._admin_cmds]:
            try:
                if item.id not in undo and item._snapshot:
                    undo[item.id] = {"time": datetime.now().isoformat(timespec="seconds"), "title": item.title,
                                     "data": item._snapshot()}
                    self._save_undo(undo)
                item._apply()
                results.append((item, True, ""))
            except Exception as exc:
                log.exception("Applying %s failed", item.id)
                results.append((item, False, str(exc)))
        if admin:
            for item in admin:
                if item.id not in undo:
                    undo[item.id] = {"time": datetime.now().isoformat(timespec="seconds"), "title": item.title,
                                     "data": item._snapshot() if item._snapshot else None, "admin": True}
            try:
                code = run_elevated([c for i in admin for c in i._admin_cmds], hwnd)
                self._save_undo(undo)
                for item in admin:
                    results.append((item, code == 0, "" if code == 0 else f"exit code {code}"))
            except (PermissionError, OSError) as exc:
                for item in admin:
                    results.append((item, False, str(exc)))
        return self._verify(results)

    def _verify(self, results):
        by_id = {i.id: i for i in self.scan()}
        out = []
        for item, ok, msg in results:
            after = by_id.get(item.id)
            if ok and after and after.state != DONE and not item.restart:
                ok, msg = False, f"Windows/driver still reports “{after.current}”."
            self._record(f"{'✔' if ok else '✖'} {item.title}: {item.current} → {item.target}"
                         + (f" ({msg})" if msg else "") + (" — restart needed" if ok and item.restart else ""))
            out.append((after or item, ok, msg))
        return out

    def undo(self, ids=None, hwnd=None):
        data = self._undo_data()
        ids = list(data) if ids is None else [i for i in ids if i in data]
        current = {i.id: i for i in (self.items or self.scan())}
        done = []
        admin_cmds = []
        for iid in ids:
            entry = data[iid]
            item = current.get(iid)
            try:
                if entry.get("admin"):
                    if item and item._admin_undo:
                        admin_cmds.extend(item._admin_undo(entry.get("data")))
                        done.append(iid)
                    continue
                if item and item._restore:
                    item._restore(entry.get("data"))
                    done.append(iid)
                    self._record(f"↩ {entry.get('title', iid)} put back")
            except Exception as exc:
                log.exception("Undo %s failed", iid)
                self._record(f"✖ Undo {entry.get('title', iid)} failed: {exc}")
        if admin_cmds:
            try:
                run_elevated(admin_cmds, hwnd)
                for iid in ids:
                    if data.get(iid, {}).get("admin"):
                        self._record(f"↩ {data[iid].get('title', iid)} put back (restart to finish)")
            except (PermissionError, OSError) as exc:
                self._record(f"✖ Undo needs administrator permission: {exc}")
                done = [d for d in done if not data.get(d, {}).get("admin")]
        for iid in done:
            data.pop(iid, None)
        self._save_undo(data)
        self.scan()
        return done

    # diagnostics -----------------------------------------------------------
    def report(self):
        from . import APP_NAME, VERSION
        pc = getattr(self.engine, "pc", None)
        lines = [f"{APP_NAME} {VERSION} — Optimize Max report", f"Scanned: {self.scanned_at:%Y-%m-%d %H:%M:%S}"
                 if self.scanned_at else "Not scanned", ""]
        if pc:
            lines += [f"CPU: {pc.cpu} ({pc.cores} threads) · RAM: {pc.ram_gb} GB · {pc.windows}",
                      "GPUs: " + "; ".join(f"{g.name} (driver {g.friendly_driver})" for g in pc.gpus),
                      f"Laptop: {pc.laptop} · on battery: {pc.on_battery} · power plan: {pc.power_plan} · "
                      f"power mode: {pc.power_mode}", ""]
        changed = self.changed_ids()
        for group in GROUPS:
            group_items = [i for i in self.items if i.group == group]
            if not group_items:
                continue
            lines.append(f"== {group} ==")
            for i in group_items:
                flag = {DONE: "OK  ", IMPROVE: "FIX ", INFO: "INFO", UNAVAILABLE: "N/A ", IN_GAME: "GAME",
                        OPTIONAL: "OPT "}[i.state]
                lines.append(f"[{flag}] {i.title}: {i.current} → {i.target}" + ("  (changed by TrueStretch)"
                                                                               if i.id in changed else ""))
                for d in i.debug:
                    lines.append(f"         {d}")
                if i.note:
                    lines.append(f"         note: {i.note}")
            lines.append("")
        if self.history:
            lines.append("== Changes this session ==")
            lines += [f"{t:%H:%M:%S}  {text}" for t, text in self.history]
        from .support import _scrub
        return _scrub("\n".join(lines))          # no account ids in a report people paste into bug reports


def is_game_running():
    return GAME_EXE.lower() in running_processes()


__all__ = ["Optimizer", "Item", "GROUPS", "DONE", "IMPROVE", "INFO", "UNAVAILABLE", "IN_GAME", "is_game_running",
           "os"]
