"""Optimize Max: the 'Inside VALORANT' rows read the real values from RiotUserSettings.ini (the local copy of the Riot
account settings). Crafted files cover: a tuned account (everything right), an untuned one (everything wrong, FPS cap
below the refresh rate), a fresh account (no keys -> game defaults, nothing claimed), a missing file, and the FPS
limiter cases. Then the real PC: every account's file parses and the scan builds the same 14 rows. Read-only."""
import os
import sys
import tempfile
from pathlib import Path

os.environ["APPDATA"] = tempfile.mkdtemp(prefix="ts-ingame-")
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))

from truestretch import riotsettings as rs                                   # noqa: E402
from truestretch.optimizer import DONE, IN_GAME                              # noqa: E402

fails = []


def check(c, t):
    print(("PASS " if c else "FAIL ") + t)
    c or fails.append(t)


def account(name, lines):
    folder = Path(tempfile.mkdtemp(prefix="ts-acct-")) / name
    (folder / "WindowsClient").mkdir(parents=True)
    (folder / "Windows").mkdir()
    gus = folder / "WindowsClient" / "GameUserSettings.ini"
    gus.write_text("[/Script/ShooterGame.ShooterGameUserSettings]\r\nFrameRateLimit=0.000000\r\n", encoding="utf-8")
    if lines is not None:
        (folder / "Windows" / "RiotUserSettings.ini").write_text(
            "[Settings]\r\nLocalSettingsVersion=7\r\n" + "".join(l + "\r\n" for l in lines), encoding="utf-8")
    return gus


def by_id(items):
    return {i.id: i for i in items}


TUNED = ["EAresIntSettingName::NvidiaReflexLowLatencySetting=2", "EAresBoolSettingName::MultithreadedRenderingEnabled=True",
         "EAresIntSettingName::MaterialQuality=0", "EAresIntSettingName::TextureQuality=0",
         "EAresIntSettingName::DetailQuality=0", "EAresIntSettingName::UIQuality=0", "EAresIntSettingName::AntiAliasing=0",
         "EAresIntSettingName::AnisotropicFiltering=1", "EAresIntSettingName::BloomQuality=0",
         "EAresBoolSettingName::DisableDistortion=True", "EAresBoolSettingName::ShadowsEnabled=False",
         "EAresBoolSettingName::LimitFramerateAlways=False", "EAresStringSettingName::CrosshairProfileName=x"]
UNTUNED = ["EAresIntSettingName::NvidiaReflexLowLatencySetting=1", "EAresBoolSettingName::MultithreadedRenderingEnabled=False",
           "EAresIntSettingName::MaterialQuality=2", "EAresIntSettingName::TextureQuality=1",
           "EAresIntSettingName::DetailQuality=2", "EAresIntSettingName::UIQuality=1", "EAresIntSettingName::AntiAliasing=3",
           "EAresIntSettingName::AnisotropicFiltering=16", "EAresIntSettingName::BloomQuality=1",
           "EAresBoolSettingName::DisableDistortion=False", "EAresBoolSettingName::ShadowsEnabled=True",
           "EAresBoolSettingName::LimitFramerateAlways=True", "EAresFloatSettingName::MaxFramerateAlways=60.000000"]
READ = {"reflex", "multithread", "material", "texture", "detail", "ui", "aa", "af", "bloom", "distortion", "shadows",
        "fps_limit"}

gus = account("11111111-2222-3333-4444-555555555555-eu", TUNED)
riot = rs.riot_settings_path(gus)
check(riot.is_file() and riot.parent.name == "Windows", "RiotUserSettings.ini is found next to the account's GameUserSettings.ini")
items = by_id(rs.ingame_items(riot, 144, "Account 1111"))
check(len(items) == 14, f"14 rows ({len(items)})")
check(all(items[f"ingame_{k}"].state == DONE for k in READ), "tuned account: every readable setting is Optimized")
check(items["ingame_reflex"].current == "On + Boost" and items["ingame_af"].current == "1x"
      and items["ingame_fps_limit"].current == "Off", "tuned account: values shown in plain words")
check(items["ingame_vignette"].state == IN_GAME and items["ingame_vignette"].current == "Set in game"
      and items["ingame_clarity"].state == IN_GAME, "Vignette / Improve Clarity (no known key) stay manual")
check(all("Account 1111" in i.note and "VALORANT \u2192 Settings \u2192 Video" in i.note for i in items.values()),
      "every row says which account it was read from and where to change it")
check(not any(i.can_apply for i in items.values()), "nothing is applicable - read-only")

items = by_id(rs.ingame_items(rs.riot_settings_path(account("a", UNTUNED)), 144))
check(all(items[f"ingame_{k}"].state == IN_GAME for k in READ), "untuned account: every readable setting needs changing")
want = {"reflex": "On", "multithread": "Off", "material": "High", "texture": "Medium", "detail": "High", "ui": "Medium",
        "aa": "On", "af": "16x", "bloom": "On", "distortion": "On", "shadows": "On",
        "fps_limit": "60 FPS cap (screen: 144 Hz)"}
bad = {k: items[f"ingame_{k}"].current for k, v in want.items() if items[f"ingame_{k}"].current != v}
check(not bad, f"untuned account: current values decoded ({bad or 'all as expected'})")
check(items["ingame_fps_limit"].target == "Off, or at least 144 FPS", "FPS limit target names the refresh rate")
check(any("MultithreadedRenderingEnabled = 'False'" in d for d in items["ingame_multithread"].debug),
      "technical details show the raw key and value")

items = by_id(rs.ingame_items(rs.riot_settings_path(account("b", [])), 144))
check(all(i.state == IN_GAME for i in items.values()) and items["ingame_reflex"].current == rs.GAME_DEFAULT
      and items["ingame_fps_limit"].current == rs.GAME_DEFAULT, "fresh account (no keys): game defaults, nothing claimed")
items = by_id(rs.ingame_items(rs.riot_settings_path(account("c", None)), None))
check(len(items) == 14 and all(i.state == IN_GAME for i in items.values()), "missing file: 14 manual rows, no crash")
items = by_id(rs.ingame_items(None))
check(len(items) == 14 and items["ingame_fps_limit"].target == "Off (or a little above your refresh rate)",
      "no account at all: still 14 rows")

cases = [({"EAresBoolSettingName::LimitFramerateAlways": "True", "EAresFloatSettingName::MaxFramerateAlways": "240.0"}, 144, "240 FPS cap", True),
         ({"EAresBoolSettingName::LimitFramerateAlways": "True", "EAresFloatSettingName::MaxFramerateAlways": "144.0"}, 144, "144 FPS cap", True),
         ({"EAresBoolSettingName::LimitFramerateAlways": "True", "EAresFloatSettingName::MaxFramerateAlways": "120.0"}, 144, "120 FPS cap (screen: 144 Hz)", False),
         ({"EAresBoolSettingName::LimitFramerateAlways": "True", "EAresFloatSettingName::MaxFramerateAlways": "120.0"}, None, "120 FPS cap", True),
         ({"EAresBoolSettingName::LimitFramerateAlways": "True"}, 144, "On (cap unknown)", False),
         ({"EAresBoolSettingName::LimitFramerateAlways": "False", "EAresFloatSettingName::MaxFramerateAlways": "60.0"}, 144, "Off", True),
         ({}, 144, None, True)]
for values, hz, text, ok in cases:
    got = rs.fps_limit(values, hz)
    check(got == (text, ok), f"FPS limit {values.get('EAresFloatSettingName::MaxFramerateAlways')} @ {hz} Hz -> {got}")

# the real PC ----------------------------------------------------------------------------------------------
from truestretch.games.valorant import CONFIG_ROOT                           # noqa: E402
real = sorted(CONFIG_ROOT.glob("*/Windows/RiotUserSettings.ini")) if CONFIG_ROOT.is_dir() else []
for path in real:
    items = rs.ingame_items(path, 165, path.parent.parent.name[:8])
    shown = {i.title: (i.current, i.state) for i in items}
    check(len(items) == 14 and all(i.state in (DONE, IN_GAME) for i in items), f"real file {path.parent.parent.name[:8]}: {shown}")
if real:
    from PySide6.QtCore import QCoreApplication
    app = QCoreApplication([])
    from truestretch.settings import Settings
    from truestretch.games import GAMES
    from truestretch.engine import Engine
    from truestretch import optimizer as opt
    e = Engine(Settings({g.id: g.default_settings() for g in GAMES})); e.timer.stop()
    items = opt._in_game_items(e)
    check(len(items) == 14 and all(i.group == "Inside VALORANT" for i in items), "scan step builds the 14 rows from the engine's targets")
    o = opt.Optimizer(e); o.items = items
    check(o.score() == 100, f"in-game rows don't count in the score ({o.score()})")
else:
    print("INFO no VALORANT accounts on this PC - real-file checks skipped")

print("\nALL PASSED" if not fails else f"\n{len(fails)} FAILED: {fails}")
sys.exit(1 if fails else 0)
