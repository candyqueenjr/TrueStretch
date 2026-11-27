"""Optimize Max undo without the scan (2.4.0): every change keeps a self-describing backup in the undo file, so Undo
puts the exact original back even when a later scan no longer lists the setting (VALORANT uninstalled, power plan
switched, program removed). Also: the "Your changes" list, the restart reminder, the after-Optimize summary and the
Delivery Optimization check. Hardware-free: only a scratch key under HKCU\\Software\\TrueStretchTest is written
(and deleted); administrator commands and power-plan writes are captured, not run."""
import os
import sys
import tempfile
import winreg
from datetime import datetime, timedelta
from pathlib import Path

os.environ["APPDATA"] = tempfile.mkdtemp(prefix="ts-undo-")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from truestretch import optimizer as opt                      # noqa: E402
from truestretch import optimizer_more as more                # noqa: E402
from truestretch import powerplan                             # noqa: E402
from truestretch.optimizer import DONE, HKCU, IMPROVE, Item, reg_spec   # noqa: E402

fails = []


def check(c, t):
    print(("PASS " if c else "FAIL ") + t)
    c or fails.append(t)


KEY = r"Software\TrueStretchTest\Undo"


def wipe():
    for sub in (KEY, r"Software\TrueStretchTest"):
        try:
            winreg.DeleteKey(HKCU, sub)
        except OSError:
            pass


def values():
    out = {}
    try:
        with winreg.OpenKey(HKCU, KEY) as k:
            i = 0
            while True:
                try:
                    n, v, t = winreg.EnumValue(k, i)
                except OSError:
                    break
                out[n] = (v, t)
                i += 1
    except OSError:
        pass
    return out


wipe()
with winreg.CreateKeyEx(HKCU, KEY, 0, winreg.KEY_SET_VALUE) as k:
    winreg.SetValueEx(k, "Text", 0, winreg.REG_SZ, "original")
    winreg.SetValueEx(k, "Blob", 0, winreg.REG_BINARY, bytes([2, 0, 0, 0, 9, 8, 7]))
    # "Missing" deliberately absent: undo must delete it again
before = values()


def apply_change():
    with winreg.CreateKeyEx(HKCU, KEY, 0, winreg.KEY_SET_VALUE) as k:
        winreg.SetValueEx(k, "Text", 0, winreg.REG_SZ, "optimized")
        winreg.SetValueEx(k, "Blob", 0, winreg.REG_BINARY, bytes([3]) + bytes(11))
        winreg.SetValueEx(k, "Missing", 0, winreg.REG_DWORD, 1)


def make_item():
    done = values().get("Text", ("",))[0] == "optimized"
    return Item("t_reg", "Windows", "Test setting", "", "optimized" if done else "original", "optimized",
                DONE if done else IMPROVE, "More FPS", 2, fallback=reg_spec(HKCU, KEY, "Text", "Blob", "Missing"),
                _apply=apply_change, _snapshot=lambda: "own-snapshot",
                _restore=lambda d: (_ for _ in ()).throw(AssertionError("item restore must not run")))


o = opt.Optimizer(None)
listed = {"on": True}


def fake_scan(progress=None):
    o.items = [make_item()] if listed["on"] else []
    o.scanned_at = datetime.now()
    return o.items


o.scan = fake_scan
o.scan()
results = o.apply(["t_reg"])
check(results and results[0][1], "the change is applied and verified")
entry = o._undo_data()["t_reg"]
check(entry.get("from") == "original" and entry.get("to") == "optimized" and entry.get("group") == "Windows",
      "the undo entry keeps what changed (from → to, group) for the Your changes list")
fb = entry.get("fallback") or {}
check(fb.get("kind") == "reg" and fb["backup"][0][2]["Blob"][0] == {"hex": "02000000090807"}
      and fb["backup"][0][2]["Missing"] is None, "the backup is JSON-safe (binary as hex, missing value as None)")

listed["on"] = False                       # the next scan doesn't produce the item any more
o.items = []
done = o.undo()
check(done == ["t_reg"], "Undo works although the scan no longer lists the setting")
check(values() == before, f"registry byte-identical after the fallback undo ({values()} vs {before})")
check(not o.changed_ids(), "the undo file is empty afterwards")
check(not o.last_undo_failed, "nothing reported as failed")

# An old-format entry (no fallback) for a missing item is still reported, not silently dropped.
o._save_undo({"old": {"time": "2026-11-01T10:00:00", "title": "Old change", "data": 1}})
o.undo()
check(o.last_undo_failed == ("Old change",) and "old" in o.changed_ids(),
      "an entry without a backup and without its item is reported and kept")
o._save_undo({})

# Admin changes: the undo commands are stored when the change is made.
ran = []
opt.run_elevated = lambda cmds, hwnd=None, *a, **k: ran.append(list(cmds)) or 0
admin_item = Item("t_admin", "Network", "Admin test", "", "A", "B", IMPROVE, "Stable ping", 2, admin=True,
                  restart=True, _admin_cmds=["cmd-apply"], _snapshot=lambda: 8,
                  _admin_undo=lambda d: [f"cmd-undo-{d}"])
listed["on"] = False
o.items = [admin_item]
o.scan = lambda progress=None: o.items
o.apply(["t_admin"])
e2 = o._undo_data().get("t_admin", {})
check(ran and ran[0] == ["cmd-apply"], "admin change runs its command elevated")
check(e2.get("undo_cmds") == ["cmd-undo-8"] and e2.get("restart") is True,
      "admin entry keeps its undo commands and the restart flag")
check(o.restart_pending() == ["Admin test"], "a restart-needing change is reminded until Windows restarts")
data = o._undo_data()
data["t_admin"]["time"] = (opt.boot_time() - timedelta(minutes=5)).isoformat(timespec="seconds")
o._save_undo(data)
check(o.restart_pending() == [], "a change made before the last restart is not reminded any more")
o.items = []
o.scan = lambda progress=None: []
ran.clear()
o.undo()
check(ran == [["cmd-undo-8"]], f"admin undo uses the stored commands when the item is gone ({ran})")

# Power-plan and power-mode fallbacks.
writes = []
orig_write = powerplan.write_ac
powerplan.write_ac = lambda sub, setting, value: writes.append((sub, setting, value))
try:
    opt.run_fallback({"kind": "power", "sub": "SUB_PROCESSOR", "setting": "PROCTHROTTLEMIN", "value": 5})
finally:
    powerplan.write_ac = orig_write
check(writes == [("SUB_PROCESSOR", "PROCTHROTTLEMIN", 5)], "power-plan fallback writes the saved value")
try:
    opt.run_fallback({"kind": "nonsense"})
    check(False, "an unknown backup kind raises")
except ValueError:
    check(True, "an unknown backup kind raises (reported as failed, never ignored)")

# Every real registry/power item carries a fallback.
power_items = more.power_items(type("PC", (), {"laptop": False})())
check(all(i.fallback.get("kind") == "power" for i in power_items if i._apply),
      f"all {len([i for i in power_items if i._apply])} power-plan rows carry a power fallback")
for fn in (opt._game_mode, opt._game_dvr, opt._pointer, more.transparency_item):
    it = fn()
    check(it.fallback.get("kind") == "reg", f"{it.id} carries a registry fallback")
check(opt._pointer().fallback.get("after") == "mouse", "mouse acceleration fallback re-applies the live setting")

# changes(): newest first with readable fields.
o._save_undo({"a": {"time": "2026-11-20T10:00:00", "title": "First", "from": "On", "to": "Off", "group": "Windows"},
              "b": {"time": "2026-11-26T10:00:00", "title": "Second"}, "c": {"title": "No time"}})
ch = o.changes()
check([c["id"] for c in ch] == ["b", "a", "c"], "Your changes: newest first, entries without a time last")
check(ch[1]["from"] == "On" and ch[1]["to"] == "Off" and ch[0]["from"] == "", "old entries without from/to still list")
o._save_undo({})

# Delivery Optimization check.
it = more.delivery_item({"mode": 1, "provider": 99, "upload_pct": 50})
check(it.state == DONE, "local network only: already optimal")
it = more.delivery_item({"mode": 3, "provider": 8, "upload_pct": 50})
check(it.state == IMPROVE and it.admin and it.restart and "/d 1" in it._admin_cmds[0], "internet uploads: to do (admin)")
check(it._admin_undo(it._snapshot())[0].endswith("/d 3 /f"), "undo puts 'PCs on the internet' back when set in Settings")
it = more.delivery_item({"mode": 3, "provider": 99})
check("reg delete" in it._admin_undo(it._snapshot())[0], "undo deletes the value when it was Windows' default")
it = more.delivery_item({"mode": 3, "provider": 5})
check(it.state == "info" and not it.can_apply, "set by a policy: shown, never changed")
check(more.delivery_item(None) is None and more.delivery_item({"mode": "x"}) is None, "no data: no row")
check("HKU\\S-1-5-20" in more.DO_KEY, "writes the per-machine Delivery Optimization setting Windows Settings uses")

# After-Optimize summary.
from truestretch.ui.optimize_page import summarize            # noqa: E402
a = Item("x", "Windows", "A", "", "", "", DONE, "More FPS", 2)
b = Item("y", "Windows", "B", "", "", "", DONE, "More FPS", 2, restart=True)
c = Item("z", "Windows", "C", "", "", "", DONE, "Lower input delay", 2)
d = Item("w", "Windows", "D", "", "", "", IMPROVE, "Stable ping", 2)
s = summarize([(a, True, ""), (b, True, ""), (c, True, ""), (d, False, "Windows still reports Off")])
check([i.title for i in s["done"]] == ["A", "B", "C"] and s["failed"][0][1].startswith("Windows"),
      "summary splits done and failed")
check(s["impacts"] == [("More FPS", 2), ("Lower input delay", 1)], "summary counts what improves, most first")
check(s["restart"] == ["B"], "summary lists what needs a restart")

wipe()
print("\nALL PASSED" if not fails else f"\n{len(fails)} FAILED: {fails}")
sys.exit(1 if fails else 0)
