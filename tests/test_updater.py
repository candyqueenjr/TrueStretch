"""Updater mechanics against a fake GitHub API on localhost: newer/older detection, checksum, swap, rollback."""
import hashlib, http.server, json, os, shutil, sys, tempfile, threading
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="ts-upd-"))
PAYLOAD = b"MZ" + os.urandom(300_000)                 # stands in for the new TrueStretch.exe
state = {"version": "v9.9.9", "sha": hashlib.sha256(PAYLOAD).hexdigest(), "digest": True}


class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        port = self.server.server_address[1]
        if self.path == "/latest":
            asset = {"name": "TrueStretch.exe", "size": len(PAYLOAD),
                     "browser_download_url": f"http://127.0.0.1:{port}/exe"}
            if state["digest"]:
                asset["digest"] = "sha256:" + state["sha"]
            body = json.dumps({"tag_name": state["version"], "body": "## Fixed\n- things",
                               "html_url": "https://example.invalid", "assets": [
                                   asset, {"name": "TrueStretch.exe.sha256",
                                           "browser_download_url": f"http://127.0.0.1:{port}/sha"}]}).encode()
        elif self.path == "/exe":
            body = PAYLOAD
        elif self.path == "/sha":
            body = f"{state['sha']}  TrueStretch.exe\n".encode()
        else:
            self.send_response(404); self.end_headers(); return
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
os.environ["TRUESTRETCH_UPDATE_URL"] = f"http://127.0.0.1:{srv.server_address[1]}/latest"
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))
from truestretch import updater

fails = []
def check(c, t):
    print(("PASS " if c else "FAIL ") + t); c or fails.append(t)

r = updater.latest_release()
check(r.version == "9.9.9" and r.newer, "newer version detected (digest)")
state["digest"] = False
r = updater.latest_release()
check(r.sha256 == state["sha"], "checksum read from .sha256 file when there is no digest")
state["version"] = "v1.0.0"
check(not updater.latest_release().newer, "same version = up to date")
state["version"] = "v0.9.0"
check(not updater.latest_release().newer, "older version = up to date")
check(updater.parse_version("v1.10.0") > updater.parse_version("1.9.9"), "1.10.0 > 1.9.9")

# install into a fake TrueStretch.exe (a copy of the old bytes)
state["version"] = "v9.9.9"
exe = TMP / "TrueStretch.exe"
exe.write_bytes(b"OLD")
updater.installed_exe = lambda: exe
r = updater.latest_release()
seen = []
updater.install(r, lambda d, t: seen.append((d, t)))
check(exe.read_bytes() == PAYLOAD, "new exe in place")
check(updater.old_copy(exe).read_bytes() == b"OLD", "old exe kept as TrueStretch.old.exe until next start")
check(seen and seen[-1][0] == len(PAYLOAD), "progress reported")
updater.cleanup_after_update()
check(not updater.old_copy(exe).exists(), "old copy removed on next start")

# corrupted download: refused, current version untouched
exe.write_bytes(b"CURRENT")
r = updater.latest_release()
r.sha256 = "0" * 64
try:
    updater.install(r)
    check(False, "bad checksum refused")
except updater.UpdateError as exc:
    check(exe.read_bytes() == b"CURRENT", f"bad checksum refused, current exe untouched ({exc})")
check(not list(TMP.glob("*.part")) and not (TMP / "TrueStretch.new.exe").exists(), "no leftovers after refusal")

# offline
os.environ["TRUESTRETCH_UPDATE_URL"] = "http://127.0.0.1:1/latest"
import importlib
importlib.reload(updater)
try:
    updater.latest_release()
    check(False, "offline handled")
except updater.UpdateError:
    check(True, "offline -> quiet UpdateError (no crash)")


# Unpack-folder cleanup (%LOCALAPPDATA%\TrueStretch\<version>): other versions go, the running one and any folder
# another running copy still uses stay, nothing outside version folders is touched.
image = updater.running_image()
check(image.is_file() and image.name.lower() in ("python.exe", "pythonw.exe"),
      f"running_image() is this process's program file ({image.name}; a venv launcher runs the base python.exe)")
cache = TMP / "cache"
current = cache / "1.2.0.0"
busy = cache / "1.0.0.0"
for name in ("1.1.1.0", "1.2.0.0", "1.3.0", "1.0.0.0", "9", "logs", "1.2.0.0.bak"):
    (cache / name).mkdir(parents=True)
    (cache / name / "TrueStretch.exe").write_bytes(b"MZ")
    (cache / name / "PySide6").mkdir()
    (cache / name / "PySide6" / "Qt6Core.dll").write_bytes(b"x")
(cache / "notes.txt").write_text("keep")
import ctypes
GENERIC_READ, OPEN_EXISTING, INVALID = 0x80000000, 3, ctypes.c_void_p(-1).value
handle = ctypes.windll.kernel32.CreateFileW(str(busy / "TrueStretch.exe"), GENERIC_READ, 0, None, OPEN_EXISTING, 0, None)
check(handle not in (None, INVALID), "exclusive handle held on the 'busy' folder's exe (like a running copy)")
check(updater.in_use(busy) and not updater.in_use(cache / "1.1.1.0") and not updater.in_use(cache / "logs"),
      "in_use(): locked exe = in use; free exe / no exe = not in use")
from truestretch.system import process_paths
mine = process_paths(Path(sys.executable).name)
check(any(p.resolve() == image.resolve() for p in mine), f"process_paths() lists this process's program file ({len(mine)} python processes)")
check(updater.in_use(cache / "1.3.0", images=[cache / "1.3.0" / "TrueStretch.exe"]), "in_use(): a running copy's program file inside the folder = in use")
check(not updater.in_use(cache / "1.3.0", images=[cache / "1.3.0.1" / "TrueStretch.exe", cache / "1.3" / "x.exe"]),
      "in_use(): a copy running from a folder with a similar name doesn't count")
check(updater.in_use(cache / "1.1.1.0", images=[str(cache / "1.1.1.0" / "TrueStretch.exe").upper()]) is True, "in_use(): path case ignored")
# the program file is deleted first, so a copy we somehow missed stops the removal before its other files are touched
import tempfile as _tf
held = cache / "1.3.0" / "held"
held.mkdir()
h2 = ctypes.windll.kernel32.CreateFileW(str(cache / "1.3.0" / "TrueStretch.exe"), 0x80000000, 0, None, 3, 0, None)
check(not updater._remove_version_folder(cache / "1.3.0") and (cache / "1.3.0" / "PySide6" / "Qt6Core.dll").exists(),
      "locked program file -> folder left completely intact")
ctypes.windll.kernel32.CloseHandle(h2)
del _tf
check(updater.remove_old_versions(cache, TMP / "elsewhere" / "1.2.0.0") == [], "current outside the cache -> nothing removed")
check(updater.remove_old_versions(TMP / "missing", (TMP / "missing") / "1.2.0.0") == [], "missing cache -> nothing removed")
check(sorted(p.name for p in cache.iterdir()) == ["1.0.0.0", "1.1.1.0", "1.2.0.0", "1.2.0.0.bak", "1.3.0", "9", "logs", "notes.txt"],
      "nothing deleted by the refused calls")
gone = updater.remove_old_versions(cache, current)
check(sorted(f.name for f in gone) == ["1.1.1.0", "1.3.0"], f"other versions removed: {sorted(f.name for f in gone)}")
check(sorted(p.name for p in cache.iterdir()) == ["1.0.0.0", "1.2.0.0", "1.2.0.0.bak", "9", "logs", "notes.txt"],
      f"kept: current, in-use, non-version folders, files: {sorted(p.name for p in cache.iterdir())}")
check((current / "PySide6" / "Qt6Core.dll").exists() and (busy / "PySide6" / "Qt6Core.dll").exists(), "kept folders intact")
check(updater.remove_old_versions(str(cache).upper(), str(current).lower()) == [], "case-insensitive paths, second run: nothing left to remove")
ctypes.windll.kernel32.CloseHandle(handle)
check(updater.remove_old_versions(cache, current) == [busy], "once that copy has exited its folder goes too")

srv.shutdown()
shutil.rmtree(TMP, ignore_errors=True)
print("\nALL PASSED" if not fails else f"\n{len(fails)} FAILED")
