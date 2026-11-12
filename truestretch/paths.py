"""Where TrueStretch keeps its files, and logging setup."""

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from . import APP_NAME

DATA_DIR = Path(os.environ.get("APPDATA") or Path.home()) / APP_NAME
BACKUP_DIR = DATA_DIR / "backups"
LOG_DIR = DATA_DIR / "logs"
SETTINGS_FILE = DATA_DIR / "settings.json"
STATE_FILE = DATA_DIR / "session.json"
LOG_FILE = LOG_DIR / "truestretch.log"

log = logging.getLogger(APP_NAME)


def is_frozen():
    return getattr(sys, "frozen", False) or "__compiled__" in globals()


def resource_path(relative):
    """Path to a bundled file, both from source and inside the packaged .exe."""
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return Path(base) / relative
    return Path(__file__).resolve().parent.parent / relative


def setup_logging():
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(LOG_FILE, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s  %(levelname)-7s  %(message)s"))
    log.setLevel(logging.INFO)
    log.addHandler(handler)
    if not is_frozen():
        log.addHandler(logging.StreamHandler())
