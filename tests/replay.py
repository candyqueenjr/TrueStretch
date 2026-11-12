"""Replay real VALORANT logs through the watcher, line by line; print every stretch / native switch."""
import os, re, sys, tempfile
from pathlib import Path
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))
from truestretch.games.valorant import Valorant
from truestretch.matchwatch import MatchWatcher

v = Valorant()
logs = Path(os.environ["LOCALAPPDATA"]) / "VALORANT" / "Saved" / "Logs"
TS = re.compile(rb"^\[(\d{4}\.\d\d\.\d\d-\d\d\.\d\d\.\d\d:\d{3})\]")
for name in sys.argv[1:]:
    src = (logs / name).read_bytes().split(b"\n")
    tmp = Path(tempfile.mkdtemp()) / "ShooterGame.log"
    tmp.write_bytes(b"")
    w = MatchWatcher(tmp, v.parse_log_line, v.MENU_MAPS)
    print(f"== {name}")
    with open(tmp, "ab") as f:
        for i, line in enumerate(src):
            f.write(line + b"\n")
            interesting = (b"LogMapLoadModel" in line or b"Transitioning from" in line
                           or b"Pregame_GetMatch" in line or b"Resolution changed" in line)
            if not interesting and i % 400:
                continue
            f.flush()
            if w.poll():
                ts = TS.match(line)
                print(f"   {'STRETCH' if w.in_match else 'NATIVE '} at {ts.group(1).decode() if ts else '?'}  (map={w.map})")
            if b"Resolution changed to" in line:
                print(f"   game re-read size at {TS.match(line).group(1).decode()}: {w.game_resolution}  "
                      f"-> desktop is {'STRETCHED (bad)' if w.in_match else 'native (ok)'}")
