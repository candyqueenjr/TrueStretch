"""After a release is published: check the exe GitHub really serves to players, and hold it back if it's bad.

  python tools/verify_release.py 1.6.0            (run when the Release workflow has finished)
  python tools/verify_release.py 1.6.0 --no-hold  (report only, never change the release)

release.py's gates test the LOCAL build. Players get the exe the Release workflow built on GitHub, so this downloads
that exact file from releases/latest/download (what the website and the in-app updater use) into a fresh folder and
checks:
  1. the latest release is v<version> and is not a draft or pre-release;
  2. its SHA-256 equals GitHub's asset digest, the TrueStretch.exe.sha256 file and the hash in the release notes;
  3. the exe's Windows file version says <version>;
  4. Microsoft Defender lets it start like a real double-click (tests/defender_launch.py);
  5. the repository's contributors are only candyqueenjr.

If 1-4 fail, the release is marked as a pre-release (unless --no-hold). The in-app updater only follows
"latest release", which skips pre-releases, so players stay on the previous version until it's fixed. Undo with
  gh release edit v<version> -R candyqueenjr/TrueStretch --prerelease=false --latest
Exit code 0 = everything passed.
"""
import hashlib
import json
import re
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = "candyqueenjr/TrueStretch"
OWNER = "candyqueenjr"
ASSET = "TrueStretch.exe"
DOWNLOAD = f"https://github.com/{REPO}/releases/latest/download/{ASSET}"


# ---- pure helpers (covered by tests/test_verify_release.py) ----

def sha_from_notes(body):
    """The hash in the release notes' "Verify your download" block (lower-case), or ""."""
    m = re.search(r"SHA-256\s+([0-9A-Fa-f]{64})\b", body or "")
    return m.group(1).lower() if m else ""


def sha_from_sidecar(text):
    """The hash in TrueStretch.exe.sha256 ("<hex>  TrueStretch.exe"), or ""."""
    first = (text or "").strip().split()
    return first[0].lower() if first and re.fullmatch(r"[0-9A-Fa-f]{64}", first[0]) else ""


def sha_from_digest(digest):
    """GitHub's asset digest "sha256:<hex>", or ""."""
    digest = digest or ""
    return digest.split(":", 1)[1].lower() if digest.startswith("sha256:") else ""


def version_matches(file_version, version):
    """build.ps1 stamps X.Y.Z (or X.Y.Z.0) as the exe's file version."""
    parts = re.findall(r"\d+", file_version or "")
    want = version.split(".")
    return len(parts) >= 3 and parts[:3] == want and all(p == "0" for p in parts[3:])


def check_release(data, version):
    """Problems with the release metadata itself (list of strings; empty = fine)."""
    problems = []
    if data.get("tag_name") != f"v{version}":
        problems.append(f"latest release is {data.get('tag_name')!r}, not v{version}")
    if data.get("draft") or data.get("prerelease"):
        problems.append("release is a draft or pre-release")
    names = [a.get("name") for a in data.get("assets", [])]
    for need in (ASSET, ASSET + ".sha256"):
        if need not in names:
            problems.append(f"release has no {need}")
    return problems


def compare_hashes(actual, digest, sidecar, notes):
    """Every published hash must equal the downloaded file's hash."""
    problems = []
    for label, value in (("GitHub asset digest", digest), ("TrueStretch.exe.sha256", sidecar),
                         ("release notes", notes)):
        if not value:
            problems.append(f"{label}: no hash found")
        elif value != actual:
            problems.append(f"{label} says {value}, downloaded file is {actual}")
    return problems


# ---- the real check ----

def gh_json(*args):
    out = subprocess.run(["gh", "api", *args], capture_output=True, text=True, encoding="utf-8")
    if out.returncode != 0:
        raise RuntimeError(out.stderr.strip() or "gh api failed")
    return json.loads(out.stdout)


def fetch(url, dest=None):
    req = urllib.request.Request(url, headers={"User-Agent": "TrueStretch-release-check"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        if dest is None:
            return resp.read()
        h = hashlib.sha256()
        with open(dest, "wb") as f:
            while chunk := resp.read(1 << 20):
                h.update(chunk)
                f.write(chunk)
        return h.hexdigest()


def file_version(path):
    return subprocess.run(["powershell", "-NoProfile", "-Command",
                           f"(Get-Item -LiteralPath '{path}').VersionInfo.FileVersion"],
                          capture_output=True, text=True).stdout.strip()


def hold(version):
    subprocess.run(["gh", "release", "edit", f"v{version}", "-R", REPO, "--prerelease"], capture_output=True)
    print(f"HELD: v{version} is now a pre-release, so the in-app updater ignores it.")
    print(f"  Undo when fixed: gh release edit v{version} -R {REPO} --prerelease=false --latest")


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if len(args) != 1 or not re.fullmatch(r"\d+\.\d+\.\d+", args[0]):
        print("usage: verify_release.py <X.Y.Z> [--no-hold]")
        return 2
    version, may_hold = args[0], "--no-hold" not in sys.argv
    data = gh_json(f"repos/{REPO}/releases/latest")
    problems = check_release(data, version)
    exe_ok = True
    if not problems:
        assets = {a["name"]: a for a in data["assets"]}
        with tempfile.TemporaryDirectory(prefix="ts-verify-") as tmp:
            exe = Path(tmp) / ASSET
            actual = fetch(DOWNLOAD, exe)
            sidecar = sha_from_sidecar(fetch(assets[ASSET + ".sha256"]["browser_download_url"]).decode("ascii", "ignore"))
            problems += compare_hashes(actual, sha_from_digest(assets[ASSET].get("digest")), sidecar,
                                       sha_from_notes(data.get("body")))
            fv = file_version(exe)
            if not version_matches(fv, version):
                problems.append(f"exe file version is {fv!r}, not {version}")
            print(f"downloaded {exe.stat().st_size / 1e6:.1f} MB, SHA-256 {actual.upper()}, file version {fv}")
            launch = subprocess.run([sys.executable, str(ROOT / "tests" / "defender_launch.py"), str(exe)],
                                    capture_output=True, text=True)
            print(launch.stdout.strip())
            if launch.returncode != 0:
                exe_ok = False
                problems.append("Defender launch gate failed on the published exe")
    logins = [c.get("login") for c in gh_json(f"repos/{REPO}/contributors")]
    contributors_ok = logins == [OWNER]
    print(f"contributors: {logins}")
    for p in problems:
        print("FAIL:", p)
    if not contributors_ok:
        print(f"FAIL: contributors should be only {OWNER}")
    if problems:
        if may_hold and data.get("tag_name") == f"v{version}" and not data.get("prerelease"):
            hold(version)
        print("RELEASE CHECK FAILED" + ("" if exe_ok else " - players must not get this exe"))
        return 1
    if not contributors_ok:
        print("RELEASE CHECK FAILED (contributors only - the exe itself is fine, release not held)")
        return 1
    print(f"RELEASE CHECK PASSED - v{version} is what players download, and it starts cleanly")
    return 0


if __name__ == "__main__":
    sys.exit(main())
