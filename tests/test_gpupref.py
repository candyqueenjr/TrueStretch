r"""Windows keeps several per-app graphics settings in ONE registry string (HKCU\Software\Microsoft\DirectX\
UserGpuPreferences\<exe> = "AppStatus=4096;AutoHDREnable=1;GpuPreference=2;"). TrueStretch sets GpuPreference there
in two places (the game page's "high-performance graphics card" tweak and Optimize Max's "VALORANT on the fast
graphics card"); both must keep every other pair Windows or the player wrote. Tested on the real registry under a
fake game path that is removed again at the end."""
import os
import sys
import tempfile
import winreg
from pathlib import Path
from types import SimpleNamespace

os.environ["APPDATA"] = tempfile.mkdtemp(prefix="ts-gpu-")
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))

from truestretch import optimizer as opt                                     # noqa: E402
from truestretch.games.valorant import GPU_PREF_KEY, Valorant                # noqa: E402
from truestretch.system import flag_value, flags_with, reg_delete, reg_get, reg_set   # noqa: E402

fails = []


def check(c, t):
    print(("PASS " if c else "FAIL ") + t)
    c or fails.append(t)


# ---- the string helpers (pure) --------------------------------------------------------------------------------
check(flags_with("", "GpuPreference", "2") == "GpuPreference=2;", "empty string -> just our pair")
check(flags_with(None, "GpuPreference", "2") == "GpuPreference=2;", "missing value -> just our pair")
check(flags_with("AppStatus=4096;GpuPreference=2;", "GpuPreference", "2") == "AppStatus=4096;GpuPreference=2;",
      "already set -> unchanged")
check(flags_with("AppStatus=4096;AutoHDREnable=1;", "GpuPreference", "2")
      == "AppStatus=4096;AutoHDREnable=1;GpuPreference=2;", "Windows' own pairs kept, ours appended")
check(flags_with("GpuPreference=1;AutoHDREnable=0;", "GpuPreference", "2") == "AutoHDREnable=0;GpuPreference=2;",
      "power-saving -> high performance, Auto HDR choice kept")
check(flags_with("AppStatus=4096;GpuPreference=2;", "GpuPreference", None) == "AppStatus=4096;",
      "removing ours leaves Windows' pair")
check(flags_with("GpuPreference=2;", "GpuPreference", None) == "", "removing the only pair -> empty")
check(flags_with(";SwapEffectUpgradeEnable=1;", "SwapEffectUpgradeEnable", "1") == "SwapEffectUpgradeEnable=1;",
      "Windows' leading ';' form is understood")
check(flags_with("VRROptimizeEnable=1;", "SwapEffectUpgradeEnable", "1")
      == "VRROptimizeEnable=1;SwapEffectUpgradeEnable=1;", "global settings string: VRR flag kept")
check(flag_value("AppStatus=4096;GpuPreference=2;", "GpuPreference") == "2", "flag_value reads ours")
check(flag_value("AppStatus=4096;GpuPreference=2;", "AutoHDREnable") is None, "flag_value: missing -> None")
check(flag_value("GpuPreference=12;", "GpuPreference") == "12", "flag_value doesn't match by substring")

# ---- the real registry, under a fake game path ---------------------------------------------------------------
FAKE = r"C:\TrueStretch-test\fake-VALORANT-Win64-Shipping.exe"
WINDOWS_OWN = "AppStatus=4096;AutoHDREnable=1;"
assert reg_get(winreg.HKEY_CURRENT_USER, GPU_PREF_KEY, FAKE) is None, "leftover test value - delete it first"
info = SimpleNamespace(game_exe=Path(FAKE), installed=True)
engine = SimpleNamespace(info={"valorant": info})
pc = SimpleNamespace(gpus=[object(), object()])          # a two-GPU laptop


def raw():
    return reg_get(winreg.HKEY_CURRENT_USER, GPU_PREF_KEY, FAKE)


try:
    # Optimize Max item: apply -> verify -> undo byte-identical
    reg_set(winreg.HKEY_CURRENT_USER, GPU_PREF_KEY, FAKE, WINDOWS_OWN)
    item = opt._gpu_pref(engine, pc)
    check(item.state == opt.IMPROVE and item.current == "Let Windows decide", "scan: no GpuPreference -> improve")
    saved = item._snapshot()
    item._apply()
    check(raw() == WINDOWS_OWN + "GpuPreference=2;", f"apply keeps Windows' pairs: {raw()!r}")
    after = opt._gpu_pref(engine, pc)
    check(after.state == opt.DONE and after.current == "High performance", "re-scan: done / High performance")
    item._restore(saved)
    check(raw() == WINDOWS_OWN, f"undo puts the exact string back: {raw()!r}")

    reg_set(winreg.HKEY_CURRENT_USER, GPU_PREF_KEY, FAKE, "GpuPreference=1;")
    check(opt._gpu_pref(engine, pc).current == "Power saving", "scan shows 'Power saving' for GpuPreference=1")
    opt._gpu_pref(engine, pc)._apply()
    check(raw() == "GpuPreference=2;", "power saving -> high performance")

    # Game page tweak: on keeps Windows' pairs, off removes only ours, deletes the value when nothing is left
    tweak = next(t for t in Valorant().tweaks(info) if t.id == "gpu")
    reg_set(winreg.HKEY_CURRENT_USER, GPU_PREF_KEY, FAKE, WINDOWS_OWN)
    check(tweak.is_on() is False, "tweak: off without GpuPreference")
    tweak.set_on(True)
    check(tweak.is_on() and raw() == WINDOWS_OWN + "GpuPreference=2;", f"tweak on keeps Windows' pairs: {raw()!r}")
    tweak.set_on(False)
    check(not tweak.is_on() and raw() == WINDOWS_OWN, f"tweak off leaves Windows' pairs: {raw()!r}")
    reg_set(winreg.HKEY_CURRENT_USER, GPU_PREF_KEY, FAKE, "GpuPreference=2;")
    tweak.set_on(False)
    check(raw() is None, "tweak off removes the value when only ours was in it")
    tweak.set_on(True)
    check(raw() == "GpuPreference=2;", "tweak on from nothing")
finally:
    reg_delete(winreg.HKEY_CURRENT_USER, GPU_PREF_KEY, FAKE)
check(raw() is None, "fake value removed")

print("\nALL PASSED" if not fails else f"\n{len(fails)} FAILED: {fails}")
sys.exit(1 if fails else 0)
