"""Line-based editing of Unreal Engine style .ini files.

Only the keys we change are touched; every other line, the encoding and the
line endings are kept exactly as they were. Writes are atomic (temp file + replace).
"""

import os
import stat
import tempfile
import threading
from pathlib import Path

_WRITE_LOCK = threading.Lock()


class IniFile:
    def __init__(self, path):
        self.path = Path(path)
        raw = self.path.read_bytes() if self.path.exists() else b""
        if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
            self.encoding = "utf-16"
        elif raw.startswith(b"\xef\xbb\xbf"):
            self.encoding = "utf-8-sig"
        else:
            self.encoding = "utf-8"
        self.lossy = False
        try:
            self.text = raw.decode(self.encoding)
        except UnicodeDecodeError:
            self.encoding = "mbcs"
            try:
                self.text = raw.decode(self.encoding)
            except UnicodeDecodeError:
                self.text = raw.decode(self.encoding, errors="replace")
                self.lossy = True
        self.newline = "\r\n" if "\r\n" in self.text or not self.text else "\n"

    def _bounds(self, lines, section):
        header = f"[{section}]".lower()
        start = None
        for i, line in enumerate(lines):
            s = line.strip()
            if start is None:
                if s.lower() == header:
                    start = i
            elif s.startswith("[") and s.endswith("]"):
                return start, i
        return (start, len(lines)) if start is not None else (None, None)

    def get(self, section, keys):
        lines = self.text.splitlines()
        start, end = self._bounds(lines, section)
        found = {}
        if start is None:
            return found
        wanted = {k.lower(): k for k in keys}
        for line in lines[start + 1:end]:
            key, sep, value = line.partition("=")
            if sep and key.strip().lower() in wanted:
                found[wanted[key.strip().lower()]] = value.strip()
        return found

    def set(self, section, values):
        """Replace keys in [section], appending missing ones at the end of that section."""
        lines = self.text.splitlines()
        start, end = self._bounds(lines, section)
        if start is None:
            if lines and lines[-1].strip():
                lines.append("")
            lines.append(f"[{section}]")
            start, end = len(lines) - 1, len(lines)
        pending = {k.lower(): (k, str(v)) for k, v in values.items()}
        for i in range(start + 1, end):
            key, sep, _ = lines[i].partition("=")
            if sep and key.strip().lower() in pending:
                _, value = pending.pop(key.strip().lower())
                lines[i] = f"{key.strip()}={value}"
        insert_at = end
        while insert_at > start + 1 and not lines[insert_at - 1].strip():
            insert_at -= 1
        for key, value in pending.values():
            lines.insert(insert_at, f"{key}={value}")
            insert_at += 1
        self.text = self.newline.join(lines) + self.newline

    def remove(self, section, keys):
        """Delete keys from [section] (used by Undo when a key didn't exist before)."""
        lines = self.text.splitlines()
        start, end = self._bounds(lines, section)
        if start is None:
            return
        drop = {k.lower() for k in keys}
        kept = [line for i, line in enumerate(lines)
                if not (start < i < end and line.partition("=")[1] and line.partition("=")[0].strip().lower() in drop)]
        self.text = self.newline.join(kept) + self.newline

    def save(self):
        """Atomic and crash-safe: a unique temp file next to the original, flushed to disk, then swapped in. A lock
        keeps two writers (the engine and an Optimize Max worker thread) from interleaving. A file whose bytes
        couldn't be decoded exactly is never written back - saving it would replace those characters with '?'."""
        if self.lossy:
            raise OSError(f"{self.path.name} has characters TrueStretch can't read safely, so it wasn't changed")
        data = self.text.encode(self.encoding)
        with _WRITE_LOCK:
            fd, tmp = tempfile.mkstemp(prefix=f".{self.path.name}.", suffix=".truestretch.tmp",
                                       dir=str(self.path.parent))
            try:
                with os.fdopen(fd, "wb") as f:
                    f.write(data)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp, self.path)
            except BaseException:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
                raise


def is_read_only(path):
    return not Path(path).stat().st_mode & stat.S_IWRITE


def set_read_only(path, read_only):
    os.chmod(path, stat.S_IREAD if read_only else stat.S_IREAD | stat.S_IWRITE)
