from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ..model import Rule
from ..rules import rule_types_for_scope

PRIO_LABELS = {1: "try – מנסה", 2: "must – חובה"}
MUST = 2


class _ShiftCountsRow(QWidget):
    """A labeled spinbox for one shift inside a counts-param rule."""

    def __init__(self, shift: str, times: str, value: int, on_changed):
        super().__init__()
        self._on_changed = on_changed
        layout = QHBoxLayout(self)
        layout.setContentsMargins(24, 0, 24, 0)
        layout.addWidget(QLabel(f"{shift} ({times}):"))
        self.spin = QSpinBox()
        self.spin.setRange(0, 21)
        self.spin.setValue(int(value))
        self.spin.valueChanged.connect(self._emit)
        layout.addWidget(self.spin)
        layout.addStretch()

    def _emit(self, *_) -> None:
        if callable(self._on_changed):
            self._on_changed()


class RuleWidget(QWidget):
    """One editable rule row.

    For plain params rules: [checkbox] [type] [n] [priority] [−]
    For "counts" map rules: additionally a sub-row with one spinbox per shift.
    """

    def __init__(self, rule: Rule, scope: str, on_delete, shifts: dict[str, str]):
        super().__init__()
        self.rule = rule
        self.shifts = shifts
        self._on_delete = on_delete
        self._initializing = True

        outer = QVBoxLayout(self)
        outer.setContentsMargins(4, 2, 4, 2)
        outer.setSpacing(2)

        layout = QHBoxLayout()
        self.types = rule_types_for_scope(scope)
        self.enabled = QCheckBox()
        self.enabled.setChecked(rule.enabled)
        layout.addWidget(self.enabled)

        self.type_box = QComboBox()
        for rt in self.types:
            self.type_box.addItem(rt.label, rt.key)
        layout.addWidget(self.type_box)

        self.param_spin = QSpinBox()
        self.param_spin.setRange(0, 21)
        layout.addWidget(self.param_spin)

        self.prio_box = QComboBox()
        for prio, label in PRIO_LABELS.items():
            self.prio_box.addItem(label, prio)
        layout.addWidget(self.prio_box)

        del_btn = QPushButton("−")
        del_btn.setFixedWidth(30)
        del_btn.clicked.connect(lambda: self._on_delete(self))
        layout.addWidget(del_btn)
        layout.addStretch()
        outer.addLayout(layout)

        self._counts_spinners: list[_ShiftCountsRow] = []
        self._counts_row = QWidget()
        counts_layout = QVBoxLayout(self._counts_row)
        counts_layout.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self._counts_row)

        index = max(0, self.type_box.findData(rule.type))
        self.type_box.setCurrentIndex(index)
        self.param_spin.setValue(int(rule.params.get("n", self._default_param())))
        self.prio_box.setCurrentIndex(0 if rule.priority == 1 else 1)
        self._rebuild_counts_spinners()

        self.enabled.stateChanged.connect(self._collect)
        self.type_box.currentIndexChanged.connect(self._on_type_changed)
        self.param_spin.valueChanged.connect(self._collect)
        self.prio_box.currentIndexChanged.connect(self._collect)
        self._initializing = False
        self._collect()

    def _default_param(self) -> int:
        rt = self._current_type()
        return int(rt.params.get("n", 0)) if rt.params else 0

    def _current_type(self):
        return self.types[self.type_box.currentIndex()]

    def _is_counts_rule(self) -> bool:
        return "counts" in self._current_type().params

    def _rebuild_counts_spinners(self) -> None:
        for row in self._counts_spinners:
            row.setParent(None)
            row.deleteLater()
        self._counts_spinners = []
        self._counts_row.setVisible(self._is_counts_rule())
        self.param_spin.setVisible(not self._is_counts_rule())
        if not self._is_counts_rule():
            return
        counts = dict(self.rule.params.get("counts", {}))
        for shift, times in self.shifts.items():
            row = _ShiftCountsRow(
                shift, times, counts.get(shift, 1), self._collect
            )
            self._counts_spinners.append(row)
            self._counts_row.layout().addWidget(row)

    def _on_type_changed(self) -> None:
        if self._initializing:
            return
        self.param_spin.setValue(self._default_param())
        self._rebuild_counts_spinners()
        self._collect()

    def _collect(self) -> None:
        if self._initializing:
            return
        rt = self._current_type()
        self.rule.type = rt.key
        self.rule.enabled = self.enabled.isChecked()
        self.rule.priority = self.prio_box.currentData() or 1
        if self._is_counts_rule():
            counts = {s: r.spin.value() for s, r in zip(self.shifts, self._counts_spinners)}
            self.rule.params = {"counts": counts}
        elif rt.params:
            self.rule.params = {"n": self.param_spin.value()}
        else:
            self.rule.params = {}


class RulesDialog(QDialog):
    """Edit a list of rules for a given scope ("worker" | "global")."""

    def __init__(
        self,
        parent,
        title: str,
        rules: list[Rule],
        scope: str,
        shifts: dict[str, str] | None = None,
    ):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.scope = scope
        self.shifts = shifts or {}
        self._rows: list[RuleWidget] = []

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("כללים – סוג, פרמטר ועדיפות (1=מנסה, 2=חובה):"))

        self.rows_layout = QVBoxLayout()
        layout.addLayout(self.rows_layout)

        add_btn = QPushButton("+ הוסף כלל")
        add_btn.clicked.connect(self._add_rule)
        ok_btn = QPushButton("אישור")
        ok_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton("בטל")
        cancel_btn.clicked.connect(self.reject)
        btns = QHBoxLayout()
        btns.addWidget(add_btn)
        btns.addWidget(ok_btn)
        btns.addWidget(cancel_btn)
        btns.addStretch()
        layout.addLayout(btns)

        for rule in rules:
            self._add_row(Rule.from_dict(rule.to_dict()))

    def _add_rule(self) -> None:
        types = rule_types_for_scope(self.scope)
        if not types:
            return
        index = len(self._rows)
        current_keys = {row.rule.type for row in self._rows}
        unused = [rt for rt in types if rt.key not in current_keys]
        chosen = (unused or [types[index % len(types)]])[0]
        self._add_row(Rule(type=chosen.key, params=dict(chosen.params)))

    def _add_row(self, rule: Rule) -> None:
        row = RuleWidget(
            rule, self.scope, on_delete=self._remove_row, shifts=self.shifts
        )
        self._rows.append(row)
        self.rows_layout.addWidget(row)

    def _remove_row(self, row: RuleWidget) -> None:
        self._rows.remove(row)
        self.rows_layout.removeWidget(row)
        row.deleteLater()

    def rules_out(self) -> list[Rule]:
        """Collect rows, de-duplicated by type (a type must appear once).

        Params/enabled come from the last row of that type; priority
        escalates to must if any row of that type was must.
        """
        merged: dict[str, Rule] = {}
        order: list[str] = []
        for row in self._rows:
            row._collect()
            key = row.rule.type
            if not key:
                continue
            if key in merged:
                kept = merged[key]
                if row.rule.priority == MUST and kept.priority != MUST:
                    kept.priority = MUST
                kept.params = row.rule.params
                kept.enabled = row.rule.enabled
            else:
                merged[key] = row.rule
                order.append(key)
        return [merged[k] for k in order]
