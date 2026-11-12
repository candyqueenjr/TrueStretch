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

srv.shutdown()
shutil.rmtree(TMP, ignore_errors=True)
print("\nALL PASSED" if not fails else f"\n{len(fails)} FAILED")
