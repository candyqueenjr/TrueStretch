"""Power-plan values through powrprof (powerplan.py) instead of parsing translated powercfg text.
Offline part: GUID handling. Real part (any Windows): every value the Optimize Max power rows use, read through the
API, equals what `powercfg /qh` prints for the same setting (English Windows only - that text IS the bug on other
languages, so the comparison is skipped when the line isn't there), and writing a value back unchanged works."""
import re
import subprocess
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from truestretch import powerplan                          # noqa: E402
from truestretch.optimizer_more import POWER, power_items  # noqa: E402

fails = []


def check(c, t):
    print(("PASS " if c else "FAIL ") + t)
    c or fails.append(t)


# ---- GUID handling (offline) ----
u = uuid.UUID("54533251-82be-4824-96c1-47b60b740d00")
check(powerplan.as_uuid("SUB_PROCESSOR") == u and powerplan.as_uuid("sub_processor") == u, "alias -> GUID (any case)")
check(powerplan.as_uuid("54533251-82be-4824-96c1-47b60b740d00") == u, "GUID string passes through")
check(powerplan.as_uuid(u) is u, "uuid.UUID passes through")
g = powerplan.GUID.of("SUB_PROCESSOR")
check(g.Data1 == 0x54533251 and g.Data2 == 0x82BE and g.Data3 == 0x4824 and bytes(g.Data4) == bytes.fromhex("96c147b60b740d00"),
      "GUID struct is little-endian the way Windows wants it")
check(g.uuid() == u, "GUID struct -> uuid round trip")
try:
    powerplan.as_uuid("NOT_AN_ALIAS")
    check(False, "unknown alias raises ValueError")
except ValueError:
    check(True, "unknown alias raises ValueError")
for alias, text in powerplan.ALIASES.items():
    check(uuid.UUID(text) is not None, f"alias {alias} is a valid GUID")

# ---- the real power plan on this PC ----
scheme = powerplan.active_scheme()
check(isinstance(scheme, uuid.UUID), f"active scheme read: {scheme}")


def powercfg_ac(sub, setting):
    """What powercfg prints (English Windows), None if the line isn't there (other language / not in plan)."""
    try:
        out = subprocess.run(["powercfg", "/qh", "SCHEME_CURRENT", sub, setting], capture_output=True, text=True,
                             timeout=15, errors="replace").stdout
    except (OSError, subprocess.TimeoutExpired):
        return None
    m = re.search(r"Current AC Power Setting Index:\s*(0x[0-9a-fA-F]+)", out)
    return int(m.group(1), 16) if m else None


compared = 0
for iid, title, sub, setting, want, names, *_ in POWER:
    api = powerplan.read_ac(sub, setting)
    text = powercfg_ac(sub, setting)
    if text is None:
        print(f"skip  {iid}: powercfg gave no English AC line (not in this plan, or non-English Windows); API = {api}")
        continue
    compared += 1
    check(api == text, f"{iid}: API {api} == powercfg {text}")
    dc = powerplan.read_dc(sub, setting)
    check(dc is None or isinstance(dc, int), f"{iid}: DC value readable ({dc})")
print(f"compared {compared} of {len(POWER)} settings with powercfg")

check(powerplan.read_ac("SUB_PROCESSOR", "00000000-0000-0000-0000-000000000001") is None,
      "a setting that isn't in the plan reads as None (no exception)")

# writing back the current value changes nothing and must not raise (what apply/undo do with a real value)
value = powerplan.read_ac("SUB_PROCESSOR", "CPMINCORES")
if value is not None:
    try:
        powerplan.write_ac("SUB_PROCESSOR", "CPMINCORES", value)
        check(powerplan.read_ac("SUB_PROCESSOR", "CPMINCORES") == value, f"write of the current value ({value}) accepted")
    except OSError as exc:
        check(False, f"write of the current value raised: {exc}")
    # a real change and its undo, the way Optimize Max applies and restores a row (Core parking 100% <-> 99%)
    other = 99 if value != 99 else 98
    try:
        powerplan.write_ac("SUB_PROCESSOR", "CPMINCORES", other)
        changed = powerplan.read_ac("SUB_PROCESSOR", "CPMINCORES")
    finally:
        powerplan.write_ac("SUB_PROCESSOR", "CPMINCORES", value)
    check(changed == other, f"a changed value is read back through the API ({value} -> {changed})")
    check(powerplan.read_ac("SUB_PROCESSOR", "CPMINCORES") == value, f"and restored exactly ({value})")
    if powercfg_ac("SUB_PROCESSOR", "CPMINCORES") is not None:
        check(powercfg_ac("SUB_PROCESSOR", "CPMINCORES") == value, "powercfg agrees the original is back")
else:
    print("skip  write test: CPMINCORES not in this plan")

# the Optimize Max rows are built from these values (no 'Not in this power plan' for settings the API returns)
class _Pc:
    laptop = False


items = power_items(_Pc())
known = [i for i in items if i.state != "unavailable"]
check(len(items) >= 1, f"power_items built {len(items)} rows ({len(known)} with a value)")
for i in items:
    check(any("powrprof" in d for d in i.debug), f"{i.id}: technical report names the API ({i.debug[0][:60]})")

print("\nALL PASSED" if not fails else f"\n{len(fails)} FAILED: {fails}")
sys.exit(1 if fails else 0)
