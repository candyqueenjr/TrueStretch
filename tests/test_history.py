"""Match history (2.0): matches are read from VALORANT-style logs, get their map, are stored once (no duplicates when
the same log is read again), keep growing after VALORANT deletes its old logs, survive a damaged history file, and
produce the after-match note. Synthetic logs only - nothing from a real PC."""
import json
import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path

os.environ["APPDATA"] = tempfile.mkdtemp(prefix="ts-history-")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from truestretch import history, matchperf          # noqa: E402

fails = []


def check(c, t):
    print(("PASS " if c else "FAIL ") + t)
    c or fails.append(t)


def round_block(ts, n, frametime=5.0, secs=100.0):
    frames = int(secs * 1000 / frametime)
    return "\n".join([
        f"[{ts}:000][  1]LogClientPerRoundTelemetryComponent: End of Round Perf statistics",
        f"\tRound {n} Performance:",
        f"\t\tAvg.Frametime (ms): {frametime}",
        f"\t\tTotal Frames: {frames}",
        "\t\tGame Thread Frames Under 1 fps: 0",
        f"\t\tGame Thread Frames Over 60 fps: {frames}",
        f"[{ts}:001][  1]LogClientPerRoundTelemetryComponent:",
        "\t\tAvg. Engine Latency (ms): 6.5",
        f"[{ts}:002][  1]LogClientPerRoundTelemetryComponent:",
        f"\t\tTotal Time(secs): {secs}",
        f"\t\tGPU Time(mean): {frametime * 0.9}",
        f"[{ts}:003][  1]LogSomethingElse: next",
    ])


def map_line(ts, name):
    return (f"[{ts}:500][  1]LogMapLoadModel: Update: [Map Name: {name} | Changed: TRUE] [Local World: TRUE | "
            "Changed: TRUE] [Match Setup: TRUE | Changed: TRUE] [Map Ready: TRUE | Changed: TRUE]")


log_dir = Path(tempfile.mkdtemp(prefix="ts-logs-"))
match1 = [map_line("2026.11.20-18.00.00", "MainMenuV2"), map_line("2026.11.20-18.01.00", "Infinity"),
          round_block("2026.11.20-18.05.00", 0), round_block("2026.11.20-18.07.00", 1),
          map_line("2026.11.20-18.10.00", "MainMenuV2")]
match2 = [map_line("2026.11.20-19.00.00", "Duality"), round_block("2026.11.20-19.05.00", 0, frametime=4.0),
          round_block("2026.11.20-19.07.00", 1, frametime=4.0)]
(log_dir / "ShooterGame.log").write_text("\n".join(match1 + match2) + "\n", encoding="utf-8")

# ---- parsing ------------------------------------------------------------------------------------------------------
rounds = matchperf.parse_rounds((log_dir / "ShooterGame.log").read_text())
check([r["map"] for r in rounds] == ["Infinity", "Infinity", "Duality", "Duality"],
      "every round knows its map (menus ignored; 'Infinity' isn't mistaken for the 'Init' menu)")
check(history.map_name("Infinity") == "Abyss" and history.map_name("Duality") == "Bind"
      and history.map_name("HURM_Alley") == "Team Deathmatch" and history.map_name(None) == "Unknown map",
      "internal map names shown as the names players know")

# ---- storing ------------------------------------------------------------------------------------------------------
records, new = history.update(log_dir, "1440 × 1080")
check(len(records) == 2 and len(new) == 2, "first read: both matches stored")
check(all(r["stretch"] is None for r in new), "matches found before the history existed get no stretch size")
check(abs(records[1]["fps"] - 250) < 1 and abs(records[0]["fps"] - 200) < 1, "average FPS per match")
records, new = history.update(log_dir, "1440 × 1080")
check(len(records) == 2 and not new, "same log read again: no duplicates")

match3 = [map_line("2026.11.21-20.00.00", "Ascent"), round_block("2026.11.21-20.05.00", 0, frametime=3.0)]
(log_dir / "ShooterGame.log").write_text("\n".join(match3) + "\n", encoding="utf-8")     # VALORANT replaced its log
since = datetime(2026, 11, 21, 12, 0)
records, new = history.update(log_dir, "1280 × 1080", optimized_since=since)
check(len(records) == 3 and len(new) == 1, "old matches stay after VALORANT deletes its log; the new one is added")
check(new[0]["stretch"] == "1280 × 1080" and new[0]["optimized"], "live match: stretch size and Optimize Max recorded")
stored = json.loads(history.HISTORY_FILE.read_text(encoding="utf-8"))
check(stored["version"] == 1 and len(stored["matches"]) == 3, "history file written")

# ---- summaries & the after-match note ------------------------------------------------------------------------------
st = history.stats(records)
check(st["matches"] == 3 and st["fps"] and st["latency"] and abs(st["latency"] - 6.5) < 0.01, "summary cards")
text = history.report_text(new[0])
check(text.startswith("Match finished: Ascent") and "FPS average" in text and "ms game delay" in text,
      "after-match note: " + text)

# ---- damaged history file -------------------------------------------------------------------------------------------
history.HISTORY_FILE.write_text("{ not json", encoding="utf-8")
check(history.load() == [] and history.HISTORY_FILE.with_suffix(".broken.json").exists(),
      "damaged history: set aside, app keeps working")

print("\nALL PASSED" if not fails else f"\n{len(fails)} FAILED")
sys.exit(1 if fails else 0)
