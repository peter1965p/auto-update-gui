"""Einstiegspunkt: QApplication, Theme und Hauptfenster."""
import sys

from PyQt6.QtGui import QPalette
from PyQt6.QtWidgets import QApplication

from . import common
from .common import apply_theme
from .window import MainWindow


def create(argv=None):
    """Baut App und Fenster, ohne die Ereignisschleife zu starten (auch für Tests)."""
    argv = sys.argv if argv is None else argv
    app = QApplication.instance() or QApplication(argv)
    app.setStyle("Fusion")
    app.setQuitOnLastWindowClosed(False)
    common.ORIG_PAL = QPalette(app.palette())
    apply_theme(app)
    return app, MainWindow(app)


def main(argv=None):
    argv = sys.argv if argv is None else argv
    app, win = create(argv)
    if "--tray" not in argv and "--no-show" not in argv:
        win.show()
    return app.exec()
