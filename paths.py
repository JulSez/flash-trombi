from __future__ import annotations

import os
import shutil
from pathlib import Path

APP_NAME = "FlashTrombi"


def _default_data_dir() -> Path:
    override = os.environ.get("FLASH_TROMBI_DATA_DIR")
    if override:
        return Path(override).expanduser().resolve()

    if os.name == "nt":
        root = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        return root / APP_NAME

    xdg = os.environ.get("XDG_DATA_HOME")
    if xdg:
        return Path(xdg).expanduser() / APP_NAME
    return Path.home() / ".local" / "share" / APP_NAME


DATA_DIR = _default_data_dir()
DB_PATH = DATA_DIR / "flash_trombi.sqlite3"
CLASSES_DIR = DATA_DIR / "classes"
BACKUPS_DIR = DATA_DIR / "backups"


def migrate_legacy_data() -> bool:
    """Move/copy the old ./data directory to the per-user data directory once."""
    if DB_PATH.exists():
        return False

    legacy = Path.cwd() / "data"
    legacy_db = legacy / "flash_trombi.sqlite3"
    if legacy.resolve() == DATA_DIR.resolve() or not legacy_db.exists():
        return False

    DATA_DIR.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(legacy, DATA_DIR, dirs_exist_ok=True)
    return True


def ensure_data_dirs() -> None:
    migrate_legacy_data()
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    CLASSES_DIR.mkdir(parents=True, exist_ok=True)
    BACKUPS_DIR.mkdir(parents=True, exist_ok=True)
