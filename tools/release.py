"""Publish a TrueStretch release to GitHub (public repo candyqueenjr/TrueStretch, releases + site only).

  python tools/release.py 1.2.0 notes.md

Refuses unless: VERSION in truestretch/__init__.py matches, the latest Nuitka build is newer than every source file,
and the full test suite including the compiled-exe gates (self-update + Defender launch) passes. Then it creates the
GitHub release with TrueStretch.exe + TrueStretch.exe.sha256 (notes: "{SHA}" is replaced by the hash) and copies the
build to dist/. Commits to the public repo (CHANGELOG/README/site) are made separately, as candyqueenjr, with no
Claude attribution.
"""
import hashlib
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUILD = Path.home() / "AppData" / "Local" / "TrueStretch-build" / "nuitka" / "TrueStretch.exe"
REPO = "candyqueenjr/TrueStretch"


def fail(msg):
    print("RELEASE REFUSED:", msg)
    sys.exit(1)


def main():
    if len(sys.argv) != 3:
        fail("usage: release.py <version> <notes.md>")
    version, notes = sys.argv[1], Path(sys.argv[2])
    code = (ROOT / "truestretch" / "__init__.py").read_text(encoding="utf-8")
    if f'VERSION = "{version}"' not in code:
        fail(f"truestretch/__init__.py doesn't say VERSION = \"{version}\"")
    if not BUILD.is_file():
        fail("no build - run build.ps1 -Protected first")
    newest_src = max(p.stat().st_mtime for p in list((ROOT / "truestretch").rglob("*.py")) + [ROOT / "main.py"])
    if BUILD.stat().st_mtime < newest_src:
        fail("the build is older than the source - rebuild first")
    existing = subprocess.run(["gh", "release", "view", f"v{version}", "-R", REPO], capture_output=True)
    if existing.returncode == 0:
        fail(f"v{version} already exists")
    tests = subprocess.run([sys.executable, str(ROOT / "tests" / "run_all.py"), "--build"])
    if tests.returncode != 0:
        fail("tests failed - nothing was published")
    sha = hashlib.sha256(BUILD.read_bytes()).hexdigest().upper()
    tmp = Path(tempfile.mkdtemp(prefix="ts-release-"))
    exe = tmp / "TrueStretch.exe"
    shutil.copy(BUILD, exe)
    (tmp / "TrueStretch.exe.sha256").write_text(f"{sha}  TrueStretch.exe\n", encoding="ascii")
    body = notes.read_text(encoding="utf-8").replace("{SHA}", sha)
    (tmp / "notes.md").write_text(body, encoding="utf-8")
    title = re.search(r"^##\s*(.+)$", body, re.M)
    subprocess.run(["gh", "release", "create", f"v{version}", str(exe), str(tmp / "TrueStretch.exe.sha256"),
                    "-R", REPO, "--title", title.group(1).strip() if title else f"TrueStretch {version}",
                    "--notes-file", str(tmp / "notes.md"), "--latest"], check=True)
    try:
        shutil.copy(BUILD, ROOT / "dist" / "TrueStretch.exe")
        (ROOT / "dist" / "TrueStretch.exe.sha256").write_text(f"{sha}  TrueStretch.exe\n", encoding="ascii")
    except OSError as exc:
        print("note: dist/ not updated (TrueStretch is probably open):", exc)
    print(f"RELEASED v{version}  sha256 {sha}")


if __name__ == "__main__":
    main()
