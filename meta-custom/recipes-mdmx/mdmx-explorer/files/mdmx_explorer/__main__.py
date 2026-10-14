"""Entry point. Nuitka compiles this via pysidedeploy.spec's `main_file`."""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from .mainwindow import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("mdmx-explorer")
    app.setDesktopFileName("mdmx-explorer")
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
