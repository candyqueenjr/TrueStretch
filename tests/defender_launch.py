"""Release gate: does Windows Defender let the compiled TrueStretch.exe start like a real double-click?

On-demand scans are NOT enough: on 2026-11-06 MpCmdRun said "no threats" for a build that Defender blocked at every
launch (Program:Win32/Contebrew.A!ml). So this test launches the exe as a separate test instance, waits,
checks that the app process is running from %LOCALAPPDATA%\\TrueStretch\\<version>, and that Defender logged no new
detection. Exit code 0 = safe to release.

Usage: python tests/defender_launch.py [path-to-exe]   (default: the latest Nuitka build)
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

BUILD = Path(os.environ["LOCALAPPDATA"]) / "TrueStretch-build" / "nuitka" / "TrueStretch.exe"


def ps(cmd):
    return subprocess.run(["powershell", "-NoProfile", "-Command", cmd], capture_output=True, text=True).stdout.strip()


def detections_since(start):
    raw = ps("Get-MpThreatDetection | Select-Object @{n='t';e={$_.InitialDetectionTime.ToUniversalTime().ToString('o')}},"
             "@{n='r';e={$_.Resources -join ';'}} | ConvertTo-Json -Compress")
    if not raw:
        return []
    data = json.loads(raw)
    data = data if isinstance(data, list) else [data]
    return [d for d in data if datetime.fromisoformat(d["t"].replace("Z", "+00:00")) >= start]


def processes(folder):
    raw = ps("Get-CimInstance Win32_Process -Filter \"Name='TrueStretch.exe'\" | Select-Object ProcessId,ExecutablePath "
             "| ConvertTo-Json -Compress")
    if not raw:
        return []
    data = json.loads(raw)
    data = data if isinstance(data, list) else [data]
    return [d for d in data if d.get("ExecutablePath") and (str(folder).lower() in d["ExecutablePath"].lower()
                                                          or "\\appdata\\local\\truestretch\\" in
                                                          d["ExecutablePath"].lower())]


def main():
    exe = Path(sys.argv[1]) if len(sys.argv) > 1 else BUILD
    folder = Path(tempfile.mkdtemp(prefix="ts-defender-", dir=os.environ["USERPROFILE"] + r"\Downloads"
                                   if os.path.isdir(os.environ["USERPROFILE"] + r"\Downloads") else None))
    target = folder / "TrueStretch.exe"
    shutil.copy(exe, target)
    before = {d["ProcessId"] for d in processes(folder)}
    start = datetime.now(timezone.utc)
    # Its own user name + settings folder, so it doesn't just hand over to a TrueStretch that's already open.
    # (Defender scans the unpacked program on every launch, sandboxed or not - this is what blocked 1.1.0.)
    env = dict(os.environ, USERNAME="ts-defender-test", APPDATA=str(folder / "appdata"))
    subprocess.Popen([str(target), "--minimized"], env=env, creationflags=0x00000008)
    ok_running = False
    for _ in range(30):
        time.sleep(1)
        new = [d for d in processes(folder) if d["ProcessId"] not in before]
        if any("\\appdata\\local\\truestretch\\" in d["ExecutablePath"].lower() for d in new):
            ok_running = True
            break
    time.sleep(3)
    found = detections_since(start)
    for d in processes(folder):
        if d["ProcessId"] not in before:
            subprocess.run(["taskkill", "/F", "/PID", str(d["ProcessId"])], capture_output=True)
    time.sleep(2)
    shutil.rmtree(folder, ignore_errors=True)
    print(f"app started from %LOCALAPPDATA%\\TrueStretch: {ok_running}")
    print(f"new Defender detections: {found or 'none'}")
    passed = ok_running and not found
    print("DEFENDER LAUNCH PASSED" if passed else "DEFENDER LAUNCH FAILED - do not release")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
