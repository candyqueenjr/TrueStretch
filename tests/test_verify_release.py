"""tools/verify_release.py: the after-publish check of the exe players really download. Only the pure parts are
tested here (no network, no GitHub, no exe): reading the three published hashes, comparing them, the file-version
match and the release-metadata checks. Also makes sure the release-notes template, the Release workflow and the
version stamp still produce what the checker looks for."""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import verify_release as vr                               # noqa: E402

fails = []


def check(c, t):
    print(("PASS " if c else "FAIL ") + t)
    c or fails.append(t)


H = "a113ac2daff3199670dba66ce88dbf16f6f9927e7d26b7396388da06b51baf61"
U = H.upper()

# hashes in the release notes
body = f"## TrueStretch 1.5.0\n\n### Verify your download\n```\nSHA-256  {U}\n```\n\nAlready using TrueStretch?"
check(vr.sha_from_notes(body) == H, "notes: hash read and lower-cased")
check(vr.sha_from_notes(body.replace(U, "{SHA}")) == "", "notes: unreplaced {SHA} placeholder = no hash")
check(vr.sha_from_notes("") == "" and vr.sha_from_notes(None) == "", "notes: empty body = no hash")
check(vr.sha_from_notes(f"SHA-256  {U}0") == "", "notes: 65 hex digits is not a hash")
# the .sha256 file and GitHub's digest
check(vr.sha_from_sidecar(f"{U}  TrueStretch.exe\r\n") == H, "sidecar: '<hex>  name' read")
check(vr.sha_from_sidecar("﻿") == "" and vr.sha_from_sidecar("") == "", "sidecar: empty = no hash")
check(vr.sha_from_sidecar("not-a-hash TrueStretch.exe") == "", "sidecar: garbage = no hash")
check(vr.sha_from_digest(f"sha256:{H}") == H, "digest: sha256:<hex> read")
check(vr.sha_from_digest(None) == "" and vr.sha_from_digest(f"md5:{H}") == "", "digest: missing/other = no hash")

# comparing
check(vr.compare_hashes(H, H, H, H) == [], "compare: all equal = no problems")
other = "0" * 64
p = vr.compare_hashes(H, H, other, H)
check(len(p) == 1 and "sha256" in p[0], "compare: one mismatch reported by name")
p = vr.compare_hashes(H, "", H, H)
check(len(p) == 1 and "no hash" in p[0], "compare: a missing hash is a problem, not a pass")

# file version
check(vr.version_matches("1.5.0", "1.5.0"), "version: 1.5.0")
check(vr.version_matches("1.5.0.0", "1.5.0"), "version: 1.5.0.0")
check(vr.version_matches("1, 5, 0, 0", "1.5.0"), "version: comma form")
check(not vr.version_matches("1.4.0", "1.5.0"), "version: older build refused")
check(not vr.version_matches("1.5.0.1", "1.5.0"), "version: different build number refused")
check(not vr.version_matches("", "1.5.0") and not vr.version_matches(None, "1.5.0"), "version: unreadable refused")
check(not vr.version_matches("1.50.0", "1.5.0"), "version: 1.50.0 is not 1.5.0")

# release metadata
good = {"tag_name": "v1.5.0", "draft": False, "prerelease": False,
        "assets": [{"name": "TrueStretch.exe"}, {"name": "TrueStretch.exe.sha256"}]}
check(vr.check_release(good, "1.5.0") == [], "release: good metadata")
check(any("not v1.6.0" in x for x in vr.check_release(good, "1.6.0")), "release: latest is an older tag")
check(vr.check_release(dict(good, prerelease=True), "1.5.0") != [], "release: pre-release refused")
check(vr.check_release(dict(good, draft=True), "1.5.0") != [], "release: draft refused")
check(any(".sha256" in x for x in vr.check_release(dict(good, assets=[{"name": "TrueStretch.exe"}]), "1.5.0")),
      "release: missing .sha256 file")
check(any("no TrueStretch.exe" in x for x in vr.check_release(dict(good, assets=[]), "1.5.0")),
      "release: missing exe")

# the pieces the checker relies on still exist in the repo
wf = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
check('Replace("{SHA}", $sha)' in wf and "TrueStretch.exe.sha256" in wf,
      "workflow: still fills {SHA} in the notes and uploads the .sha256 file")
notes = sorted((ROOT / "release-notes").glob("*.md"), key=lambda n: [int(x) for x in re.findall(r"\d+", n.stem)])
check(bool(notes) and all("SHA-256  {SHA}" in n.read_text(encoding="utf-8") for n in notes[-1:]),
      "newest release notes keep the 'SHA-256  {SHA}' line")
init = (ROOT / "truestretch" / "__init__.py").read_text(encoding="utf-8")
ver = init.split('VERSION = "', 1)[1].split('"', 1)[0]
vi = (ROOT / "tools" / "version_info.txt").read_text(encoding="utf-8")
check(f"StringStruct('FileVersion', '{ver}')" in vi, f"version_info.txt FileVersion = {ver} (what the exe check reads)")

print("\nALL PASSED" if not fails else f"\n{len(fails)} FAILED: {fails}")
sys.exit(1 if fails else 0)
