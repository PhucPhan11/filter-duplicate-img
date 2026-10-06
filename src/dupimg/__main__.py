"""Launch the GUI: python -m dupimg"""

from __future__ import annotations

import multiprocessing
import sys


def main() -> None:
    multiprocessing.freeze_support()  # needed for the hashing workers in a frozen .exe

    from PySide6.QtWidgets import QApplication

    from .ui.main_window import MainWindow

    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
