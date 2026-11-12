"""How VALORANT actually ran in the player's last match, read from the game's own per-round statistics.

At the end of every round VALORANT writes a statistics block into
`%LOCALAPPDATA%\\VALORANT\\Saved\\Logs\\ShooterGame.log` (the previous sessions are kept as
`ShooterGame-backup-<date>.log`):

    [2026.11.12-09.51.52:665][437]LogClientPerRoundTelemetryComponent: End of Round Perf statistics
        Round 0 Performance:
            Avg.Frametime (ms): 4.96
            Total Frames: 26208
            Game Thread Frames Under 1 fps: 0
            Game Thread Frames Over 1 fps: 6        <- frames between 1 and 10 FPS (the buckets add up to Total Frames)
            ...
            Game Thread Frames Over 480 fps: 0
    ...LogClientPerRoundTelemetryComponent:
            Total Time(secs): 129.89
            System Memory Util(mean): 82.89
            GPU Time(mean): 2.05                    <- ms the graphics card worked per frame
            Runtime PSO Hitches: 0                  <- shader-compile stutters

Rounds are numbered from 0 in every match, so "Round 0" starts a new match. The timestamp in brackets is UTC.
Format verified on real logs, release-13.09 and release-13.10, 2026-11-12. Read only."""

import re
from datetime import datetime, timezone
from pathlib import Path

MAX_BYTES = 64 * 1024 * 1024          # a long session's log is ~10 MB; never read something absurd

_START = re.compile(r"\[(\d{4})\.(\d\d)\.(\d\d)-(\d\d)\.(\d\d)\.(\d\d):\d+\]\[\s*\d+\]"
                    r"LogClientPerRoundTelemetryComponent: End of Round Perf statistics")
_ROUND = re.compile(r"^\s*Round (\d+) Performance:")
_VALUE = re.compile(r"^\s+([A-Za-z][A-Za-z0-9 .+()]*?)\s*:\s*(-?\d+(?:\.\d+)?)\s*$")
_BUCKET = re.compile(r"^Game Thread Frames (Under|Over) (\d+) fps$")

GPU_BOUND, CPU_BOUND = 0.80, 0.60     # share of each frame the graphics card was busy


def _utc(m):
    try:
        return datetime(*map(int, m.groups()), tzinfo=timezone.utc).astimezone().replace(tzinfo=None)
    except (ValueError, OverflowError, OSError):
        return None


def parse_rounds(text):
    """[{"round", "time" (local datetime | None), "frametime", "frames", "secs", "gpu", "memory", "hitches",
    "buckets": {(lo FPS): frames}}] for every complete round block in the text, in order."""
    rounds, cur = [], None
    for line in text.splitlines():
        m = _START.search(line)
        if m:
            cur = {"time": _utc(m), "round": None, "buckets": {}}
            continue
        if cur is None:
            continue
        if line.startswith("["):                     # a normal log line; the block's continuation lines don't count
            if "LogClientPerRoundTelemetryComponent:" not in line:
                if cur["round"] is not None:
                    rounds.append(cur)
                cur = None
            continue
        m = _ROUND.match(line)
        if m:
            cur["round"] = int(m.group(1))
            continue
        m = _VALUE.match(line)
        if not m:
            continue
        name, value = m.group(1).strip(), float(m.group(2))
        b = _BUCKET.match(name)
        if b:
            cur["buckets"][0 if b.group(1) == "Under" else int(b.group(2))] = int(value)
            continue
        key = {"Avg.Frametime (ms)": "frametime", "Total Frames": "frames", "Total Time(secs)": "secs",
               "GPU Time(mean)": "gpu", "System Memory Util(mean)": "memory", "Runtime PSO Hitches": "hitches"}.get(name)
        if key:
            cur[key] = value
    if cur is not None and cur["round"] is not None:
        rounds.append(cur)
    return [r for r in rounds if r.get("frames") and r.get("secs")]


def last_match(rounds):
    """The rounds of the last match in the list (from its last 'Round 0'), or []."""
    starts = [n for n, r in enumerate(rounds) if r["round"] == 0]
    return rounds[starts[-1]:] if starts else rounds


def summary(match):
    """{"fps", "rounds", "minutes", "gpu_busy" (0..1 | None), "slow_share" (frames under 60 FPS, 0..1 | None),
    "memory" (% | None), "hitches", "ended"} for one match, or None."""
    if not match:
        return None
    frames = sum(r["frames"] for r in match)
    secs = sum(r["secs"] for r in match)
    if frames <= 0 or secs <= 0:
        return None
    frame_ms = 1000.0 * secs / frames
    timed = [r for r in match if r.get("gpu") is not None]
    gpu_ms = (sum(r["gpu"] * r["frames"] for r in timed) / sum(r["frames"] for r in timed)) if timed else None
    bucketed = [r for r in match if r["buckets"] and sum(r["buckets"].values()) == int(r["frames"])]
    slow = None
    if bucketed:
        total = sum(r["frames"] for r in bucketed)
        slow = sum(n for r in bucketed for lo, n in r["buckets"].items() if lo < 60) / total
    mem = [r["memory"] for r in match if r.get("memory") is not None]
    return {"fps": frames / secs, "rounds": len(match), "minutes": secs / 60.0,
            "gpu_busy": min(1.0, gpu_ms / frame_ms) if gpu_ms is not None and frame_ms > 0 else None,
            "slow_share": slow, "memory": max(mem) if mem else None,
            "hitches": int(sum(r.get("hitches", 0) for r in match)), "ended": match[-1]["time"]}


def limit(info, fps_cap=None):
    """What sets the FPS: "cap" (the in-game FPS limit), "gpu", "cpu", "both" or None (unknown)."""
    if not info:
        return None
    if fps_cap and info["fps"] >= 0.95 * fps_cap:
        return "cap"
    busy = info["gpu_busy"]
    if busy is None:
        return None
    if busy >= GPU_BOUND:
        return "gpu"
    return "cpu" if busy <= CPU_BOUND else "both"


def _read(path):
    try:
        with open(path, "rb") as f:
            return f.read(MAX_BYTES).decode("utf-8", "replace")
    except OSError:
        return ""


def latest(log_dir):
    """summary() of the last match in the newest log that has one (current log first, then backups), or None."""
    log_dir = Path(log_dir)
    try:
        backups = sorted(log_dir.glob("ShooterGame-backup-*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
    except OSError:
        backups = []
    for path in [log_dir / "ShooterGame.log"] + backups[:5]:
        match = last_match(parse_rounds(_read(path)))
        info = summary(match)
        if info:
            info["file"] = path.name
            return info
    return None


__all__ = ["parse_rounds", "last_match", "summary", "limit", "latest"]
