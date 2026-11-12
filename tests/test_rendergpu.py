"""Optimize Max: "Graphics chip VALORANT used" reads which adapter VALORANT rendered on from ShooterGame.log.
Crafted logs cover: laptop on the NVIDIA chip (fast), laptop on the Intel chip (slow), Basic Render Driver, a desktop
with one card (no row), two identical cards, a log without adapter lines, a missing file, the misleading
`LogInit: GPU:` line, and a log with two starts (the last one counts). Then the real log on this PC, if present.
Read-only: nothing is written outside a temp folder."""
import os
import sys
import tempfile
from pathlib import Path

os.environ["APPDATA"] = tempfile.mkdtemp(prefix="ts-rgpu-")
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))

from truestretch import rendergpu as rg                                      # noqa: E402
from truestretch.optimizer import DONE, INFO, _render_gpu                     # noqa: E402

fails = []


def check(c, t):
    print(("PASS " if c else "FAIL ") + t)
    c or fails.append(t)


HEAD = ("\ufeffLog file open, 11/11/26 01:40:39\r\nTime Zone UTC/GMT 4:00\r\n"
        "LogInit: OS: Windows 11 (25H2), CPU: i7, GPU: Intel(R) UHD Graphics, Disk: SSD\r\n")
NV = ("[2026.11.10-21.40.40:882][  0]LogD3D11RHI:    {i}. 'NVIDIA GeForce RTX 3060 Laptop GPU' (Feature Level 11_1)\r\n"
      "[2026.11.10-21.40.40:882][  0]LogD3D11RHI:       5994/0/8010 MB DedicatedVideo/DedicatedSystem/SharedSystem, "
      "Outputs:1, VendorId:0x10de\r\n")
IGPU = ("[2026.11.10-21.40.41:410][  0]LogD3D11RHI:    {i}. 'Intel(R) UHD Graphics' (Feature Level 11_1)\r\n"
        "[2026.11.10-21.40.41:410][  0]LogD3D11RHI:       128/0/8010 MB DedicatedVideo/DedicatedSystem/SharedSystem, "
        "Outputs:1, VendorId:0x8086\r\n")
BASIC = ("[2026.11.10-21.40.41:446][  0]LogD3D11RHI:    {i}. 'Microsoft Basic Render Driver' (Feature Level 11_1)\r\n"
         "[2026.11.10-21.40.41:446][  0]LogD3D11RHI:       0/0/8010 MB DedicatedVideo/DedicatedSystem/SharedSystem, "
         "Outputs:0, VendorId:0x1414\r\n")


def log(adapters, pool_mb):
    text = HEAD + "[2026.11.10-21.40.39:482][  0]LogD3D11RHI: D3D11 adapters:\r\n"
    text += "".join(a.format(i=n) for n, a in enumerate(adapters))
    text += "[2026.11.10-21.40.41:526][  0]LogD3D11RHI: Creating new Direct3DDevice\r\n"
    text += "[2026.11.10-21.40.41:526][  0]LogD3D11RHI:     GPU DeviceId: 0x2520\r\n"
    if pool_mb is not None:
        text += f"[2026.11.10-21.40.41:526][  0]LogD3D11RHI: Texture pool is 4195 MB (70% of {pool_mb} MB)\r\n"
    text += "LogMapLoadModel: Update: [Map Name: /Game/Maps/Menu/MainMenuV2]\r\n" * 3
    return text


class FakeEngine:
    info = {}


def item_for(text):
    path = Path(tempfile.mkdtemp(prefix="ts-rlog-")) / "ShooterGame.log"
    path.write_text(text, encoding="utf-8")
    return _render_gpu(FakeEngine(), path)


laptop_fast = rg.parse(log([NV, IGPU, BASIC], 5994))
check(laptop_fast and len(laptop_fast["adapters"]) == 3, "three adapters parsed")
check(laptop_fast["chosen"]["name"] == "NVIDIA GeForce RTX 3060 Laptop GPU", "chosen adapter = the one the texture pool was sized from")
check(laptop_fast["fast"]["vendor"] == 0x10de, "fast adapter = most dedicated video memory")
check(laptop_fast["started"] and laptop_fast["started"].hour == 1 and laptop_fast["started"].day == 11, "start time from 'Log file open' (local)")
check(rg.verdict(laptop_fast) == "fast", "laptop on NVIDIA -> fast (LogInit 'GPU: Intel' is ignored)")
it = item_for(log([NV, IGPU, BASIC], 5994))
check(it and it.state == DONE and it.current.startswith("NVIDIA") and not it.can_apply, "row: DONE, shows the NVIDIA name, nothing to apply")

slow = rg.parse(log([NV, IGPU, BASIC], 128))
check(rg.verdict(slow) == "slow" and slow["chosen"]["vendor"] == 0x8086, "laptop on the Intel chip -> slow")
it = item_for(log([NV, IGPU, BASIC], 128))
check(it and it.state == INFO and it.current == "Intel(R) UHD Graphics" and it.target.startswith("NVIDIA"),
      "row: INFO, Intel → NVIDIA")
check(it and "fast graphics card" in it.note, "row note points to the fix")
check(it and not it.can_apply, "slow row is read-only")

basic = rg.parse(log([NV, BASIC], 0))
check(rg.verdict(basic) == "basic", "Basic Render Driver -> basic")
basic1 = rg.parse(log([BASIC], 0))
check(rg.verdict(basic1) == "basic", "Basic Render Driver on a one-card PC still shown")
it = item_for(log([BASIC], 0))
check(it and it.state == INFO and "basic display driver" in it.why, "basic row explains it")

desk = rg.parse(log([NV, BASIC], 5994))
check(rg.verdict(desk) is None, "desktop with one card -> no row")
check(item_for(log([NV, BASIC], 5994)) is None, "desktop: scan step returns nothing")

twin = rg.parse(log([NV, NV, BASIC], 5994))
check(rg.verdict(twin) == "fast", "two identical cards -> fast, not unknown")

check(rg.verdict(rg.parse(log([NV, IGPU, BASIC], None))) is None, "no texture pool line -> unknown, no row")
check(rg.verdict(rg.parse(log([NV, IGPU, BASIC], 4096))) is None, "pool size matching no adapter -> unknown, no row")
check(rg.parse(HEAD + "LogMapLoadModel: nothing\r\n") is None, "log without adapter lines -> None")
check(rg.last_start(Path(tempfile.mkdtemp()) / "missing.log") is None, "missing log -> None")
check(_render_gpu(FakeEngine(), Path(tempfile.mkdtemp()) / "missing.log") is None, "missing log: scan step returns nothing")

two = rg.parse(log([NV, IGPU, BASIC], 128) + log([NV, IGPU, BASIC], 5994)[len(HEAD):])
check(rg.verdict(two) == "fast", "two starts in one file -> the last one counts")

real = Path(os.environ.get("LOCALAPPDATA", "")) / "VALORANT" / "Saved" / "Logs" / "ShooterGame.log"
if real.is_file():
    info = rg.last_start(real)
    if info is None:
        print("INFO real log has no adapter list (game never reached the renderer)")
    else:
        names = [a["name"] for a in info["adapters"]]
        check(bool(names), f"real log parses: {names}")
        check(info["chosen"] is not None, f"real log: chosen adapter found ({info['chosen'] and info['chosen']['name']})")
        print(f"INFO real log verdict: {rg.verdict(info)}, started {info['started']}")
        it = _render_gpu(FakeEngine())
        check(it is None or it.id == "render_gpu", "real scan step builds the row (or none)")
else:
    print("INFO no ShooterGame.log on this PC - real-log part skipped")

print("ALL PASSED" if not fails else f"{len(fails)} FAILED")
sys.exit(1 if fails else 0)
