from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List


@dataclass(frozen=True)
class RuleType:
    key: str
    label: str                                    # displayed in the GUI
    scope: str                                    # "worker" | "global"
    params: Dict[str, object] = field(default_factory=dict)  # param name -> default


_registry: Dict[str, RuleType] = {}


def register(rule_type: RuleType) -> None:
    _registry[rule_type.key] = rule_type


def get_rule_type(key: str) -> RuleType | None:
    return _registry.get(key)


def all_rule_types() -> List[RuleType]:
    return list(_registry.values())


def rule_types_for_scope(scope: str) -> List[RuleType]:
    return [rt for rt in _registry.values() if rt.scope == scope]


register(RuleType(
    key="max_week_shifts",
    label="מקסימום משמרות בשבוע",
    scope="worker",
    params={"n": 4},
))
register(RuleType(
    key="max_week_days",
    label="מקסימום ימים בשבוע",
    scope="worker",
    params={"n": 4},
))
register(RuleType(
    key="min_week_shifts",
    label="מינימום משמרות בשבוע",
    scope="worker",
    params={"n": 3},
))
register(RuleType(
    key="min_workers_per_shift",
    label="מספר עובדים נדרש במשמרת",
    scope="global",
    params={"counts": {}},  # shift name -> required workers (defaults to 1)
))
register(RuleType(
    key="rest_shifts",
    label="מרווח הפסקה בין משמרות (משמרות)",
    scope="global",
    params={"n": 2},
))
register(RuleType(
    key="fairness",
    label="שוויון במשמרות בין עובדים",
    scope="global",
    params={},
))
