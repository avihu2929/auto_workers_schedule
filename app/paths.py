from __future__ import annotations

import sys
from pathlib import Path

# bundled default config ships inside the exe (PyInstaller data) or the
# project root in dev mode
if getattr(sys, "frozen", False):
    _BUNDLED_DIR = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    # user-editable data lives next to the exe
    DATA_DIR = Path(sys.executable).resolve().parent
    BUNDLED_CONFIG = _BUNDLED_DIR / "config.yaml"
else:
    DATA_DIR = Path(__file__).resolve().parent.parent
    BUNDLED_CONFIG = DATA_DIR / "config.yaml"

WORKERS_FILE = DATA_DIR / "workers.json"
RULES_FILE = DATA_DIR / "rules.json"
CONFIG_FILE = DATA_DIR / "config.yaml"

_DEFAULT_CONFIG = """days:
  - ראשון
  - שני
  - שלישי
  - רביעי
  - חמישי
  - שישי
  - שבת

shifts:
  בוקר:
    start: "06:00"
    end: "14:00"
  צהריים:
    start: "14:00"
    end: "22:00"
  לילה:
    start: "22:00"
    end: "06:00"
"""


def ensure_data_files() -> None:
    """Create default data files on first run (frozen app or fresh checkout)."""
    if not WORKERS_FILE.exists():
        WORKERS_FILE.write_text('{"workers": []}', encoding="utf-8")
    if not RULES_FILE.exists():
        RULES_FILE.write_text('{"rules": []}', encoding="utf-8")
    if not CONFIG_FILE.exists():
        if BUNDLED_CONFIG.exists():
            import shutil

            shutil.copyfile(BUNDLED_CONFIG, CONFIG_FILE)
        else:
            CONFIG_FILE.write_text(_DEFAULT_CONFIG, encoding="utf-8")
