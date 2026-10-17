from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

RED_FILL = QColor("#b71c1c")
RED_PARTIAL = QColor("#e57373")


class SlotReasonsDialog(QDialog):
    """Explains why each worker is or isn't on one schedule slot."""

    def __init__(self, parent, title: str, rows: list[tuple[str, str]], need_text: str):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(420)
        layout = QVBoxLayout(self)
        if need_text:
            layout.addWidget(QLabel(need_text))
        for name, reason in rows:
            row = QHBoxLayout()
            worker_label = QLabel(name)
            worker_label.setMinimumWidth(90)
            reason_label = QLabel(reason)
            reason_label.setWordWrap(True)
            reason_label.setStyleSheet("color:#555;")
            row.addWidget(worker_label)
            row.addWidget(reason_label, 1)
            layout.addLayout(row)
        close_btn = QPushButton("סגור")
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn)


class ScheduleWindow(QWidget):
    """Displays the weekly schedule: days x shifts, one worker per slot.

    The assignment logic will populate `entries` (day -> shift -> worker).
    """

    def __init__(
        self,
        days: list[str],
        shifts: dict[str, str],
        entries=None,
        parent=None,
        explainer=None,
    ):
        super().__init__(parent)
        self.setWindowFlag(Qt.WindowType.Window)
        self.days = days
        self.shifts = shifts
        self.shift_names = list(shifts)
        self.explainer = explainer
        # problem slots by (day, shift) -> reason (set in set_report)
        self._problems: dict[tuple[str, str], str] = {}
        # entries[day][shift] -> assignment (list of worker names)
        self.entries = entries or {}

        self.setWindowTitle("סידור העבודה")
        self.setMinimumSize(760, 480)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("סידור עבודה שבועי"))

        self.table = QTableWidget(len(self.shift_names), len(self.days))
        self.table.setHorizontalHeaderLabels(self.days)
        self.table.setVerticalHeaderLabels(
            [f"{s}\n({self.shifts[s]})" for s in self.shift_names]
        )
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setMinimumWidth(140)
        self.table.verticalHeader().setDefaultSectionSize(64)
        self.table.cellClicked.connect(self._on_cell_clicked)

        for r, shift in enumerate(self.shift_names):
            for c, day in enumerate(self.days):
                assigned = self.entries.get(day, {}).get(shift)
                item = QTableWidgetItem(assigned or "")
                item.setFlags(Qt.ItemFlag.ItemIsEnabled)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.table.setItem(r, c, item)
        layout.addWidget(self.table)
        self._status = QLabel("")
        self._status.setWordWrap(True)
        layout.addWidget(self._status)

    def _on_cell_clicked(self, row: int, column: int) -> None:
        day, shift = self.days[column], self.shift_names[row]
        reason = self._problems.get((day, shift))
        if reason is None:
            return
        if self.explainer is None:
            QMessageBox.information(self, f"{day} {shift}", reason)
            return
        rows = self.explainer(day, shift)
        current = self.entries.get(day, {}).get(shift) or "—"
        dialog = SlotReasonsDialog(
            self,
            title=f"{day} {shift} – מצב שיבוץ",
            rows=rows,
            need_text=f"מצב: {reason}  |  שיבוץ נוכחי: {current}",
        )
        dialog.exec()

    def _cell_item(self, day: str, shift: str) -> QTableWidgetItem | None:
        r = self.shift_names.index(shift) if shift in self.shift_names else -1
        c = self.days.index(day) if day in self.days else -1
        if r < 0 or c < 0:
            return None
        return self.table.item(r, c)

    def set_report(self, result) -> None:
        # reset styling from previous runs
        for r in range(self.table.rowCount()):
            for c in range(self.table.columnCount()):
                item = self.table.item(r, c)
                item.setBackground(self.palette().window().color())
                item.setForeground(self.palette().color(self.foregroundRole()))
                item.setToolTip("")
                if not (self.days[c] in self.entries
                        and self.shift_names[r] in self.entries[self.days[c]]):
                    item.setText("—")

        for day, shift, reason in result.unfilled:
            item = self._cell_item(day, shift)
            if item is None:
                continue
            self._problems[(day, shift)] = reason
            current = item.text()
            partial = current and current != "—"
            item.setBackground(RED_PARTIAL if partial else RED_FILL)
            item.setForeground(QColor("white"))
            if not partial:
                item.setText("—")
            item.setToolTip(reason + "\n(לחץ להסבר מלא)")

        lines: list[str] = []
        if result.unfilled:
            lines.append(f"משמרות לא משובצות: {len(result.unfilled)}")
            for day, shift, reason in result.unfilled[:6]:
                lines.append(f"   {day} {shift} – {reason}")
            if len(result.unfilled) > 6:
                lines.append("   ...")
        if result.warnings:
            lines.append("הערות:")
            lines.extend(f"• {w}" for w in result.warnings[:12])
            if len(result.warnings) > 12:
                lines.append("• ...")
        self._status.setText("\n".join(lines) if lines else "הסידור מלא – אין הערות")
