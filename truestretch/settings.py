"""User settings (settings.json) and the session state used for crash recovery (session.json)."""

import copy
import json
import os
from datetime import datetime

from .paths import SETTINGS_FILE, STATE_FILE, atomic_write_text, log

APP_DEFAULTS = {
    "theme": "dark",                  # dark | light | system
    "start_with_windows": False,
    "start_minimized": False,
    "close_to_tray": True,
    "notifications": True,
    "confirm_display_change": True,
    "confirm_seconds": 15,
    "keep_backups": 15,
    "last_game": "valorant",
    "onboarded": False,
    "auto_update": True,              # ask GitHub for a newer version at start and every few hours
    "match_reports": True,            # a short "how the match ran" note after every match
}


def _merge(defaults, saved):
    out = copy.deepcopy(defaults)
    for key, value in (saved or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


class Settings:
    def __init__(self, game_defaults):
        self._game_defaults = game_defaults
        saved = {}
        try:
            saved = json.loads(SETTINGS_FILE.read_text(encoding="utf-8-sig"))   # tolerate a BOM from editors
        except FileNotFoundError:
            pass
        except (OSError, ValueError) as exc:
            log.warning("settings.json unreadable, using defaults: %s", exc)
            try:
                SETTINGS_FILE.replace(SETTINGS_FILE.with_suffix(".broken.json"))
            except OSError:
                pass
        self.data = {
            "app": _merge(APP_DEFAULTS, saved.get("app")),
            "games": {gid: _merge(d, saved.get("games", {}).get(gid)) for gid, d in game_defaults.items()},
        }

    @property
    def app(self):
        return self.data["app"]

    def game(self, game_id):
        return self.data["games"][game_id]

    def save(self):
        try:
            atomic_write_text(SETTINGS_FILE, json.dumps(self.data, indent=2))
        except OSError as exc:
            log.error("Couldn't save settings: %s", exc)

    def reset(self):
        self.data = {"app": copy.deepcopy(APP_DEFAULTS),
                     "games": {gid: copy.deepcopy(d) for gid, d in self._game_defaults.items()}}
        self.save()


class SessionState:
    """Remembers that the desktop is stretched, so it can be undone even after a crash or reboot."""

    def __init__(self):
        self.data = {}
        try:
            self.data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except FileNotFoundError:
            pass
        except (OSError, ValueError) as exc:
            log.error("session.json unreadable (%s); kept as session.broken.json", exc)
            try:
                STATE_FILE.replace(STATE_FILE.with_suffix(".broken.json"))
            except OSError:
                pass
        if not isinstance(self.data, dict):
            self.data = {}

    @property
    def stretched(self):
        return bool(self.data.get("stretched"))

    def mark_stretched(self, game_id, device, previous, stretched):
        # Keep the very first "previous" mode if we're re-applying while already stretched.
        if not self.stretched:
            self.data["previous"] = previous.to_list() if previous else None
        self.data.update({
            "stretched": True, "game": game_id, "device": device, "owner": os.getpid(),
            "mode": stretched.to_list(), "since": datetime.now().isoformat(timespec="seconds"),
        })
        self._save()

    def remember(self, key, value):
        """Store a value only the first time (e.g. the scaling mode before we changed it)."""
        if key not in self.data:
            self.data[key] = value
            self._save()

    def keep_on_exit(self):
        """The player chose to stay stretched when TrueStretch quits: tell the guard process not to undo it."""
        if self.stretched:
            self.data["keep_on_exit"] = True
            self._save()

    def clear(self):
        self.data = {}
        self._save()

    def _save(self):
        try:
            atomic_write_text(STATE_FILE, json.dumps(self.data, indent=2))
        except OSError as exc:
            log.error("Couldn't save session state: %s", exc)
