"""End-to-end with the COMPILED exe: a copy in a temp folder updates itself from a fake GitHub (localhost),
restarts into the new version, and cleans up the old copy. Isolated APPDATA + user name, so the real app is untouched."""
import hashlib, http.server, json, os, shutil, subprocess, tempfile, threading, time
from pathlib import Path

BUILD = Path(os.environ["LOCALAPPDATA"]) / "TrueStretch-build" / "nuitka" / "TrueStretch.exe"
TMP = Path(tempfile.mkdtemp(prefix="ts-e2e-"))
app_dir = TMP / "app"; app_dir.mkdir()
exe = app_dir / "TrueStretch.exe"
shutil.copy(BUILD, exe)
PAYLOAD = BUILD.read_bytes()
SHA = hashlib.sha256(PAYLOAD).hexdigest()


class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        port = self.server.server_address[1]
        if self.path == "/latest":
            body = json.dumps({"tag_name": "v9.9.9", "body": "test", "html_url": "https://example.invalid",
                               "assets": [{"name": "TrueStretch.exe", "size": len(PAYLOAD), "digest": "sha256:" + SHA,
                                           "browser_download_url": f"http://127.0.0.1:{port}/exe"}]}).encode()
        elif self.path == "/exe":
            body = PAYLOAD
        else:
            self.send_response(404); self.end_headers(); return
        self.send_response(200); self.send_header("Content-Length", str(len(body))); self.end_headers()
        self.wfile.write(body)


srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
env = dict(os.environ, APPDATA=str(TMP / "appdata"), USERNAME="ts-e2e-test",
           TRUESTRETCH_UPDATE_URL=f"http://127.0.0.1:{srv.server_address[1]}/latest")
log = TMP / "appdata" / "TrueStretch" / "logs" / "truestretch.log"


def procs():
    out = subprocess.run(["powershell", "-NoProfile", "-Command",
                          "Get-CimInstance Win32_Process -Filter \"Name like 'TrueStretch%'\" | "
                          "ForEach-Object { \"$($_.ProcessId)|$($_.ExecutablePath)|$($_.CommandLine)\" }"],
                         capture_output=True, text=True).stdout
    return [l for l in out.splitlines() if str(TMP).lower() in l.lower()]


fails = []
def check(c, t):
    print(("PASS " if c else "FAIL ") + t); c or fails.append(t)

try:
    t0 = time.time()
    rc = subprocess.run([str(exe), "--update"], env=env, timeout=180).returncode
    print(f"     --update finished in {time.time() - t0:.1f}s, exit {rc}")
    check(rc == 0, "compiled exe downloaded + verified + installed the update")
    check((app_dir / "TrueStretch.exe").read_bytes() == PAYLOAD, "new TrueStretch.exe in place")
    started = False
    for _ in range(60):
        time.sleep(1)
        text = log.read_text(encoding="utf-8", errors="replace") if log.exists() else ""
        if text.count("Starting TrueStretch") >= 1 and "Watchdog started" in text:
            started = True
            break
    print("     log:\n       " + "\n       ".join(log.read_text(encoding="utf-8", errors="replace").splitlines()[-8:]))
    check(started, "new version started by itself after the update")
    check(any("--updated" in p for p in procs()), "it was started as the updated version (--updated)")
    for _ in range(40):
        if not (app_dir / "TrueStretch.old.exe").exists():
            break
        time.sleep(1)
    check(not (app_dir / "TrueStretch.old.exe").exists(), "old version cleaned up")
    check(sorted(p.name for p in app_dir.iterdir()) == ["TrueStretch.exe"], f"folder is clean: {sorted(p.name for p in app_dir.iterdir())}")
finally:
    for line in procs():
        pid = line.split("|", 1)[0]
        subprocess.run(["taskkill", "/F", "/PID", pid], capture_output=True)
    srv.shutdown()
    time.sleep(2)
    shutil.rmtree(TMP, ignore_errors=True)
print("\nALL PASSED" if not fails else f"\n{len(fails)} FAILED")
