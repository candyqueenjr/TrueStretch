"""Safety nets added in 2.0, tested without touching the real screen, registry or game files:
switching back only forgets the stretch once the screen has really left it (and retries otherwise), the guard
process respects "stay stretched after quitting", in-match scaling is never saved to Windows' display database,
crash-safe writes, damaged files are set aside instead of silently wiping data, and a settings file that can't be
decoded exactly is never written back."""
import json
import os
import sys
import tempfile
import types
from pathlib import Path

os.environ["APPDATA"] = tempfile.mkdtemp(prefix="ts-safety-")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from truestretch import display, displayconfig, engine as eng, paths, settings, watchdog   # noqa: E402
from truestretch.display import DisplayError, Mode                                            # noqa: E402
from truestretch.inifile import IniFile                                                        # noqa: E402

fails = []


def check(c, t):
    print(("PASS " if c else "FAIL ") + t)
    c or fails.append(t)


NATIVE, STRETCH = Mode(1920, 1080, 144), Mode(1440, 1080, 144)


class FakeScreen:
    """Stands in for the display module functions revert_display uses."""

    def __init__(self, current=STRETCH, refuse=False, ignore=False):
        self.current, self.refuse, self.ignore = current, refuse, ignore
        self.calls = []

    def current_mode(self, device=None):
        return self.current

    def available_modes(self, device=None):
        return [NATIVE, STRETCH]

    def set_mode(self, mode, device=None, persist=True):
        self.calls.append(("set", mode, persist))
        if self.refuse:
            raise DisplayError("refused")
        if not self.ignore:
            self.current = mode

    def restore_saved_mode(self, device=None):
        self.calls.append(("saved",))
        if not self.ignore:
            self.current = NATIVE


def stub_engine(screen):
    s = types.SimpleNamespace()
    s.state = settings.SessionState()
    s.state.mark_stretched("valorant", r"\\.\DISPLAY1", NATIVE, STRETCH)
    s.games = {"valorant": None}
    s.gs = lambda gid: {"normal": "previous", "width": 1440, "height": 1080}
    s.messages = []
    s.notify = lambda level, text: s.messages.append((level, text))
    s.changed = types.SimpleNamespace(emit=lambda: None)
    s._revert_retry, s._revert_error_shown = None, False
    s._revert_target = types.MethodType(eng.Engine._revert_target, s)
    s._revert_failed = types.MethodType(eng.Engine._revert_failed, s)
    return s


real = {name: getattr(display, name) for name in ("current_mode", "available_modes", "set_mode", "restore_saved_mode")}
real_scaling = displayconfig.set_scaling
displayconfig.set_scaling = lambda *a, **k: True


def use(screen):
    for name in real:
        setattr(display, name, getattr(screen, name))


try:
    # 1. normal switch back
    screen = FakeScreen()
    use(screen)
    s = stub_engine(screen)
    ok = eng.Engine.revert_display(s, "test")
    check(ok and screen.current == NATIVE and not s.state.stretched, "switch back: native again, stretch forgotten")

    # 2. the screen can't be read (driver reset): keep the record and retry later
    screen = FakeScreen(current=None)
    use(screen)
    s = stub_engine(screen)
    ok = eng.Engine.revert_display(s, "test")
    check(not ok and s.state.stretched and s._revert_retry, "screen unreadable: stretch kept on record, retry planned")
    check(sum(1 for lvl, _ in s.messages if lvl == "error") == 1, "...and the player is told once")
    eng.Engine.revert_display(s, "again")
    check(sum(1 for lvl, _ in s.messages if lvl == "error") == 1, "...not again on the retry")

    # 3. Windows refuses the mode: fall back to Windows' saved mode (never stretched)
    screen = FakeScreen(refuse=True)
    use(screen)
    s = stub_engine(screen)
    ok = eng.Engine.revert_display(s, "test")
    check(ok and ("saved",) in screen.calls and screen.current == NATIVE, "refused: saved-mode fallback used")

    # 4. nothing works: the stretch stays on record (the guard process and the retry still know about it)
    screen = FakeScreen(refuse=True, ignore=True)
    use(screen)
    s = stub_engine(screen)
    ok = eng.Engine.revert_display(s, "test")
    check(not ok and s.state.stretched, "still stretched after every attempt: not forgotten")

    # 5. the player already switched to something else: nothing forced, record cleared
    screen = FakeScreen(current=Mode(1600, 900, 60))
    use(screen)
    s = stub_engine(screen)
    ok = eng.Engine.revert_display(s, "test")
    check(ok and not screen.calls and not s.state.stretched, "desktop no longer stretched: left alone, record cleared")
finally:
    for name, fn in real.items():
        setattr(display, name, fn)
    displayconfig.set_scaling = real_scaling

# ---- in-match scaling is applied without saving -------------------------------------------------------------------
captured = {}
fake_user32 = types.SimpleNamespace(SetDisplayConfig=lambda n, p, nm, m, flags: captured.setdefault("flags", flags)
                                    and 0 or 0)
orig_user32, orig_query, orig_info = displayconfig.user32, displayconfig._query, displayconfig._info


class Path_:
    def __init__(self):
        self.sourceInfo = types.SimpleNamespace(adapterId=0, id=0)
        self.targetInfo = types.SimpleNamespace(scaling=1)


def fake_info(obj, kind, adapter, ident):
    obj.viewGdiDeviceName = r"\\.\DISPLAY1"
    return True


try:
    displayconfig.user32 = fake_user32
    displayconfig._query = lambda: ([Path_()], [], 1, 0)
    displayconfig._info = fake_info
    displayconfig.set_scaling(r"\\.\DISPLAY1", displayconfig.SCALING_STRETCHED, save=False)
    no_save = captured.pop("flags")
    displayconfig.set_scaling(r"\\.\DISPLAY1", displayconfig.SCALING_STRETCHED)
    with_save = captured.pop("flags")
    check(not no_save & displayconfig.SDC_SAVE_TO_DATABASE, "in-match scaling: not saved to Windows' display database")
    check(bool(with_save & displayconfig.SDC_SAVE_TO_DATABASE), "normal scaling change: still saved")
finally:
    displayconfig.user32, displayconfig._query, displayconfig._info = orig_user32, orig_query, orig_info

# ---- the guard process respects "stay stretched after quitting" ---------------------------------------------------
st = settings.SessionState()
st.mark_stretched("valorant", r"\\.\DISPLAY1", NATIVE, STRETCH)
st.keep_on_exit()
reverted = []
orig_set = display.set_mode
display.set_mode = lambda *a, **k: reverted.append(a)
try:
    watchdog.run(999999)                 # a pid that doesn't exist: "TrueStretch has ended"
finally:
    display.set_mode = orig_set
check(not reverted and json.loads(paths.STATE_FILE.read_text())["stretched"], "watchdog leaves a kept stretch alone")
settings.SessionState().clear()

# ---- crash-safe writes & damaged files ----------------------------------------------------------------------------
target = Path(os.environ["APPDATA"]) / "atomic.txt"
paths.atomic_write_text(target, "one")
paths.atomic_write_text(target, "two")
leftovers = [p for p in target.parent.iterdir() if p.name.startswith(".atomic.txt.")]
check(target.read_text() == "two" and not leftovers, "atomic write replaces the file and leaves no temp files")

paths.STATE_FILE.write_text("{ broken", encoding="utf-8")
st = settings.SessionState()
check(st.data == {} and paths.STATE_FILE.with_suffix(".broken.json").exists(),
      "damaged session.json is set aside (kept as .broken.json)")

from truestretch import optimizer as opt          # noqa: E402
opt.UNDO_FILE.write_text("[1, 2", encoding="utf-8")
o = opt.Optimizer(types.SimpleNamespace())
o.items = []
check(o._undo_data() == {} and o.undo_broken, "damaged undo file: detected")
try:
    o.apply(["anything"])
    blocked = False
except OSError:
    blocked = True
check(blocked, "...and Optimize refuses to run, so the original values can't be overwritten")

# ---- settings files that can't be decoded exactly are never written back -------------------------------------------
ini_path = Path(os.environ["APPDATA"]) / "GameUserSettings.ini"
ini_path.write_bytes(b"[ScalabilityGroups]\r\nsg.ResolutionQuality=100\r\n")
ini = IniFile(ini_path)
ini.set("ScalabilityGroups", {"sg.ResolutionQuality": "75"})
ini.save()
check(IniFile(ini_path).get("ScalabilityGroups", ["sg.ResolutionQuality"]) == {"sg.ResolutionQuality": "75"}
      and ini_path.read_bytes().endswith(b"\r\n"), "normal ini: saved, CRLF kept")
ini = IniFile(ini_path)
ini.lossy = True                      # what the reader sets when the bytes couldn't be decoded exactly
try:
    ini.save()
    refused = False
except OSError:
    refused = True
check(refused, "lossy ini: refused instead of writing '?' into the player's file")

print("\nALL PASSED" if not fails else f"\n{len(fails)} FAILED")
sys.exit(1 if fails else 0)
