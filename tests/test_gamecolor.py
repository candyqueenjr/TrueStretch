"""Game Color (2.3): the colour boost is on only while the game window is in front, follows the chosen strength,
always goes back to the exact level that was there before (alt-tab, game closed, TrueStretch quitting, a crash
recovered at the next start or by the guard process), never stacks on top of itself after a failed restore, and
stops after a driver error instead of retrying every half second. Uses a fake driver; on a PC with an NVIDIA
screen it also does one real round trip (vibrance up by 5, read back, put back - byte-identical level)."""
import json
import os
import sys
import tempfile
from pathlib import Path

os.environ["APPDATA"] = tempfile.mkdtemp(prefix="ts-color-")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from truestretch import gamecolor                     # noqa: E402
from truestretch.gamecolor import ColorError, GameColor, Screen   # noqa: E402

fails = []


def check(c, t):
    print(("PASS " if c else "FAIL ") + t)
    c or fails.append(t)


GAME = {"valorant-win64-shipping.exe"}
DEV = r"\\.\DISPLAY1"


class FakeDriver:
    """One NVIDIA-like screen (0..100, normal 50). Records every set."""

    def __init__(self, level=50, fail_set=False):
        self.level, self.fail_set, self.sets = level, fail_set, []

    def screen(self):
        return Screen("nvidia", DEV, DEV, self.level, 50, 0, 100)

    def find(self, device):
        if device and device.lower() != DEV.lower():
            return None, None, "not this screen"
        return self, self.screen(), None

    def make(self, name):
        return self

    def set_level(self, key, level):
        if self.fail_set:
            raise ColorError("driver said no")
        self.sets.append(level)
        self.level = level


class Front:
    exe = None

    def __call__(self):
        return self.exe


def controller(driver, front):
    return GameColor(find=driver.find, make=driver.make, front=front)


# ---- Screen maths ---------------------------------------------------------------
s = Screen("nvidia", DEV, DEV, 50, 50, 0, 100)
check([s.target(p) for p in (0, 30, 50, 70, 100)] == [50, 65, 75, 85, 100], "NVIDIA strengths map 50->100 %")
a = Screen("amd", "0:0", DEV, 100, 100, 0, 200)
check([a.target(p) for p in (0, 50, 100)] == [100, 150, 200], "AMD saturation maps 100->200")
check(s.shown(75) == "75 %" and a.shown(150) == "150", "values are shown the way each vendor's panel shows them")
check(s.target(500) == 100 and s.target(-3) == 50, "strength is clamped")
check([k for k, _, _ in gamecolor.LEVELS] == ["light", "medium", "strong", "max"], "four strength presets")

# ---- on only while the game is in front ----------------------------------------
drv, front = FakeDriver(), Front()
gc = controller(drv, front)
front.exe = "explorer.exe"
gc.tick(True, 50, DEV, GAME)
check(drv.sets == [] and not gc.applied, "nothing changes while another window is in front")
front.exe = "valorant-win64-shipping.exe"
gc.tick(True, 50, DEV, GAME)
check(drv.level == 75 and gc.applied, "the game in front -> vibrance 75 %")
saved = json.loads(gamecolor.COLOR_FILE.read_text(encoding="utf-8"))
check(saved["previous"] == 50 and saved["owner"] == os.getpid(), "the level before is on disk while it's on")
gc.tick(True, 50, DEV, GAME)
check(drv.sets == [75], "no driver call when nothing changed")
gc.tick(True, 100, DEV, GAME)
check(drv.level == 100 and json.loads(gamecolor.COLOR_FILE.read_text())["target"] == 100,
      "a new strength applies at once")
front.exe = "discord.exe"
gc.tick(True, 100, DEV, GAME)
check(drv.level == 50 and not gc.applied and not gamecolor.COLOR_FILE.exists(),
      "alt-tab -> exact level back, file gone")
front.exe = "valorant-win64-shipping.exe"
gc.tick(True, 30, DEV, GAME)
check(drv.level == 65, "back in the game -> on again")
gc.tick(False, 30, DEV, GAME)
check(drv.level == 50 and not gc.applied, "switched off (or the game closed) -> normal")
front.exe = None
gc.tick(True, 50, DEV, GAME)
check(drv.level == 50, "desktop / lock screen in front -> normal")

# ---- a player who already had their own vibrance --------------------------------
drv, front = FakeDriver(level=63), Front()
gc = controller(drv, front)
front.exe = "valorant-win64-shipping.exe"
gc.tick(True, 50, DEV, GAME)
gc.off()
check(drv.level == 63, "a custom level (63 %) comes back exactly, not the driver default")

# ---- preview on the desktop -----------------------------------------------------
drv, front = FakeDriver(), Front()
gc = controller(drv, front)
gc.preview(100.0, 4.0)
gc.tick(False, 70, DEV, GAME, now=101.0)
check(drv.level == 85, "preview shows the strength while the game isn't running")
gc.tick(False, 70, DEV, GAME, now=104.5)
check(drv.level == 50 and not gc.applied, "preview ends by itself")

# ---- crash recovery -------------------------------------------------------------
drv = FakeDriver(level=85)
gamecolor.write_saved({"backend": "nvidia", "key": DEV, "device": DEV, "previous": 50, "default": 50,
                       "maximum": 100, "target": 85, "percent": 70, "owner": 999999})
check(not gamecolor.restore_saved(only_owner=1234, make=drv.make) and drv.level == 85,
      "the guard leaves a boost alone that another TrueStretch applied")
check(gamecolor.restore_saved(only_owner=999999, make=drv.make) and drv.level == 50,
      "the guard puts back what its TrueStretch applied")
check(not gamecolor.COLOR_FILE.exists(), "and removes the file")
gamecolor.write_saved({"backend": "nvidia", "key": DEV, "device": DEV, "previous": 50, "default": 50,
                       "maximum": 100, "target": 85, "percent": 70, "owner": 999999})
drv.level = 85
check(GameColor(find=drv.find, make=drv.make, front=Front()).recover() and drv.level == 50,
      "the next start puts back a boost left by a crash or power cut")
check(not gamecolor.restore_saved(make=drv.make), "nothing saved -> nothing to do")
gamecolor.COLOR_FILE.write_text("{broken", encoding="utf-8")
check(gamecolor.read_saved() == {} and not gamecolor.restore_saved(make=drv.make), "a damaged file is ignored")
gamecolor.clear_saved()

# ---- a failed restore never loses the original ----------------------------------
drv, front = FakeDriver(), Front()
gc = controller(drv, front)
front.exe = "valorant-win64-shipping.exe"
gc.tick(True, 50, DEV, GAME)                        # 75, previous 50 on disk
drv.fail_set = True
check(not gc.off() and gamecolor.COLOR_FILE.exists(), "a restore the driver refused keeps the file")
drv.fail_set = False
gc.tick(True, 50, DEV, GAME)                        # reads 75 as "current" - must still remember 50
check(gc.applied["previous"] == 50, "turning on again keeps the true original (50), not the boosted 75")
gc.off()
check(drv.level == 50, "and puts back 50")

# ---- errors stop retries ---------------------------------------------------------
drv, front = FakeDriver(fail_set=True), Front()
gc = controller(drv, front)
front.exe = "valorant-win64-shipping.exe"
msg = gc.tick(True, 50, DEV, GAME)
check(msg == "driver said no" and gc.failed, "a driver error is reported once")
check(gc.tick(True, 50, DEV, GAME) is None, "and not retried every half second")
gc.preview(0.0)
check(gc.failed is None, "pressing Preview (or changing a setting) tries again")
drv2, front2 = FakeDriver(), Front()
gc2 = GameColor(find=lambda d: (None, None, "Intel screen"), make=drv2.make, front=front2)
front2.exe = "valorant-win64-shipping.exe"
check(gc2.tick(True, 50, DEV, GAME) == "Intel screen" and drv2.sets == [],
      "an unsupported screen says why and changes nothing")
gamecolor.clear_saved()

# ---- the real window-in-front reader ---------------------------------------------
fg = gamecolor.foreground_exe()
check(fg is None or (isinstance(fg, str) and fg.endswith(".exe")), f"foreground window read ({fg})")

# ---- real NVIDIA round trip (skipped without an NVIDIA screen) --------------------
try:
    from truestretch.system import running_processes
    if GAME & running_processes():
        print("SKIP real driver round trip: VALORANT is running")
        raise OSError("skip")
    nv = gamecolor.NvidiaColor()
    screens = nv.screens()
    if not screens:
        print("SKIP real driver round trip: no screen on the NVIDIA graphics")
        raise OSError("skip")
    sc = screens[0]
    before = sc.level
    check(sc.minimum <= before <= sc.maximum and sc.minimum < sc.maximum,
          f"NVIDIA reports a sane range ({sc.minimum}..{sc.maximum}, now {before}, normal {sc.default})")
    up = min(sc.maximum, before + 5) if before + 5 <= sc.maximum else before - 5
    try:
        nv.set_level(sc.key, up)
        now_level = next(x.level for x in nv.screens() if x.key == sc.key)
        check(now_level == up, f"real set reads back ({before} -> {now_level})")
    finally:
        nv.set_level(sc.key, before)
    after = next(x.level for x in nv.screens() if x.key == sc.key)
    check(after == before, f"real level put back exactly ({after})")
except OSError as exc:
    if str(exc) != "skip":
        print(f"SKIP real driver round trip: {exc}")

print("\nALL PASSED" if not fails else f"\n{len(fails)} FAILED")
sys.exit(1 if fails else 0)
