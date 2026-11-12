"""Optimize Max: "Your last match" reads VALORANT's own end-of-round performance statistics from ShooterGame.log.
Crafted logs cover: one match (average FPS = frames / time, GPU-bound / CPU-bound / both, frames under 60 FPS from
the buckets, memory, shader hitches, UTC -> local time), two matches in one file (the last one counts), the in-game
FPS cap as the limit, a block cut off mid-way, a log without statistics, the fallback to the newest backup log, a
missing folder. Then every real log on this PC, if present. Read-only: nothing is written outside a temp folder."""
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

os.environ["APPDATA"] = tempfile.mkdtemp(prefix="ts-mperf-")
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))

from truestretch import matchperf as mp                                        # noqa: E402
from truestretch.optimizer import INFO, _match_perf                            # noqa: E402

fails = []


def check(c, t):
    print(("PASS " if c else "FAIL ") + t)
    c or fails.append(t)


def block(rnd, frames, secs, gpu, memory=80.0, hitches=0, slow=0, stamp="2026.11.12-09.51.52:665"):
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
            "\t\tAvg. Engine Latency (ms): 6.38\r\n\t\tEngine Latency Frames Over 144fps: 10\r\n"
            f"[{stamp}][437]LogClientPerRoundTelemetryComponent: \r\n"
            f"\t\tTotal Time(secs): {secs}\r\n\t\tValorant CPU Util(mean): 399.13\r\n"
            f"\t\tSystem Memory Util(mean): {memory}\r\n\t\tGPU Time(mean): {gpu}\r\n"
            "\t\tGPU Frames Over 360fps: 20766\r\n\t\tValorant Memory MB(mean): 3275.90\r\n"
            f"\t\tRuntime PSO Hitches: {hitches}\r\n\t\tRHI: D3D11\r\n"
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

real = Path(os.environ.get("LOCALAPPDATA", "")) / "VALORANT" / "Saved" / "Logs"
if real.is_dir():
    for path in sorted(real.glob("ShooterGame*.log")):
        rs = mp.parse_rounds(mp._read(path))
        s = mp.summary(mp.last_match(rs))
        ok = all(r.get("frames", 0) > 0 and r.get("secs", 0) > 0 for r in rs)
        check(ok and (s is None or 1 < s["fps"] < 2000), f"real {path.name}: {len(rs)} rounds, "
              + (f"last match {s['fps']:.0f} FPS, limit {mp.limit(s)}" if s else "no match"))
        bucket_ok = [r for r in rs if r["buckets"] and sum(r["buckets"].values()) == int(r["frames"])]
        check(len(bucket_ok) == len(rs), f"real {path.name}: buckets add up to Total Frames in every round")
    it = _match_perf(FakeEngine())
    check(it is None or it.id == "match_perf", "real scan step builds the row (or none)")
    if it:
        print(f"INFO real row: {it.title} | {it.why} | {it.note}")
else:
    print("INFO no VALORANT logs on this PC - real-log part skipped")

print("ALL PASSED" if not fails else f"{len(fails)} FAILED")
sys.exit(1 if fails else 0)
