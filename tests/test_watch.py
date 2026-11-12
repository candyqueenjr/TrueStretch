"""Replays today's failure: old log ends in RangeV2 ready, the game starts, then replaces the log."""
import os, sys, tempfile
from pathlib import Path
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))
from truestretch.games.valorant import Valorant
from truestretch.matchwatch import MatchWatcher

v = Valorant()
d = Path(tempfile.mkdtemp())
log = d / "ShooterGame.log"
L = lambda m, r: (f"[2026.11.05-11.35.58:389][ 79]LogMapLoadModel: Update: [Map Name: {m} | Changed: FALSE] "
                  f"[Local World: TRUE | Changed: FALSE] [Match Setup: TRUE | Changed: FALSE] "
                  f"[Map Ready: {'TRUE' if r else 'FALSE'} | Changed: TRUE]\n")
fails = []
def check(c, t):
    print(("PASS " if c else "FAIL ") + t); c or fails.append(t)

log.write_text("x" * 5000 + "\n" + L("MainMenuV2", True) + L("RangeV2", False) + L("RangeV2", True))
w = MatchWatcher(log, v.parse_log_line, v.MENU_MAPS)
w.arm()                                   # game process just appeared
check(not w.poll() and not w.in_match, "old session's 'RangeV2 ready' is ignored at game start")
os.replace(log, d / "ShooterGame-backup.log")   # the game rotates its log...
log.write_text(L("Init", True))                 # ...and starts a fresh one
check(not w.poll() and not w.in_match, "fresh log: menu, not in match")
with open(log, "a") as f:
    f.write(L("MainMenuV2", True) + L("Juliett", False))
check(not w.poll() and not w.in_match, "map loading: not yet")
with open(log, "a") as f:
    f.write(L("Juliett", True))
check(w.poll() and w.in_match, "map ready: stretch now")
with open(log, "a") as f:
    f.write(L("MainMenuV2", True))
check(w.poll() and not w.in_match, "back to menu: revert")
with open(log, "a") as f:
    f.write(L("RangeV2", True))
w.poll()
os.replace(log, d / "ShooterGame-backup2.log")
log.write_text(L("Init", True))
check(w.poll() and not w.in_match, "log replaced while in match: reported as a change (reverts)")
# app started while the game is already running mid-match: reads the whole log
w2 = MatchWatcher(log, v.parse_log_line, v.MENU_MAPS)
with open(log, "a") as f:
    f.write(L("Jam", True))
check(w2.poll() and w2.in_match, "app opened mid-match: picks up the current match")

# --- A real session's shape (owner's log 2026-11-10, VALORANT release-13.09/13.10 era), rebuilt from synthetic lines
# in the exact formats the game writes (no player name, server, match id). Agent select now polls Pregame_GetMatch
# every second or so (up to ~40 times per match) and once more when the menu loads after a match; a dodged/remade
# match loads its map and leaves again within ~11 s. Expected: one stretch per real map, native on every leave.
def M(m, r=True):
    return L(m, r)
GM = ("[2026.11.10-22.01.29:805][742]LogPlatformCommon: Platform HTTP Query End. QueryName: [Pregame_GetMatch], "
      "URL [GET https://example.invalid/pregame/v1/matches/00000000-0000-0000-0000-000000000000], "
      "Response Code: [200], Seconds Since Query [0.084000]\n")
def LEAVE(to):
    return f"[2026.11.10-22.20.03:906][988]LogGameFlowStateManager: [PlatformTime: 1.0] Transitioning from InGame to {to}\n"
def agent_select(polls):
    return GM + M("CharacterSelectPersistentLevel") + GM * polls
session = [
    M("Init"), M("MainMenuV2"), M("RangeV2", False), M("RangeV2"),            # Range
    LEAVE("TransitionToInGame"), M("Init"), M("MainMenuV2"),
    agent_select(11), M("HURM_Helix", False), M("HURM_Helix"),                  # remade match: 11 s in the map
    LEAVE("TransitionToInGame"), M("Init"), GM, M("MainMenuV2"),
    agent_select(10), M("HURM_Helix"), M("HURM_Helix"),                         # same map logged ready twice
    LEAVE("TransitionToMainMenu"), M("MainMenuV2"), GM,
    agent_select(40), M("Duality"), LEAVE("TransitionToMainMenu"), M("MainMenuV2"), GM,
    agent_select(27), M("Jam"), LEAVE("TransitionToMainMenu"), M("MainMenuV2"),
]
log3 = Path(tempfile.mkdtemp()) / "ShooterGame.log"
log3.write_text("")
w3 = MatchWatcher(log3, v.parse_log_line, v.MENU_MAPS)
switches = []
for chunk in session:
    for line in chunk.splitlines(keepends=True):     # one poll per line, like the app reading a live log
        with open(log3, "a") as f:
            f.write(line)
        if w3.poll():
            switches.append(("STRETCH " if w3.in_match else "NATIVE ") + (w3.map or ""))
expected = ["STRETCH RangeV2", "NATIVE RangeV2", "STRETCH HURM_Helix", "NATIVE HURM_Helix", "STRETCH HURM_Helix",
            "NATIVE HURM_Helix", "STRETCH Duality", "NATIVE Duality", "STRETCH Jam", "NATIVE Jam"]
check(switches == expected, f"real session shape: {len(expected)} switches, none from agent-select polling "
      f"(got {switches})" if switches != expected else "real session shape: one stretch per map, native on "
      "every leave, agent-select polling never switches")
check(not w3.in_match, "session ends native in the menu")
print("\nALL PASSED" if not fails else f"\n{len(fails)} FAILED")
