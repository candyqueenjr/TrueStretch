"""Runs the whole TrueStretch test suite. Exit code 0 only if everything passed.

  python tests/run_all.py            source-level tests (needs VALORANT closed for the display/optimizer tests)
  python tests/run_all.py --build    also the compiled-exe tests: self-update cycle + Defender launch gate

The optimizer test applies every safe optimization on this PC, verifies it, and undoes it again (files compared
byte for byte). The auto test briefly switches the built-in Intel screen to a stretched mode and back.
"""
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PY = sys.executable
SOURCE = ["test_watch.py", "test_updater.py", "test_omen.py", "test_auto.py", "test_ingame.py", "test_gpupref.py", "test_rendergpu.py", "test_matchperf.py",
          "test_accesskeys.py", "test_pagefile.py",
          "test_optimizer.py"]
BUILD = ["e2e_update.py", "defender_launch.py"]
# --ci: the read-only tests that need no VALORANT, screen or driver (GitHub Actions runners have none of these)
CI = ["test_watch.py", "test_updater.py", "test_ingame.py", "test_matchperf.py", "test_rendergpu.py", "test_pagefile.py"]
PASS_MARKERS = ("ALL PASSED", "PASSED")


def valorant_running():
    out = subprocess.run(["tasklist"], capture_output=True, text=True).stdout.lower()
    return "valorant-win64-shipping.exe" in out


def run(name):
    proc = subprocess.run([PY, str(HERE / name)], capture_output=True, text=True, encoding="utf-8",
                          errors="replace", env={**__import__("os").environ, "PYTHONIOENCODING": "utf-8"},
                          timeout=900)
    out = proc.stdout + proc.stderr
    ok = proc.returncode == 0 and any(m in out for m in PASS_MARKERS) and "FAILED" not in out
    fails = [line for line in out.splitlines() if line.startswith("FAIL") or "Traceback" in line][:8]
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + ("" if ok else "\n      " + "\n      ".join(fails or out.splitlines()[-8:])))
    return ok


def main():
    if "--ci" in sys.argv:
        results = [run(n) for n in CI]
        print(f"\n{sum(results)}/{len(results)} passed")
        return 0 if all(results) else 1
    if valorant_running():
        print("VALORANT is running - close it first (the tests change display and game settings).")
        return 2
    names = SOURCE + (BUILD if "--build" in sys.argv else [])
    results = [run(n) for n in names]
    print(f"\n{sum(results)}/{len(results)} passed")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
