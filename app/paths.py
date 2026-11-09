from __future__ import annotations
import os
import sys
from pathlib import Path

APP_ID = "MustacomAquaGestionPro"

def data_dir() -> Path:
    override = os.environ.get("MUSTACOM_DATA_DIR")
    if override:
        root = Path(override).expanduser()
    elif sys.platform == "win32":
        root = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local")) / "MUSTACOM" / APP_ID
    else:
        root = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / APP_ID
    root.mkdir(parents=True, exist_ok=True)
    for name in ("attachments", "exports", "backups", "logs"):
        (root / name).mkdir(exist_ok=True)
    return root

def resource_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent.parent

def database_path() -> Path:
    return data_dir() / "mustacom_aqua.db"
