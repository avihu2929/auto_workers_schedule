from __future__ import annotations

import yaml
from pathlib import Path
from typing import Dict, List, Tuple

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.yaml"


def load_config(path: Path = CONFIG_PATH) -> Tuple[List[str], Dict[str, str]]:
    """Returns (days, shifts) where shifts maps shift name -> "HH:MM-HH:MM"."""
    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    days: List[str] = list(raw.get("days", []))
    shifts: Dict[str, str] = {}
    for name, spec in raw.get("shifts", {}).items():
        shifts[name] = f"{spec.get('start')}-{spec.get('end')}"
    return days, shifts
