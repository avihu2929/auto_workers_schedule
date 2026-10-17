from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

# Cell priority in the availability grid: absent/0 = normal, 1 = try
PREFER = 1


@dataclass
class Rule:
    type: str
    priority: int = 1  # 1 = try (soft), 2 = must (hard)
    params: Dict[str, object] = field(default_factory=dict)
    enabled: bool = True

    def to_dict(self) -> dict:
        return {
            "type": self.type,
            "priority": self.priority,
            "params": self.params,
            "enabled": self.enabled,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Rule":
        return cls(
            type=data.get("type", ""),
            priority=int(data.get("priority", 1)),
            params=dict(data.get("params", {})),
            enabled=bool(data.get("enabled", True)),
        )


@dataclass
class Worker:
    name: str
    # day name -> list of shift names the worker is available for (hard constraint)
    availability: Dict[str, List[str]] = field(default_factory=dict)
    # day -> shift -> 1 (try); absent = 0 (normal preference weight)
    cell_priority: Dict[str, Dict[str, int]] = field(default_factory=dict)
    rules: List[Rule] = field(default_factory=list)

    def is_available(self, day: str, shift: str) -> bool:
        return shift in self.availability.get(day, [])

    def toggle(self, day: str, shift: str) -> None:
        """Cycle a cell: unavailable -> normal -> try -> unavailable."""
        slots = self.availability.setdefault(day, [])
        cell_priorities = self.cell_priority.setdefault(day, {})
        if shift not in slots:
            slots.append(shift)
            cell_priorities.pop(shift, None)
        elif cell_priorities.get(shift) != PREFER:
            cell_priorities[shift] = PREFER
        else:
            slots.remove(shift)
            cell_priorities.pop(shift, None)
            if not slots:
                del self.availability[day]
            if not cell_priorities:
                del self.cell_priority[day]

    def clear(self, day: str, shift: str) -> None:
        """Set a cell directly to unavailable."""
        slots = self.availability.get(day)
        if slots is not None:
            if shift in slots:
                slots.remove(shift)
            if not slots:
                del self.availability[day]
        cell_priorities = self.cell_priority.get(day)
        if cell_priorities is not None:
            cell_priorities.pop(shift, None)
            if not cell_priorities:
                del self.cell_priority[day]

    def prefers(self, day: str, shift: str) -> bool:
        return self.cell_priority.get(day, {}).get(shift) == PREFER

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "availability": self.availability,
            "cell_priority": self.cell_priority,
            "rules": [r.to_dict() for r in self.rules],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Worker":
        rules = [Rule.from_dict(r) for r in data.get("rules", []) if isinstance(r, dict)]
        return cls(
            name=data["name"],
            availability=data.get("availability", {}),
            cell_priority=data.get("cell_priority", {}),
            rules=rules,
        )


def normalize_workers(raw: object) -> List[Worker]:
    """Best-effort normalization of loaded JSON into Worker objects."""
    if not isinstance(raw, dict):
        return []
    items = raw.get("workers", [])
    if not isinstance(items, list):
        items = [items]
    workers: List[Worker] = []
    for item in items:
        if isinstance(item, dict) and isinstance(item.get("name"), str):
            workers.append(Worker.from_dict(item))
    return workers
