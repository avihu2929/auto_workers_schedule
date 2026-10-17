from __future__ import annotations

import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from app.gui.main_window import MainApp
from app.storage import Store


def main() -> int:
    app = QApplication(sys.argv)
    app.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
    window = MainApp(store=Store())
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
