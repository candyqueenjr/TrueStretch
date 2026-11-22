"""Guard process: if TrueStretch is closed, crashes or is killed while the desktop is stretched, put the
normal resolution back (after the game closes). Runs as `TrueStretch.exe --watchdog <pid>`, without Qt."""

import ctypes
import json
import os
import subprocess
import sys
import time

from . import display, displayconfig
from .display import Mode
from .paths import STATE_FILE, atomic_write_text, log
from .system import launch_command, running_processes

SYNCHRONIZE = 0x00100000
INFINITE = 0xFFFFFFFF
GAME_EXES = {"valorant-win64-shipping.exe"}
DETACHED_PROCESS = 0x00000008
CREATE_NEW_PROCESS_GROUP = 0x00000200
CREATE_BREAKAWAY_FROM_JOB = 0x01000000


def start_for(pid):
    """Launch the guard for this TrueStretch process. It lives outside TrueStretch's own process/job, so it
    survives TrueStretch being killed."""
    cmd = launch_command("--watchdog", str(pid))
    errors = []
    for flags in (DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP | CREATE_BREAKAWAY_FROM_JOB,
                  DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP, 0):
        try:
            subprocess.Popen(cmd, creationflags=flags, close_fds=True, stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            log.info("Watchdog started (%s)", cmd[0])
            return True
        except OSError as exc:
            errors.append(f"{flags:#x}: {exc}")
    log.warning("Couldn't start the watchdog %s: %s", cmd, "; ".join(errors))
    return False


def _read_state():
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _alive(pid):
    handle = ctypes.windll.kernel32.OpenProcess(SYNCHRONIZE, False, pid)
    if not handle:
        return False
    still = ctypes.windll.kernel32.WaitForSingleObject(handle, 0) == 0x102   # WAIT_TIMEOUT
    ctypes.windll.kernel32.CloseHandle(handle)
    return still


def run(pid):
    handle = ctypes.windll.kernel32.OpenProcess(SYNCHRONIZE, False, pid)
    if handle:
        ctypes.windll.kernel32.WaitForSingleObject(handle, INFINITE)
        ctypes.windll.kernel32.CloseHandle(handle)
    log.info("Watchdog: TrueStretch %s ended", pid)
    while True:
        state = _read_state()
        if not state.get("stretched"):
            return                                       # nothing to undo
        if state.get("keep_on_exit"):
            log.info("Watchdog: the player chose to stay stretched after quitting; leaving the desktop as it is")
            return
        owner = int(state.get("owner") or 0)
        if owner and owner != pid and _alive(owner):
            return                                       # a newer TrueStretch took over
        if GAME_EXES & running_processes():
            time.sleep(2)                                # keep the stretch until the game closes
            continue
        break
    device = state.get("device")
    target = Mode.from_list(state.get("previous"))
    try:
        try:
            if not target:
                raise display.DisplayError("no previous mode stored")
            display.set_mode(target, device)
        except display.DisplayError as exc:
            log.warning("Watchdog: %s; using Windows' saved mode (never the stretched one)", exc)
            display.restore_saved_mode(device)
        prev_scaling = state.get("previous_scaling")
        if prev_scaling is not None and device:
            displayconfig.set_scaling(device, int(prev_scaling))
        atomic_write_text(STATE_FILE, "{}")
        log.info("Watchdog: desktop restored to %s", target or "the saved mode")
    except Exception:
        log.exception("Watchdog couldn't restore the desktop")


if __name__ == "__main__":
    run(int(sys.argv[1]))
    os._exit(0)
