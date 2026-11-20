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
            Avg. Engine Latency (ms): 6.13          <- the game's own part of the input delay per frame
            Avg. Work (ms): 4.83                    <- (always = Work + Slop + Slack, checked on 395 real rounds)
            Avg. Slop (ms): 0.17
            Avg. Slack (ms): 1.14
    ...LogClientPerRoundTelemetryComponent:
            Total Time(secs): 129.89
            Valorant CPU Util(mean): 429.70         <- % of ONE processor thread, summed over threads (430 = 4.3 threads)
            System CPU Util(mean): 56.23            <- % of ALL threads in use (every program; always >= VALORANT's share)
            System Memory Util(mean): 82.89         <- % of the PC's memory in use (all programs)
            Valorant Memory Util(mean): 14.05       <- % of the PC's memory VALORANT itself used
            Valorant Memory MB(mean): 2251.27       <- the same in MB (MB / % = the PC's total memory)
            GPU Time(mean): 2.05                    <- ms the graphics card worked per frame
            Runtime PSO Hitches: 0                  <- shader-compile stutters

Rounds are numbered from 0 in every match, so "Round 0" starts a new match. The timestamp in brackets is UTC.
Format verified on real logs, release-13.09 and release-13.10, 2026-11-12 (the VALORANT memory lines
2026-11-18, the engine latency line 2026-11-19, the two CPU lines 2026-11-20 - VALORANT's figure never exceeded
thread count x the system figure on 395 real rounds). Read only."""

import os
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
    """[{"round", "time" (local datetime | None), "frametime", "frames", "secs", "gpu", "memory", "hitches", "latency",
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
               "GPU Time(mean)": "gpu", "System Memory Util(mean)": "memory", "Runtime PSO Hitches": "hitches",
               "Valorant Memory MB(mean)": "game_mb", "Valorant Memory Util(mean)": "game_pct",
               "Avg. Engine Latency (ms)": "latency", "Valorant CPU Util(mean)": "game_cpu",
               "System CPU Util(mean)": "sys_cpu"}.get(name)
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
    "memory" (% | None), "hitches", "ended", "started", and from the round where memory was fullest: "game_mb"
    (MB VALORANT itself used | None), "total_mb" (the PC's memory | None), "others_mb" (everything else | None),
    "latency" (VALORANT's average engine latency in ms, weighted by frames | None), "game_cpu" (% of one processor
    thread VALORANT used, summed over threads, weighted by time | None), "sys_cpu" (% of all threads every program
    used | None)} for one match, or None."""
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
    peak = max((r for r in match if r.get("memory") is not None), key=lambda r: r["memory"], default=None)
    game_mb, total_mb, others_mb = _memory_split(peak)
    lat = [r for r in match if r.get("latency") is not None and 0 < r["latency"] < 1000]
    latency = sum(r["latency"] * r["frames"] for r in lat) / sum(r["frames"] for r in lat) if lat else None
    game_cpu, sys_cpu = _cpu_means(match)
    return {"fps": frames / secs, "rounds": len(match), "minutes": secs / 60.0,
            "gpu_busy": min(1.0, gpu_ms / frame_ms) if gpu_ms is not None and frame_ms > 0 else None,
            "slow_share": slow, "memory": max(mem) if mem else None,
            "hitches": int(sum(r.get("hitches", 0) for r in match)), "ended": match[-1]["time"],
            "started": _started(match[0]), "game_mb": game_mb, "total_mb": total_mb, "others_mb": others_mb,
            "latency": latency, "game_cpu": game_cpu, "sys_cpu": sys_cpu}


def _cpu_means(match):
    """Time-weighted means of the two CPU lines over the rounds that have both with plausible values, else None."""
    rows = [r for r in match if r.get("game_cpu") is not None and r.get("sys_cpu") is not None
            and r["game_cpu"] >= 0 and 0 <= r["sys_cpu"] <= 100 and r["secs"] > 0]
    if not rows:
        return None, None
    secs = sum(r["secs"] for r in rows)
    return (sum(r["game_cpu"] * r["secs"] for r in rows) / secs, sum(r["sys_cpu"] * r["secs"] for r in rows) / secs)


def _cpus():
    try:
        return os.cpu_count() or None
    except Exception:
        return None


def cpu_split(info, cpus=None):
    """(threads VALORANT itself kept busy on average, threads every other program kept busy, the PC's thread count)
    for a match summary; each None when unknown or when the numbers don't fit the PC (the logs are written by this
    PC, so its thread count applies). VALORANT's line is % of one thread summed over threads; the system line is %
    of all threads, so others = system % x threads - VALORANT's threads."""
    cpus = cpus or _cpus()
    if not info or not cpus or info.get("game_cpu") is None or info.get("sys_cpu") is None:
        return None, None, cpus
    game = info["game_cpu"] / 100.0
    if game > cpus:                                           # more than the whole processor: not this PC's log
        return None, None, cpus
    others = info["sys_cpu"] / 100.0 * cpus - game
    return game, (others if others >= 0 else None), cpus


def _memory_split(r):
    """(MB VALORANT used, the PC's total MB, MB used by everything else) for one round, each None when unknown or
    implausible. Total = VALORANT MB / VALORANT % (the log has no total line); others = system % of total - VALORANT."""
    if not r:
        return None, None, None
    game_mb, game_pct, system = r.get("game_mb"), r.get("game_pct"), r.get("memory")
    if not game_mb or game_mb <= 0:
        return None, None, None
    if not game_pct or game_pct <= 0 or game_pct > 100 or system is None or not 0 < system <= 100:
        return game_mb, None, None
    total = 100.0 * game_mb / game_pct
    if not 1024 <= total <= 4 * 1024 * 1024:               # 1 GB .. 4 TB, or the numbers don't belong together
        return game_mb, None, None
    others = total * system / 100.0 - game_mb
    return game_mb, total, (others if others >= 0 else None)


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


def _latency(matches):
    """Frame-weighted average engine latency (ms) of a list of match summaries, or None unless every match has it
    (a mix would compare different sets of matches)."""
    if not matches or any(m.get("latency") is None for m in matches):
        return None
    frames = [m["fps"] * m["minutes"] * 60.0 for m in matches]
    total = sum(frames)
    return sum(m["latency"] * f for m, f in zip(matches, frames)) / total if total > 0 else None


def _average(matches):
    """Time-weighted average FPS (= all frames / all seconds) and total minutes of a list of match summaries."""
    minutes = sum(m["minutes"] for m in matches)
    return (sum(m["fps"] * m["minutes"] for m in matches) / minutes if minutes > 0 else None), minutes


def compare(matches, since, keep=COMPARE_KEEP, min_minutes=COMPARE_MIN_MINUTES):
    """Average FPS of the matches before vs after `since` (the first Optimize Max change, local datetime):
    {"before", "after" (FPS), "n_before", "n_after", "change" (after / before - 1), "latency_before",
    "latency_after" (engine latency ms, None unless every match on that side has it)} or None when either side has no
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
    return {"before": fb, "after": fa, "n_before": len(before), "n_after": len(after), "change": fa / fb - 1.0,
            "latency_before": _latency(before), "latency_after": _latency(after)}


__all__ = ["parse_rounds", "last_match", "split_matches", "summary", "limit", "latest", "all_matches", "compare",
           "cpu_split"]
