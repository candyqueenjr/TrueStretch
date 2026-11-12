"""Optimize Max: the Sticky / Filter / Toggle Keys shortcut items on the real PC. For each one: simulate a fresh
Windows install (shortcut on), scan, apply (only the shortcut bit may change), verify by re-scan, undo through the
JSON undo data, and check the live state and the registry key are identical to before. The real settings are put
back at the end whatever happens."""
import json
import os
import subprocess
import sys
import tempfile

os.environ["APPDATA"] = tempfile.mkdtemp(prefix="ts-keys-")
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))
assert "valorant-win64-shipping.exe" not in subprocess.run(
    ["tasklist"], capture_output=True, text=True).stdout.lower(), "close VALORANT first"

from truestretch import accesskeys as ak                                     # noqa: E402
from truestretch.optimizer import DONE, IMPROVE, INFO                        # noqa: E402
from truestretch.optimizer_more import accessibility_hotkey_items            # noqa: E402

fails = []


def check(c, t):
    print(("PASS " if c else "FAIL ") + t)
    c or fails.append(t)


def item(fid):
    return next(i for i in accessibility_hotkey_items() if i.id == f"hotkey_{fid}")


check(len(accessibility_hotkey_items()) == 3, "scan lists one item per shortcut")
for f in ak.FEATURES:
    original = ak.snapshot(f)
    try:
        if original["live"]["dwFlags"] & ak.ON:
            it = item(f.id)
            check(it.state == INFO and not it.can_apply, f"{f.title}: feature in use -> shown as info, not touched")
            continue
        ak.set_hotkey(f, True)                                   # what a fresh Windows install has
        check(ak.hotkey_active(f) == (True, True), f"{f.title}: shortcut on (live + registry) for the test")
        it = item(f.id)
        check(it.state == IMPROVE and it.can_apply and it.current == "On", f"{f.title}: scan says On -> can improve")
        data = json.loads(json.dumps(it._snapshot()))             # the undo file round-trips through JSON
        it._apply()
        check(ak.hotkey_active(f) == (False, False), f"{f.title}: apply turned the shortcut off (live + registry)")
        check(item(f.id).state == DONE, f"{f.title}: re-scan verifies Off")
        now = ak.fields(ak.read(f))
        same_rest = {k: v for k, v in now.items() if k != "dwFlags"} == {k: v for k, v in data["live"].items()
                                                                           if k != "dwFlags"}
        check(same_rest and (now["dwFlags"] | ak.HOTKEY) == data["live"]["dwFlags"],
              f"{f.title}: only the shortcut bit changed")
        it._restore(data)
        check(ak.snapshot(f) == data, f"{f.title}: undo -> live state and registry identical to before apply")
        check(item(f.id).state == IMPROVE, f"{f.title}: after undo the scan says 'can improve' again")
    finally:
        ak.restore(f, original)
    check(ak.snapshot(f) == original, f"{f.title}: real settings put back exactly")

print("\nALL PASSED" if not fails else f"\n{len(fails)} FAILED")
sys.exit(1 if fails else 0)
