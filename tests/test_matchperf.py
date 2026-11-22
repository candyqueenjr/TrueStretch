"""Optimize Max: "Your last match" reads VALORANT's own end-of-round performance statistics from ShooterGame.log.
Crafted logs cover: one match (average FPS = frames / time, GPU-bound / CPU-bound / both, frames under 60 FPS from
the buckets, memory, shader hitches, UTC -> local time; how much
memory VALORANT itself used vs other programs; processor threads VALORANT vs other programs kept busy), two matches in one file (the last one counts), the in-game
FPS cap as the limit, a block cut off mid-way, a log without statistics, the fallback to the newest backup log, a
missing folder; before vs after Optimize Max (matches split at Round 0, start times, de-duplicated across logs,
time-weighted averages, a match running at apply time counts on neither side, too little play, the FPS-cap case, the
oldest change time from the undo file). Then every real log on this PC, if present. Read-only: nothing is written outside a temp folder."""
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

os.environ["APPDATA"] = tempfile.mkdtemp(prefix="ts-mperf-")
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))

from truestretch import matchperf as mp                                        # noqa: E402
from truestretch.optimizer import INFO, UNDO_FILE, Optimizer, _match_perf   # noqa: E402
import truestretch.optimizer as opt                                            # noqa: E402

real_cap = opt._fps_cap

fails = []


def check(c, t):
    print(("PASS " if c else "FAIL ") + t)
    c or fails.append(t)


def block(rnd, frames, secs, gpu, memory=80.0, hitches=0, slow=0, stamp="2026.11.12-09.51.52:665", game_mb=3275.90,
          game_pct=None, latency=6.38, game_cpu=399.13, sys_cpu=None):
    """One end-of-round block in the exact real layout (tabs, two continuation headers). `slow` frames go into the
    30-45 FPS bucket, the rest into 144-240."""
    ft = 1000.0 * secs / frames
    return (f"[{stamp}][437]LogClientPerRoundTelemetryComponent: End of Round Perf statistics\r\n"
            f"\tRound {rnd} Performance:\r\n\t\tAvg.Frametime (ms): {ft:.2f}\r\n\t\tTotal Frames: {frames}\r\n"
            "\t\tGame Thread Frames Under 1 fps: 0\r\n\t\tGame Thread Frames Over 1 fps: 0\r\n"
            f"\t\tGame Thread Frames Over 30 fps: {slow}\r\n\t\tGame Thread Frames Over 60 fps: 0\r\n"
            f"\t\tGame Thread Frames Over 144 fps: {frames - slow}\r\n\t\tGame Thread Frames Over 480 fps: 0\r\n"
            "\t\tFlips At 120Hz: 0\r\n"
            f"[{stamp}][437]LogClientPerRoundTelemetryComponent: \r\n"
            + (f"\t\tAvg. Engine Latency (ms): {latency}\r\n" if latency is not None else "")
            + "\t\tAvg. Work (ms): 4.83\r\n\t\tEngine Latency Frames Over 144fps: 10\r\n"
            f"[{stamp}][437]LogClientPerRoundTelemetryComponent: \r\n"
            f"\t\tTotal Time(secs): {secs}\r\n"
            + (f"\t\tValorant CPU Util(mean): {game_cpu}\r\n" if game_cpu is not None else "")
            + (f"\t\tSystem CPU Util(mean): {sys_cpu}\r\n" if sys_cpu is not None else "")
            + f"\t\tSystem Memory Util(mean): {memory}\r\n\t\tGPU Time(mean): {gpu}\r\n"
            "\t\tGPU Frames Over 360fps: 20766\r\n"
            + (f"\t\tValorant Memory Util(mean): {game_pct}\r\n" if game_pct is not None else "")
            + (f"\t\tValorant Memory MB(mean): {game_mb}\r\n" if game_mb is not None else "")
            + f"\t\tRuntime PSO Hitches: {hitches}\r\n\t\tRHI: D3D11\r\n"
            f"[{stamp}][437]LogShooterGameState: Warning: AShooterGameState::OnRoundEnded for round '{rnd}'\r\n")


HEAD = "\ufeffLog file open, 11/12/26 13:46:10\r\n[2026.11.12-09.46.12:977][  0]LogInit: something\r\n"


class FakeEngine:
    info = {}

    def selected_targets(self, gid):
        return []

    def native_mode(self, gid):
        return type("M", (), {"hz": 144})()


def folder(text):
    d = Path(tempfile.mkdtemp(prefix="ts-mlog-"))
    (d / "ShooterGame.log").write_text(text, encoding="utf-8")
    return d


# one match, CPU-bound (gpu 2 ms of a 5 ms frame)
cpu_log = HEAD + block(0, 24000, 120.0, 2.0) + block(1, 20000, 100.0, 2.0, memory=86.5)
rounds = mp.parse_rounds(cpu_log)
check(len(rounds) == 2 and [r["round"] for r in rounds] == [0, 1], "two round blocks parsed")
check(rounds[0]["buckets"] == {0: 0, 1: 0, 30: 0, 60: 0, 144: 24000, 480: 0}, "frame-time buckets parsed")
local = datetime(2026, 11, 12, 9, 51, 52, tzinfo=timezone.utc).astimezone().replace(tzinfo=None)
check(rounds[0]["time"] == local, "block time: UTC timestamp converted to local time")
info = mp.summary(mp.last_match(rounds))
check(info and abs(info["fps"] - 200.0) < 0.01, f"average FPS = total frames / total time ({info and info['fps']:.2f})")
check(info and abs(info["gpu_busy"] - 0.4) < 0.001, "graphics card busy 2 ms of 5 ms = 40%")
check(info and info["slow_share"] == 0.0 and info["memory"] == 86.5 and info["hitches"] == 0, "no slow frames, peak memory")
check(mp.limit(info) == "cpu", "40% busy -> processor sets the FPS")
check(mp.limit(info, fps_cap=300) == "cpu", "a cap far above the FPS doesn't change the verdict")
check(mp.limit(info, fps_cap=200) == "cap", "FPS at the in-game cap -> the cap sets the FPS")

gpu = mp.summary(mp.last_match(mp.parse_rounds(HEAD + block(0, 12000, 100.0, 7.9))))
check(gpu and mp.limit(gpu) == "gpu", "graphics card busy ~95% -> graphics card sets the FPS")
both = mp.summary(mp.last_match(mp.parse_rounds(HEAD + block(0, 12000, 100.0, 5.8))))
check(both and mp.limit(both) == "both", "~70% busy -> both")

# two matches: the second one counts; stutters, memory and hitches
two = (HEAD + block(0, 30000, 100.0, 2.0) + block(1, 30000, 100.0, 2.0)
       + block(0, 9000, 100.0, 9.0, memory=93.0, hitches=12, slow=450) + block(1, 11000, 100.0, 8.0, slow=0))
info2 = mp.summary(mp.last_match(mp.parse_rounds(two)))
check(info2 and info2["rounds"] == 2 and abs(info2["fps"] - 100.0) < 0.01, "two matches in one file -> only the last")
check(info2 and abs(info2["slow_share"] - 450 / 20000) < 1e-9, "frames under 60 FPS share from the buckets (2.25%)")
check(info2 and info2["memory"] == 93.0 and info2["hitches"] == 12, "peak memory and shader hitches summed")

# memory: how much VALORANT itself used vs other programs (16 GB PC, 2 GB game, 97% full -> 13.5 GB others, shown as 14 GB)
mem_log = HEAD + block(0, 24000, 120.0, 2.0, memory=85.0, game_mb=1800.0, game_pct=11.25)     + block(1, 24000, 120.0, 2.0, memory=97.0, game_mb=2048.0, game_pct=12.5)     + block(2, 24000, 120.0, 2.0, memory=90.0, game_mb=2100.0, game_pct=12.8)
mi = mp.summary(mp.last_match(mp.parse_rounds(mem_log)))
check(mi and mi["game_mb"] == 2048.0 and abs(mi["total_mb"] - 16384.0) < 0.01,
      "memory: game MB taken from the fullest round, total = MB / %")
check(mi and abs(mi["others_mb"] - (16384 * 0.97 - 2048)) < 0.01, "memory: others = system % of total - game")
it = _match_perf(FakeEngine(), folder(mem_log))
check(it and "97% full" in it.note and "VALORANT itself used 2.0 GB of your 16 GB" in it.note
      and "other programs about 14 GB" in it.note and "frees the most" in it.note,
      f"note: other programs filled the memory ({it and it.note})")
check(it and any("valorant MB 2048, total MB 16384, others MB 13844" in x for x in it.debug), "memory split in diagnostics")
big = HEAD + block(0, 24000, 120.0, 2.0, memory=95.0, game_mb=5000.0, game_pct=62.5)     # 8 GB PC, game 4.9 GB
it = _match_perf(FakeEngine(), folder(big))
check(it and "VALORANT itself used 4.9 GB of your 7.8 GB" in it.note and "more memory (RAM) helps most" in it.note,
      f"note: the game itself needs most of the memory ({it and it.note})")
old_fmt = HEAD + block(0, 24000, 120.0, 2.0, memory=95.0, game_mb=None)
it = _match_perf(FakeEngine(), folder(old_fmt))
check(it and it.note == "Windows memory was 95% full during the match - close browsers and launchers before playing.",
      "note: log without the VALORANT memory lines -> the plain advice")
check(mp._memory_split({"memory": 95.0, "game_mb": 2048.0}) == (2048.0, None, None), "split: no % -> game MB only")
check(mp._memory_split({"memory": 95.0, "game_mb": 2048.0, "game_pct": 0.001}) == (2048.0, None, None),
      "split: implausible total (> 4 TB) -> game MB only")
check(mp._memory_split({"memory": 5.0, "game_mb": 2048.0, "game_pct": 50.0}) == (2048.0, 4096.0, None),
      "split: system % below the game's own -> others unknown")
check(mp._memory_split(None) == (None, None, None) and mp._memory_split({"memory": 90.0}) == (None, None, None),
      "split: nothing -> nothing")
it = _match_perf(FakeEngine(), folder(HEAD + block(0, 24000, 120.0, 2.0, memory=80.0, game_mb=2048.0, game_pct=12.5)))
check(it and it.note == "", "memory under 90% -> no memory note")

# a block cut off before Total Time (the game was closed mid-write) is ignored
cut = HEAD + block(0, 24000, 120.0, 2.0) + ("[2026.11.12-10.00.00:000][  1]LogClientPerRoundTelemetryComponent: End of "
                                            "Round Perf statistics\r\n\tRound 1 Performance:\r\n\t\tTotal Frames: 5\r\n")
check(len(mp.parse_rounds(cut)) == 1, "incomplete last block ignored")
check(mp.parse_rounds(HEAD + "[2026.11.12-09.46.17:366][  0]LogMapLoadModel: Update: [Map Name: Init\r\n") == [],
      "log without statistics -> no rounds")
check(mp.summary([]) is None and mp.limit(None) is None, "empty -> None")

# scan step: row text, state, read-only
d = Path(tempfile.mkdtemp(prefix="ts-mlog-"))
(d / "ShooterGame.log").write_text(two, encoding="utf-8")
it = _match_perf(FakeEngine(), d)
check(it and it.id == "match_perf" and it.group == "Your PC" and it.state == INFO and not it.can_apply,
      "row: Your PC, INFO, nothing to apply")
check(it and it.title == "Your last match: 100 FPS average" and it.current == "100 FPS" and it.target == "144+ FPS",
      f"row title/current/target ({it and it.title} | {it and it.target})")
check(it and "graphics card sets the FPS" in it.why, "GPU-bound match explained")
check(it and "slower than 60 FPS" in it.note and "93% full" in it.note and "shader stutter" in it.note,
      "notes: stutters, memory, shader hitches")
it = _match_perf(FakeEngine(), folder(cpu_log))
check(it and "processor sets the FPS" in it.why and it.note == "", "CPU-bound match explained, no notes when healthy")

# current log has no match (game just started) -> newest backup with one
d = Path(tempfile.mkdtemp(prefix="ts-mlog-"))
(d / "ShooterGame.log").write_text(HEAD, encoding="utf-8")
old = d / "ShooterGame-backup-2026.11.10-17.06.21.log"
new = d / "ShooterGame-backup-2026.11.11-17.06.21.log"
old.write_text(HEAD + block(0, 5000, 100.0, 2.0), encoding="utf-8")
new.write_text(HEAD + block(0, 7000, 100.0, 2.0), encoding="utf-8")
os.utime(old, (1_700_000_000, 1_700_000_000))
info3 = mp.latest(d)
check(info3 and info3["file"] == new.name and abs(info3["fps"] - 70.0) < 0.01, "falls back to the newest backup log")
check(mp.latest(Path(tempfile.mkdtemp()) / "missing") is None, "missing log folder -> None")
check(_match_perf(FakeEngine(), Path(tempfile.mkdtemp())) is None, "no logs: scan step returns nothing")

# ---- before vs after Optimize Max ---------------------------------------------------------------------------
def at(day, hh, mm):
    return f"2026.11.{day:02d}-{hh:02d}.{mm:02d}.00:000"


def loc(day, hh, mm):
    return datetime(2026, 11, day, hh, mm, tzinfo=timezone.utc).astimezone().replace(tzinfo=None)


ms = mp.split_matches(mp.parse_rounds(two))
check([len(m) for m in ms] == [2, 2], "split_matches: a new match at every Round 0")
check(mp.split_matches([]) == [], "split_matches: nothing -> nothing")
s0 = mp.summary(mp.parse_rounds(HEAD + block(0, 6000, 120.0, 2.0, stamp=at(12, 10, 2)))[:1])
check(s0 and s0["started"] == loc(12, 10, 0), "match start = end of its first round minus the round length")

# two logs: an old session (2 matches before) and a new one (1 match after), plus a duplicate copy of one match
d = Path(tempfile.mkdtemp(prefix="ts-mcmp-"))
(d / "ShooterGame-backup-2026.11.10-10.00.00.log").write_text(
    HEAD + block(0, 30000, 300.0, 2.0, stamp=at(10, 10, 5)) + block(1, 30000, 300.0, 2.0, stamp=at(10, 10, 10))
    + block(0, 54000, 600.0, 2.0, stamp=at(10, 11, 10)), encoding="utf-8")       # 100 FPS 10 min, 90 FPS 10 min
(d / "ShooterGame-backup-2026.11.10-12.00.00.log").write_text(
    HEAD + block(0, 54000, 600.0, 2.0, stamp=at(10, 11, 10)), encoding="utf-8")  # same match again (copied log)
(d / "ShooterGame.log").write_text(
    HEAD + block(0, 66000, 600.0, 2.0, stamp=at(14, 20, 10)), encoding="utf-8")  # 110 FPS 10 min
allm = mp.all_matches(d)
check(len(allm) == 3 and [round(m["fps"]) for m in allm] == [100, 90, 110], "all_matches: oldest first, no duplicates "
      f"({[round(m['fps']) for m in allm]})")
since = loc(12, 9, 0)
c = mp.compare(allm, since)
check(c and abs(c["before"] - 95.0) < 0.01 and abs(c["after"] - 110.0) < 0.01 and c["n_before"] == 2
      and c["n_after"] == 1, f"compare: time-weighted 95 -> 110 FPS ({c})")
check(c and abs(c["change"] - (110 / 95 - 1)) < 1e-9, "compare: change = after / before - 1")
check(mp.compare(allm, None) is None, "compare: nothing applied -> no comparison")
check(mp.compare(allm, loc(9, 0, 0)) is None and mp.compare(allm, loc(15, 0, 0)) is None,
      "compare: all matches on one side -> no comparison")
check(mp.compare(allm, loc(10, 11, 5)) and mp.compare(allm, loc(10, 11, 5))["n_before"] == 1
      and mp.compare(allm, loc(10, 11, 5))["n_after"] == 1, "compare: the match running at apply time counts on neither side")
check(mp.compare(allm, since, min_minutes=11) is None, "compare: too little play on a side -> no comparison")
check(mp.compare(allm, since, keep=1)["n_before"] == 1 and abs(mp.compare(allm, since, keep=1)["before"] - 90) < 0.01,
      "compare: only the nearest matches before")
check(mp.all_matches(Path(tempfile.mkdtemp()) / "missing") == [], "all_matches: missing folder -> []")

it = _match_perf(FakeEngine(), d, since=since)
check(it and "Since Optimize Max" in it.why and "110 FPS on average over 1 match," in it.why
      and "before: 95 FPS over 2 matches (+16%)" in it.why, f"row: before/after sentence ({it and it.why})")
check(it and any(x.startswith("before/after") for x in it.debug), "row: comparison in the diagnostics")
it = _match_perf(FakeEngine(), d)
check(it and "Since Optimize Max" not in it.why, "row: nothing applied -> no comparison sentence")



# ---- engine latency (the game's own part of the input delay) --------------------------------------------------
lat_log = HEAD + block(0, 24000, 120.0, 2.0, latency=5.0) + block(1, 20000, 100.0, 2.0, latency=8.0)
li = mp.summary(mp.last_match(mp.parse_rounds(lat_log)))
check(li and abs(li["latency"] - (5.0 * 24000 + 8.0 * 20000) / 44000) < 1e-9,
      f"latency: frame-weighted average of the rounds ({li and li['latency']})")
check(mp.parse_rounds(lat_log)[0]["buckets"] == {0: 0, 1: 0, 30: 0, 60: 0, 144: 24000, 480: 0},
      "latency: 'Engine Latency Frames' lines don't mix into the frame-time buckets")
it = _match_perf(FakeEngine(), folder(lat_log))
check(it and "Game delay: 6.4 ms per frame on average" in it.why and "engine latency" in it.why,
      f"row: game delay sentence ({it and it.why})")
check(it and any("engine latency 6.36" in x for x in it.debug), "latency in the diagnostics")
no_lat = HEAD + block(0, 24000, 120.0, 2.0, latency=None)
check(mp.summary(mp.parse_rounds(no_lat))["latency"] is None, "latency: log without the line -> None")
it = _match_perf(FakeEngine(), folder(no_lat))
check(it and "Game delay" not in it.why, "row: no latency line -> no game delay sentence")
odd = HEAD + block(0, 24000, 120.0, 2.0, latency=0) + block(1, 20000, 100.0, 2.0, latency=4000)
check(mp.summary(mp.parse_rounds(odd))["latency"] is None, "latency: 0 ms or absurd values ignored")
part = HEAD + block(0, 24000, 120.0, 2.0, latency=None) + block(1, 20000, 100.0, 2.0, latency=7.0)
check(mp.summary(mp.parse_rounds(part))["latency"] == 7.0, "latency: rounds without it are left out")

# ---- processor threads: VALORANT itself vs other programs (the game's own CPU lines) ---------------------------
cpu_log2 = HEAD + block(0, 24000, 120.0, 2.0, game_cpu=400.0, sys_cpu=50.0) + block(1, 12000, 60.0, 2.0, game_cpu=100.0, sys_cpu=20.0)
ci = mp.summary(mp.last_match(mp.parse_rounds(cpu_log2)))
check(ci and abs(ci["game_cpu"] - 300.0) < 1e-9 and abs(ci["sys_cpu"] - 40.0) < 1e-9,
      f"cpu: time-weighted means of both lines ({ci and (ci['game_cpu'], ci['sys_cpu'])})")
g, o, n = mp.cpu_split(ci, cpus=8)
check(n == 8 and abs(g - 3.0) < 1e-9 and abs(o - 0.2) < 1e-9, f"cpu split: 300% = 3.0 threads, 40% of 8 - 3.0 = 0.2 others ({g}, {o})")
check(mp.cpu_split(ci, cpus=2) == (None, None, 2), "cpu split: VALORANT above the whole processor -> not this PC's log")
low = mp.summary(mp.last_match(mp.parse_rounds(HEAD + block(0, 24000, 120.0, 2.0, game_cpu=400.0, sys_cpu=10.0))))
check(mp.cpu_split(low, cpus=8) == (4.0, None, 8), "cpu split: system below VALORANT's own share -> others unknown")
check(mp.cpu_split(mp.summary(mp.last_match(mp.parse_rounds(HEAD + block(0, 24000, 120.0, 2.0)))), cpus=8) == (None, None, 8),
      "cpu split: log without the system line -> nothing")
check(mp.cpu_split(ci, cpus=None)[2] == mp._cpus() and (mp._cpus() or 0) >= 1, "cpu split: thread count from this PC by default")
check(mp.cpu_split(None, cpus=8) == (None, None, 8), "cpu split: no match -> nothing")
odd_cpu = HEAD + block(0, 24000, 120.0, 2.0, game_cpu=-5.0, sys_cpu=50.0) + block(1, 24000, 120.0, 2.0, game_cpu=200.0, sys_cpu=140.0)
check(mp.summary(mp.last_match(mp.parse_rounds(odd_cpu)))["game_cpu"] is None, "cpu: negative / >100% system values ignored")
real_cpus = mp._cpus
mp._cpus = lambda: 8
try:
    it = _match_perf(FakeEngine(), folder(HEAD + block(0, 24000, 120.0, 2.0, game_cpu=420.0, sys_cpu=45.0)))   # 45% of 8 = 3.6 < 4.2
    check(it and "processor threads" not in it.why, "row: numbers that don't fit (system < game) -> no sentence")
    it = _match_perf(FakeEngine(), folder(HEAD + block(0, 24000, 120.0, 2.0, game_cpu=420.0, sys_cpu=80.0)))
    check(it and "Of your 8 processor threads, VALORANT itself kept about 4.2 busy on average and your other programs "
          "about 2.2." in it.why and "what to close" in it.why, f"row: processor-limited, others >= 1 thread -> close them ({it and it.why})")
    check(it and any("cpu game 420.0% sys 80.0% -> threads game 4.2 others 2.2 of 8" in x for x in it.debug), "cpu split in the diagnostics")
    it = _match_perf(FakeEngine(), folder(HEAD + block(0, 24000, 120.0, 2.0, game_cpu=420.0, sys_cpu=55.0)))
    check(it and "other programs about 0.2." in it.why and "processor's own speed sets your FPS" in it.why,
          f"row: others under 1 thread -> the processor's speed ({it and it.why})")
    opt._fps_cap = lambda engine: None
    try:
        it = _match_perf(FakeEngine(), folder(HEAD + block(0, 12000, 100.0, 5.8, game_cpu=420.0, sys_cpu=80.0)))   # ~70% busy
        check(it and "processor threads" in it.why and "Processor and graphics card are both" in it.why, "row: 'both' verdict shows the split too")
    finally:
        opt._fps_cap = real_cap
    it = _match_perf(FakeEngine(), folder(HEAD + block(0, 12000, 100.0, 7.9, game_cpu=420.0, sys_cpu=80.0)))
    check(it and "processor threads" not in it.why, "row: graphics-card-limited -> no processor sentence")
    opt._fps_cap = lambda engine: 200.0
    try:
        it = _match_perf(FakeEngine(), folder(HEAD + block(0, 24000, 120.0, 2.0, game_cpu=420.0, sys_cpu=80.0)))
        check(it and "processor threads" not in it.why, "row: FPS at the cap -> no processor sentence")
    finally:
        opt._fps_cap = real_cap
finally:
    mp._cpus = real_cpus

# before vs after: latency on both sides (frame-weighted across matches)
dl = Path(tempfile.mkdtemp(prefix="ts-mlat-"))
(dl / "ShooterGame-backup-2026.11.10-10.00.00.log").write_text(
    HEAD + block(0, 30000, 300.0, 2.0, stamp=at(10, 10, 5), latency=8.0)
    + block(0, 60000, 600.0, 2.0, stamp=at(10, 11, 10), latency=6.5), encoding="utf-8")
(dl / "ShooterGame.log").write_text(
    HEAD + block(0, 66000, 600.0, 2.0, stamp=at(14, 20, 10), latency=5.5), encoding="utf-8")
cl = mp.compare(mp.all_matches(dl), since)
check(cl and abs(cl["latency_before"] - (8.0 * 30000 + 6.5 * 60000) / 90000) < 1e-9 and cl["latency_after"] == 5.5,
      f"compare: latency before 7.0 -> after 5.5 ms ({cl})")
it = _match_perf(FakeEngine(), dl, since=since)
check(it and "Game delay since Optimize Max: 5.5 ms, before: 7.0 ms." in it.why, f"row: latency before/after ({it and it.why})")
(dl / "ShooterGame.log").write_text(
    HEAD + block(0, 66000, 600.0, 2.0, stamp=at(14, 20, 10), latency=None), encoding="utf-8")
cl = mp.compare(mp.all_matches(dl), since)
check(cl and cl["latency_after"] is None and cl["latency_before"] is not None, "compare: a side without latency -> None")
it = _match_perf(FakeEngine(), dl, since=since)
check(it and "Since Optimize Max" in it.why and "Game delay since" not in it.why,
      "row: FPS comparison kept, latency comparison hidden when a side lacks it")
check(mp._latency([]) is None, "latency average: nothing -> None")


opt._fps_cap = lambda engine: 110.0
try:
    it = _match_perf(FakeEngine(), d, since=since)
    check(it and "Since Optimize Max" not in it.why, "row: FPS at the in-game cap -> no comparison (it says nothing)")
finally:
    opt._fps_cap = real_cap

# applied_since: the oldest change still in the undo file
o = Optimizer(FakeEngine())
UNDO_FILE.parent.mkdir(parents=True, exist_ok=True)
check(not UNDO_FILE.exists() and o.applied_since() is None, "applied_since: no undo file -> None")
UNDO_FILE.write_text('{"a": {"time": "2026-11-14T20:00:00"}, "b": {"time": "2026-11-12T09:00:00", "admin": true},'
                     ' "c": {"title": "no time"}, "d": {"time": "garbage"}}', encoding="utf-8")
check(o.applied_since() == datetime(2026, 11, 12, 9, 0), "applied_since: oldest valid time, bad entries skipped")
UNDO_FILE.write_text("not json", encoding="utf-8")
check(o.applied_since() is None, "applied_since: broken undo file -> None")
UNDO_FILE.unlink(missing_ok=True)   # a damaged file is moved aside as .broken.json since 2.0

real = Path(os.environ.get("LOCALAPPDATA", "")) / "VALORANT" / "Saved" / "Logs"
if real.is_dir():
    for path in sorted(real.glob("ShooterGame*.log")):
        rs = mp.parse_rounds(mp._read(path))
        s = mp.summary(mp.last_match(rs))
        ok = all(r.get("frames", 0) > 0 and r.get("secs", 0) > 0 for r in rs)
        check(ok and (s is None or 1 < s["fps"] < 2000), f"real {path.name}: {len(rs)} rounds, "
              + (f"last match {s['fps']:.0f} FPS, limit {mp.limit(s)}" if s else "no match"))
        mem_ok = [r for r in rs if r.get("game_mb") and r.get("game_pct")]
        tot = {round(100 * r["game_mb"] / r["game_pct"] / 64) for r in mem_ok}
        check(not rs or (len(mem_ok) == len(rs) and len(tot) <= 2), f"real {path.name}: VALORANT memory lines in every "
              f"round, total memory consistent ({sorted(t * 64 for t in tot)} MB)")
        bucket_ok = [r for r in rs if r["buckets"] and sum(r["buckets"].values()) == int(r["frames"])]
        check(len(bucket_ok) == len(rs), f"real {path.name}: buckets add up to Total Frames in every round")
        check(all(r.get("latency") and 0 < r["latency"] < 1000 for r in rs),
              f"real {path.name}: engine latency line in every round")
        ncpu = mp._cpus() or 0
        check(all(r.get("game_cpu") is not None and r.get("sys_cpu") is not None
                  and r["game_cpu"] <= ncpu * r["sys_cpu"] + 1e-6 for r in rs),
              f"real {path.name}: both CPU lines in every round, VALORANT's share never above {ncpu} threads x system %")
    it = _match_perf(FakeEngine())
    check(it is None or it.id == "match_perf", "real scan step builds the row (or none)")
    allr = mp.all_matches(real)
    check(all(m["started"] <= m["ended"] for m in allr), f"real: {len(allr)} matches across all logs, start <= end")
    if len(allr) >= 2:
        mid = allr[len(allr) // 2]["started"]
        cr = mp.compare(allr, mid)
        print(f"INFO real before/after split at {mid:%d %b %H:%M}: {cr}")
    if it:
        print(f"INFO real row: {it.title} | {it.why} | {it.note}")
else:
    print("INFO no VALORANT logs on this PC - real-log part skipped")

print("ALL PASSED" if not fails else f"{len(fails)} FAILED")
sys.exit(1 if fails else 0)
