"""The per-refresh read cache (readcache.py): nothing is cached outside a `reads()` block, everything with the same
key is read once inside one, nested blocks share the outer cache, errors don't poison it, and a worker thread never
sees the UI thread's cache. Also checks that the display readers really go through it (with the Windows calls
replaced by counters - no screen is touched)."""
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from truestretch import display, displayconfig, monitors, readcache   # noqa: E402
from truestretch.readcache import memo, reads                          # noqa: E402

fails = []


def check(c, t):
    print(("PASS " if c else "FAIL ") + t)
    c or fails.append(t)


calls = {"n": 0}


def compute():
    calls["n"] += 1
    return calls["n"]


# outside a block: no caching at all
calls["n"] = 0
memo("a", compute); memo("a", compute)
check(calls["n"] == 2 and not readcache.active(), "outside reads(): every call computes")

# inside: once per key
calls["n"] = 0
with reads():
    check(readcache.active(), "inside reads(): active")
    first = memo("a", compute)
    check(memo("a", compute) == first and calls["n"] == 1, "same key computed once")
    memo("b", compute)
    check(calls["n"] == 2, "a different key computes again")
    with reads():                                        # nested: shares the outer cache
        check(memo("a", compute) == first and calls["n"] == 2, "nested block shares the cache")
    check(readcache.active(), "nested block leaving keeps the outer cache alive")
check(not readcache.active(), "after the block: off again")
calls["n"] = 0
memo("a", compute)
check(calls["n"] == 1, "after the block: computed fresh (no stale value kept)")


# an error inside compute propagates and leaves no half-entry
def boom():
    raise OSError("driver said no")


with reads():
    try:
        memo("x", boom)
        check(False, "error propagates")
    except OSError:
        check(True, "error propagates")
    calls["n"] = 0
    check(memo("x", compute) == 1, "the failed key is computed again next time")

# thread isolation: a worker inside the UI thread's block does not see its cache
seen = {}
with reads():
    memo("shared", lambda: "ui-value")

    def worker():
        seen["active"] = readcache.active()
        seen["value"] = memo("shared", lambda: "worker-value")
    t = threading.Thread(target=worker); t.start(); t.join()
check(seen == {"active": False, "value": "worker-value"}, "a worker thread never sees the UI thread's cache")

# the real readers are wired through memo (Windows calls replaced by counters)
counts = {"displays": 0, "modes": 0, "accepted": 0, "monitors": 0, "devices": 0}
orig = (display._list_displays, display._available_modes, display._mode_accepted, displayconfig._monitors,
        monitors._list_monitor_devices)


def fake(name, value):
    def f(*a, **k):
        counts[name] += 1
        return value
    return f


display._list_displays = fake("displays", [])
display._available_modes = fake("modes", [])
display._mode_accepted = fake("accepted", True)
displayconfig._monitors = fake("monitors", [])
monitors._list_monitor_devices = fake("devices", [])
try:
    with reads():
        for _ in range(5):
            display.list_displays()
            display.available_modes(r"\\.\DISPLAY1")
            display.available_modes(r"\\.\DISPLAY2")
            display.mode_accepted(display.Mode(1440, 1080, 144), r"\\.\DISPLAY1")
            display.mode_accepted(display.Mode(1280, 960, 144), r"\\.\DISPLAY1")
            displayconfig.monitors()
            monitors.list_monitor_devices()
    check(counts == {"displays": 1, "modes": 2, "accepted": 2, "monitors": 1, "devices": 1},
          f"inside a refresh each reader runs once per distinct question: {counts}")
    for k in counts:
        counts[k] = 0
    display.list_displays(); display.list_displays()
    display.available_modes(r"\\.\DISPLAY1"); display.available_modes(r"\\.\DISPLAY1")
    displayconfig.monitors(); displayconfig.monitors()
    check(counts["displays"] == 2 and counts["modes"] == 2 and counts["monitors"] == 2,
          "outside a refresh the readers always ask Windows (the engine reads back fresh after every change)")
finally:
    (display._list_displays, display._available_modes, display._mode_accepted, displayconfig._monitors,
     monitors._list_monitor_devices) = orig

print("\nALL PASSED" if not fails else f"\n{len(fails)} FAILED: {fails}")
sys.exit(1 if fails else 0)
