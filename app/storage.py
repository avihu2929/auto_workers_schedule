from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import List, Optional, Tuple

from .model import Rule, Worker
from . import paths

DEFAULT_WORKERS_FILE = paths.WORKERS_FILE
DEFAULT_RULES_FILE = paths.RULES_FILE


def _write_json_atomic(path: Path, data: object) -> None:
    if not path.parent.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.stem}-", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


class Store:
    def __init__(
        self,
        path: Path = DEFAULT_WORKERS_FILE,
        rules_path: Path = DEFAULT_RULES_FILE,
    ):
        self.path = path
        self.rules_path = rules_path

    # ------------------------------------------------------------ workers
    def load(self) -> Tuple[List[Worker], Optional[str]]:
        """Returns (workers, error). error is set when the file exists but could not be read/parsed."""
        if not self.path.exists():
            return [], None
        try:
            with open(self.path, encoding="utf-8") as f:
                raw = json.load(f)
            from .model import normalize_workers
            return normalize_workers(raw), None
        except (json.JSONDecodeError, OSError) as exc:
            return [], str(exc)

    def save(self, workers: List[Worker]) -> None:
        data = {"workers": [w.to_dict() for w in workers]}
        _write_json_atomic(self.path, data)

    # ------------------------------------------------------- global rules
    def load_global_rules(self) -> Tuple[List[Rule], Optional[str]]:
        if not self.rules_path.exists():
            return [], None
        try:
            with open(self.rules_path, encoding="utf-8") as f:
                raw = json.load(f)
        except (json.JSONDecodeError, OSError) as exc:
            return [], str(exc)
        items = raw.get("rules", []) if isinstance(raw, dict) else []
        rules = [Rule.from_dict(r) for r in items if isinstance(r, dict)]
        return rules, None

    def save_global_rules(self, rules: List[Rule]) -> None:
        _write_json_atomic(self.rules_path, {"rules": [r.to_dict() for r in rules]})
