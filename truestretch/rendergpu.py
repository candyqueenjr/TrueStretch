"""Which graphics chip VALORANT actually rendered on, read from the game's own start-up log.

On laptops with two graphics chips (Intel/AMD built-in + NVIDIA/AMD dedicated) Windows decides per program which one
runs it; the "VALORANT on the fast graphics card" setting asks for the dedicated one, but only the game itself knows
what it got. VALORANT (Unreal Engine, Direct3D 11) writes it at every start into
`%LOCALAPPDATA%\\VALORANT\\Saved\\Logs\\ShooterGame.log`:

    LogD3D11RHI: D3D11 adapters:
    LogD3D11RHI:    0. 'NVIDIA GeForce RTX 3060 Laptop GPU' (Feature Level 11_1)
    LogD3D11RHI:       5994/0/8010 MB DedicatedVideo/DedicatedSystem/SharedSystem, Outputs:1, VendorId:0x10de
    LogD3D11RHI:    1. 'Intel(R) UHD Graphics' (Feature Level 11_1)
    LogD3D11RHI:       128/0/8010 MB DedicatedVideo/DedicatedSystem/SharedSystem, Outputs:1, VendorId:0x8086
    LogD3D11RHI: Creating new Direct3DDevice
    LogD3D11RHI: Texture pool is 4195 MB (70% of 5994 MB)

The texture pool is sized from the chosen adapter's dedicated video memory, so "of 5994 MB" identifies it. (The
`LogInit: ... GPU: ...` line is NOT reliable - on this PC it names the Intel chip while the game ran on the NVIDIA one.)
Format verified on real logs, release-13.09, 2026-11-12. Read only."""

import re
from datetime import datetime
from pathlib import Path

BASIC_RENDER = 0x1414            # "Microsoft Basic Render Driver": software rendering, no graphics driver in use
HEAD_BYTES = 4 * 1024 * 1024     # the adapter lines come in the first seconds; the whole log can be tens of MB

_ADAPTER = re.compile(r"LogD3D11RHI:\s+(\d+)\. '(.+?)'")
_MEMORY = re.compile(r"LogD3D11RHI:\s+(\d+)/\d+/\d+ MB DedicatedVideo.*?VendorId:0x([0-9a-fA-F]+)")
_POOL = re.compile(r"LogD3D11RHI: Texture pool is \d+ MB \(\d+% of (\d+) MB\)")
_OPENED = re.compile(r"Log file open, (\d\d/\d\d/\d\d \d\d:\d\d:\d\d)")


def read_head(path):
    """The start of the log as text ('' when missing/unreadable). The game keeps the file open but shares reading."""
    try:
        with open(path, "rb") as f:
            return f.read(HEAD_BYTES).decode("utf-8", "replace")
    except OSError:
        return ""


def parse(text):
    """{"adapters": [{"index", "name", "mb", "vendor"}], "chosen": adapter | None, "fast": adapter | None,
    "started": datetime | None} from one game start, or None when the log has no adapter list (no D3D11 start yet)."""
    adapters, current = [], None
    blocks = text.split("LogD3D11RHI: D3D11 adapters:")
    if len(blocks) < 2:
        return None
    body = blocks[-1]                               # the last start in the file
    for line in body.splitlines():
        m = _ADAPTER.search(line)
        if m:
            current = {"index": int(m.group(1)), "name": m.group(2).strip(), "mb": None, "vendor": None}
            adapters.append(current)
            continue
        m = _MEMORY.search(line)
        if m and current is not None and current["mb"] is None:
            current["mb"], current["vendor"] = int(m.group(1)), int(m.group(2), 16)
            continue
        if "Creating new Direct3DDevice" in line:
            break
    adapters = [a for a in adapters if a["mb"] is not None]
    if not adapters:
        return None
    real = [a for a in adapters if a["vendor"] != BASIC_RENDER]
    fast = max(real, key=lambda a: a["mb"]) if real else None
    chosen = None
    m = _POOL.search(body)
    if m:
        mb = int(m.group(1))
        matches = [a for a in adapters if a["mb"] == mb]
        if len(matches) == 1:
            chosen = matches[0]
        elif matches and fast and all(a["mb"] == fast["mb"] for a in matches):
            chosen = matches[0]                     # two identical cards: either one is "the fast one"
    started = None
    m = _OPENED.search(text[:300])
    if m:
        try:
            started = datetime.strptime(m.group(1), "%m/%d/%y %H:%M:%S")
        except ValueError:
            started = None
    return {"adapters": adapters, "chosen": chosen, "fast": fast, "started": started}


def verdict(info):
    """"fast" | "slow" | "basic" | None (nothing worth showing: one graphics chip, or unknown)."""
    if not info or not info["chosen"]:
        return None
    chosen, fast = info["chosen"], info["fast"]
    if chosen["vendor"] == BASIC_RENDER:
        return "basic"
    if len([a for a in info["adapters"] if a["vendor"] != BASIC_RENDER]) < 2:
        return None
    return "fast" if fast and chosen["mb"] >= fast["mb"] else "slow"


def last_start(log_path):
    return parse(read_head(Path(log_path)))


__all__ = ["parse", "verdict", "last_start", "read_head", "BASIC_RENDER"]
