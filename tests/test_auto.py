"""Every-PC automation: vendor custom resolutions, closest-mode fallback (real switch on the Intel screen),
first run without settings files, and re-setup after the game closes."""
import os, shutil, sys, tempfile, time
from pathlib import Path
TMP = Path(tempfile.mkdtemp(prefix="ts-auto-"))
os.environ["APPDATA"] = str(TMP / "appdata")
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QCoreApplication
app = QCoreApplication([])
import truestretch.games.valorant as val
from truestretch import display, displayconfig
from truestretch.settings import Settings
from truestretch.games import GAMES
from truestretch.engine import Engine
from truestretch.system import running_processes

assert "valorant-win64-shipping.exe" not in running_processes(), "VALORANT is running - not touching the screen"
real_root = val.CONFIG_ROOT
fails = []
def check(cond, text):
    print(("PASS " if cond else "FAIL ") + text)
    if not cond:
        fails.append(text)

# vendor libraries load or fail cleanly
for mod, cls in (("amd", "AmdApi"), ("intel", "IntelApi")):
    m = __import__(f"truestretch.{mod}", fromlist=[cls])
    try:
        getattr(m, cls)()
        print(f"INFO {cls} loaded")
    except OSError as exc:
        print(f"INFO {cls} not usable here (expected on this PC): {exc}")

e = Engine(Settings({g.id: g.default_settings() for g in GAMES})); e.timer.stop()
gs = e.gs("valorant")
intel = next(d for d in display.list_displays() if d.vendor == "intel")
nvidia = next(d for d in display.list_displays() if d.vendor == "nvidia")

# 1) Intel screen: driver refuses every x1080 custom size -> closest built-in mode, automatically
gs["display"] = intel.device
expect = {1568: None, 1440: (1400, 1050), 1360: (1280, 1024), 1280: (1280, 1024)}
for w in (1568, 1440, 1360, 1280):
    gs["width"], gs["height"] = w, 1080
    e._resolved.clear()
    mode = e.ensure_stretch_mode("valorant")
    f = (1920 / 1080) / (mode.width / mode.height)
    print(f"     intel {w}x1080 -> {mode} (models {f:.2f}x wider)")
    check(mode.width < 1920 and f > 1.08, f"Intel {w}x1080 resolves to a real stretched mode")
    if expect[w]:
        check(mode.size == expect[w], f"Intel {w}x1080 -> {expect[w]}")
check(not any(lvl == "error" for _, lvl, _ in e.history), "no error messages on the Intel screen")

# 2) REAL switch on the Intel screen with the fallback, then back
gs["width"], gs["height"] = 1440, 1080
e._resolved.clear()
before = display.current_mode(intel.device)
scaling_before = displayconfig.monitor_for(intel.device).scaling
r = e.stretch_now("valorant", "test")
time.sleep(1.5)
now = display.current_mode(intel.device)
mon = displayconfig.monitor_for(intel.device)
print(f"     intel stretched: {now}  windows scaling={mon.scaling} (stretches={mon.stretches})")
check(now.size == (1400, 1050), "Intel screen really switched to 1400x1050")
e.revert_display("test done")
time.sleep(1.0)
check(display.current_mode(intel.device) == before, f"Intel screen back to {before}")
check(displayconfig.monitor_for(intel.device).scaling == scaling_before, "Intel scaling restored")

# 3) NVIDIA screen: exact sizes still used
gs["display"] = nvidia.device
for w in (1568, 1440, 1360, 1280):
    gs["width"], gs["height"] = w, 1080
    e._resolved.clear()
    mode = e.ensure_stretch_mode("valorant")
    check(mode.size == (w, 1080), f"NVIDIA {w}x1080 exact -> {mode}")

# 4) first run: no settings files at all -> Play works, auto-stretch waits, setup happens after the game closes
fake = TMP / "Config"
fake.mkdir()
val.CONFIG_ROOT = fake
gs["width"], gs["height"] = 1280, 1080
e._resolved.clear()
e.refresh(quiet=True)
# the monitor-driver gate depends on what is plugged in (a new monitor gets an enabled driver from Windows):
# check the gate itself, then test the first-run logic with it satisfied
from truestretch.engine import MonitorDriversOn
real_gate = e.monitor_drivers_on
e.monitor_drivers_on = lambda gid=None: True
try:
    e.prepare("valorant")
    check(False, "Play refused while a monitor driver is on")
except MonitorDriversOn:
    check(True, "Play refused while a monitor driver is on")
e.monitor_drivers_on = lambda gid=None: False
mode = e.prepare("valorant")
e.monitor_drivers_on = real_gate
check("valorant" in e._first_run, f"first-run Play accepted (stretch {mode})")
acct = fake / "0123abcd-4567-89ef-0123-456789abcdef-eu" / "WindowsClient"
acct.mkdir(parents=True)
src = next(real_root.glob("*/WindowsClient/GameUserSettings.ini"))
shutil.copy(src, acct / "GameUserSettings.ini")
ini = acct / "GameUserSettings.ini"
txt = ini.read_text(encoding="utf-8", errors="ignore")
for k in ("bShouldLetterbox=False", "FullscreenMode=1"):
    txt = txt.replace(k, k.replace("False", "True").replace("=1", "=0"))
ini.write_text(txt, encoding="utf-8")       # like VALORANT's own first-time file: letterbox + fullscreen
t = e.targets("valorant")[0]
check(not val.Valorant().target_ready(t, 1920, 1080, gs), "fresh file is NOT ready (as expected)")
e.running["valorant"] = False
e._after_close("valorant")
t = e.targets("valorant")[0]
check(val.Valorant().target_ready(t, 1920, 1080, gs), "after the game closed the new account is set up")
check("valorant" not in e._first_run, "first-run flag cleared")
msgs = [m for _, lvl, m in e.history if lvl == "success"]
print("     ", msgs[-1])
# a second close with nothing changed does nothing
n = len(e.history)
e._after_close("valorant")
check(len(e.history) == n, "nothing re-written when already set up")

val.CONFIG_ROOT = real_root
shutil.rmtree(TMP, ignore_errors=True)
print("\nALL PASSED" if not fails else f"\n{len(fails)} FAILED")
