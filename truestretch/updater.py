"""Updates from GitHub Releases (free hosting): check for a newer version, download it, verify its SHA-256 and swap
the running .exe in place. Nothing is sent to GitHub except an anonymous request for the latest release."""

import hashlib
import json
import os
import re
import subprocess
import sys
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from . import APP_NAME, VERSION
from .paths import is_frozen, log
from .system import launch_command

REPO = "candyqueenjr/TrueStretch"
RELEASES_PAGE = f"https://github.com/{REPO}/releases/latest"
API_LATEST = os.environ.get("TRUESTRETCH_UPDATE_URL") or f"https://api.github.com/repos/{REPO}/releases/latest"
ASSET_NAME = "TrueStretch.exe"
USER_AGENT = f"{APP_NAME}-Updater/{VERSION}"
TIMEOUT = 20


class UpdateError(Exception):
    pass


@dataclass
class Release:
    version: str
    tag: str
    notes: str
    url: str                  # release page
    download: str             # .exe asset
    size: int
    sha256: str               # expected hash (lower-case hex)

    @property
    def newer(self):
        return parse_version(self.version) > parse_version(VERSION)


def parse_version(text):
    nums = re.findall(r"\d+", text or "")
    return tuple(int(n) for n in nums[:3]) + (0,) * (3 - len(nums[:3]))


def _get(url, accept="application/vnd.github+json"):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": accept})
    return urllib.request.urlopen(req, timeout=TIMEOUT)


def latest_release():
    """The newest published release, or raises UpdateError."""
    try:
        with _get(API_LATEST) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:       # offline, GitHub down, rate-limited ...
        raise UpdateError(f"Couldn't reach GitHub ({exc}).") from exc
    assets = {a.get("name"): a for a in data.get("assets", [])}
    exe = assets.get(ASSET_NAME)
    if not exe:
        raise UpdateError("The latest release has no TrueStretch.exe.")
    sha = ""
    digest = exe.get("digest") or ""                       # GitHub adds "sha256:<hex>" to every asset
    if digest.startswith("sha256:"):
        sha = digest.split(":", 1)[1].lower()
    side = assets.get(ASSET_NAME + ".sha256")
    if not sha and side:
        try:
            with _get(side["browser_download_url"], "application/octet-stream") as resp:
                sha = resp.read().decode("ascii", "ignore").split()[0].lower()
        except Exception as exc:
            raise UpdateError(f"Couldn't read the checksum ({exc}).") from exc
    if not re.fullmatch(r"[0-9a-f]{64}", sha):
        raise UpdateError("The latest release has no checksum, so it can't be verified.")
    tag = data.get("tag_name", "")
    return Release(version=tag.lstrip("vV"), tag=tag, notes=(data.get("body") or "").strip(),
                   url=data.get("html_url") or RELEASES_PAGE, download=exe["browser_download_url"],
                   size=int(exe.get("size") or 0), sha256=sha)


def installed_exe():
    """The real TrueStretch.exe on disk, or None when running from source."""
    if not is_frozen():
        return None
    exe = Path(launch_command()[0])
    return exe if exe.suffix.lower() == ".exe" and exe.is_file() else None


def old_copy(exe):
    return exe.with_name(f"{exe.stem}.old{exe.suffix}")


def download(release, dest, progress=None):
    """Downloads to `dest` and checks the SHA-256. progress(done_bytes, total_bytes) is called as it goes."""
    h = hashlib.sha256()
    done = 0
    tmp = dest.with_name(dest.name + ".part")
    try:
        with _get(release.download, "application/octet-stream") as resp, open(tmp, "wb") as f:
            total = int(resp.headers.get("Content-Length") or release.size or 0)
            while True:
                chunk = resp.read(256 * 1024)
                if not chunk:
                    break
                f.write(chunk)
                h.update(chunk)
                done += len(chunk)
                if progress:
                    progress(done, total)
    except Exception as exc:
        tmp.unlink(missing_ok=True)
        raise UpdateError(f"Download failed ({exc}).") from exc
    if h.hexdigest() != release.sha256:
        tmp.unlink(missing_ok=True)
        raise UpdateError("The download didn't match its checksum, so it wasn't installed. Try again later.")
    os.replace(tmp, dest)
    return dest


def install(release, progress=None):
    """Download, verify and put the new .exe in place of this one. Returns the path to start. The running .exe is
    renamed (Windows allows that) and deleted on the next start."""
    exe = installed_exe()
    if exe is None:
        raise UpdateError("Updates install only into the packaged TrueStretch.exe.")
    new = exe.with_name(f"{exe.stem}.new{exe.suffix}")
    try:
        download(release, new, progress)
    except OSError as exc:
        raise UpdateError(f"Can't write next to {exe.name} ({exc}).") from exc
    old = old_copy(exe)
    try:
        old.unlink(missing_ok=True)
    except OSError:
        pass
    try:
        os.replace(exe, old)
    except OSError as exc:
        new.unlink(missing_ok=True)
        raise UpdateError(f"Couldn't replace {exe.name} ({exc}).") from exc
    try:
        os.replace(new, exe)
    except OSError as exc:
        os.replace(old, exe)                       # roll back: the old version keeps working
        raise UpdateError(f"Couldn't put the new version in place ({exc}).") from exc
    log.info("Updated %s to %s", exe, release.version)
    return exe


def restart_into(exe):
    """Start the new version; it waits for this process to quit before it takes over."""
    flags = 0x00000008 | 0x00000200          # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    subprocess.Popen([str(exe), "--wait-pid", str(os.getpid()), "--updated"], creationflags=flags,
                     close_fds=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def cleanup_after_update():
    """Delete the previous version left behind by an update (it may still be in use for a few seconds)."""
    exe = installed_exe()
    if not exe:
        return
    for leftover in (old_copy(exe), exe.with_name(f"{exe.stem}.new{exe.suffix}"),
                     exe.with_name(f"{exe.stem}.new{exe.suffix}.part")):
        try:
            leftover.unlink(missing_ok=True)
        except OSError:
            pass
    # The .exe unpacks itself once per version into %LOCALAPPDATA%\TrueStretch\<version> (not Temp - Windows
    # Defender's machine learning flags programs launched from Temp). Remove older versions' folders.
    import shutil
    current = Path(sys.executable).resolve().parent
    cache = Path(os.environ.get("LOCALAPPDATA", "")) / APP_NAME
    if cache.is_dir() and current.parent == cache:
        for folder in cache.iterdir():
            if folder.is_dir() and folder != current and re.fullmatch(r"\d+(\.\d+){1,3}", folder.name):
                shutil.rmtree(folder, ignore_errors=True)


def wait_for_pid(pid, seconds=20):
    SYNCHRONIZE = 0x00100000
    import ctypes
    handle = ctypes.windll.kernel32.OpenProcess(SYNCHRONIZE, False, pid)
    if handle:
        ctypes.windll.kernel32.WaitForSingleObject(handle, int(seconds * 1000))
        ctypes.windll.kernel32.CloseHandle(handle)


def cli_update():
    """`TrueStretch.exe --update`: check, install if newer and start the new version - no window needed."""
    try:
        release = latest_release()
    except UpdateError as exc:
        log.warning("Update check failed: %s", exc)
        return 1
    if not release.newer:
        log.info("Up to date (%s, latest %s)", VERSION, release.version)
        return 0
    log.info("Updating %s -> %s", VERSION, release.version)
    try:
        exe = install(release)
    except UpdateError as exc:
        log.warning("Update failed: %s", exc)
        return 1
    restart_into(exe)
    return 0


if __name__ == "__main__":
    r = latest_release()
    print(r, "newer" if r.newer else "up to date")
    sys.exit(0)
