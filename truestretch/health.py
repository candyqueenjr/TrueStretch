"""PC check: every finding explained in plain words, with a fix where TrueStretch can do it."""

from dataclasses import dataclass

from . import display, displayconfig
from .display import Mode
from .pcinfo import DRIVER_PAGES, disk_free_gb
from .guides import open_omen
from .system import open_uri, running_processes

GOOD, WARN, BAD, INFO = "good", "warn", "bad", "info"


@dataclass
class Health:
    key: str
    group: str
    title: str
    status: str
    detail: str
    fix_label: str = None
    fix: callable = None   # fix(window) -> None, or an undo callable when the screen changed


def _months(days):
    return max(1, round(days / 30))


def checks(engine, gid):
    game, info, gs, pc = engine.games[gid], engine.info[gid], engine.gs(gid), engine.pc
    out = []
    add = out.append

    # ---- the game ---------------------------------------------------------
    g = "VALORANT"
    if info.installed:
        version = info.extra.get("version")
        add(Health("installed", g, f"{game.name} is installed", GOOD,
                   f"Found in {info.install_dir}" + (f" · version {version}" if version else "") + "."))
    else:
        add(Health("installed", g, f"{game.name} wasn't found", BAD,
                   "TrueStretch looked in the Windows app list, the Riot Client's records and every drive. "
                   "Install VALORANT, start it once, then press Rescan.",
                   "Get VALORANT", lambda w: open_uri("https://playvalorant.com/download/")))
    targets = engine.targets(gid)
    if targets:
        accounts = sum(1 for t in targets if not t.is_default)
        add(Health("configs", g, f"{accounts} account{'s' if accounts != 1 else ''} found", GOOD,
                   "VALORANT keeps one settings file per account on this PC. TrueStretch stretches the ones "
                   "ticked on the Accounts tab and backs each one up first."))
    else:
        add(Health("configs", g, "No VALORANT settings yet", INFO,
                   "VALORANT creates its settings the first time you sign in. Just press Play stretched: after that "
                   "first session TrueStretch sets them up by itself, and from the next start it's stretched."))
    if info.launcher:
        add(Health("launcher", g, "Riot Client found", GOOD,
                   "Used to start VALORANT when you press Play stretched."))
    else:
        add(Health("launcher", g, "Riot Client not found", WARN,
                   "Stretching still works, but you'll need to start VALORANT yourself."))
    if pc.vanguard_installed:
        add(Health("vanguard", g, "Vanguard anti-cheat " + ("running" if pc.vanguard_running else "installed"),
                   GOOD if pc.vanguard_running else WARN,
                   "Riot's anti-cheat is ready. TrueStretch never touches the game or Vanguard — only your "
                   "display and VALORANT's own settings file." if pc.vanguard_running else
                   "Vanguard is installed but not running. VALORANT won't start until you restart your PC."))
    elif info.installed:
        add(Health("vanguard", g, "Vanguard anti-cheat missing", BAD,
                   "VALORANT needs Vanguard. Start VALORANT through the Riot Client to reinstall it, then restart."))
    current = game.current_settings(info) if info.installed else None
    if current:
        bars = ("Windowed fullscreen + Fill — ready" if current["ready"] else
                f"{current['mode']} + {'Fill' if current['fill'] else 'Letterbox'} — Play stretched fixes this")
        add(Health("ingame", g, f"In game now: {bars}", GOOD if current["ready"] else INFO,
                   f"{current['mode']} · FPS limit {current['fps_limit']} · VSync "
                   f"{'on' if current['vsync'] else 'off'}. This is what the last signed-in account is set to."))

    # ---- stretched resolution ---------------------------------------------
    g = "Stretched resolution"
    d = engine.display_for(gid)
    device = d.device if d else None
    modes = display.available_modes(device)
    w, h = int(gs["width"]), int(gs["height"])
    where = d.title if d else "your screen"
    native = engine.native_mode(gid, modes)
    if native and w >= native.width:
        add(Health("aspect", g, f"{w} × {h} isn't narrower than your screen", BAD,
                   "Nothing gets stretched. Pick a stretch level on the Resolution tab (1440 × 1080 is classic).",
                   "Choose level", lambda win: win.show_game(gid, tab="resolution")))
    elif native and h != native.height:
        add(Health("aspect", g, f"Height {h} differs from your screen ({native.height})", WARN,
                   "The picture gets blurry. Keep the screen's height and only make it narrower.",
                   "Choose level", lambda win: win.show_game(gid, tab="resolution")))
    mode = engine.stretch_mode(gid, modes)
    if mode:
        listed = bool(display.refresh_rates(modes, w, h))
        add(Health("resolution", g, f"{w} × {h} works on {where}", GOOD,
                   f"Your graphics driver accepts it at {mode.hz} Hz" + ("." if listed else
                   " (as a custom resolution — Windows doesn't list it, which is normal with the monitor drivers off).")))
    else:
        fallback = engine.closest_mode(gid, modes)
        add(Health("resolution", g, f"{w} × {h} is added when you play", GOOD if fallback else WARN,
                   "Play stretched adds it to your graphics driver automatically"
                   + (f"; if the driver refuses, TrueStretch uses {fallback.width} × {fallback.height} instead "
                      "(closest stretch your screen has)." if fallback else
                      ". Your screen offers no lower resolution to fall back on — update the graphics driver.")))
    nv = _nvidia_scaling(d)
    if nv is not None:
        add(Health("scaling", g, f"NVIDIA scaling: {nv.scaling_name}", GOOD if nv.stretches else WARN,
                   "The driver stretches lower resolutions to fill the screen." if nv.stretches else
                   "With Aspect ratio / No scaling the driver adds black bars at the sides. TrueStretch sets "
                   "Full-screen when you press Play — or do it now.",
                   None if nv.stretches else "Set Full-screen",
                   None if nv.stretches else (lambda win: engine._ensure_gpu_fullscreen(engine.display_for(gid)))))
    else:
        mon = displayconfig.monitor_for(device) if device else None
        add(Health("scaling", g, "Stretch scaling: set when you play", GOOD if mon else INFO,
                   "TrueStretch sets your graphics driver to stretch (Full panel / Stretch) and asks Windows to "
                   "stretch the picture when a match loads."))

    devs = [dv for _, dv in engine.monitor_devices() if dv]
    on = [dv for dv in devs if not dv.disabled]
    if devs and not on:
        add(Health("monitor_driver", g, "Monitor drivers are off (needed)", GOOD,
                   "VALORANT can't read your screen's real 16:9 shape, so it doesn't squeeze the stretched picture "
                   "back. Your screens keep working; brightness keys may not work on some laptops until you turn "
                   "them back on.", "Turn back on", lambda win: engine.set_monitor_drivers(True, int(win.winId()))))
    elif on:
        add(Health("monitor_driver", g, f"Monitor driver{'s' if len(on) > 1 else ''} still on", WARN,
                   f"{', '.join(dv.description for dv in on)}: VALORANT reads the real 16:9 shape and squeezes the "
                   "stretch back. Every 2026 method turns them off before launching (one administrator prompt).",
                   "Turn off (admin)", lambda win: engine.set_monitor_drivers(False, int(win.winId()))))

    # ---- other programs that rewrite game / display settings ----------------
    g = "Other programs"
    procs = running_processes()
    omen_copies = [c for t in engine.targets(gid) for c in getattr(game, "optimizer_copies", lambda t: [])(t)]
    if omen_copies or "omencommandcenterbackground.exe" in procs:
        add(Health("omen", g, "HP OMEN Gaming Hub (OMEN AI) changes VALORANT's settings", WARN,
                   "OMEN AI keeps its own copy of VALORANT's settings and puts it back over the real file — that's "
                   "how old values (Fullscreen, an old monitor, lower graphics) came back. TrueStretch now updates "
                   "OMEN's copy too, but the safest is: OMEN Gaming Hub › OMEN AI › turn optimization off for "
                   "VALORANT.", "Open OMEN Gaming Hub", lambda win: _open(open_omen, engine)))
    if "nvidia overlay.exe" in procs or "nvidia app.exe" in procs:
        add(Health("nvapp", g, "NVIDIA App is installed", INFO,
                   "If VALORANT is “Optimized” in the NVIDIA App (Graphics › VALORANT), it can reset the "
                   "display mode and resolution. Leave VALORANT on its own settings so TrueStretch's stay."))

    # ---- screens ----------------------------------------------------------
    g = "Screen quality"
    displays = display.list_displays()
    best = {}
    for dd in displays:
        dm = display.available_modes(dd.device)
        size = dd.native or (display.current_mode(dd.device) or Mode(1920, 1080, 60)).size
        r = display.refresh_rates(dm, *size)
        best[dd.device] = (r[0] if r else 0, dm)
    if d:
        cur = display.current_mode(device)
        top = display.refresh_rates(modes, *cur.size)[0] if cur and display.refresh_rates(modes, *cur.size) else None
        if cur and top and cur.hz + 1 < top:
            target = Mode(cur.width, cur.height, top)

            def raise_refresh(win, dev=device, new=target, old=cur):
                display.set_mode(new, dev)
                engine.notify("success", f"{where} now runs at {new.hz} Hz.")
                engine.changed.emit()
                return lambda: display.set_mode(old, dev)

            add(Health("refresh", g, f"{where} is running at {cur.hz} Hz — it can do {top} Hz", WARN,
                       f"Your screen can show {top} pictures per second but Windows only sends {cur.hz}. "
                       "A higher refresh rate makes movement smoother and aiming easier.",
                       f"Switch to {top} Hz", raise_refresh))
        elif cur:
            add(Health("refresh", g, f"{where} runs at its best refresh rate ({cur.hz} Hz)", GOOD,
                       "Windows is already using the highest refresh rate this screen supports."))
        mine = best.get(device, (0, None))[0]
        for other in displays:
            if other.device == device:
                continue
            hz = best.get(other.device, (0, None))[0]
            if hz >= mine + 20:
                add(Health("better_screen", g, f"{other.title} supports {hz} Hz", INFO,
                           f"That's smoother than {where} ({mine} Hz). VALORANT plays on your main display — "
                           f"to use {other.title}, make it the main display in Windows display settings, then pick "
                           "it in TrueStretch's Display tab.",
                           "Display settings", lambda win: open_uri("ms-settings:display")))

    # ---- performance ------------------------------------------------------
    g = "Performance"
    if pc.laptop and pc.on_battery:
        add(Health("battery", g, f"Running on battery ({pc.battery_percent}%)", WARN,
                   "Plug in your charger before playing: on battery, Windows and your graphics card slow down "
                   "to save power, which costs a lot of FPS."))
    elif pc.laptop:
        add(Health("battery", g, "Charger plugged in", GOOD, "Your laptop can run at full speed."))
    if pc.power_mode and pc.power_mode != "Best performance":
        add(Health("power", g, f"Windows power mode: {pc.power_mode}", WARN,
                   "“Best performance” lets your processor run at full speed while you play.",
                   "Open power settings", lambda win: open_uri("ms-settings:powersleep")))
    elif pc.power_plan == "Power saver":
        add(Health("power", g, "Power plan: Power saver", WARN,
                   "Power saver limits your processor. Pick Balanced or High performance.",
                   "Open power settings", lambda win: open_uri("ms-settings:powersleep")))
    else:
        add(Health("power", g, f"Windows power mode: {pc.power_mode or pc.power_plan or 'default'}", GOOD,
                   "Your PC is allowed to run at full speed."))
    add(Health("gamemode", g, f"Game Mode {'on' if pc.game_mode else 'off'}", GOOD if pc.game_mode else WARN,
               "Windows gives games priority and holds back updates while you play." if pc.game_mode else
               "Turning Game Mode on gives games priority and stops Windows Update interrupting you.",
               None if pc.game_mode else "Open Game Mode",
               None if pc.game_mode else (lambda win: open_uri("ms-settings:gaming-gamemode"))))

    for gpu in pc.gpus[:2]:
        age = gpu.driver_age_days
        when = gpu.driver_date.strftime("%B %Y") if gpu.driver_date else "an unknown date"
        if age is not None and age > 180:
            add(Health(f"driver_{gpu.vendor}", g, f"{gpu.name}: driver is {_months(age)} months old", WARN,
                       f"Driver {gpu.friendly_driver} is from {when}. New drivers often fix stutters and add "
                       "game fixes.", "Get latest driver",
                       lambda win, v=gpu.vendor: open_uri(DRIVER_PAGES.get(v, DRIVER_PAGES["nvidia"]))))
        else:
            add(Health(f"driver_{gpu.vendor}", g, f"{gpu.name}: driver {gpu.friendly_driver}", GOOD,
                       f"Released {when} — recent enough."))

    tweaks = {t.id: t for t in game.tweaks(info)}
    gpu_tweak = tweaks.get("gpu")
    if pc.hybrid_graphics and gpu_tweak and not gpu_tweak.unavailable_reason:
        on = _safe(gpu_tweak.is_on)
        fast = next((x.name for x in pc.gpus if x.vendor in ("nvidia", "amd")), "the fast graphics card")
        add(Health("hybrid", g, f"VALORANT {'uses' if on else 'may not use'} {fast}", GOOD if on else WARN,
                   "This PC has two graphics chips. " + (
                       "VALORANT is set to always use the fast one." if on else
                       "Windows sometimes runs games on the slower built-in chip. TrueStretch can make VALORANT "
                       "always use the fast one."),
                   None if on else "Use fast GPU", None if on else (lambda win: _set_tweak(engine, gpu_tweak))))
    fso = tweaks.get("fso")
    if fso and not fso.unavailable_reason:
        on = _safe(fso.is_on)
        add(Health("fso", g, f"Fullscreen optimizations {'disabled' if on else 'enabled'} for VALORANT",
                   GOOD if on else INFO,
                   "VALORANT runs in true exclusive fullscreen, which stretched res likes best." if on else
                   "Optional: disabling them makes VALORANT use true exclusive fullscreen, which helps stretched "
                   "res on some PCs.", None if on else "Disable them",
                   None if on else (lambda win: _set_tweak(engine, fso))))
    if pc.ram_gb:
        add(Health("ram", g, f"{round(pc.ram_gb)} GB memory",GOOD if pc.ram_gb >= 8 else WARN,
                   "Plenty for VALORANT." if pc.ram_gb >= 8 else
                   "VALORANT recommends at least 8 GB. Close other programs (browsers, Discord overlays) while "
                   "playing."))
    if info.install_dir:
        free = disk_free_gb(info.install_dir)
        if free is not None and free < 15:
            add(Health("disk", g, f"Only {free:g} GB free on drive {info.install_dir.drive}", WARN,
                       "VALORANT updates need free space. Free up at least 15 GB so patches don't fail."))
    return out


def _open(opener, engine):
    try:
        opener()
    except OSError as exc:
        engine.notify("warning", str(exc))


def _nvidia_scaling(d):
    """The NVIDIA driver's own scaling for this screen, or None (not NVIDIA / NVAPI unavailable)."""
    if not d or d.vendor != "nvidia":
        return None
    try:
        from . import nvidia
        pos = display.desktop_position(d.device)
        return next((t for t in nvidia.NvApi().targets() if pos and (t.x, t.y) == pos), None)
    except OSError:
        return None


def _safe(fn):
    try:
        return bool(fn())
    except OSError:
        return False


def _set_tweak(engine, tweak):
    tweak.set_on(True)
    engine.notify("success", f"{tweak.title}: done.")
    engine.changed.emit()


def summary(items):
    counts = {GOOD: 0, WARN: 0, BAD: 0, INFO: 0}
    for i in items:
        counts[i.status] += 1
    return counts
