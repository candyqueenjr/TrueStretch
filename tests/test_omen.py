"""OMEN AI copy stays in sync (on a COPY of the real config folder) + health check on the real PC."""
import os, shutil, sys, tempfile
from pathlib import Path
TMP = Path(tempfile.mkdtemp(prefix="ts-omen-"))
os.environ["APPDATA"] = str(TMP / "appdata")
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QCoreApplication
app = QCoreApplication([])
import truestretch.games.valorant as val
from truestretch.backups import BackupManager
from truestretch.inifile import IniFile

real = val.CONFIG_ROOT
fake = TMP / "Config"
shutil.copytree(real, fake)
val.CONFIG_ROOT = fake
v = val.Valorant()
info = v.detect()
targets = [t for t in v.targets(info) if v.optimizer_copies(t)]
assert targets, "no target with an OMEN AI copy"
t = targets[0]
omen = v.optimizer_copies(t)[0]
before_omen = omen.read_bytes()
b = BackupManager(TMP / "backups")
v.apply_target(t, 1920, 1080, {"window_mode": "windowed_fullscreen"}, b, None)
keys = ["FullscreenMode", "ResolutionSizeX", "bShouldLetterbox", "DefaultMonitorIndex", "DefaultMonitorDeviceID"]
main_v, omen_v = IniFile(t.path).get(val.SECTION, keys), IniFile(omen).get(val.SECTION, keys)
print("main :", main_v)
print("omen :", omen_v)
assert main_v == omen_v, "OMEN copy not in sync"
assert "sg.TextureQuality" in omen.read_text(), "OMEN's other lines must stay"
v.restore_target(t, b, (1920, 1080))
assert omen.read_bytes() == before_omen, "OMEN copy not restored"
print("OMEN SYNC + RESTORE PASSED")
shutil.rmtree(TMP, ignore_errors=True)

# health on the real PC (read-only)
val.CONFIG_ROOT = real
from truestretch.settings import Settings
from truestretch.games import GAMES
from truestretch.engine import Engine
from truestretch import health
e = Engine(Settings({g.id: g.default_settings() for g in GAMES})); e.timer.stop()
for i in health.checks(e, "valorant"):
    print(f"[{i.status:4}] {i.group:22} {i.title}  ->  {i.fix_label or ''}")
