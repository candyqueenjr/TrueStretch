"""Optimize Max on the real PC: apply every non-admin item, verify, then undo all and verify the originals are back."""
import os, sys, tempfile
os.environ["APPDATA"] = tempfile.mkdtemp(prefix="ts-opt-")
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QCoreApplication
app = QCoreApplication([])
from truestretch.settings import Settings
from truestretch.games import GAMES
from truestretch.engine import Engine
from truestretch import optimizer as opt

e = Engine(Settings({g.id: g.default_settings() for g in GAMES})); e.timer.stop()
assert not e.running.get("valorant"), "close VALORANT first"
o = opt.Optimizer(e)
import glob
def files():
    return {f: open(f, "rb").read() for f in glob.glob(os.path.expandvars(r"%LOCALAPPDATA%\VALORANT\Saved\Config\**\GameUserSettings.ini"), recursive=True)}
files_before = files()
before = {i.id: (i.state, i.current) for i in o.scan()}
todo = [i.id for i in o.items if i.can_apply and not i.admin]
print("applying:", todo)
fails = []
for item, ok, msg in o.apply(todo):
    print(("PASS " if ok else "FAIL ") + f"apply {item.title}: now {item.current}" + (f" ({msg})" if msg else ""))
    ok or fails.append(item.id)
after_apply = {i.id: i.state for i in o.items}
o.undo()
after_undo = {i.id: (i.state, i.current) for i in o.scan()}
for iid in todo:
    same = after_undo.get(iid) == before[iid]
    print(("PASS " if same else "FAIL ") + f"undo {iid}: {before[iid][1]} -> {after_undo.get(iid, ('?', '?'))[1]}")
    same or fails.append("undo " + iid)
print("undo file left:", o.changed_ids())
fb = files()
changed = [f for f in files_before if fb.get(f) != files_before[f]]
print(("PASS " if not changed else "FAIL ") + f"all {len(files_before)} VALORANT settings files (incl. OMEN copies) byte-identical after undo; differing: {changed}")
changed and fails.append("files")
print("\nALL PASSED" if not fails else f"\n{len(fails)} FAILED: {fails}")
