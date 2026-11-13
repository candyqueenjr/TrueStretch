"""Start a TrueStretch release: local gates, then a version tag. GitHub Actions does the rest.

  python tools/release.py 1.5.0

Refuses unless: VERSION in truestretch/__init__.py matches, release-notes/<version>.md and a CHANGELOG.md entry
exist, the working tree is clean and main is up to date with GitHub, the tag doesn't exist yet, the latest local
Nuitka build (build.ps1 -Protected) is newer than every source file, and the full test suite including the
compiled-exe gates (self-update + Microsoft Defender launch) passes on this PC.

Then it tags v<version> and pushes it. The release workflow (.github/workflows/release.yml) builds TrueStretch.exe
from the tagged source on a GitHub-hosted runner with the same flags, sends it to SignPath for code signing (approve
the request in SignPath) and publishes the GitHub release with its SHA-256 checksum. Commits are made as
candyqueenjr, with no AI attribution.
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUILD = Path.home() / "AppData" / "Local" / "TrueStretch-build" / "nuitka" / "TrueStretch.exe"
REPO = "candyqueenjr/TrueStretch"


def fail(msg):
    print("RELEASE REFUSED:", msg)
    sys.exit(1)


def git(*args):
    return subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True)


def main():
    if len(sys.argv) != 2:
        fail("usage: release.py <version>")
    version = sys.argv[1]
    tag = f"v{version}"
    code = (ROOT / "truestretch" / "__init__.py").read_text(encoding="utf-8")
    if f'VERSION = "{version}"' not in code:
        fail(f"truestretch/__init__.py doesn't say VERSION = \"{version}\"")
    if not (ROOT / "release-notes" / f"{version}.md").is_file():
        fail(f"release-notes/{version}.md is missing")
    if f"## [{version}]" not in (ROOT / "CHANGELOG.md").read_text(encoding="utf-8"):
        fail(f"CHANGELOG.md has no '## [{version}]' entry")
    if git("status", "--porcelain").stdout.strip():
        fail("uncommitted changes - commit them first")
    if git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip() != "main":
        fail("not on main")
    git("fetch", "-q", "origin")
    if git("rev-parse", "HEAD").stdout != git("rev-parse", "origin/main").stdout:
        fail("main isn't the same as GitHub's main - push or pull first")
    if git("rev-parse", "-q", "--verify", f"refs/tags/{tag}").returncode == 0 or \
            subprocess.run(["gh", "release", "view", tag, "-R", REPO], capture_output=True).returncode == 0:
        fail(f"{tag} already exists")
    if not BUILD.is_file():
        fail("no local build - run build.ps1 -Protected first (the gates test it)")
    newest_src = max(p.stat().st_mtime for p in list((ROOT / "truestretch").rglob("*.py")) + [ROOT / "main.py"])
    if BUILD.stat().st_mtime < newest_src:
        fail("the local build is older than the source - rebuild first")
    tests = subprocess.run([sys.executable, str(ROOT / "tests" / "run_all.py"), "--build"])
    if tests.returncode != 0:
        fail("tests failed - nothing was tagged")
    made = git("-c", "user.name=candyqueenjr", "-c", "user.email=candyqueenjr@users.noreply.github.com",
               "tag", "-a", tag, "-m", f"TrueStretch {version}")      # an annotated tag needs an identity
    if made.returncode != 0:
        fail("couldn't create the tag: " + made.stderr.strip())
    push = git("push", "origin", tag)
    if push.returncode != 0:
        git("tag", "-d", tag)
        fail("couldn't push the tag: " + push.stderr.strip())
    print(f"TAGGED {tag} - GitHub Actions is building, signing and publishing it:")
    print(f"  https://github.com/{REPO}/actions/workflows/release.yml")


if __name__ == "__main__":
    main()
