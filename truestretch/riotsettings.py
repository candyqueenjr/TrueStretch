"""Reads the graphics settings VALORANT keeps in the player's Riot account.

VALORANT stores the Video > Graphics Quality settings (Reflex, Multithreaded Rendering, quality levels, Bloom, ...)
and the FPS limiter in the Riot account, not in GameUserSettings.ini. The game keeps a local copy per account in
`%LOCALAPPDATA%\\VALORANT\\Saved\\Config\\<account>\\Windows\\RiotUserSettings.ini` ([Settings] section, keys like
`EAresIntSettingName::NvidiaReflexLowLatencySetting=2`). Only values the player changed are written - a missing key
means the game default. The file is uploaded to the account when the game saves, so TrueStretch only READS it (writing
it would be overwritten by the cloud copy); the Optimize Max rows show the real value and where to change it in game.

Key names and values were taken from real files on several accounts (2026-11-08, release-13.09) and match the public
configs players share (e.g. https://gist.github.com/tioxy/95b7bb70986431dbc4d844bdfc9a90b2)."""

from pathlib import Path

from .inifile import IniFile

SECTION = "Settings"
INT, BOOL, FLOAT = "EAresIntSettingName::", "EAresBoolSettingName::", "EAresFloatSettingName::"
QUALITY = {"0": "Low", "1": "Medium", "2": "High"}
REFLEX = {"0": "Off", "1": "On", "2": "On + Boost"}
WHERE_GQ, WHERE_GEN = "Video → Graphics Quality", "Video → General"
GAME_DEFAULT = "Game default"


def riot_settings_path(game_user_settings):
    """RiotUserSettings.ini next to an account's GameUserSettings.ini (…/<account>/WindowsClient/… or …/Windows/…)."""
    return Path(game_user_settings).parent.parent / "Windows" / "RiotUserSettings.ini"


def read(path, keys):
    """{key: raw value} for the keys present in [Settings]; {} when the file is missing or unreadable."""
    try:
        if not path or not Path(path).is_file():
            return {}
        return IniFile(path).get(SECTION, keys)
    except (OSError, ValueError):
        return {}


def _bool(raw):
    return None if raw is None else raw.strip().lower() == "true"


def _num(raw):
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _named(names, fallback):
    return lambda raw: names.get(raw.strip(), fallback(raw)) if raw is not None else None


def _on_off(off_when_true):
    return lambda raw: None if _bool(raw) is None else ("Off" if _bool(raw) == off_when_true else "On")


# (id, title, keys, shown(raw values) -> current text or None when at game default, target, ok(raw values),
#  why, where in the game, level)
_low = lambda v: v in (None, "0")                                                                   # noqa: E731
SPECS = [
    ("reflex", "NVIDIA Reflex Low Latency", [INT + "NvidiaReflexLowLatencySetting"],
     lambda v: _named(REFLEX, lambda r: f"Level {r}")(v[0]), "On + Boost", lambda v: v[0] == "2",
     "Biggest input-delay cut in VALORANT (NVIDIA cards).", WHERE_GQ, 3),
    ("multithread", "Multithreaded Rendering", [BOOL + "MultithreadedRenderingEnabled"],
     lambda v: _on_off(False)(v[0]), "On", lambda v: _bool(v[0]) is True,
     "Uses all processor cores - more FPS on almost every PC.", WHERE_GQ, 3),
    ("material", "Material Quality", [INT + "MaterialQuality"], lambda v: _named(QUALITY, str)(v[0]), "Low",
     lambda v: v[0] == "0", "Simpler surfaces - less to draw, clearer view.", WHERE_GQ, 2),
    ("texture", "Texture Quality", [INT + "TextureQuality"], lambda v: _named(QUALITY, str)(v[0]), "Low",
     lambda v: v[0] == "0", "Lower texture detail; frees graphics memory.", WHERE_GQ, 1),
    ("detail", "Detail Quality", [INT + "DetailQuality"], lambda v: _named(QUALITY, str)(v[0]), "Low",
     lambda v: v[0] == "0", "Removes extra scenery that can hide enemies.", WHERE_GQ, 2),
    ("ui", "UI Quality", [INT + "UIQuality"], lambda v: _named(QUALITY, str)(v[0]), "Low",
     lambda v: v[0] == "0", "Cheaper menus and HUD - no visible downside.", WHERE_GQ, 1),
    ("vignette", "Vignette", [], lambda v: None, "Off", lambda v: False,
     "Darkens screen edges - removes visibility.", WHERE_GQ, 1),
    ("aa", "Anti-Aliasing", [INT + "AntiAliasing"],
     lambda v: None if v[0] is None else ("None" if v[0] == "0" else "On"), "None or MSAA 2x",
     lambda v: v[0] == "0", "MSAA 4x costs many FPS.", WHERE_GQ, 2),
    ("af", "Anisotropic Filtering", [INT + "AnisotropicFiltering"],
     lambda v: None if v[0] is None else f"{v[0]}x", "1x or 2x", lambda v: v[0] in ("1", "2"),
     "Higher values cost FPS for detail you won't notice.", WHERE_GQ, 1),
    ("clarity", "Improve Clarity", [], lambda v: None, "Off", lambda v: False,
     "Sharpening effect with a small FPS cost.", WHERE_GQ, 1),
    ("bloom", "Bloom", [INT + "BloomQuality"],
     lambda v: None if v[0] is None else ("Off" if v[0] == "0" else "On"), "Off", lambda v: v[0] == "0",
     "Glow around bright lights - hides enemies standing near them.", WHERE_GQ, 1),
    ("distortion", "Distortion", [BOOL + "DisableDistortion"], lambda v: _on_off(True)(v[0]), "Off",
     lambda v: _bool(v[0]) is True, "Wobble effects from abilities - harder to see through.", WHERE_GQ, 1),
    ("shadows", "Cast Shadows", [BOOL + "ShadowsEnabled"], lambda v: _on_off(False)(v[0]), "Off",
     lambda v: _bool(v[0]) is False, "Character shadows cost FPS.", WHERE_GQ, 2),
]
FPS_KEYS = [BOOL + "LimitFramerateAlways", FLOAT + "MaxFramerateAlways"]
ALL_KEYS = [k for spec in SPECS for k in spec[2]] + FPS_KEYS


def fps_limit(values, refresh_hz):
    """(current text, ok, debug) for the in-game 'Limit FPS Always' setting. A cap below the screen's refresh rate
    throws away frames the screen could show; Off (or a cap at/above the refresh rate) is fine."""
    on, cap = _bool(values.get(FPS_KEYS[0])), _num(values.get(FPS_KEYS[1]))
    if not on:
        return ("Off" if on is False else None), True
    if cap is None or cap <= 0:
        return "On (cap unknown)", False
    low = bool(refresh_hz) and cap < refresh_hz
    return f"{cap:.0f} FPS cap" + (f" (screen: {refresh_hz} Hz)" if low else ""), not low


def ingame_items(riot_path, refresh_hz=None, account=""):
    """Optimize Max items for the 'Inside VALORANT' group, read from one account's RiotUserSettings.ini: DONE when
    the value already matches, IN_GAME (with the exact place in the game's settings) when it doesn't or is unknown."""
    from .optimizer import DONE as done, IN_GAME as in_game, Item as item_cls
    values = read(riot_path, ALL_KEYS)
    source = (f"Read from {account}'s last session. " if account else "") + \
        "These live in your Riot account, so only the game can change them."
    items = []
    for iid, title, keys, shown, target, ok, why, where, level in SPECS:
        raw = [values.get(k) for k in keys]
        current = shown(raw) if keys else None
        known = current is not None
        items.append(item_cls(f"ingame_{iid}", "Inside VALORANT", title, why,
                              current if known else (GAME_DEFAULT if keys else "Set in game"), target,
                              done if known and ok(raw) else in_game, "", level,
                              note=f"VALORANT → Settings → {where}. {source}",
                              debug=[f"{k} = {v!r}" for k, v in zip(keys, raw)] or
                                    ["not stored in RiotUserSettings.ini (no known key)"]))
    current, ok = fps_limit(values, refresh_hz)
    target = f"Off, or at least {refresh_hz} FPS" if refresh_hz else "Off (or a little above your refresh rate)"
    items.append(item_cls("ingame_fps_limit", "Inside VALORANT", "Limit FPS Always",
                          "Never cap below your screen's refresh rate - a lower cap throws away frames your screen "
                          "could show and adds input delay.", current if current is not None else GAME_DEFAULT,
                          target, done if current is not None and ok else in_game, "", 2,
                          note=f"VALORANT → Settings → {WHERE_GEN}. {source}",
                          debug=[f"{k} = {values.get(k)!r}" for k in FPS_KEYS] + [f"screen refresh: {refresh_hz} Hz"]))
    return items
