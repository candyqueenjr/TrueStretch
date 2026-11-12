"""REAL test of the guard: stretch the screen, start a fake owner, kill it, guard must restore the desktop."""
import json, os, subprocess, sys, tempfile, time
from pathlib import Path
appdata = Path(tempfile.mkdtemp(prefix="ts-guard-"))
os.environ["APPDATA"] = str(appdata)
ROOT = str(Path(__file__).resolve().parents[1])
sys.path.insert(0, ROOT)
from truestretch import display
from truestretch.display import Mode

py = Path(sys.executable).with_name("python.exe")
d = display.find_display()
before = display.current_mode(d.device)
print("before:", before)
owner = subprocess.Popen([str(py), "-c", "import time; time.sleep(300)"])
display.set_mode(Mode(1440, 1080, before.hz), d.device, persist=False)
state = {"stretched": True, "game": "valorant", "device": d.device, "owner": owner.pid,
         "previous": before.to_list(), "mode": [1440, 1080, before.hz]}
(appdata / "TrueStretch").mkdir(parents=True, exist_ok=True)
(appdata / "TrueStretch" / "session.json").write_text(json.dumps(state), encoding="utf-8")
guard = subprocess.Popen([str(py), str(Path(ROOT) / "main.py"), "--watchdog", str(owner.pid)],
                         env=dict(os.environ), creationflags=0x00000008 | 0x00000200)
time.sleep(2)
print("stretched:", display.current_mode(d.device), "| killing owner (like Task Manager / crash)")
subprocess.run(["taskkill", "/F", "/PID", str(owner.pid)], capture_output=True)
for _ in range(20):
    time.sleep(0.5)
    if display.current_mode(d.device) == before:
        break
after = display.current_mode(d.device)
print("after:", after, "| guard exited:", guard.poll() is not None)
print("session file:", (appdata / "TrueStretch" / "session.json").read_text())
print("GUARD TEST", "PASSED" if after == before else "FAILED")
if after != before:
    display.set_mode(before, d.device)
