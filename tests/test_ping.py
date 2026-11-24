"""Server ping board (2.1): VALORANT's per-server ping lines are parsed without keeping the account id, stored once
(no duplicates when the same log is read again), kept after VALORANT deletes its old logs, survive a damaged history
file, and turn into a board with the right order, statistics and plain-language insights. Riot's status JSON is read
offline from a sample. Synthetic logs only - nothing from a real PC, no network."""
import json
import os
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

os.environ["APPDATA"] = tempfile.mkdtemp(prefix="ts-ping-")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from truestretch import ping          # noqa: E402

fails = []


def check(c, t):
    print(("PASS " if c else "FAIL ") + t)
    c or fails.append(t)


FAKE_ID = "11111111-2222-3333-4444-555555555555"
PODS = {"aws-euc1-prod.eu-gp-frankfurt-1": 55, "aws-ist1-prod.eu-gp-istanbul-2": 44, "aws-euw2-prod.eu-gp-london-1": 67,
        "aws-afs1-prod.eu-gp-capetown-1": 194, "aws-apne1-prod.eu-gp-tokyo-1": 268}


def ping_line(ts, pods, preferred=("aws-euc1-prod.eu-gp-frankfurt-1",)):
    query = "&".join(f"aresriot.{pod}={ms}" for pod, ms in pods.items())
    pref = ",".join(f"aresriot.{p}" for p in preferred)
    return (f"[{ts}:097][729]LogPlatformCommon: Platform HTTP Query End. QueryName: [Party_FetchPlayer], URL [GET "
            f"https://glz-eu-1.eu.a.pvp.net/parties/v1/players/{FAKE_ID}?{query}&preferredgamepods={pref}], "
            "@trace_id:abc Response Code: [200], Seconds Since Query [0.136000]")


def failure_line(ts, pod):
    return f"[{ts}:450][654]LogPingManager: Warning: Failure to ping endpoint aresriot.{pod}, not reporting stats."


# ---- parsing ------------------------------------------------------------------------------------------------------
text = "\n".join([
    "Log file open, 11/21/26 23:36:09",
    failure_line("2026.11.21-19.36.41", "aws-euc1-prod.eu-gp-frankfurt-1"),
    ping_line("2026.11.21-19.36.42", PODS),
    ping_line("2026.11.21-19.36.42", PODS),                                   # VALORANT logs it twice per start
    "[2026.11.21-19.40.00:000][  1]LogOther: aresriot.something unrelated without a value",
])
samples = ping.parse(text)
check(len(samples) == 2, f"two measurement lines parsed, the failure line and the stray line ignored ({len(samples)})")
s = samples[0]
check(s["pods"] == PODS, "every server and its milliseconds are read")
check(s["preferred"] == ["aws-euc1-prod.eu-gp-frankfurt-1"], "VALORANT's preferred server is read")
check(FAKE_ID not in json.dumps(samples, default=str), "the account id is never kept")
check(isinstance(s["when"], datetime), "the timestamp is read (UTC in the log, local in the sample)")
check(ping.city("aws-euc1-prod.eu-gp-frankfurt-1") == "Frankfurt" and ping.city("aws-ist1-prod.eu-gp-istanbul-2") ==
      "Istanbul 2" and ping.city("aws-afs1-prod.eu-gp-capetown-1") == "Cape Town" and ping.city("odd-name") == "odd-name",
      "server names become city names (numbered when the city has more than one)")
check(ping.region_of("aws-apne1-prod.eu-gp-tokyo-1") == "eu" and ping.region_of("x") is None,
      "the region comes from the server name")

# ---- history file -------------------------------------------------------------------------------------------------
log_dir = Path(tempfile.mkdtemp(prefix="ts-pinglogs-"))
day1 = dict(PODS)
day2 = {**PODS, "aws-euc1-prod.eu-gp-frankfurt-1": 58, "aws-ist1-prod.eu-gp-istanbul-2": 46}
(log_dir / "ShooterGame-backup-2026.11.19-20.00.00.log").write_text(ping_line("2026.11.19-19.00.00", day1) + "\n")
(log_dir / "ShooterGame.log").write_text(ping_line("2026.11.21-19.36.42", day2) + "\n" + ping_line("2026.11.21-19.36.42", day2) + "\n")
stored = ping.update(log_dir)
check(len(stored) == 2, f"both game starts are stored, the duplicate line once ({len(stored)})")
check(ping.PING_FILE.exists() and FAKE_ID not in ping.PING_FILE.read_text(), "ping.json is written without the account id")
stored = ping.update(log_dir)
check(len(stored) == 2, "reading the same logs again adds nothing")
(log_dir / "ShooterGame-backup-2026.11.19-20.00.00.log").unlink()              # VALORANT deleted its old log
(log_dir / "ShooterGame.log").write_text(ping_line("2026.11.23-18.00.00", {**PODS, "aws-euc1-prod.eu-gp-frankfurt-1": 71}) + "\n")
stored = ping.update(log_dir)
check(len(stored) == 3 and stored[0]["when"] < stored[1]["when"] < stored[2]["when"],
      "measurements survive VALORANT deleting its logs, oldest first")
ping.PING_FILE.write_text("{not json", encoding="utf-8")
check(ping.load() == [] and ping.PING_FILE.with_suffix(".broken.json").exists(),
      "a damaged ping.json is moved aside and the history starts again")
stored = ping.update(log_dir)
check(len(stored) == 1, "after a damaged file, the logs fill the history again")

# ---- board --------------------------------------------------------------------------------------------------------
t0 = datetime(2026, 11, 10, 20, 0)
history = []
for i in range(6):
    pods = {"aws-euc1-prod.eu-gp-frankfurt-1": 24 + (i % 3), "aws-euw3-prod.eu-gp-paris-1": 31 + i,
            "aws-apne1-prod.eu-gp-tokyo-1": 250}
    history.append({"when": (t0 + timedelta(days=i)).isoformat(timespec="seconds"), "pods": pods,
                    "preferred": ["aws-euc1-prod.eu-gp-frankfurt-1"]})
b = ping.board(history, now=t0 + timedelta(days=6))
check(b is not None and [r["city"] for r in b["rows"]] == ["Frankfurt", "Paris", "Tokyo"], "rows are sorted by ping")
fr = b["rows"][0]
check(fr["now"] == 26 and fr["best"] == 24 and fr["worst"] == 26 and fr["typical"] == 25 and fr["samples"] == 6,
      f"now / best / worst / typical come from the recent samples ({fr})")
check(b["preferred"][0]["city"] == "Frankfurt" and b["best"]["city"] == "Frankfurt", "preferred and lowest server found")
check(b["region"] == "eu" and b["region_name"] == "Europe", "the region is Europe")
check(b["spread"] == (24, 26) and b["sessions"] == 6, f"between-session spread of the preferred server ({b['spread']})")
texts = [t for _, _, t in ping.insights(b)]
check(any(t.startswith("Your server is Frankfurt at 26 ms") for t in texts), "the insight names the server and ping")
check(any(t.startswith("Steady:") and "Minimum" in t for t in texts), "a steady ping advises Network Buffering Minimum")
check(ping.board([]) is None and "Network Buffering" in ping.insights(None)[0][2], "no data: an explanation")

# preferred isn't the lowest, and the ping jumps between sessions
jumpy = []
for i in range(5):
    jumpy.append({"when": (t0 + timedelta(days=i)).isoformat(timespec="seconds"),
                  "pods": {"aws-euc1-prod.eu-gp-frankfurt-1": [55, 58, 90, 56, 120][i], "aws-ist1-prod.eu-gp-istanbul-2": 44},
                  "preferred": ["aws-euc1-prod.eu-gp-frankfurt-1"]})
b2 = ping.board(jumpy, now=t0 + timedelta(days=5))
texts = [t for _, _, t in ping.insights(b2)]
check(any("lists Frankfurt as your preferred server (120 ms), but Istanbul 2 measured lower (44 ms)" in t for t in texts),
      "preferred server vs lowest ping is explained")
check(any(t.startswith("Unsteady:") and "Moderate" in t for t in texts), "a jumpy ping advises Network Buffering Moderate")
check(ping.quality(30) == "great" and ping.quality(60) == "good" and ping.quality(90) == "okay" and ping.quality(140) == "high",
      "ping words")

# old samples beyond the window are ignored for 'typical' when there are enough recent ones
old = [{"when": (t0 - timedelta(days=60)).isoformat(timespec="seconds"), "pods": {"aws-euc1-prod.eu-gp-frankfurt-1": 300},
        "preferred": []}]
b3 = ping.board(old + history, now=t0 + timedelta(days=6))
check(b3["rows"][0]["worst"] == 26, "a two-month-old measurement doesn't count as recent")

# ---- Riot status --------------------------------------------------------------------------------------------------
now = datetime(2026, 11, 24, 12, 0)
status = {
    "id": "EU", "name": "Europe", "maintenances": [], "incidents": [
        {"id": 1, "created_at": "2026-11-23T10:00:00+00:00", "updated_at": None, "archive_at": None,
         "titles": [{"locale": "de_DE", "content": "Login-Probleme"}, {"locale": "en_US", "content": "Login issues"}],
         "updates": [{"id": 9, "created_at": "2026-11-23T10:00:00+00:00", "publish": True,
                      "translations": [{"locale": "en_US", "content": "Some players can't log in."}],
                      "publish_locations": ["game"]}],
         "platforms": ["windows", "ps5"], "incident_severity": "warning"},
        {"id": 2, "created_at": "2026-11-23T10:00:00+00:00", "titles": [{"locale": "en_US", "content": "Console only"}],
         "updates": [], "platforms": ["ps5", "xbox"], "incident_severity": "critical"},
        {"id": 3, "created_at": "2026-03-02T08:20:51+00:00", "updated_at": "2026-05-28T19:37:49+00:00",
         "titles": [{"locale": "en_US", "content": "Game Server Unavailable"}], "updates": [],
         "platforms": ["windows"], "incident_severity": "critical"}]}
st = ping.parse_status(status, "eu", now=now)
check(st["region"] == "eu" and st["name"] == "Europe", "status region and name")
check([e["title"] for e in st["entries"]] == ["Login issues"], "only fresh Windows notices are listed, in English")
check(st["entries"][0]["text"] == "Some players can't log in." and st["entries"][0]["severity"] == "warning",
      "the latest update text and severity are read")
check([e["title"] for e in st["older"]] == ["Game Server Unavailable"], "months-old notices are counted separately")
check(ping.parse_status({}, "na", now=now)["entries"] == [] and ping.parse_status({}, "na", now=now)["name"] ==
      "North America", "an empty feed is fine")
check(ping.status_page("eu").startswith("https://status.riotgames.com/valorant?region=eu"), "status page link")

print("\nALL PASSED" if not fails else f"\n{len(fails)} FAILED")
sys.exit(1 if fails else 0)
