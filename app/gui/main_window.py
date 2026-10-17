from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..config import load_config
from ..model import Rule, Worker
from ..storage import Store
from .rules_dialog import RulesDialog

BG_NORMAL = QColor("#eceff1")
BG_TRY = QColor("#ffd54f")
TXT_NORMAL = "#37474f"


class NameDialog(QDialog):
    """Modal dialog that returns a worker name or None (cancelled)."""

    def __init__(self, parent, title: str, prompt: str, validate):
        super().__init__(parent)
        self.result_name: Optional[str] = None
        self._validate = validate

        self.setWindowTitle(title)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(prompt))
        self.entry = QLineEdit()
        self.entry.setAlignment(Qt.AlignmentFlag.AlignRight)
        layout.addWidget(self.entry)

        buttons = QHBoxLayout()
        ok = QPushButton("אישור")
        cancel = QPushButton("בטל")
        ok.clicked.connect(self._confirm)
        cancel.clicked.connect(self.reject)
        buttons.addWidget(ok)
        buttons.addWidget(cancel)
        layout.addLayout(buttons)

        self.error_label = QLabel("")
        self.error_label.setStyleSheet("color: #c62828;")
        layout.addWidget(self.error_label)

        self.entry.textChanged.connect(lambda _: self.error_label.setText(""))
        ok.setDefault(True)
        self.entry.setFocus()

    def _confirm(self) -> None:
        name = self.entry.text().strip()
        if not name:
            self.error_label.setText("צריך להזין שם לא ריק.")
            return
        if self._validate:
            err = self._validate(name)
            if err:
                self.error_label.setText(err)
                return
        self.result_name = name
        self.accept()


class MainApp(QWidget):
    def __init__(self, store: Store) -> None:
        super().__init__()
        self.store = store
        self.workers: list[Worker] = []
        self.current_worker: Worker | None = None
        self.schedule_window = None

        self.days, self.shifts = load_config()
        self.shift_names = list(self.shifts)

        self.setWindowTitle("מערכת סידור עבודה")
        self.setMinimumSize(780, 520)

        self._build_ui()
        self._build_table()
        self._reload_workers()

    # ------------------------------------------------------------------ UI
    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        top = QHBoxLayout()
        self.add_btn = QPushButton("+ הוסף עובד")
        self.delete_btn = QPushButton("− מחק עובד")
        self.rules_btn = QPushButton("כללים עובד")
        self.global_rules_btn = QPushButton("כללים גלובליים")
        self.schedule_btn = QPushButton("צור סידור")
        self.add_btn.clicked.connect(self.add_worker)
        self.delete_btn.clicked.connect(self.delete_worker)
        self.rules_btn.clicked.connect(self.edit_worker_rules)
        self.global_rules_btn.clicked.connect(self.edit_global_rules)
        self.schedule_btn.clicked.connect(self.open_schedule)
        top.addWidget(QLabel("עובדים:"))
        for b in (
            self.add_btn,
            self.delete_btn,
            self.rules_btn,
            self.global_rules_btn,
            self.schedule_btn,
        ):
            top.addWidget(b)
        top.addStretch()
        layout.addLayout(top)

        splitter = QSplitter(self)
        splitter.setChildrenCollapsible(False)

        list_panel = QWidget()
        list_col = QVBoxLayout()
        list_col.setContentsMargins(0, 0, 0, 0)
        list_col.addWidget(QLabel("רשימת עובדים"))
        self.listbox = QListWidget()
        self.listbox.itemSelectionChanged.connect(self.on_worker_selected)
        self.listbox.setMinimumWidth(80)
        list_col.addWidget(self.listbox)
        list_panel.setLayout(list_col)

        grid_panel = QWidget()
        grid_col = QVBoxLayout()
        grid_col.setContentsMargins(0, 0, 0, 0)
        legend = QLabel(
            "זמינות שבועית – לחץ לסימון   "
            '(אפור=סגור, בהיר=רגיל, צהוב="נסה לשבץ")'
        )
        legend.setStyleSheet("color: #555;")
        grid_col.addWidget(legend)
        self.table = QTableWidget(len(self.shift_names), len(self.days))
        grid_col.addWidget(self.table)
        grid_panel.setLayout(grid_col)

        # RTL layout: first child goes on the right
        splitter.addWidget(list_panel)
        splitter.addWidget(grid_panel)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([170, 730])
        layout.addWidget(splitter, 1)

        self.status = QLabel("")
        self.status.setStyleSheet("color: #555;")
        layout.addWidget(self.status)

    def _build_table(self) -> None:
        t = self.table
        t.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        t.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        t.setHorizontalHeaderLabels(self.days)
        t.setVerticalHeaderLabels(
            [f"{s}\n({self.shifts[s]})" for s in self.shift_names]
        )
        t.verticalHeader().setDefaultSectionSize(64)
        t.verticalHeader().setMinimumWidth(140)
        for r in range(t.rowCount()):
            for c in range(t.columnCount()):
                item = QTableWidgetItem()
                item.setText("—")
                item.setFlags(Qt.ItemFlag.ItemIsEnabled)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                item.setBackground(self.palette().window().color())
                item.setForeground(QColor("#90a4ae"))
                t.setItem(r, c, item)
        t.cellClicked.connect(self._on_cell_clicked)
        t.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        t.customContextMenuRequested.connect(self._on_cell_right_clicked)

    # ------------------------------------------------------------ workers
    def _reload_workers(self, select_name: str | None = None) -> None:
        self.workers, error = self.store.load()
        if error:
            QMessageBox.critical(
                self, "שגיאה", f"לא ניתן לטעון את הקובץ:\n{self.store.path}\n\n{error}"
            )
        self.listbox.blockSignals(True)
        self.listbox.clear()
        for w in self.workers:
            self.listbox.addItem(w.name)
        row = None
        for i, w in enumerate(self.workers):
            if select_name and w.name == select_name:
                row = i
                break
        if row is None and self.workers:
            row = 0
        if row is not None:
            self.listbox.setCurrentRow(row)
        self.listbox.blockSignals(False)
        self.on_worker_selected()

    def add_worker(self) -> None:
        def validate(name: str) -> str | None:
            if any(w.name == name for w in self.workers):
                return "עובד בשם זה כבר קיים."
            return None

        dialog = NameDialog(self, "הוסף עובד", "שם העובד:", validate)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        name = dialog.result_name
        self.workers.append(Worker(name=name))
        self.save_all(quiet=True)
        self._reload_workers(select_name=name)
        self._set_status(f"נוסף עובד: {name}")

    def delete_worker(self) -> None:
        if self.current_worker is None:
            QMessageBox.information(self, "מחיקת עובד", "בחר עובד מהרשימה קודם.")
            return
        name = self.current_worker.name
        if QMessageBox.question(self, "מחיקת עובד", f"למחוק את {name}?") != \
                QMessageBox.StandardButton.Yes:
            return
        self.workers = [w for w in self.workers if w is not self.current_worker]
        self.current_worker = None
        self.save_all(quiet=True)
        self._reload_workers()
        self._set_status(f"נמחק עובד: {name}")

    def on_worker_selected(self) -> None:
        row = self.listbox.currentRow()
        if 0 <= row < len(self.workers):
            self.current_worker = self.workers[row]
        else:
            self.current_worker = None
        self._refresh_cells()

    # --------------------------------------------------------------- grid
    def _on_cell_clicked(self, row: int, column: int) -> None:
        if self.current_worker is None:
            QMessageBox.information(
                self, "סימון זמינות", "בחר עובד מהרשימה קודם (או הוסף עובד חדש)."
            )
            return
        day = self.days[column]
        shift = self.shift_names[row]
        self.current_worker.toggle(day, shift)
        self._refresh_cells()
        self.save_all(quiet=True)
        self._set_status(f"שינוי נשמר אוטומטית ({self.store.path.name})")

    def _on_cell_right_clicked(self, pos) -> None:
        item = self.table.itemAt(pos)
        if item is None:
            return
        row = item.row()
        column = item.column()
        day = self.days[column]
        shift = self.shift_names[row]
        if self.current_worker is None:
            QMessageBox.information(
                self, "סימון זמינות", "בחר עובד מהרשימה קודם (או הוסף עובד חדש)."
            )
            return
        self.current_worker.clear(day, shift)
        self._refresh_cells()
        self.save_all(quiet=True)
        self._set_status(f"{self.current_worker.name} – {day} {shift} סומן לא זמין (נשמר)")

    def _refresh_cells(self) -> None:
        w = self.current_worker
        t = self.table
        for r in range(t.rowCount()):
            for c in range(t.columnCount()):
                item = t.item(r, c)
                day, shift = self.days[c], self.shift_names[r]
                if w is None or not w.is_available(day, shift):
                    item.setText("—")
                    item.setBackground(self.palette().window().color())
                    item.setForeground(QColor("#90a4ae"))
                    continue
                item.setForeground(QColor(TXT_NORMAL))
                if w.prefers(day, shift):
                    item.setText("try")
                    item.setBackground(BG_TRY)
                else:
                    item.setText("N")
                    item.setBackground(BG_NORMAL)

    # -------------------------------------------------------------- save
    def save_all(self, quiet: bool = False) -> None:
        try:
            self.store.save(self.workers)
        except OSError as exc:
            QMessageBox.critical(self, "שמירה נכשלה", str(exc))
            return
        if not quiet:
            self._set_status(f"נשמר ({len(self.workers)} עובדים) → {self.store.path}")
    def _set_status(self, text: str) -> None:
        self.status.setText(text)

    # --------------------------------------------------------------- rules
    def edit_worker_rules(self) -> None:
        if self.current_worker is None:
            QMessageBox.information(self, "כללים", "בחר עובד מהרשימה קודם.")
            return
        worker = self.current_worker
        dialog = RulesDialog(
            self,
            title=f"כללים לעובד: {worker.name}",
            rules=worker.rules,
            scope="worker",
        )
        if dialog.exec():
            worker.rules = dialog.rules_out()
            self.save_all(quiet=True)
            self._set_status(f"כללים נשמרו לעובד {worker.name}")

    def edit_global_rules(self) -> None:
        rules, error = self.store.load_global_rules()
        if error:
            QMessageBox.critical(self, "שגיאה", str(error))
            return
        dialog = RulesDialog(
            self,
            title="כללים גלובליים",
            rules=rules,
            scope="global",
            shifts=self.shifts,
        )
        if dialog.exec():
            self.store.save_global_rules(dialog.rules_out())
            self._set_status("כללים גלובליים נשמרו")

    def closeEvent(self, event) -> None:
        # always take the schedule window down with us — leaving it open can
        # stall exit waiting for a second top-level window's close protocol
        if self.schedule_window is not None:
            try:
                self.schedule_window.close()
                self.schedule_window.deleteLater()
            except RuntimeError:
                pass
            self.schedule_window = None
        super().closeEvent(event)

    # ------------------------------------------------------------- schedule
    def open_schedule(self) -> None:
        from ..solver import explain_slot, solve
        from .schedule_window import ScheduleWindow

        global_rules, error = self.store.load_global_rules()
        if error:
            QMessageBox.critical(self, "שגיאה", error)
            return
        result = solve(list(self.workers), list(self.days), self.shifts, global_rules)

        explainer = None
        if result.state:
            def explainer(day: str, shift: str) -> list[tuple[str, str]]:
                return explain_slot(
                    list(self.workers), list(self.days), self.shifts,
                    result.state, global_rules, day, shift,
                )

        if self.schedule_window is not None:
            self.schedule_window.close()
            self.schedule_window.deleteLater()
            self.schedule_window = None
        self.schedule_window = ScheduleWindow(
            list(self.days), self.shifts, entries=result.entries,
            parent=self, explainer=explainer,
        )
        self.schedule_window.set_report(result)
        self.schedule_window.show()
        self.schedule_window.raise_()
        self.schedule_window.activateWindow()
