"""Match history: every match the player has finished, kept by TrueStretch (VALORANT itself only keeps its last few
session logs, so the history would otherwise disappear after a few days).

Each record is built from VALORANT's own end-of-round statistics (matchperf) plus what TrueStretch knew at the
time: the stretch size in use and whether Optimize Max changes were active. Stored in %APPDATA%\\TrueStretch\\
matches.json, written atomically. Read only towards the game - nothing here changes anything."""

import json
from datetime import datetime

from . import matchperf
from .paths import DATA_DIR, atomic_write_text, log

HISTORY_FILE = DATA_DIR / "matches.json"
KEEP = 300

# VALORANT logs its internal map names. Public mapping (the names Riot uses in its own game files).
MAP_NAMES = {
    "ascent": "Ascent", "duality": "Bind", "triad": "Haven", "bonsai": "Split", "port": "Icebox", "foxtrot": "Breeze",
    "canyon": "Fracture", "pitt": "Pearl", "jam": "Lotus", "juliett": "Sunset", "infinity": "Abyss", "rook": "Corrode",
    "range": "The Range", "poveglia": "The Range",
}


def map_name(raw):
    if not raw:
        return "Unknown map"
    nice = MAP_NAMES.get(raw.lower())
    if nice:
        return nice
    if raw.upper().startswith("HURM_"):
        return "Team Deathmatch"
    return raw


def _iso(dt):
    return dt.isoformat(timespec="seconds") if dt else None


def _parse(text):
    try:
        return datetime.fromisoformat(text) if text else None
    except (TypeError, ValueError):
        return None


def load():
    """Stored records, oldest first ([] when there's no history yet or the file is unreadable)."""
    try:
        data = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
        records = data.get("matches", []) if isinstance(data, dict) else []
    except FileNotFoundError:
        return []
    except (OSError, ValueError) as exc:
        log.warning("matches.json unreadable (%s); starting a new history", exc)
        try:
            HISTORY_FILE.replace(HISTORY_FILE.with_suffix(".broken.json"))
        except OSError:
            pass
        return []
    out = []
    for r in records:
        if isinstance(r, dict) and _parse(r.get("started")) and isinstance(r.get("fps"), (int, float)):
            out.append(r)
    return sorted(out, key=lambda r: r["started"])


def _save(records):
    try:
        atomic_write_text(HISTORY_FILE, json.dumps({"version": 1, "matches": records[-KEEP:]}, indent=1))
    except OSError as exc:
        log.warning("Couldn't save the match history: %s", exc)


def record_of(info, stretch=None, optimized=False, fps_cap=None):
    """A storable record from a matchperf summary."""
    def r(v, n=1):
        return round(v, n) if isinstance(v, (int, float)) else None
    return {
        "started": _iso(info["started"]), "ended": _iso(info["ended"]), "map": info.get("map"),
        "minutes": r(info["minutes"]), "rounds": info["rounds"], "fps": r(info["fps"]),
        "slow_share": r(info.get("slow_share"), 4), "latency": r(info.get("latency"), 2),
        "gpu_busy": r(info.get("gpu_busy"), 3), "memory": r(info.get("memory")), "hitches": info.get("hitches", 0),
        "limit": matchperf.limit(info, fps_cap), "stretch": stretch, "optimized": bool(optimized),
    }


def update(log_dir, stretch=None, optimized_since=None, fps_cap=None):
    """Add every finished match found in VALORANT's logs that isn't stored yet. Returns (all records, new records).
    The stretch size is only known for matches recorded live; older ones found in the logs get None."""
    stored = load()
    known = {r["started"] for r in stored}
    found = matchperf.all_matches(log_dir)
    new = []
    newest_known = max(known) if known else None
    for info in found:
        key = _iso(info["started"])
        if not key or key in known:
            continue
        # Only the newest match can be "the one just played" with today's stretch size; matches older than what we
        # already stored were played before TrueStretch kept a history, so their stretch size is unknown.
        live = newest_known is not None and key > newest_known
        optimized = bool(optimized_since and info["started"] >= optimized_since)
        rec = record_of(info, stretch if live and info is found[-1] else None, optimized, fps_cap)
        new.append(rec)
        known.add(key)
    if new:
        stored = sorted(stored + new, key=lambda r: r["started"])
        _save(stored)
    return stored, new


def refresh_for(engine, gid="valorant"):
    """update() with what the engine knows right now (stretch size, Optimize Max active since, FPS limit).
    Safe to call from a worker thread: it only reads files."""
    from .games.valorant import LOG_DIR
    from .optimizer import Optimizer, _fps_cap
    gs = engine.gs(gid)
    stretch = f"{int(gs['width'])} × {int(gs['height'])}" if gs.get("width") and gs.get("height") else None
    try:
        since = Optimizer(engine).applied_since()
    except Exception:
        since = None
    return update(LOG_DIR, stretch, since, _fps_cap(engine))


def stats(records):
    """Totals for the summary cards: {"matches", "fps", "slow_share", "latency", "minutes"} over the given records
    (time-weighted), values None when unknown."""
    if not records:
        return {"matches": 0, "fps": None, "slow_share": None, "latency": None, "minutes": 0}
    minutes = sum(r.get("minutes") or 0 for r in records)

    def weighted(key):
        rows = [r for r in records if isinstance(r.get(key), (int, float)) and r.get("minutes")]
        total = sum(r["minutes"] for r in rows)
        return sum(r[key] * r["minutes"] for r in rows) / total if total else None
    return {"matches": len(records), "fps": weighted("fps"), "slow_share": weighted("slow_share"),
            "latency": weighted("latency"), "minutes": minutes}


LIMIT_TEXT = {"gpu": "graphics card", "cpu": "processor", "both": "processor + graphics card", "cap": "your FPS limit",
              None: "unknown"}


def report_text(rec):
    """One plain line for the after-match notification."""
    parts = [map_name(rec.get("map")), f"{rec['minutes']:.0f} min", f"{rec['fps']:.0f} FPS average"]
    if rec.get("slow_share") is not None:
        parts.append(f"{rec['slow_share'] * 100:.1f}% slow frames")
    if rec.get("latency") is not None:
        parts.append(f"{rec['latency']:.1f} ms game delay")
    if rec.get("limit"):
        parts.append(f"limited by {LIMIT_TEXT[rec['limit']]}")
    return "Match finished: " + " · ".join(parts) + "."


__all__ = ["load", "update", "stats", "record_of", "report_text", "map_name", "HISTORY_FILE", "LIMIT_TEXT"]
