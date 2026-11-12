"""What every supported game provides. Add a new game by subclassing Game and listing it in games/__init__.py."""

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


@dataclass
class InstallInfo:
    installed: bool = False
    install_dir: Path = None
    game_exe: Path = None
    launcher: Path = None
    config_root: Path = None
    icon: Path = None
    region: str = None
    found_via: str = None
    extra: dict = field(default_factory=dict)


@dataclass
class ConfigTarget:
    """One config file the game reads (for Valorant: one per account, plus the default template)."""
    key: str
    label: str
    path: Path
    last_used: datetime
    current: str            # human summary of what it's set to now
    stretched: bool
    read_only: bool
    is_default: bool = False
    last_signed_in: bool = False


@dataclass
class Tweak:
    """An optional Windows setting for the game, shown as a toggle."""
    id: str
    title: str
    description: str
    is_on: callable
    set_on: callable
    unavailable_reason: str = None


@dataclass
class Preset:
    width: int
    height: int
    aspect: str
    note: str = ""


@dataclass
class GuideStep:
    title: str
    detail: str


class Game:
    id = ""
    name = ""
    publisher = ""
    process_names = ()
    coming_soon = False
    presets = []
    window_modes = {}
    patchlines = {}

    def default_settings(self):
        return {}

    def detect(self) -> InstallInfo:
        raise NotImplementedError

    def targets(self, info) -> list:
        return []

    def apply_target(self, target, width, height, settings, backups, monitor=None):
        """monitor: (Windows monitor device id, display index) of the screen the game should use, or None."""
        raise NotImplementedError

    def restore_target(self, target, backups, normal_size):
        raise NotImplementedError

    def tweaks(self, info) -> list:
        return []

    def launch(self, info, settings):
        raise NotImplementedError

    def is_running(self, processes):
        return any(p.lower() in processes for p in self.process_names)


class ComingSoon(Game):
    coming_soon = True

    def __init__(self, game_id, name, publisher):
        self.id, self.name, self.publisher = game_id, name, publisher

    def detect(self):
        return InstallInfo()
