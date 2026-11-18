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
from datetime import datetime, timedelta, timezone
from pathlib import Path

MAX_BYTES = 64 * 1024 * 1024          # a long session's log is ~10 MB; never read something absurd

_START = re.compile(r"\[(\d{4})\.(\d\d)\.(\d\d)-(\d\d)\.(\d\d)\.(\d\d):\d+\]\[\s*\d+\]"
                    r"LogClientPerRoundTelemetryComponent: End of Round Perf statistics")
_ROUND = re.compile(r"^\s*Round (\d+) Performance:")
_VALUE = re.compile(r"^\s+([A-Za-z][A-Za-z0-9 .+()]*?)\s*:\s*(-?\d+(?:\.\d+)?)\s*$")
_BUCKET = re.compile(r"^Game Thread Frames (Under|Over) (\d+) fps$")

GPU_BOUND, CPU_BOUND = 0.80, 0.60     # share of each frame the graphics card was busy
COMPARE_KEEP = 5                      # before/after Optimize Max: at most the 5 nearest matches on each side
COMPARE_MIN_MINUTES = 5.0             # ... and at least 5 minutes of play on each side, or no comparison


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


def split_matches(rounds):
    """The rounds cut into matches: a new match starts at every 'Round 0'."""
    matches = []
    for r in rounds:
        if r["round"] == 0 or not matches:
            matches.append([])
        matches[-1].append(r)
    return matches


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
            "hitches": int(sum(r.get("hitches", 0) for r in match)), "ended": match[-1]["time"],
            "started": _started(match[0])}


def _started(first):
    """Local start time of a match: the end of its first round minus that round's length (None if unknown)."""
    try:
        return first["time"] - timedelta(seconds=first["secs"]) if first["time"] else None
    except (OverflowError, TypeError):
        return None


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
    for path in _logs(log_dir, backups=5):
        match = last_match(parse_rounds(_read(path)))
        info = summary(match)
        if info:
            info["file"] = path.name
            return info
    return None


def _logs(log_dir, backups=10):
    log_dir = Path(log_dir)
    try:
        olds = sorted(log_dir.glob("ShooterGame-backup-*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
    except OSError:
        olds = []
    return [log_dir / "ShooterGame.log"] + olds[:backups]


def all_matches(log_dir):
    """summary() of every match in the current log and the backups VALORANT keeps, oldest first, without
    duplicates."""
    seen, out = set(), []
    for path in _logs(log_dir):
        for match in split_matches(parse_rounds(_read(path))):
            info = summary(match)
            if info and info["started"] and info["ended"] and (info["started"], info["ended"]) not in seen:
                seen.add((info["started"], info["ended"]))
                info["file"] = path.name
                out.append(info)
    return sorted(out, key=lambda m: m["started"])


def _average(matches):
    """Time-weighted average FPS (= all frames / all seconds) and total minutes of a list of match summaries."""
    minutes = sum(m["minutes"] for m in matches)
    return (sum(m["fps"] * m["minutes"] for m in matches) / minutes if minutes > 0 else None), minutes


def compare(matches, since, keep=COMPARE_KEEP, min_minutes=COMPARE_MIN_MINUTES):
    """Average FPS of the matches before vs after `since` (the first Optimize Max change, local datetime):
    {"before", "after" (FPS), "n_before", "n_after", "change" (after / before - 1)} or None when either side has no
    match or less than `min_minutes` of play. A match that was running at `since` counts on neither side."""
    if not since:
        return None
    before = [m for m in matches if m["ended"] < since][-keep:]
    after = [m for m in matches if m["started"] >= since][-keep:]
    if not before or not after:
        return None
    fb, mb = _average(before)
    fa, ma = _average(after)
    if not fb or not fa or mb < min_minutes or ma < min_minutes:
        return None
    return {"before": fb, "after": fa, "n_before": len(before), "n_after": len(after), "change": fa / fb - 1.0}


__all__ = ["parse_rounds", "last_match", "split_matches", "summary", "limit", "latest", "all_matches", "compare"]
