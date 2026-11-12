"""VALORANT support: finds the install, the per-account configs, and applies true stretched res."""

import json
import os
import re
import subprocess
import winreg
from datetime import datetime
from pathlib import Path

from ..inifile import IniFile, is_read_only, set_read_only
from ..system import fixed_drives, flag_value, flags_with, reg_get, reg_delete, reg_set
from .base import ConfigTarget, Game, InstallInfo, Preset, Tweak

SECTION = "/Script/ShooterGame.ShooterGameUserSettings"
UNINSTALL_PATHS = [
    (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Uninstall\Riot Game valorant.live"),
    (winreg.HKEY_LOCAL_MACHINE, r"Software\Microsoft\Windows\CurrentVersion\Uninstall\Riot Game valorant.live"),
    (winreg.HKEY_LOCAL_MACHINE, r"Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\Riot Game valorant.live"),
]
PROGRAM_DATA = Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData"))
RIOT_METADATA = PROGRAM_DATA / "Riot Games" / "Metadata" / "valorant.live"
RIOT_INSTALLS = PROGRAM_DATA / "Riot Games" / "RiotClientInstalls.json"
CONFIG_ROOT = Path(os.environ.get("LOCALAPPDATA", "")) / "VALORANT" / "Saved" / "Config"
LOG_DIR = Path(os.environ.get("LOCALAPPDATA", "")) / "VALORANT" / "Saved" / "Logs"
GAME_EXE_REL = Path("ShooterGame") / "Binaries" / "Win64" / "VALORANT-Win64-Shipping.exe"
COMMON_INSTALL_DIRS = [r"Riot Games\VALORANT\live", r"Program Files\Riot Games\VALORANT\live",
                       r"Games\Riot Games\VALORANT\live", r"Games\VALORANT\live"]
COMMON_CLIENT_PATHS = [r"Riot Games\Riot Client\RiotClientServices.exe",
                       r"Program Files\Riot Games\Riot Client\RiotClientServices.exe",
                       r"Games\Riot Games\Riot Client\RiotClientServices.exe"]

LAYERS_KEY = r"Software\Microsoft\Windows NT\CurrentVersion\AppCompatFlags\Layers"
GPU_PREF_KEY = r"Software\Microsoft\DirectX\UserGpuPreferences"
FSO_FLAG = "DISABLEDXMAXIMIZEDWINDOWEDMODE"
MAP_RE = re.compile(r"LogMapLoadModel: Update: \[Map Name: ([^|\]]*)\|.*?\[Map Ready: (TRUE|FALSE)")
# Leaving a match/the Range. A match found while in the Range logs Pregame_GetMatch ~7 s before agent select
# loads; VALORANT re-reads the desktop size when agent select loads, so the desktop must be native by then.
LEAVE_RE = re.compile(r"Transitioning from InGame to |QueryName: \[Pregame_GetMatch\]")
RES_RE = re.compile(r"LogShooterGameUserSettings: Resolution changed to: \[(\d+) x (\d+)\]")
ACCOUNT_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}-\w+$", re.I)
VERSION_RE = re.compile(r"Branch: release-([\d.]+)")
UUID_RE = re.compile(r"Logged in user changed: ([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})", re.I)


def _existing(path):
    return Path(path) if path and Path(path).exists() else None


def _clean(path):
    return str(path).strip().strip('"').replace("/", "\\") if path else None


class Valorant(Game):
    id = "valorant"
    name = "VALORANT"
    publisher = "Riot Games"
    process_names = ("VALORANT-Win64-Shipping.exe",)
    # How much wider models get. Measured in The Range (13.09): with the desktop switched after the map loads,
    # VALORANT crops the sides at every one of these (scale 1.00) instead of squeezing the picture back - the
    # 1.45:1 limit from the videos only applies when the resolution is set before launch.
    STRETCH_LEVELS = [(1.225, "Light"), (1.333, "Classic 4:3"), (1.5, "Strong"), (1.778, "Extreme")]

    def presets_for(self, native_width=1920, native_height=1080):
        w0, h = native_width or 1920, native_height or 1080
        return [Preset(round(w0 / f / 8) * 8, h, f"{f:.2f}× wider", note) for f, note in self.STRETCH_LEVELS]

    @property
    def presets(self):
        return self.presets_for(1920, 1080)
    window_modes = {"windowed_fullscreen": ("Windowed fullscreen", 1), "fullscreen": ("Fullscreen", 0),
                    "windowed": ("Windowed", 2)}
    MENU_MAPS = ("Init", "MainMenuV2", "MainMenu", "CharacterSelectPersistentLevel", "Menu")

    # ---- match detection (VALORANT's own log) ------------------------------

    @staticmethod
    def parse_log_line(line):
        """("map", name, ready) | ("leave",) | ("resolution", w, h) | None"""
        m = MAP_RE.search(line)
        if m:
            return "map", m.group(1).strip(), m.group(2) == "TRUE"
        if LEAVE_RE.search(line):
            return ("leave",)
        m = RES_RE.search(line)
        if m:
            return "resolution", int(m.group(1)), int(m.group(2))
        return None

    def match_watcher(self):
        from ..matchwatch import MatchWatcher
        return MatchWatcher(LOG_DIR / "ShooterGame.log", self.parse_log_line, self.MENU_MAPS)
    patchlines = {"live": "Live", "pbe": "PBE (test server)"}

    def default_settings(self):
        return {
            "width": 1440, "height": 1080, "refresh": "max",
            "window_mode": "windowed_fullscreen", "lock_config": False, "auto_match": True,
            "display": "primary", "normal": "previous",
            "revert_on_exit": True, "revert_on_app_exit": True,
            "patchline": "live", "launch_timeout_min": 10,
            "excluded": [], "nicknames": {}, "gpu_scaling_confirmed": False,
            "auto_scaling": True,
        }

    # ---- detection --------------------------------------------------------

    def detect(self):
        info = InstallInfo(config_root=CONFIG_ROOT if CONFIG_ROOT.is_dir() else None)

        for root, path in UNINSTALL_PATHS:
            location = reg_get(root, path, "InstallLocation")
            if location and Path(_clean(location)).is_dir():
                info.install_dir = Path(_clean(location))
                info.found_via = "Windows uninstall registry"
                info.icon = _existing(_clean(reg_get(root, path, "DisplayIcon")))
                uninstall = reg_get(root, path, "UninstallString") or ""
                match = re.match(r'\s*"([^"]+)"', uninstall)
                info.launcher = _existing(_clean(match.group(1))) if match else None
                break

        settings_yaml = RIOT_METADATA / "valorant.live.product_settings.yaml"
        try:
            text = settings_yaml.read_text(encoding="utf-8", errors="replace")
            region = re.search(r'^\s*region:\s*"?([^"\n]+)"?', text, re.M)
            info.region = region.group(1).strip() if region else None
            if not info.install_dir:
                path = re.search(r'^product_install_full_path:\s*"?([^"\n]+)"?', text, re.M)
                if path and Path(_clean(path.group(1))).is_dir():
                    info.install_dir = Path(_clean(path.group(1)))
                    info.found_via = "Riot product settings"
        except OSError:
            pass

        try:
            installs = json.loads(RIOT_INSTALLS.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            installs = {}
        if not info.install_dir:
            for game_dir, client in (installs.get("associated_client") or {}).items():
                if "valorant" in game_dir.lower() and Path(_clean(game_dir)).is_dir():
                    info.install_dir = Path(_clean(game_dir))
                    info.found_via = "Riot Client installs list"
                    info.launcher = info.launcher or _existing(_clean(client))
                    break
        if not info.launcher:
            for key in ("rc_live", "rc_default"):
                info.launcher = _existing(_clean(installs.get(key)))
                if info.launcher:
                    break

        drives = fixed_drives()
        if not info.install_dir:
            for drive in drives:
                for rel in COMMON_INSTALL_DIRS:
                    candidate = Path(drive) / rel
                    if (candidate / GAME_EXE_REL).is_file():
                        info.install_dir, info.found_via = candidate, "drive scan"
                        break
                if info.install_dir:
                    break
        if not info.launcher:
            for drive in drives:
                for rel in COMMON_CLIENT_PATHS:
                    if (Path(drive) / rel).is_file():
                        info.launcher = Path(drive) / rel
                        break
                if info.launcher:
                    break

        if info.install_dir:
            info.game_exe = _existing(info.install_dir / GAME_EXE_REL)
        info.icon = info.icon or _existing(RIOT_METADATA / "valorant.live.ico")
        if not info.icon and info.install_dir:
            info.extra["exe_for_icon"] = _existing(info.install_dir / "VALORANT.exe")
        info.installed = bool(info.install_dir)
        info.extra["last_signed_in"], info.extra["version"] = self._read_log()
        return info

    def _read_log(self):
        """The account Valorant last logged into and the game version, from Valorant's own log."""
        if not LOG_DIR.is_dir():
            return None, None
        logs = sorted((p for p in LOG_DIR.glob("ShooterGame*.log") if p.stat().st_size > 0),
                      key=lambda p: p.stat().st_mtime, reverse=True)
        account = version = None
        for log_file in logs[:3]:
            try:
                with open(log_file, "r", encoding="utf-8", errors="replace") as f:
                    head = f.read(3_000_000)
            except OSError:
                continue
            if not version:
                m = VERSION_RE.search(head)
                version = m.group(1) if m else None
            ids = UUID_RE.findall(head)
            if ids and not account:
                account = ids[-1].lower()
            if account and version:
                break
        return account, version

    def current_settings(self, info):
        """What VALORANT is set to right now, for the account that signed in last."""
        targets = [t for t in self.targets(info) if t.path.exists()]
        target = next((t for t in targets if t.last_signed_in), None) or next(
            (t for t in targets if not t.is_default), None)
        if not target:
            return None
        try:
            v = IniFile(target.path).get(SECTION, [
                "ResolutionSizeX", "ResolutionSizeY", "bShouldLetterbox", "LastConfirmedFullscreenMode",
                "FullscreenMode", "FrameRateLimit", "bUseVSync", "DefaultMonitorIndex", "DefaultMonitorDeviceID"])
        except OSError:
            return None
        mode_num = v.get("FullscreenMode", v.get("LastConfirmedFullscreenMode", "0"))
        mode = next((name for name, num in self.window_modes.values() if str(num) == mode_num), "Fullscreen")
        try:
            fps = float(v.get("FrameRateLimit", "0"))
        except ValueError:
            fps = 0
        black_bars = v.get("bShouldLetterbox", "True").lower() != "false"
        return {
            # 2026 method: the game runs Windowed Fullscreen + Fill; the desktop is stretched during matches.
            "ready": not black_bars and mode_num == "1",
            "fill": not black_bars,
            "account": target, "resolution": f"{v.get('ResolutionSizeX', '?')} × {v.get('ResolutionSizeY', '?')}",
            "black_bars": v.get("bShouldLetterbox", "True").lower() != "false", "mode": mode,
            "fps_limit": f"{fps:.0f} FPS" if fps > 0 else "Unlimited",
            "vsync": v.get("bUseVSync", "False").lower() == "true",
        }

    # ---- config files -----------------------------------------------------

    def targets(self, info):
        if not CONFIG_ROOT.is_dir():
            return []
        last = info.extra.get("last_signed_in")
        found = []
        for folder in CONFIG_ROOT.iterdir():
            if not folder.is_dir() or folder.name == "CrashReportClient":
                continue
            if folder.name in ("WindowsClient", "Windows"):
                ini = folder / "GameUserSettings.ini"
                found.append(self._target("_default", "Default for new accounts", ini, is_default=True))
                continue
            for sub in ("WindowsClient", "Windows"):
                ini = folder / sub / "GameUserSettings.ini"
                # A reset (deleted) file still counts for real account folders: Play stretched writes a fresh one.
                if ini.is_file() or (ini.parent.is_dir() and sub == "WindowsClient" and ACCOUNT_RE.match(folder.name)):
                    ident, _, region = folder.name.rpartition("-")
                    ident = ident or folder.name
                    label = f"Account {ident[:8]}" + (f" \u00b7 {region.upper()}" if region else "")
                    found.append(self._target(folder.name, label, ini,
                                              last_signed_in=bool(last and folder.name.lower().startswith(last))))
                    break
        found.sort(key=lambda t: (t.is_default, -t.last_used.timestamp()))
        return found

    def _target(self, key, label, path, **kw):
        if not path.exists():
            when = path.parent.stat().st_mtime if path.parent.exists() else 0
            return ConfigTarget(key=key, label=label, path=path, last_used=datetime.fromtimestamp(when),
                                current="reset \u2014 fresh file on next Play", stretched=False, read_only=False, **kw)
        try:
            v = IniFile(path).get(SECTION, ["ResolutionSizeX", "ResolutionSizeY", "bShouldLetterbox"])
        except OSError:
            v = {}
        stretched = v.get("bShouldLetterbox", "").lower() == "false"
        res = f"{v.get('ResolutionSizeX', '?')} \u00d7 {v.get('ResolutionSizeY', '?')}"
        return ConfigTarget(key=key, label=label, path=path,
                            last_used=datetime.fromtimestamp(path.stat().st_mtime),
                            current=f"{res} \u00b7 {'stretched' if stretched else 'black bars'}",
                            stretched=stretched, read_only=is_read_only(path), **kw)

    @staticmethod
    def resolution_values(width, height, letterbox, window_mode=None):
        values = {
            "bShouldLetterbox": str(letterbox),
            "bLastConfirmedShouldLetterbox": str(letterbox),
            "ResolutionSizeX": width, "ResolutionSizeY": height,
            "LastUserConfirmedResolutionSizeX": width, "LastUserConfirmedResolutionSizeY": height,
            "DesiredScreenWidth": width, "DesiredScreenHeight": height,
            "LastUserConfirmedDesiredScreenWidth": width, "LastUserConfirmedDesiredScreenHeight": height,
        }
        if window_mode is not None:
            values.update({"FullscreenMode": window_mode, "LastConfirmedFullscreenMode": window_mode,
                           "PreferredFullscreenMode": window_mode})
        return values

    def target_ready(self, target, width, height, settings):
        """True when this account's file already has the size, Fill and window mode TrueStretch needs."""
        mode_value = self.window_modes.get(settings.get("window_mode"), ("", 0))[1]
        try:
            v = IniFile(target.path).get(SECTION, ["bShouldLetterbox", "FullscreenMode", "ResolutionSizeX",
                                                   "ResolutionSizeY"])
        except OSError:
            return True                                     # unreadable: leave it alone
        return (v.get("bShouldLetterbox", "").lower() == "false" and str(v.get("FullscreenMode")) == str(mode_value)
                and str(v.get("ResolutionSizeX")) == str(width) and str(v.get("ResolutionSizeY")) == str(height))

    def apply_target(self, target, width, height, settings, backups, monitor=None):
        mode_value = self.window_modes.get(settings.get("window_mode"), ("", 0))[1]
        values = self.resolution_values(width, height, False, mode_value)
        # With the monitor drivers disabled VALORANT itself saves an empty monitor and index -1; match that so it
        # doesn't go looking for a screen it can't see. With them on, point it at the right screen.
        device_id, index = monitor if monitor else ("", -1)
        quoted = '"' + device_id.replace("\\", "\\\\") + '"' if device_id else ""
        values.update({"DefaultMonitorDeviceID": quoted, "LastConfirmedDefaultMonitorDeviceID": quoted,
                       "DefaultMonitorIndex": index, "LastConfirmedDefaultMonitorIndex": index})
        if target.path.exists():
            set_read_only(target.path, False)
            backups.create(self.id, target.key, target.label, target.path)
        else:
            target.path.parent.mkdir(parents=True, exist_ok=True)   # after a reset: VALORANT fills in the rest
        ini = IniFile(target.path)
        ini.set(SECTION, values)
        ini.save()
        check = IniFile(target.path).get(SECTION, values)
        if any(str(check.get(k)) != str(v) for k, v in values.items()):
            raise OSError("the file didn't keep the new values after saving")
        if settings.get("lock_config", False):
            set_read_only(target.path, True)
        self._sync_optimizer_copies(target, values, backups)

    @staticmethod
    def optimizer_copies(target):
        """Copies of this settings file kept by other programs that put them back later - HP OMEN Gaming Hub's
        OMEN AI keeps one in WindowsClient\\OmenAI\\<n>\\GameUserSettings.ini."""
        folder = target.path.parent / "OmenAI"
        return sorted(folder.glob("*/GameUserSettings.ini")) if folder.is_dir() else []

    def _sync_optimizer_copies(self, target, values, backups):
        """Write the same display values into those copies, so when OMEN AI restores its copy it restores ours."""
        for i, copy in enumerate(self.optimizer_copies(target)):
            try:
                set_read_only(copy, False)
                backups.create(self.id, f"{target.key}-omenai-{i}", f"{target.label} (OMEN AI copy)", copy)
                ini = IniFile(copy)
                ini.set(SECTION, values)
                ini.save()
            except OSError:
                pass

    def reset_target(self, target, backups):
        """Delete the file (after a backup) - VALORANT or the next Play stretched makes a clean one."""
        set_read_only(target.path, False)
        backups.create(self.id, target.key, target.label, target.path)
        target.path.unlink()

    def restore_target(self, target, backups, normal_size):
        for i, copy in enumerate(self.optimizer_copies(target)):     # OMEN AI's copies go back too
            original = backups.original(self.id, f"{target.key}-omenai-{i}")
            if original:
                try:
                    set_read_only(copy, False)
                    copy.write_bytes(original.read_bytes())
                except OSError:
                    pass
        if not target.path.exists():
            original = backups.original(self.id, target.key)
            if original:
                target.path.write_bytes(original.read_bytes())
                return "restored from the original backup"
            return "nothing to restore (file was reset and never recreated)"
        set_read_only(target.path, False)
        original = backups.original(self.id, target.key)
        if original:
            ini_text = original.read_bytes()
            target.path.write_bytes(ini_text)
            return "restored from the original backup"
        ini = IniFile(target.path)
        ini.set(SECTION, self.resolution_values(normal_size[0], normal_size[1], True))
        ini.save()
        return f"no backup found, reset to {normal_size[0]} \u00d7 {normal_size[1]} with black bars"

    # ---- Windows tweaks ---------------------------------------------------

    def tweaks(self, info):
        exe = str(info.game_exe) if info.game_exe else None
        reason = None if exe else "VALORANT's game files weren't found on this PC."

        def fso_on():
            value = reg_get(winreg.HKEY_CURRENT_USER, LAYERS_KEY, exe, "") if exe else ""
            return FSO_FLAG in (value or "").upper().split()

        def fso_set(on):
            flags = [f for f in (reg_get(winreg.HKEY_CURRENT_USER, LAYERS_KEY, exe, "") or "").split()
                     if f != "~" and f.upper() != FSO_FLAG]
            if on:
                flags.append(FSO_FLAG)
            if flags:
                reg_set(winreg.HKEY_CURRENT_USER, LAYERS_KEY, exe, "~ " + " ".join(flags))
            else:
                reg_delete(winreg.HKEY_CURRENT_USER, LAYERS_KEY, exe)

        def gpu_on():
            value = reg_get(winreg.HKEY_CURRENT_USER, GPU_PREF_KEY, exe, "") if exe else ""
            return flag_value(value, "GpuPreference") == "2"

        def gpu_set(on):
            # Windows stores other per-app flags in the same string (AutoHDREnable, AppStatus): keep them.
            raw = reg_get(winreg.HKEY_CURRENT_USER, GPU_PREF_KEY, exe, "") or ""
            new = flags_with(raw, "GpuPreference", "2" if on else None)
            if new:
                reg_set(winreg.HKEY_CURRENT_USER, GPU_PREF_KEY, exe, new)
            else:
                reg_delete(winreg.HKEY_CURRENT_USER, GPU_PREF_KEY, exe)

        return [
            Tweak("fso", "Disable fullscreen optimizations",
                  "Makes Windows run VALORANT in true exclusive fullscreen, which stretched res needs on some PCs.",
                  fso_on, fso_set, reason),
            Tweak("gpu", "Always use the high-performance graphics card",
                  "For laptops and PCs with two graphics cards: forces VALORANT onto the faster one.",
                  gpu_on, gpu_set, reason),
        ]

    # ---- launching --------------------------------------------------------

    def launch(self, info, settings):
        if not info.launcher:
            raise FileNotFoundError("The Riot Client (RiotClientServices.exe) wasn't found on this PC.")
        patchline = settings.get("patchline", "live")
        subprocess.Popen([str(info.launcher), "--launch-product=valorant", f"--launch-patchline={patchline}"])
