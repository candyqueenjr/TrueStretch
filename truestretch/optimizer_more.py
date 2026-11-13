"""More Optimize Max checks: Windows power-plan internals, startup apps, overlays and background programs, memory,
storage, network, extra NVIDIA driver settings, more VALORANT file settings, and graphics-panel settings for AMD/Intel.
Every item is a real, readable setting; anything TrueStretch can't change safely is shown as information instead."""

import csv
import io
import json
import os
import re
import subprocess
import winreg
from pathlib import Path

from . import accesskeys, pagefile
from .optimizer import (DONE, GAME_EXE, HKCU, HKLM, IMPROVE, IN_GAME, INFO, NO_WINDOW, OPTIONAL, UNAVAILABLE, Item,
                        _dbg, _reg, _reg_dword, _reg_restore, _reg_snapshot)
from .system import running_processes

# ---- Windows power plan internals (the active plan, "plugged in" values only) ------------------------------

POWER = [  # id, title, subgroup, setting, target, names, why, impact, level, laptop_note
    ("cpu_min", "Processor minimum state (plugged in)", "SUB_PROCESSOR", "PROCTHROTTLEMIN", 100, None,
     "How slow Windows lets the processor run between frames. At 100% the CPU never clocks down while you play, "
     "which removes frame-time spikes in VALORANT (it's very CPU-heavy).", "Steadier FPS", 3, True),
    ("cpu_boost", "Processor boost mode (plugged in)", "SUB_PROCESSOR", "PERFBOOSTMODE", 2,
     {0: "Disabled", 1: "Enabled", 2: "Aggressive", 3: "Efficient enabled", 4: "Efficient aggressive",
      5: "Aggressive at guaranteed", 6: "Efficient aggressive at guaranteed"},
     "Lets the processor jump to its turbo clock straight away instead of easing into it.", "More FPS", 2, True),
    ("core_parking", "Core parking: minimum active cores (plugged in)", "SUB_PROCESSOR", "CPMINCORES", 100, None,
     "Windows 'parks' (sleeps) processor cores to save power; waking them adds tiny delays. 100% keeps all cores "
     "awake while plugged in.", "Steadier FPS", 2, False),
    ("usb_suspend", "USB selective suspend (plugged in)", "2a737441-1930-4402-8d77-b2bebba308a3",
     "48e6b7a6-50f5-4782-a5d4-53bb8f07e226", 0, {0: "Disabled", 1: "Enabled"},
     "Lets Windows put USB ports to sleep. That can make a mouse or keyboard hitch for a moment when it wakes.",
     "Consistent input", 2, False),
    ("pcie_aspm", "PCI Express link power saving (plugged in)", "SUB_PCIEXPRESS", "ASPM", 0,
     {0: "Off", 1: "Moderate", 2: "Maximum"},
     "Puts the link to your graphics card into low-power states between frames; waking it adds latency.",
     "Lower input delay", 2, False),
    ("wifi_power", "Wi-Fi adapter power saving (plugged in)", "19cbb8fa-5279-450e-9fac-8a3d5fedd0c1",
     "12bbebe6-58d6-4636-95bb-3217ef867c1a", 0,
     {0: "Maximum performance", 1: "Low power saving", 2: "Medium power saving", 3: "Maximum power saving"},
     "Wi-Fi power saving sleeps the adapter between packets, which causes ping spikes.", "Stable ping", 2, False),
]


def _powercfg(*args):
    out = subprocess.run(["powercfg", *args], capture_output=True, text=True, creationflags=NO_WINDOW, timeout=15)
    return out.returncode, out.stdout


def _power_value(sub, setting):
    code, out = _powercfg("/qh", "SCHEME_CURRENT", sub, setting)
    m = re.search(r"Current AC Power Setting Index:\s*(0x[0-9a-fA-F]+)", out)
    return (int(m.group(1), 16) if m else None), out


def _power_set(sub, setting, value):
    code, out = _powercfg("/setacvalueindex", "SCHEME_CURRENT", sub, setting, str(int(value)))
    if code != 0:
        raise OSError(f"powercfg refused ({out.strip() or code})")
    _powercfg("/setactive", "SCHEME_CURRENT")


def power_items(pc):
    items = []
    for iid, title, sub, setting, want, names, why, impact, level, laptop_note in POWER:
        value, raw = _power_value(sub, setting)
        if value is None:
            if iid == "wifi_power":
                continue                     # no Wi-Fi adapter on this PC
            items.append(Item(iid, "Windows power", title, why, "Not in this power plan", "—", UNAVAILABLE, impact,
                              level, debug=[f"powercfg /qh SCHEME_CURRENT {sub} {setting} → no AC value"]))
            continue
        shown = (names or {}).get(value, f"{value}%" if names is None else str(value))
        target = (names or {}).get(want, f"{want}%" if names is None else str(want))
        note = "Only the 'plugged in' value changes; battery life is untouched."
        if laptop_note and pc.laptop:
            note += " Laptops run a little warmer while gaming."
        items.append(Item(iid, "Windows power", title, why, shown, target, DONE if value == want else IMPROVE,
                          impact, level, note=note,
                          debug=[f"powercfg SCHEME_CURRENT {sub} {setting}: AC index = {value:#x}"],
                          _apply=lambda s=sub, st=setting, w=want: _power_set(s, st, w),
                          _snapshot=lambda v=value: v,
                          _restore=lambda d, s=sub, st=setting: _power_set(s, st, d)))
    return items


# ---- Windows extras ----------------------------------------------------------------------------------------

def transparency_item():
    key, name = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize", "EnableTransparency"
    raw = _reg(HKCU, key, name)
    on = raw is None or raw != 0
    return Item("transparency", "Windows", "Transparency effects", "See-through taskbar and windows cost a little "
                "graphics work in the background. Purely cosmetic.", "On" if on else "Off", "Off",
                OPTIONAL if on else DONE, "Less background work", 1, debug=[_dbg(HKCU, key, name, raw)],
                _apply=lambda: _reg_dword(HKCU, key, name, 0), _snapshot=lambda: _reg_snapshot(HKCU, key, name),
                _restore=lambda d: _reg_restore(HKCU, key, d))


def page_file_item(pc=None, entries=..., live_mb=...):
    """The Windows page file. Only "switched off" is something to fix; a custom size is the player's choice."""
    entries = pagefile.read() if entries is ... else entries
    live_mb = pagefile.live_mb() if live_mb is ... else live_mb
    state = pagefile.status(entries)
    if state is None:                                # missing or not understood: say nothing rather than guess
        return None
    ram = getattr(pc, "ram_gb", 0) or 0
    title = "Page file (extra room when memory is full)"
    why = ("When memory fills up, Windows moves what isn't in use to the page file. Without one, VALORANT or "
           "Windows can freeze or close the moment memory runs out. It adds no FPS when switched off.")
    debug = [f"HKLM\\{pagefile.KEY} → {pagefile.VALUE} = {entries!r}",
             f"page file in use now: {live_mb if live_mb is not None else '?'} MB (commit limit − physical memory)"]
    level = 2 if ram and ram <= 16 else 1
    if state == pagefile.OFF:
        now = "Off" if not live_mb else "Off from the next restart"
        return Item("page_file", "Windows", title, why, now, "Managed by Windows", IMPROVE, "Fewer crashes", level,
                    note="Needs administrator permission and a restart.", admin=True, restart=True, debug=debug,
                    _admin_cmds=pagefile.apply_cmds(), _snapshot=lambda: entries,
                    _admin_undo=lambda d: pagefile.undo_cmds(d))
    if state == pagefile.CUSTOM:
        now = f"Custom size (up to {pagefile.custom_max_mb(entries) / 1024:.0f} GB)"
    else:
        now = "Managed by Windows"
    if live_mb == 0:                                 # configured, but Windows hasn't restarted since
        now += " — from the next restart"
    return Item("page_file", "Windows", title, why, now, "On", DONE, "Fewer crashes", level, debug=debug,
                _snapshot=lambda: entries, _admin_undo=lambda d: pagefile.undo_cmds(d))


# ---- Windows accessibility keyboard shortcuts (the prompts that pop over the game) ---------------------------------

HOTKEY_WHY = {
    "sticky": "Tapping Shift five times - easy to do while walking - pops the Sticky Keys prompt over the game. In "
              "windowed fullscreen that takes the focus away from VALORANT mid-round.",
    "filter": "Holding the right Shift key for 8 seconds (walking!) can switch Filter Keys on, which makes Windows "
              "ignore quick or repeated key presses - and shows a prompt over the game.",
    "toggle": "Holding Num Lock for 5 seconds shows the Toggle Keys prompt over the game and starts beeping on Caps "
              "Lock and Num Lock.",
}


def accessibility_hotkey_items():
    """One item per shortcut. Only the shortcut is turned off; the feature itself stays available in Settings. If the
    player actually uses the feature (it is on), it is left alone and shown as information."""
    items = []
    for f in accesskeys.FEATURES:
        iid, title = f"hotkey_{f.id}", f"{f.title} shortcut ({f.shortcut})"
        try:
            live_flags = accesskeys.read(f).dwFlags
            stored = accesskeys.registry_flags(f)
        except OSError as exc:
            items.append(Item(iid, "Windows", title, "", "Couldn't read", "—", UNAVAILABLE,
                              note=f"Windows didn't answer ({exc}).", debug=[repr(exc)]))
            continue
        live = bool(live_flags & accesskeys.HOTKEY)
        comes_back = stored is not None and bool(stored & accesskeys.HOTKEY)   # loaded again at the next sign-in
        debug = [f"SystemParametersInfo dwFlags = {live_flags:#x} (shortcut {'on' if live else 'off'}, feature "
                 f"{'on' if live_flags & accesskeys.ON else 'off'})", _dbg(HKCU, f.reg_key, "Flags", stored)]
        level = 1 if f.id == "toggle" else 2
        if live_flags & accesskeys.ON:
            items.append(Item(iid, "Windows", title, HOTKEY_WHY[f.id], "In use", "Off", INFO, "No pop-ups", level,
                              note=f"You use {f.title}, so TrueStretch leaves it and its shortcut alone.", debug=debug))
            continue
        current = "On" if live else ("Off until the next sign-in" if comes_back else "Off")
        items.append(Item(iid, "Windows", title, HOTKEY_WHY[f.id], current, "Off",
                          IMPROVE if (live or comes_back) else DONE, "No pop-ups", level,
                          note=f"{f.title} itself stays available in Windows Settings > Accessibility > Keyboard.",
                          debug=debug,
                          _apply=lambda f=f: accesskeys.set_hotkey(f, False),
                          _snapshot=lambda f=f: accesskeys.snapshot(f),
                          _restore=lambda d, f=f: accesskeys.restore(f, d)))
    return items


def pending_restart_item():
    keys = [r"SOFTWARE\Microsoft\Windows\CurrentVersion\WindowsUpdate\Auto Update\RebootRequired",
            r"SOFTWARE\Microsoft\Windows\CurrentVersion\Component Based Servicing\RebootPending"]
    pending = []
    for k in keys:
        try:
            winreg.CloseKey(winreg.OpenKey(HKLM, k))
            pending.append(k)
        except OSError:
            pass
    if not pending:
        return None
    return Item("pending_restart", "Windows", "Windows is waiting for a restart", "Updates are installed but not "
                "finished. Until you restart, Windows keeps working on them in the background.", "Restart pending",
                "Restarted", INFO, "Less background work", 2, note="Restart your PC before you play.",
                debug=[f"HKLM\\{k} exists" for k in pending])


# ---- Startup apps --------------------------------------------------------------------------------------------

RUN = r"Software\Microsoft\Windows\CurrentVersion\Run"
APPROVED_RUN = r"Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run"
APPROVED_FOLDER = r"Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\StartupFolder"
HEAVY = {  # programs that are commonly safe to not start with Windows, and use CPU/RAM in the background
    "discord": "Discord", "spotify": "Spotify", "steam": "Steam", "epicgameslauncher": "Epic Games Launcher",
    "onedrive": "OneDrive", "teams": "Microsoft Teams", "msteams": "Microsoft Teams", "skype": "Skype",
    "opera": "Opera", "operagx": "Opera GX", "chrome": "Google Chrome", "msedge": "Microsoft Edge",
    "overwolf": "Overwolf", "medal": "Medal", "outplayed": "Outplayed", "ccleaner": "CCleaner", "battle.net": "Battle.net",
    "eadesktop": "EA app", "ubisoftconnect": "Ubisoft Connect", "goggalaxy": "GOG Galaxy", "dropbox": "Dropbox",
    "googledrive": "Google Drive", "zoom": "Zoom", "telegram": "Telegram", "whatsapp": "WhatsApp", "slack": "Slack",
    "adobe": "Adobe updater", "itunes": "iTunes helper", "wallpaper": "Wallpaper Engine", "lghub": "Logitech G HUB",
}
KEEP = ("riot", "vanguard", "vgtray", "securityhealth", "defender", "nvidia", "nvcontainer", "realtek", "audio",
        "synaptics", "elan", "touchpad", "intel", "amd", "radeon", "igfx", "onedrivesetup", "truestretch", "omen",
        "hp", "dell", "lenovo", "asus", "msi", "acer", "ctfmon", "bluetooth", "wacom")


def _approved(key, name):
    try:
        with winreg.OpenKey(HKCU, key) as k:
            data, _ = winreg.QueryValueEx(k, name)
        return bytes(data)
    except OSError:
        return None


def _set_approved(key, name, data):
    with winreg.CreateKeyEx(HKCU, key, 0, winreg.KEY_SET_VALUE) as k:
        winreg.SetValueEx(k, name, 0, winreg.REG_BINARY, data)


def _restore_approved(key, name, data):
    if data is None:
        try:
            with winreg.OpenKey(HKCU, key, 0, winreg.KEY_SET_VALUE) as k:
                winreg.DeleteValue(k, name)
        except OSError:
            pass
    else:
        _set_approved(key, name, bytes.fromhex(data))


def startup_items():
    entries = []
    try:
        with winreg.OpenKey(HKCU, RUN) as k:
            i = 0
            while True:
                try:
                    name, cmd, _ = winreg.EnumValue(k, i)
                except OSError:
                    break
                entries.append((name, str(cmd), APPROVED_RUN, f"HKCU\\{RUN} → {name}"))
                i += 1
    except OSError:
        pass
    folder = Path(os.environ.get("APPDATA", "")) / r"Microsoft\Windows\Start Menu\Programs\Startup"
    for f in folder.glob("*.lnk") if folder.is_dir() else []:
        entries.append((f.name, str(f), APPROVED_FOLDER, str(f)))
    items = []
    for name, cmd, approved_key, where in entries:
        low = (name + " " + cmd).lower()
        if any(k in low for k in KEEP):
            continue
        data = _approved(approved_key, name)
        enabled = data is None or data[0] in (2, 6)
        friendly = next((v for k, v in HEAVY.items() if k in low), None)
        title = f"Starts with Windows: {friendly or name}"
        if not enabled:
            state = DONE
        else:
            state = IMPROVE if friendly else OPTIONAL
        items.append(Item(f"startup_{name}", "Startup apps", title,
                          "Opens every time Windows starts and keeps running in the background, using processor time "
                          "and memory while you play. Disabling only stops the automatic start — you can still open "
                          "it yourself, and Undo turns it back on.", "Starts with Windows" if enabled else "Disabled",
                          "Disabled", state, "Less background work", 2 if friendly else 1,
                          debug=[where, f"StartupApproved: {data.hex() if data else 'not set (enabled)'}"],
                          _apply=lambda k=approved_key, n=name: _set_approved(k, n, bytes([3]) + bytes(11)),
                          _snapshot=lambda d=data: d.hex() if d else None,
                          _restore=lambda d, k=approved_key, n=name: _restore_approved(k, n, d)))
    return items


# ---- Overlays and heavy background programs (information: closing someone's apps is their decision) --------

OVERLAYS = [  # process (lower case), name, what to do
    ("discord.exe", "Discord", "Discord's in-game overlay hooks into VALORANT. Turn it off: Discord → User Settings → "
     "Game Overlay → Enable in-game overlay → Off. Also set Advanced → Hardware Acceleration off if FPS drops."),
    ("nvidia overlay.exe", "NVIDIA overlay", "NVIDIA App's overlay and Instant Replay record in the background. Turn "
     "off Instant Replay (Alt+Z → Instant Replay) unless you use it."),
    ("nvsphelper64.exe", "NVIDIA Instant Replay", "Instant Replay keeps recording the last minutes of gameplay. Turn "
     "it off with Alt+Z unless you use it."),
    ("gamebar.exe", "Xbox Game Bar", "Game Bar is open. Its background recording is checked separately above."),
    ("rtss.exe", "RivaTuner Statistics Server", "RTSS overlays and frame limiters add latency in VALORANT. Close it "
     "or remove VALORANT from its profiles."),
    ("msiafterburner.exe", "MSI Afterburner", "Afterburner's on-screen display uses RTSS. Fine for monitoring; close "
     "it if you don't need the overlay."),
    ("overwolf.exe", "Overwolf", "Overwolf apps run overlays and recording inside games. Close it while playing."),
    ("medal.exe", "Medal", "Medal records clips in the background, which costs FPS. Pause it or close it."),
    ("obs64.exe", "OBS Studio", "OBS is open. If you're not streaming or recording, close it."),
    ("wallpaper64.exe", "Wallpaper Engine", "Animated wallpapers keep using the graphics card. Set it to pause when "
     "a game is running (Wallpaper Engine → Settings → Performance)."),
]


def overlay_items():
    procs = running_processes()
    out = []
    for exe, name, todo in OVERLAYS:
        if exe in procs:
            out.append(Item(f"overlay_{exe}", "Background & overlays", f"{name} is running", todo, "Running",
                            "Off while playing", INFO, "More FPS", 2, debug=[f"process {exe} is running"]))
    return out


def memory_hog_items(limit_mb=700):
    try:
        raw = subprocess.run(["tasklist", "/fo", "csv", "/nh"], capture_output=True, text=True,
                             creationflags=NO_WINDOW, timeout=15).stdout
    except (OSError, subprocess.TimeoutExpired):
        return []
    usage = {}
    for row in csv.reader(io.StringIO(raw)):
        if len(row) < 5:
            continue
        name = row[0].lower()
        try:
            kb = int(re.sub(r"[^0-9]", "", row[4]) or 0)
        except ValueError:
            continue
        usage[name] = usage.get(name, 0) + kb
    skip = {"valorant-win64-shipping.exe", "memory compression", "system", "dwm.exe", "explorer.exe",
            "msmpeng.exe", "truestretch.exe", "riotclientservices.exe", "vgc.exe", "svchost.exe", "csrss.exe"}
    out = []
    for name, kb in sorted(usage.items(), key=lambda x: -x[1]):
        mb = kb // 1024
        if mb < limit_mb or name in skip:
            continue
        nice = name.removesuffix(".exe")
        out.append(Item(f"hog_{name}", "Background & overlays", f"{nice} is using {mb / 1024:.1f} GB of memory",
                        "Programs open in the background compete with VALORANT for memory and processor time. Close "
                        "the ones you don't need while you play.", f"{mb:,} MB", "Closed while playing", INFO,
                        "Smoother FPS", 1, debug=[f"tasklist: {name} total working set {kb:,} KB"]))
        if len(out) >= 6:
            break
    return out


# ---- Hardware facts that matter (memory speed / channels, drive type, connection) -----------------------------

def _ps_json(script):
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command", script + " | ConvertTo-Json -Compress"],
                             capture_output=True, text=True, creationflags=NO_WINDOW, timeout=25).stdout.strip()
        data = json.loads(out) if out else []
        return data if isinstance(data, list) else [data]
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return []


def memory_items():
    sticks = _ps_json("Get-CimInstance Win32_PhysicalMemory | Select-Object Capacity,Speed,ConfiguredClockSpeed,"
                      "DeviceLocator,PartNumber")
    if not sticks:
        return []
    items = []
    rated = max((s.get("Speed") or 0) for s in sticks)
    running = min((s.get("ConfiguredClockSpeed") or 0) for s in sticks) or rated
    dbg = [f"{s.get('DeviceLocator')}: {int(s.get('Capacity') or 0) // 2**30} GB, rated {s.get('Speed')} MT/s, "
           f"running {s.get('ConfiguredClockSpeed')} MT/s, {str(s.get('PartNumber') or '').strip()}" for s in sticks]
    if rated and running and running < rated - 100:
        items.append(Item("ram_speed", "Your PC", f"Memory runs at {running} instead of {rated} MT/s",
                          "Your memory is rated faster than it's running. VALORANT gains a lot of FPS from fast "
                          "memory. Turn on XMP (Intel) or EXPO/DOCP (AMD) in your BIOS.", f"{running} MT/s",
                          f"{rated} MT/s", INFO, "More FPS", 3, debug=dbg,
                          note="This is a BIOS setting — TrueStretch can't change it from Windows."))
    else:
        items.append(Item("ram_speed", "Your PC", "Memory speed", "Memory runs at its rated speed.",
                          f"{running} MT/s", f"{rated} MT/s", DONE, "More FPS", 3, debug=dbg))
    if len(sticks) == 1:
        items.append(Item("ram_channels", "Your PC", "Only one memory stick (single channel)",
                          "With one stick the processor can use only half its memory bandwidth. A second identical "
                          "stick (dual channel) often gives VALORANT 15–30% more FPS.", "1 stick", "2 matching sticks",
                          INFO, "More FPS", 3, debug=dbg, note="A hardware upgrade — nothing to change in Windows."))
    return items


def storage_item(engine):
    info = engine.info.get("valorant")
    if not info or not info.install_dir:
        return None
    drive = str(info.install_dir)[:1].upper()
    data = _ps_json(f"Get-Partition -DriveLetter {drive} | Get-Disk | ForEach-Object {{ Get-PhysicalDisk -DeviceNumber "
                    f"$_.Number }} | Select-Object FriendlyName,MediaType,BusType")
    if not data:
        return None
    d = data[0]
    media, bus = str(d.get("MediaType")), str(d.get("BusType"))
    hdd = media in ("3", "HDD")
    return Item("storage", "Your PC", f"VALORANT is on {'a hard drive' if hdd else 'a solid-state drive'}",
                "Loading maps and agents is much faster from an SSD. A hard drive can also cause stutter." if hdd else
                "Fast drive — maps and agents load quickly.", d.get("FriendlyName", "?"), "SSD",
                INFO if hdd else DONE, "Faster loading", 2 if hdd else 1,
                debug=[f"drive {drive}: MediaType={media} BusType={bus}"])


def network_item():
    data = _ps_json("Get-NetAdapter | Where-Object Status -eq 'Up' | Select-Object Name,InterfaceDescription,"
                    "MediaType,PhysicalMediaType,LinkSpeed")
    if not data:
        return None
    wifi = [a for a in data if "802.11" in str(a.get("PhysicalMediaType")) or "wi" in str(a.get("Name")).lower()]
    wired = [a for a in data if a not in wifi and "802.3" in str(a.get("PhysicalMediaType"))]
    dbg = [f"{a.get('Name')}: {a.get('InterfaceDescription')} ({a.get('PhysicalMediaType')}, {a.get('LinkSpeed')})"
           for a in data]
    if wired:
        return Item("network", "Network", "Connected with a cable", "A wired connection gives the most stable ping.",
                    "Ethernet", "Ethernet", DONE, "Stable ping", 3, debug=dbg)
    if wifi:
        return Item("network", "Network", "You're playing on Wi-Fi", "Wi-Fi adds jitter and packet loss compared to "
                    "a cable. If you can, plug in an Ethernet cable — it's the biggest ping improvement there is.",
                    "Wi-Fi", "Ethernet cable", INFO, "Stable ping", 3, debug=dbg)
    return None


# ---- More NVIDIA settings (VALORANT's profile only) ------------------------------------------------------------

def nvidia_extra_specs():
    from . import nvdrs
    return [
        ("nv_latency", "Low Latency Mode", 0x007BA09E, 1, {1: "On", 0: "Off (game decides)"},
         "Keeps the graphics card's queue of waiting frames to one. In VALORANT, NVIDIA Reflex (in game) takes over "
         "when it's on; this covers you when it isn't.", "Lower input delay", 2),
        ("nv_refresh", "Preferred refresh rate", 0x0064B541, 1, {1: "Highest available", 0: "Application-controlled"},
         "Makes sure VALORANT always runs at your screen's highest refresh rate.", "Smoother picture", 2),
        ("nv_fps_cap", "Max Frame Rate (driver cap)", 0x10835002, 0, {0: "Off"},
         "A driver frame cap below your refresh rate limits FPS and adds delay. VALORANT's own limiter is better.",
         "More FPS", 2),
    ], nvdrs


# ---- VALORANT files: more settings -------------------------------------------------------------------------------

MORE_VALORANT = [  # section key, title, target value, label map, why, impact, level
    ("/Script/ShooterGame.ShooterGameUserSettings", "bUseHDRDisplayOutput", "HDR output", "False",
     {"True": "On", "False": "Off"}, "HDR adds tone-mapping work and can wash out the picture on most monitors.",
     "More FPS", 1),
    ("/Script/ShooterGame.ShooterGameUserSettings", "bUseDynamicResolution", "Dynamic resolution", "False",
     {"True": "On", "False": "Off"}, "Lowers the resolution on the fly when FPS drops — blurry exactly when it "
     "matters.", "Sharp picture", 2),
    ("ScalabilityGroups", "sg.GlobalIlluminationQuality", "Global illumination quality", "0",
     {"0": "Low", "1": "Medium", "2": "High", "3": "Epic"}, "Indirect lighting quality. Set to Low for maximum FPS.",
     "More FPS", 1),
    ("ScalabilityGroups", "sg.ReflectionQuality", "Reflection quality", "0",
     {"0": "Low", "1": "Medium", "2": "High", "3": "Epic"}, "Reflections on surfaces. Set to Low for maximum FPS.",
     "More FPS", 1),
]


# ---- Graphics panel settings for AMD / Intel (no public API to change them safely) ---------------------------------

AMD_PANEL = [
    ("Radeon Anti-Lag", "On", "Lowers input delay — AMD's answer to NVIDIA Reflex.", 3),
    ("Radeon Chill", "Off", "Lowers FPS on purpose to save power.", 2),
    ("Radeon Boost", "Off", "Drops resolution while you move the mouse — blurry flicks.", 2),
    ("Enhanced Sync", "Off", "Can cause stutter in VALORANT.", 1),
    ("Wait for Vertical Refresh", "Always off", "Same as VSync: adds input delay.", 2),
    ("Texture Filtering Quality", "Performance", "Less filtering work, no visible difference in VALORANT.", 1),
    ("Tessellation Mode", "Override, Off", "VALORANT doesn't need tessellation.", 1),
]
INTEL_PANEL = [
    ("Low Latency", "On", "Cuts input delay on Intel Arc graphics.", 3),
    ("Vertical Sync", "Application choice / Off", "VSync adds input delay.", 2),
    ("Power plan for graphics", "Maximum performance", "Keeps the graphics chip at full speed while plugged in.", 2),
]


def panel_items(vendor):
    rows = AMD_PANEL if vendor == "amd" else INTEL_PANEL if vendor == "intel" else []
    where = ("AMD Software: Adrenalin → Gaming → Games → VALORANT" if vendor == "amd"
             else "Intel Graphics Software → Gaming → VALORANT")
    group = "Inside AMD Software" if vendor == "amd" else "Inside Intel Graphics"
    return [Item(f"{vendor}_panel_{i}", group, name, why, "Set in panel", want, IN_GAME, "", level, note=where)
            for i, (name, want, why, level) in enumerate(rows)]


__all__ = ["power_items", "transparency_item", "accessibility_hotkey_items", "pending_restart_item", "page_file_item", "startup_items",
           "overlay_items",
           "memory_hog_items", "memory_items", "storage_item", "network_item", "nvidia_extra_specs", "MORE_VALORANT",
           "panel_items", "GAME_EXE", "UNAVAILABLE", "IN_GAME", "INFO", "OPTIONAL"]
