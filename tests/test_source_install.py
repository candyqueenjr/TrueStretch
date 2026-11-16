"""One-command install (install.ps1, for PCs where Smart App Control blocks the unsigned .exe): the in-app update of
a source install and the launcher's swap. Everything happens in a temp folder with a fake install:

  - a developer checkout (this repo) is never treated as a source install
  - install_source() downloads the release's source zip, checks it is TrueStretch at the right version, and stages
    it in app.new without touching the running app\\
  - a zip with the wrong version or without main.py is refused and nothing is staged
  - launcher.apply_pending_update() swaps app.new in (app.old removed); with nothing staged it does nothing
  - restart_into() builds "pythonw launcher.pyw --wait-pid <pid> --updated" for a source install
"""
import importlib.machinery
import importlib.util
import json
import os
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT_REPO = Path(__file__).resolve().parents[1]
os.environ["APPDATA"] = tempfile.mkdtemp(prefix="ts-srcinst-")
sys.path.insert(0, str(ROOT_REPO))
from truestretch import updater  # noqa: E402

fails = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  ({detail})" if detail and not cond else ""))
    if not cond:
        fails.append(name)


def load_launcher():
    path = ROOT_REPO / "tools" / "launcher.pyw"
    loader = importlib.machinery.SourceFileLoader("ts_launcher", str(path))
    spec = importlib.util.spec_from_loader("ts_launcher", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def fake_app(folder, version):
    (folder / "truestretch").mkdir(parents=True)
    (folder / "main.py").write_text("print('TrueStretch')\n", encoding="utf-8")
    (folder / "truestretch" / "__init__.py").write_text(f'APP_NAME = "TrueStretch"\nVERSION = "{version}"\n',
                                                        encoding="utf-8")
    (folder / "requirements.txt").write_text("PySide6==6.12.0\n", encoding="utf-8")


def make_zip(path, top, version, with_main=True):
    with zipfile.ZipFile(path, "w") as z:
        if with_main:
            z.writestr(f"{top}/main.py", "print('new')\n")
        z.writestr(f"{top}/truestretch/__init__.py", f'VERSION = "{version}"\n')
        z.writestr(f"{top}/requirements.txt", "PySide6==6.12.0\n")
    return path


def release(version):
    return updater.Release(version=version, tag=f"v{version}", notes="", url="", download="", size=0, sha256="")


tmp = Path(tempfile.mkdtemp(prefix="ts-srcroot-"))
root = tmp / "TrueStretch-src"
fake_app(root / "app", "1.0.0")
(root / "install.json").write_text(json.dumps({"kind": "source", "tag": "v1.0.0"}), encoding="utf-8")
(root / "launcher.pyw").write_text("# launcher\n", encoding="utf-8")

# 1. this checkout is not a source install
check("developer checkout is not a source install", updater.source_root() is None, str(updater.source_root()))

# 2. good update is staged
good = make_zip(tmp / "good.zip", "TrueStretch-9.9.9", "9.9.9")
updater.SOURCE_ZIP = good.as_uri().replace("good.zip", "{tag}.zip")
(tmp / "v9.9.9.zip").write_bytes(good.read_bytes())
target = updater.install_source(release("9.9.9"), root=root)
new_init = root / "app.new" / "truestretch" / "__init__.py"
check("install_source returns the launcher", target == root / "launcher.pyw", str(target))
check("update staged in app.new", new_init.is_file() and 'VERSION = "9.9.9"' in new_init.read_text())
check("running app untouched", 'VERSION = "1.0.0"' in (root / "app" / "truestretch" / "__init__.py").read_text())
check("no leftovers", not (root / "app.staging").exists() and not (root / "update.zip").exists())

# 3. bad zips are refused, nothing staged
import shutil  # noqa: E402
shutil.rmtree(root / "app.new")
(tmp / "v9.9.8.zip").write_bytes(make_zip(tmp / "w.zip", "TrueStretch-9.9.7", "9.9.7").read_bytes())
try:
    updater.install_source(release("9.9.8"), root=root)
    check("wrong version refused", False, "no error")
except updater.UpdateError as exc:
    check("wrong version refused", "9.9.7" in str(exc), str(exc))
check("wrong version: nothing staged", not (root / "app.new").exists())
(tmp / "v9.9.6.zip").write_bytes(make_zip(tmp / "n.zip", "Other-9.9.6", "9.9.6", with_main=False).read_bytes())
try:
    updater.install_source(release("9.9.6"), root=root)
    check("non-TrueStretch zip refused", False, "no error")
except updater.UpdateError:
    check("non-TrueStretch zip refused", True)
check("non-TrueStretch zip: nothing staged", not (root / "app.new").exists())

# 4. launcher swap
launcher = load_launcher()
check("launcher: nothing staged -> no swap", launcher.apply_pending_update(str(root)) is False)
updater.install_source(release("9.9.9"), root=root)
check("launcher: staged -> swap", launcher.apply_pending_update(str(root)) is True)
check("launcher: app is the new version", 'VERSION = "9.9.9"' in (root / "app" / "truestretch" / "__init__.py").read_text())
check("launcher: app.new and app.old gone", not (root / "app.new").exists() and not (root / "app.old").exists())
cmd = launcher.command(str(root), ["--updated"])
check("launcher: starts venv pythonw with app\\main.py",
      cmd[0].endswith(os.path.join("venv", "Scripts", "pythonw.exe")) and cmd[1].endswith(os.path.join("app", "main.py"))
      and cmd[2] == "--updated", str(cmd))

# 5. restart command for a source install
captured = {}


class FakePopen:
    def __init__(self, args, **kw):
        captured["args"] = args


real = updater.subprocess.Popen
updater.subprocess.Popen = FakePopen
try:
    updater.restart_into(root / "launcher.pyw")
finally:
    updater.subprocess.Popen = real
a = captured.get("args", [])
check("restart: pythonw launcher.pyw --wait-pid <pid> --updated",
      len(a) == 5 and a[0].lower().endswith(("pythonw.exe", "python.exe")) and a[1].endswith("launcher.pyw")
      and a[2] == "--wait-pid" and a[3] == str(os.getpid()) and a[4] == "--updated", str(a))

shutil.rmtree(tmp, ignore_errors=True)
print("FAILED" if fails else "ALL PASSED")
sys.exit(1 if fails else 0)
