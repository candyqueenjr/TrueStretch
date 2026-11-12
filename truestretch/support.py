"""Support file: a zip with what's needed to understand a problem on someone else's PC - TrueStretch's own logs and
settings, a PC summary, and only the display-related lines of VALORANT's log (no chat, names or account ids)."""

import json
import os
import re
import zipfile
from datetime import datetime
from pathlib import Path

from . import APP_NAME, VERSION, display, displayconfig
from .paths import LOG_DIR, SETTINGS_FILE, STATE_FILE

GAME_LOG_DIR = Path(os.environ.get("LOCALAPPDATA", "")) / "VALORANT" / "Saved" / "Logs"
KEEP = re.compile(r"LogMapLoadModel: Update|Transitioning from|Resolution changed to|Log file open|Branch: release|"
                  r"QueryName: \[Pregame_GetMatch\]|LogShooterGameUserSettings|ForceLetterbox")
UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)
URL = re.compile(r"https?://\S+")


def _desktop():
    for env in ("USERPROFILE",):
        base = os.environ.get(env)
        for sub in ("Desktop", "OneDrive\\Desktop"):
            if base and (Path(base) / sub).is_dir():
                return Path(base) / sub
    return Path.home()


def _scrub(text):
    return URL.sub("<url>", UUID.sub("<id>", text))


def _game_log_lines(path, limit=4000):
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    return "\n".join(_scrub(line) for line in lines if KEEP.search(line))[-limit * 200:]


def summary(engine):
    pc = getattr(engine, "pc", None)
    out = {"app": APP_NAME, "version": VERSION, "created": datetime.now().isoformat(timespec="seconds"),
           "displays": [], "monitors": [], "games": {}}
    for d in display.list_displays():
        out["displays"].append({"device": d.device, "name": d.title, "gpu": d.gpu, "vendor": d.vendor,
                                "native": d.native, "current": str(display.current_mode(d.device))})
    for m in displayconfig.monitors():
        out["monitors"].append({"device": m.device, "name": m.name, "connection": m.connection,
                                "native": m.native, "hz": m.native_hz, "scaling": m.scaling})
    for gid in engine.games:
        gs = engine.gs(gid)
        out["games"][gid] = {"settings": {k: v for k, v in gs.items() if k not in ("nicknames",)},
                             "running": engine.running.get(gid), "checks": [
                                 (c.key, c.ok, c.detail) for c in engine.checks(gid)]}
    if pc is not None:
        out["pc"] = {k: str(v) for k, v in vars(pc).items()} if hasattr(pc, "__dict__") else str(pc)
    return out


def create_support_file(engine):
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = _desktop() / f"TrueStretch-support-{stamp}.zip"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("summary.json", json.dumps(summary(engine), indent=2, default=str))
        for f in sorted(LOG_DIR.glob("truestretch.log*")):
            z.write(f, f"logs/{f.name}")
        for f in (SETTINGS_FILE, STATE_FILE):
            if f.is_file():
                z.write(f, f.name)
        logs = sorted(GAME_LOG_DIR.glob("ShooterGame*.log"), key=lambda p: p.stat().st_mtime, reverse=True)[:2]
        for f in logs:
            z.writestr(f"valorant/{f.stem}-display.txt", _game_log_lines(f))
    return path
