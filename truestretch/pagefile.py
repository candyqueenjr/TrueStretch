r"""The Windows page file: is it on?

When memory fills up, Windows moves what isn't in use to the page file. The most memory all programs together can
ask for (the "commit limit") is the physical memory plus every page file; without a page file it is the physical
memory alone, and a program that asks for more gets refused - the game closes or freezes. Some "FPS tweak" guides
tell players to switch the page file off; it adds no FPS.

Windows reads the list of page files at start-up from

    HKLM\SYSTEM\CurrentControlSet\Control\Session Manager\Memory Management  ->  PagingFiles  (REG_MULTI_SZ)

    ?:\pagefile.sys                 Windows manages it on every drive (the default)
    C:\pagefile.sys 0 0             Windows manages the size on that drive
    C:\pagefile.sys 4096 8192       custom size in MB (start, maximum)
    (empty)                         no page file

A change takes effect at the next restart, so the live state is read separately: GlobalMemoryStatusEx reports the
commit limit (ullTotalPageFile) and the physical memory (ullTotalPhys); the difference is the page file in use now.
Changing the value needs administrator rights; the command lines below are run through one Windows prompt."""

import ctypes
import re
import winreg

KEY = r"SYSTEM\CurrentControlSet\Control\Session Manager\Memory Management"
VALUE = "PagingFiles"
AUTO = r"?:\pagefile.sys"

OFF, MANAGED, CUSTOM = "off", "managed", "custom"

_ENTRY = re.compile(r"^(\?|[A-Za-z]):\\[\w .\\-]*?(?: (\d+) (\d+))?$")
_SEP = "*"                            # can't be part of a file name and means nothing to cmd.exe


def read(root=winreg.HKEY_LOCAL_MACHINE, key=KEY):
    """The configured list (list of str), or None when the value is missing or isn't a string list."""
    try:
        with winreg.OpenKey(root, key) as k:
            value, kind = winreg.QueryValueEx(k, VALUE)
    except OSError:
        return None
    if kind != winreg.REG_MULTI_SZ or not isinstance(value, list):
        return None
    return [str(v) for v in value]


def parse(entries):
    """[(path, start MB, max MB)] - sizes are 0 when Windows manages them. None if an entry isn't understood."""
    out = []
    for e in entries:
        m = _ENTRY.match(e)
        if not m:
            return None
        out.append((e[:m.start(2) - 1] if m.group(2) else e, int(m.group(2) or 0), int(m.group(3) or 0)))
    return out


def status(entries):
    """OFF (no page file), MANAGED (Windows picks the size), CUSTOM (fixed sizes) or None (unknown - leave alone)."""
    if entries is None:
        return None
    if entries == []:
        return OFF
    parsed = parse(entries)
    if not parsed:
        return None
    if any(start == 0 and top == 0 for _, start, top in parsed):
        return MANAGED
    return CUSTOM


def custom_max_mb(entries):
    return sum(top for _, _, top in (parse(entries) or []))


class _MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]


def live_mb():
    """MB of page file Windows is using right now (commit limit minus physical memory), or None."""
    s = _MEMORYSTATUSEX()
    s.dwLength = ctypes.sizeof(_MEMORYSTATUSEX)
    try:
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(s)):
            return None
    except (OSError, AttributeError):
        return None
    return max(0, int(s.ullTotalPageFile) - int(s.ullTotalPhys)) // (1024 * 1024)


def _target(key, root_name):
    return f'"{root_name}\\{key}" /v {VALUE}'


def apply_cmds(key=KEY, root_name="HKLM"):
    """cmd lines that let Windows manage the page file again (its default)."""
    return [f'reg add {_target(key, root_name)} /t REG_MULTI_SZ /d "{AUTO}" /f']


def restorable(entries):
    """True if undo_cmds() can put exactly this list back."""
    return entries is None or entries == [] or bool(parse(entries))


def undo_cmds(saved, key=KEY, root_name="HKLM"):
    """cmd lines that put the saved list back exactly (None = the value didn't exist)."""
    if saved is None:
        return [f'reg delete {_target(key, root_name)} /f']
    saved = list(saved)
    if not restorable(saved):
        raise ValueError("page file list can't be restored safely: %r" % (saved,))
    if not saved:
        return [f'reg add {_target(key, root_name)} /t REG_MULTI_SZ /d "" /f']
    return [f'reg add {_target(key, root_name)} /t REG_MULTI_SZ /s {_SEP} /d "{_SEP.join(saved)}" /f']


__all__ = ["KEY", "VALUE", "AUTO", "OFF", "MANAGED", "CUSTOM", "read", "parse", "status", "custom_max_mb", "live_mb",
           "apply_cmds", "restorable", "undo_cmds"]
