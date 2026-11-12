"""Backups of every file TrueStretch changes.

Layout: backups/<game>/<target>/
    target.json            where the file lives and what it's called
    original.ini           the file before TrueStretch ever touched it (never deleted automatically)
    auto-YYYYmmdd-HHMMSS.ini   a copy taken before each change (oldest pruned)
"""

import json
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .inifile import set_read_only


@dataclass
class Backup:
    path: Path
    game_id: str
    target_key: str
    target_label: str
    target_path: Path
    kind: str           # "original" or "auto"
    created: datetime


class BackupManager:
    def __init__(self, root, keep=15):
        self.root = Path(root)
        self.keep = keep

    def folder(self, game_id, key):
        return self.root / game_id / key

    def create(self, game_id, key, label, source):
        source = Path(source)
        folder = self.folder(game_id, key)
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "target.json").write_text(
            json.dumps({"label": label, "path": str(source)}, indent=2), encoding="utf-8")
        original = folder / ("original" + source.suffix)
        if not original.exists():
            shutil.copyfile(source, original)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        copy = folder / f"auto-{stamp}{source.suffix}"
        shutil.copyfile(source, copy)
        autos = sorted(folder.glob(f"auto-*{source.suffix}"))
        for old in autos[:-self.keep] if self.keep > 0 else []:
            old.unlink(missing_ok=True)
        return copy

    def original(self, game_id, key):
        folder = self.folder(game_id, key)
        found = sorted(folder.glob("original.*")) if folder.is_dir() else []
        return found[0] if found else None

    def list(self, game_id=None):
        backups = []
        games = [self.root / game_id] if game_id else (list(self.root.iterdir()) if self.root.is_dir() else [])
        for game_dir in games:
            if not game_dir.is_dir():
                continue
            for target_dir in game_dir.iterdir():
                if not target_dir.is_dir():
                    continue
                try:
                    meta = json.loads((target_dir / "target.json").read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    continue
                for f in target_dir.iterdir():
                    if f.name == "target.json" or not f.is_file():
                        continue
                    kind = "original" if f.stem == "original" else "auto"
                    backups.append(Backup(f, game_dir.name, target_dir.name, meta.get("label", target_dir.name),
                                          Path(meta.get("path", "")), kind,
                                          datetime.fromtimestamp(f.stat().st_mtime)))
        backups.sort(key=lambda b: b.created, reverse=True)
        return backups

    def restore(self, backup):
        dest = backup.target_path
        if not dest.parent.is_dir():
            raise FileNotFoundError(f"The folder for this file no longer exists:\n{dest.parent}")
        if dest.exists():
            set_read_only(dest, False)
        shutil.copyfile(backup.path, dest)

    def delete(self, backup):
        backup.path.unlink(missing_ok=True)

    def size_bytes(self):
        if not self.root.is_dir():
            return 0
        return sum(f.stat().st_size for f in self.root.rglob("*") if f.is_file())
