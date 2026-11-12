"""The brain: applies / reverts stretched res for a game and watches the game process."""

import time
from dataclasses import dataclass
from datetime import datetime

from PySide6.QtCore import QObject, QTimer, Signal

from . import display, displayconfig, monitors, pcinfo
from .backups import BackupManager
from .display import DisplayError, Mode
from .games import GAMES
from .paths import BACKUP_DIR, log
from .settings import SessionState
from .system import running_processes

POLL_MS = 500
VENDOR_NAMES = {"nvidia": "NVIDIA", "amd": "AMD", "intel": "Intel"}


class StretchError(Exception):
    pass


class MonitorDriversOn(StretchError):
    """The monitor drivers must be disabled before launch; the UI offers to do it (admin prompt)."""


@dataclass
class Check:
    key: str
    title: str
    ok: object          # True, False (blocking), or None (warning / needs the user)
    detail: str


@dataclass
class ApplyResult:
    display_changed: bool
    previous: Mode
    mode: Mode


class Engine(QObject):
    changed = Signal()                  # anything the UI shows may have changed
    message = Signal(str, str)          # level (info|success|warning|error), text
    game_state = Signal(str, bool)      # game id, running

    def __init__(self, settings):
        super().__init__()
        self.settings = settings
        self.games = {g.id: g for g in GAMES}
        self.backups = BackupManager(BACKUP_DIR, keep=settings.app["keep_backups"])
        self.state = SessionState()
        self.info = {}
        self.running = {}
        self.history = []
        self._launch_started = {}
        self.watchers = {g.id: g.match_watcher() for g in GAMES if hasattr(g, "match_watcher")}
        self.paused = False                 # hotkey can pause auto-stretch for the rest of a match
        self._resolved = {}                 # gid -> ((w, h, device), Mode really used)
        self._create_tried = set()          # sizes we already asked the driver to add this session
        self._gpu_scaling_done = set()      # displays whose driver scaling was checked this session
        self._first_run = set()             # games started before they had any settings file
        self._lock_warned = {}              # gid -> resolution we already warned about
        self._migrate_settings()
        self.refresh(quiet=True)

    def _migrate_settings(self):
        """One-time upgrade of setups saved before the 2026 method (4:3 / 5:4, exclusive Fullscreen, locked files)."""
        for gid, game in self.games.items():
            gs = self.gs(gid)
            if gs.get("_method_2026b"):
                continue
            w, h = int(gs.get("width", 0)), int(gs.get("height", 0))
            d = self.display_for(gid)
            native_w, native_h = d.native if d and d.native else (1920, 1080)
            if hasattr(game, "presets_for") and (not h or h != native_h or w >= native_w):
                best = game.presets_for(native_w, native_h)[1]   # keep the screen's own height: sharp, not blurry
                gs["width"], gs["height"] = best.width, best.height
            if "windowed_fullscreen" in getattr(game, "window_modes", {}):
                gs["window_mode"] = "windowed_fullscreen"
            gs["lock_config"] = False
            gs.setdefault("auto_match", True)
            gs["_method_2026b"] = True
        self.settings.save()
        self.timer = QTimer(self)
        self.timer.setInterval(POLL_MS)
        self.timer.timeout.connect(self.poll)
        self.timer.start()

    # ---- general ----------------------------------------------------------

    def refresh(self, quiet=False):
        self._resolved = {}
        try:
            self.pc = pcinfo.scan()
        except Exception:
            log.exception("PC scan failed")
            self.pc = pcinfo.PcInfo()
        procs = running_processes()
        for gid, game in self.games.items():
            try:
                self.info[gid] = game.detect()
            except Exception:  # detection must never take the app down
                log.exception("Detection failed for %s", gid)
                from .games.base import InstallInfo
                self.info[gid] = InstallInfo()
            self.running[gid] = game.is_running(procs)
        if not quiet:
            self.notify("info", "Re-scanned this PC.")
        self.changed.emit()

    def notify(self, level, text):
        getattr(log, {"success": "info"}.get(level, level), log.info)(text)
        self.history.append((datetime.now(), level, text))
        del self.history[:-300]
        self.message.emit(level, text)

    def gs(self, gid):
        return self.settings.game(gid)

    def save(self):
        self.settings.save()
        self.changed.emit()

    # ---- display ----------------------------------------------------------

    def display_for(self, gid):
        device = self.gs(gid).get("display", "primary")
        return display.find_display(None if device == "primary" else device)

    def modes_for(self, gid):
        d = self.display_for(gid)
        return display.available_modes(d.device if d else None)

    def stretch_mode(self, gid, modes=None):
        """The mode the desktop switches to in a match, or None if the driver won't accept that size."""
        gs = self.gs(gid)
        d = self.display_for(gid)
        device = d.device if d else None
        modes = modes if modes is not None else display.available_modes(device)
        w, h = int(gs["width"]), int(gs["height"])
        rates = display.refresh_rates(modes, w, h)
        wanted = gs.get("refresh", "max")
        if rates:
            return Mode(w, h, wanted if isinstance(wanted, int) and wanted in rates else rates[0])
        # Not listed: with the monitor drivers disabled the driver still accepts custom sizes. Try the screen's
        # own refresh rates from fastest down.
        native = self.native_mode(gid, modes)
        for hz in display.refresh_rates(modes, *native.size) if native else []:
            if display.mode_accepted(Mode(w, h, hz), device):
                return Mode(w, h, hz)
        return None

    def native_mode(self, gid, modes=None):
        """The screen's own resolution at its fastest refresh rate (what menus run at)."""
        d = self.display_for(gid)
        modes = modes if modes is not None else display.available_modes(d.device if d else None)
        if not modes:
            return None
        size = d.native if d and d.native and display.refresh_rates(modes, *d.native) else display.sizes(modes)[0]
        return Mode(*size, display.refresh_rates(modes, *size)[0])

    def normal_mode(self, gid, modes=None):
        """The mode to go back to when stretching ends."""
        gs = self.gs(gid)
        d = self.display_for(gid)
        modes = modes if modes is not None else display.available_modes(d.device if d else None)
        if not modes:
            return None
        choice = gs.get("normal", "previous")
        if choice != "previous":
            try:
                w, h = (int(v) for v in choice.lower().split("x"))
                rates = display.refresh_rates(modes, w, h)
                if rates:
                    return Mode(w, h, rates[0])
            except ValueError:
                pass
        if self.state.stretched:
            prev = Mode.from_list(self.state.data.get("previous"))
            if prev and prev in modes:
                return prev
        current = display.current_mode(d.device if d else None)
        stretched_size = (int(gs["width"]), int(gs["height"]))
        if current and current.size != stretched_size:
            return current
        biggest = display.sizes(modes)[0]
        return Mode(*biggest, display.refresh_rates(modes, *biggest)[0])

    # ---- status -----------------------------------------------------------

    def targets(self, gid):
        try:
            return self.games[gid].targets(self.info[gid])
        except Exception:
            log.exception("Listing config files failed")
            return []

    def selected_targets(self, gid):
        excluded = set(self.gs(gid).get("excluded", []))
        return [t for t in self.targets(gid) if t.key not in excluded]

    def target_name(self, gid, target):
        return self.gs(gid).get("nicknames", {}).get(target.key) or target.label

    def checks(self, gid):
        game, info, gs = self.games[gid], self.info[gid], self.gs(gid)
        targets = self.targets(gid)
        selected = self.selected_targets(gid)
        mode = self.stretch_mode(gid)
        size = f"{gs['width']} × {gs['height']}"
        return [
            Check("installed", f"{game.name} installed", info.installed,
                  str(info.install_dir) if info.installed else f"{game.name} wasn't found on this PC."),
            Check("configs", "Game settings files found", (bool(targets) and bool(selected)) or (None if not targets
                                                                                         else False),
                  f"{len(selected)} of {len(targets)} selected" if targets
                  else f"Set up automatically after your first {game.name} session"),
            Check("launcher", "Riot Client found", bool(info.launcher),
                  str(info.launcher) if info.launcher else "Needed only for the Play button."),
            Check("resolution", f"{size} works on your display", True,
                  f"Ready at {mode.hz} Hz" if mode else "Added to your graphics driver automatically when you play"),
            Check("monitors", "Monitor drivers off", None if self.monitor_drivers_on(gid) else True,
                  "Play stretched turns them off (admin prompt)" if self.monitor_drivers_on(gid)
                  else "VALORANT can't read the 16:9 shape"),
            self._scaling_check(gid),
        ]

    def _scaling_check(self, gid):
        gs = self.gs(gid)
        mon = self.monitor(gid)
        title = "Picture stretched to full screen"
        if mon and mon.stretches:
            return Check("scaling", title, True, f"{mon.name}: scaling is set to stretch")
        if gs.get("auto_scaling", True) and mon:
            return Check("scaling", title, True, "TrueStretch turns stretch scaling on when you play")
        return Check("scaling", title, True, "TrueStretch sets the graphics driver to stretch when you play")

    def is_stretched(self, gid=None):
        return self.state.stretched and (gid is None or self.state.data.get("game") == gid)

    # ---- actions ----------------------------------------------------------

    def prepare(self, gid):
        """Everything that must be true BEFORE VALORANT starts (2026 method):
        monitor drivers disabled, the stretched size accepted by the driver, GPU scaling Full-screen,
        and the game on Windowed Fullscreen + Fill at the native resolution. The desktop stays native -
        the match watcher stretches it once a match has loaded."""
        game, gs = self.games[gid], self.gs(gid)
        if self.running.get(gid):
            raise StretchError(f"Close {game.name} first — it reads these settings only when it starts.")
        targets = self.selected_targets(gid)
        first_run = not self.targets(gid)
        if not targets and not first_run:
            raise StretchError(f"No {game.name} settings files are selected (Accounts tab).")
        if self.monitor_drivers_on(gid):
            raise MonitorDriversOn(
                "VALORANT must not see your monitor's real 16:9 shape, or it squeezes the picture back to normal. "
                "TrueStretch turns the monitor drivers off in Device Manager (one administrator prompt) — your "
                "screen keeps working, and they can be turned back on any time.")
        mode = self.ensure_stretch_mode(gid)
        native = self.native_mode(gid)
        d = self.display_for(gid)
        self._ensure_gpu_fullscreen(d)
        monitor = display.monitor_ref(d)
        nw, nh = native.size if native else (1920, 1080)
        for t in targets:
            try:
                game.apply_target(t, nw, nh, gs, self.backups, monitor)
            except OSError as exc:
                raise StretchError(f"Couldn't update {self.target_name(gid, t)}: {exc}") from exc
        if self.state.stretched:
            self.revert_display("starting fresh")
        self.paused = False
        gs["prepared"] = True
        self.settings.save()
        if first_run:
            self._first_run.add(gid)
            self.notify("info", f"First time on this PC: {game.name} creates its settings when you sign in. Play "
                                "this session normally — when you close the game TrueStretch sets everything up, "
                                "and from the next start it stretches by itself.")
        else:
            self.notify("success", f"Ready: {game.name} starts at {nw} × {nh}; TrueStretch switches to {mode} "
                                   "as soon as a match has loaded.")
        self.changed.emit()
        return mode

    def create_custom_resolution(self, gid):
        """Adds the stretched size to the graphics driver - NVIDIA, AMD or Intel - like their control panels'
        'Custom resolution' page. Returns the usable Mode, or None when this driver can't (the caller falls back
        to the closest built-in mode, so the user never has to do it by hand)."""
        gs = self.gs(gid)
        w, h = int(gs["width"]), int(gs["height"])
        d = self.display_for(gid)
        native = self.native_mode(gid)
        if not d or not native:
            return None
        nw, nh = native.size
        before = display.current_mode(d.device)
        try:
            if d.vendor == "nvidia":
                from . import nvidia
                api = nvidia.NvApi()
                pos = display.desktop_position(d.device)
                display_id = api.display_id_at(*pos) if pos else None
                if display_id is None:
                    raise OSError("NVIDIA doesn't drive this screen")
                api.add_custom_resolution(display_id, w, h, native.hz)
            elif d.vendor == "amd":
                from . import amd
                api = amd.AmdApi()
                disp = api.display_for(d.device)
                if disp is None:
                    raise OSError("AMD doesn't drive this screen")
                api.add_custom_mode(disp, w, h, native.hz, nw, nh)
            elif d.vendor == "intel":
                from . import intel
                api = intel.IntelApi()
                out = self._intel_output(api, d)
                if out is None:
                    raise OSError("Intel doesn't drive this screen")
                api.add_custom_mode(out, w, h)
            else:
                return None
            if before and display.current_mode(d.device) != before:
                display.set_mode(before, d.device)
        except (OSError, DisplayError) as exc:
            log.warning("Custom resolution %sx%s not created on %s: %s", w, h, d.vendor, exc)
            return None
        mode = self.stretch_mode(gid)
        if mode:
            self.notify("success", f"Custom resolution {mode} added to the {VENDOR_NAMES.get(d.vendor, d.vendor)} "
                                   "driver.")
        else:
            log.info("The driver saved %sx%s, but Windows won't use it until the next restart", w, h)
        return mode

    @staticmethod
    def _intel_output(api, d):
        mon = displayconfig.monitor_for(d.device)
        outs = api.outputs()
        out = next((o for o in outs if mon and o.target_id == mon.target_id), None)
        return out or (outs[0] if len(outs) == 1 else None)

    def closest_mode(self, gid, modes=None):
        """When the driver can't add the exact size: the built-in mode with the nearest stretch (same idea, e.g.
        1400 x 1050 or 1280 x 960 for 4:3), so stretching works on every PC without a graphics panel."""
        gs = self.gs(gid)
        d = self.display_for(gid)
        modes = modes if modes is not None else display.available_modes(d.device if d else None)
        native = self.native_mode(gid, modes)
        if not native:
            return None
        nw, nh = native.size
        w, h = int(gs["width"]), int(gs["height"])
        want = (nw / nh) / (w / h)
        best = None
        for mw, mh in display.sizes(modes):
            if mh < 600 or mh > nh or mw >= nw:
                continue
            factor = (nw / nh) / (mw / mh)
            if factor < 1.08:
                continue
            score = (round(abs(factor - want), 2), -mh)
            if best is None or score < best[0]:
                best = (score, mw, mh)
        if not best:
            return None
        _, mw, mh = best
        rates = display.refresh_rates(modes, mw, mh)
        hz = native.hz if native.hz in rates else rates[0]
        return Mode(mw, mh, hz)

    def resolved_mode(self, gid, modes=None):
        """(mode, exact) the desktop will really use for the chosen level on this screen, without changing
        anything: the exact size if the driver takes it, otherwise the closest built-in one."""
        exact = self.stretch_mode(gid, modes)
        if exact:
            return exact, True
        return self.closest_mode(gid, modes), False

    def ensure_stretch_mode(self, gid):
        """The mode to stretch to: the chosen size (added to the driver automatically if needed), or the
        closest built-in mode when this driver can't add it. Only raises if the screen has no usable mode."""
        gs = self.gs(gid)
        d = self.display_for(gid)
        key = (int(gs["width"]), int(gs["height"]), d.device if d else None)
        cached = self._resolved.get(gid)
        if cached and cached[0] == key:
            return cached[1]
        mode = self.stretch_mode(gid)
        if mode is None and key not in self._create_tried:
            self._create_tried.add(key)
            mode = self.create_custom_resolution(gid)
        if mode is None:
            mode = self.closest_mode(gid)
            if mode is None:
                raise StretchError(f"Your screen doesn't offer any stretched resolution ({key[0]} × {key[1]} or "
                                   "similar). Update the graphics driver from the My PC page and try again.")
            native = self.native_mode(gid)
            nw, nh = native.size if native else (1920, 1080)
            factor = (nw / nh) / (mode.width / mode.height)
            self.notify("info", f"Your graphics driver can't add {key[0]} × {key[1]}, so TrueStretch uses {mode} — "
                                f"the closest stretch it has (models {factor:.2f}× wider).")
        self._resolved[gid] = (key, mode)
        return mode

    def _ensure_gpu_fullscreen(self, d):
        """Graphics-driver scaling = Full-screen / Full panel / Stretch. Without it the driver keeps the aspect
        ratio and you get black bars at the sides however the game is set. NVIDIA, AMD and Intel."""
        if not d or d.device in self._gpu_scaling_done:
            return
        try:
            if d.vendor == "nvidia":
                from . import nvidia
                api = nvidia.NvApi()
                pos = display.desktop_position(d.device)
                target = next((t for t in api.targets() if pos and (t.x, t.y) == pos), None)
                if target and not target.stretches:
                    api.set_scaling(nvidia.FULL_SCREEN_GPU, *pos)
                    self.notify("info", "NVIDIA scaling set to Full-screen.")
            elif d.vendor == "amd":
                from . import amd
                api = amd.AmdApi()
                disp = api.display_for(d.device)
                if disp and api.full_panel(disp):
                    self.notify("info", "AMD scaling set to Full panel.")
            elif d.vendor == "intel":
                from . import intel
                api = intel.IntelApi()
                out = self._intel_output(api, d)
                if out and api.supports_stretch(out) and api.scaling(out) != intel.SCALING_STRETCHED:
                    api.set_scaling(out, intel.SCALING_STRETCHED)
                    self.notify("info", "Intel scaling set to Stretch.")
        except OSError as exc:
            log.warning("%s scaling not set through the driver (Windows' own scaling covers it): %s", d.vendor, exc)
        self._gpu_scaling_done.add(d.device)

    def stretch_now(self, gid, reason=""):
        """Switch the desktop to the stretched resolution (VALORANT on Windowed Fullscreen follows it)."""
        mode = self.ensure_stretch_mode(gid)
        d = self.display_for(gid)
        device = d.device if d else None
        previous = display.current_mode(device)
        if previous != mode:
            try:
                display.set_mode(mode, device, persist=False)
            except DisplayError as exc:
                raise StretchError(str(exc)) from exc
        self.state.mark_stretched(gid, device, previous if previous != mode else None, mode)
        self._ensure_stretch_scaling(gid, d)
        self._ensure_gpu_fullscreen(d)
        self.notify("success", f"Stretched to {mode}" + (f" ({reason})." if reason else "."))
        self.changed.emit()
        return ApplyResult(previous != mode, previous, mode)

    def stretch_levels(self, gid):
        """[(width, height, factor, note)] from least to most stretch, for this screen."""
        game = self.games[gid]
        native = self.native_mode(gid)
        nw, nh = native.size if native else (1920, 1080)
        if not hasattr(game, "presets_for"):
            return []
        return [(p.width, p.height, nw / p.width, p.note) for p in game.presets_for(nw, nh)]

    def step_stretch(self, gid, direction):
        """Hotkey Ctrl+Alt+Up (direction=+1, more) / Down (-1, less). Applies at once if stretched now."""
        gs = self.gs(gid)
        levels = self.stretch_levels(gid)
        if not levels:
            return
        w = int(gs["width"])
        if direction > 0:
            nxt = next(((lw, lh, f, n) for lw, lh, f, n in levels if lw < w), None)
        else:
            nxt = next(((lw, lh, f, n) for lw, lh, f, n in reversed(levels) if lw > w), None)
        if not nxt:
            self.notify("info", "Already at the " + ("strongest" if direction > 0 else "lightest") + " stretch.")
            return
        gs["width"], gs["height"] = nxt[0], nxt[1]
        self.settings.save()
        label = f"{nxt[0]} × {nxt[1]} — {nxt[3]}, models {nxt[2]:.2f}× wider"
        if self.is_stretched(gid):
            self.stretch_now(gid, label)
        else:
            self.notify("info", f"Stretch level: {label}. Used from the next match (or press Ctrl+Alt+S).")
        self.changed.emit()

    def toggle_stretch(self, gid):
        """Hotkey: stretch now / back to native now (and stop auto-stretch until the next match)."""
        if self.is_stretched(gid):
            self.paused = True
            self.revert_display("hotkey")
        else:
            self.paused = False
            self.stretch_now(gid, "hotkey")

    def match_state(self, gid):
        w = self.watchers.get(gid)
        if not w or not self.running.get(gid):
            return "not running"
        if w.in_match:
            return "in match"
        return "menu" if w.map else "starting"

    def monitor(self, gid):
        d = self.display_for(gid)
        return displayconfig.monitor_for(d.device) if d else None

    def monitor_drivers_on(self, gid=None):
        """True when any monitor driver is still enabled in Device Manager (the game could read the 16:9 shape)."""
        return any(dev and not dev.disabled for _, dev in self.monitor_devices())

    def _ensure_stretch_scaling(self, gid, d):
        """Makes the graphics driver stretch the picture to the full screen (no black bars)."""
        if not d or not self.gs(gid).get("auto_scaling", True):
            return False
        mon = displayconfig.monitor_for(d.device)
        if not mon or mon.stretches:
            return False
        try:
            ok = displayconfig.set_scaling(d.device, displayconfig.SCALING_STRETCHED)
            after = displayconfig.monitor_for(d.device)
            ok = ok and (after is None or after.stretches)
        except OSError:
            ok = False
        if ok:
            self.state.remember("previous_scaling", mon.scaling)
            return True
        if self._nvidia_stretches(d):     # NVIDIA reports its own scaling; Windows may still say "identity"
            return False
        return False

    def repair_scaling(self, gid):
        """The player saw black bars: set the driver and Windows scaling again from scratch."""
        d = self.display_for(gid)
        if not d:
            return
        self._gpu_scaling_done.discard(d.device)
        self._ensure_gpu_fullscreen(d)
        try:
            displayconfig.set_scaling(d.device, displayconfig.SCALING_STRETCHED)
        except OSError as exc:
            log.warning("Windows scaling not set: %s", exc)

    def _nvidia_stretches(self, d):
        if not d or d.vendor != "nvidia":
            return False
        try:
            from . import nvidia
            pos = display.desktop_position(d.device)
            return any(t.stretches for t in nvidia.NvApi().targets() if pos and (t.x, t.y) == pos)
        except OSError:
            return False

    # ---- monitor drivers (Device Manager) ----------------------------------

    def monitor_devices(self):
        """[(displayconfig.Monitor, monitors.MonitorDevice or None)] for every active screen."""
        try:
            devices = monitors.list_monitor_devices()
            return [(m, monitors.device_for(m, devices)) for m in displayconfig.monitors()]
        except OSError:
            log.exception("Listing monitor devices failed")
            return []

    def set_monitor_drivers(self, enabled, hwnd=None):
        """Disable (or re-enable) every monitor in Device Manager. Disabled before launch, VALORANT can't read the
        screen's native 16:9 shape, so it doesn't squeeze the stretched picture back."""
        if not monitors.pnputil_supported():
            monitors.open_device_manager()
            raise StretchError("This Windows version can't do it automatically. Device Manager is open: expand "
                               "Monitors, right-click each monitor and choose Disable device.")
        targets = [dev.instance_id for _, dev in self.monitor_devices() if dev and dev.disabled == enabled]
        if not targets:
            self.notify("info", "Monitor drivers are already " + ("enabled." if enabled else "disabled."))
            return
        try:
            code = monitors.set_enabled(targets, enabled, hwnd)
        except PermissionError as exc:
            raise StretchError(f"{exc} Monitor drivers weren't changed.") from exc
        except OSError as exc:
            raise StretchError(str(exc)) from exc
        still = [dev for _, dev in self.monitor_devices() if dev and dev.instance_id in targets
                 and dev.disabled != (not enabled)]
        if code == 3010 or still:
            self.notify("warning", "Done — restart your PC to finish changing the monitor drivers.")
        elif code != 0:
            raise StretchError(f"pnputil reported error {code}. Try it by hand in Device Manager.")
        else:
            self.notify("success", f"{len(targets)} monitor driver(s) " + ("turned back on." if enabled else
                                                                           "disabled."))
        self.changed.emit()

    # ---- settings file reset ----------------------------------------------

    def reset_configs(self, gid):
        """Video step 3: delete VALORANT's settings files (backed up first) so they start clean."""
        game = self.games[gid]
        if self.running.get(gid):
            raise StretchError(f"Close {game.name} first.")
        done = 0
        for t in self.selected_targets(gid):
            if not t.path.exists():
                continue
            try:
                game.reset_target(t, self.backups)
                done += 1
            except OSError as exc:
                raise StretchError(f"Couldn't reset {self.target_name(gid, t)}: {exc}") from exc
        self.notify("success", f"{done} settings file(s) reset (backed up first). Press Play stretched and "
                               "TrueStretch writes fresh ones with your stretched resolution.")
        self.changed.emit()

    def set_stretch_scaling_now(self, gid):
        """Turn on stretch scaling without stretching the desktop (from the My PC page)."""
        d = self.display_for(gid)
        if not d:
            raise StretchError("No display found.")
        if not displayconfig.set_scaling(d.device, displayconfig.SCALING_STRETCHED):
            raise StretchError("Windows didn't accept the change. Set scaling to Full-screen in your graphics panel.")
        self.notify("success", f"Stretch scaling is on for {d.title}.")
        self.changed.emit()

    def revert_display(self, reason=""):
        if not self.state.stretched:
            return False
        gid = self.state.data.get("game") or next(iter(self.games))
        device = self.state.data.get("device")
        target = self.normal_mode(gid)
        current = display.current_mode(device)
        if target and current and current != target:
            try:
                display.set_mode(target, device)
            except DisplayError as exc:
                self.notify("error", str(exc))
                return False
            self.notify("success", f"Desktop back to {target}" + (f" ({reason})." if reason else "."))
        previous_scaling = self.state.data.get("previous_scaling")
        if previous_scaling is not None and device:
            try:
                displayconfig.set_scaling(device, int(previous_scaling))
            except (OSError, ValueError):
                log.warning("Couldn't put the previous scaling mode back")
        self.state.clear()
        self.changed.emit()
        return True

    def restore(self, gid):
        game, gs = self.games[gid], self.gs(gid)
        if self.running.get(gid):
            raise StretchError(f"Close {game.name} first.")
        normal = self.normal_mode(gid)
        normal_size = normal.size if normal else (1920, 1080)
        for t in self.selected_targets(gid):
            try:
                result = game.restore_target(t, self.backups, normal_size)
                self.notify("info", f"{self.target_name(gid, t)}: {result}.")
            except OSError as exc:
                self.notify("error", f"{self.target_name(gid, t)}: couldn't restore ({exc}).")
        if self.state.stretched:
            self.revert_display("restored")
        else:
            d = self.display_for(gid)
            current = display.current_mode(d.device if d else None)
            if normal and current and current.size == (int(gs["width"]), int(gs["height"])):
                try:
                    display.set_mode(normal, d.device if d else None)
                    self.notify("success", f"Desktop back to {normal}.")
                except DisplayError as exc:
                    self.notify("error", str(exc))
        self.changed.emit()

    def launch(self, gid):
        game = self.games[gid]
        try:
            game.launch(self.info[gid], self.gs(gid))
        except OSError as exc:
            raise StretchError(str(exc)) from exc
        self._launch_started[gid] = time.monotonic()
        self.notify("info", f"Launching {game.name} through the Riot Client…")
        self.changed.emit()

    def is_launching(self, gid):
        return gid in self._launch_started and not self.running.get(gid)

    # ---- watching ---------------------------------------------------------

    def poll(self):
        procs = running_processes()
        for gid, game in self.games.items():
            now, before = game.is_running(procs), self.running.get(gid, False)
            gs = self.gs(gid)
            if now != before:
                self.running[gid] = now
                self.game_state.emit(gid, now)
                if now:
                    self._launch_started.pop(gid, None)
                    self.notify("info", f"{game.name} started.")
                    self._lock_warned.pop(gid, None)
                    if gid in self.watchers:
                        self.watchers[gid].arm()          # the log still holds the last session until replaced
                    if self.is_stretched(gid):
                        self.revert_display(f"{game.name} is starting")   # it must start on the native desktop
                else:
                    self.notify("info", f"{game.name} closed.")
                    if gid in self.watchers:
                        self.watchers[gid].reset()
                    QTimer.singleShot(3000, lambda g=gid: self._after_close(g))   # the game saves as it exits
                    if self.is_stretched(gid) and gs.get("revert_on_exit", True):
                        self.revert_display(f"{game.name} closed")
                self.changed.emit()
            if now and gid in self.watchers:
                self._follow_match(gid)
            elif gid in self._launch_started:
                if time.monotonic() - self._launch_started[gid] > int(gs.get("launch_timeout_min", 10)) * 60:
                    self._launch_started.pop(gid)
                    self.notify("warning", f"{game.name} didn't start in time.")
                    if self.is_stretched(gid) and gs.get("revert_on_exit", True):
                        self.revert_display("game didn't start")
                    self.changed.emit()

    def _follow_match(self, gid):
        watcher = self.watchers[gid]
        changed = watcher.poll()
        self._check_locked(gid, watcher)
        if not changed:
            self._keep_level(gid, watcher)
            return
        gs = self.gs(gid)
        if watcher.in_match:
            if gid in self._first_run:
                return                      # this session still runs on VALORANT's own first-time settings
            if gs.get("auto_match", True) and not self.paused and not self.is_stretched(gid):
                try:
                    self.stretch_now(gid, f"{watcher.map} loaded")
                except StretchError as exc:
                    self.notify("error", str(exc))
        else:
            self.paused = False
            if self.is_stretched(gid):
                self.revert_display("back to the menu")
        self.changed.emit()

    def _after_close(self, gid):
        """After the game exits: set up any account it created or changed (first sign-in, new account, the game or
        another program resetting the resolution), so the next start is stretched without the user doing anything."""
        game, gs = self.games[gid], self.gs(gid)
        if self.running.get(gid) or not gs.get("prepared") or not hasattr(game, "target_ready"):
            return
        first = gid in self._first_run
        self._first_run.discard(gid)
        native = self.native_mode(gid)
        nw, nh = native.size if native else (1920, 1080)
        d = self.display_for(gid)
        monitor = display.monitor_ref(d)
        fixed = []
        for t in self.selected_targets(gid):
            if not t.path.exists() or game.target_ready(t, nw, nh, gs):
                continue
            try:
                game.apply_target(t, nw, nh, gs, self.backups, monitor)
                fixed.append(self.target_name(gid, t))
            except OSError as exc:
                log.warning("Couldn't set up %s after the game closed: %s", t.path, exc)
        if fixed:
            self.notify("success", f"Set up {', '.join(fixed)} for stretching" + (
                " — your first session is done. From the next start VALORANT stretches by itself." if first else
                f" ({game.name} had changed the settings). The next start is stretched again."))
            self.changed.emit()

    def _check_locked(self, gid, watcher):
        """VALORANT re-reads the desktop size at start-up and when agent select loads. If the desktop was stretched
        at that moment (switched by hand, another program), it locks onto that size and won't stretch again until
        it restarts. Say so plainly instead of leaving the player guessing."""
        res = watcher.game_resolution
        if not res or res == self._lock_warned.get(gid):
            return
        gs = self.gs(gid)
        stretched_sizes = {(int(gs["width"]), int(gs["height"]))}
        if self.state.data.get("mode"):
            stretched_sizes.add(tuple(self.state.data["mode"][:2]))
        if res not in stretched_sizes:
            return                       # native, or the player picked something in VALORANT's own menu
        self._lock_warned[gid] = res
        self.notify("warning", f"VALORANT locked itself to {res[0]} × {res[1]} because the screen was stretched "
                               "while it loaded, so it won't stretch this session. Restart VALORANT (Play "
                               "stretched) and it stretches again.")

    def _keep_level(self, gid, watcher):
        """In a match and stretched, but the chosen level changed (tile clicked, app restarted): follow it."""
        if not (watcher.in_match and self.is_stretched(gid)) or self.paused:
            return
        current = display.current_mode(self.state.data.get("device"))
        try:
            wanted = self.ensure_stretch_mode(gid)
        except StretchError:
            return
        if current and current.size != wanted.size:
            try:
                self.stretch_now(gid, "new stretch level")
            except StretchError as exc:
                self.paused = True                 # don't retry every second
                self.notify("error", str(exc))

    def needs_recovery(self):
        return self.state.stretched and not any(self.running.values())

    def shutdown(self):
        self.timer.stop()
        gid = self.state.data.get("game")
        if (self.state.stretched and not any(self.running.values())
                and gid in self.games and self.gs(gid).get("revert_on_app_exit", True)):
            self.revert_display("app closed")
