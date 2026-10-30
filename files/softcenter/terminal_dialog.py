import codecs
import fcntl
import os
import pty
import re
import signal
import struct
import termios

from PyQt6.QtCore import QSocketNotifier, Qt, pyqtSignal as Signal
from PyQt6.QtGui import QColor, QFont, QTextCharFormat, QTextCursor
from PyQt6.QtWidgets import (QDialog, QHBoxLayout, QLabel, QLineEdit,
                               QPlainTextEdit, QPushButton, QVBoxLayout)

from .common import sh
from .pacbar import PacBar

COLS, ROWS = 110, 30
LOCK_FILE = "/var/lib/pacman/db.lck"
LOCK_RX = re.compile(r"db\.lck|Datenbank nicht sperren|Datenbank konnte nicht gesperrt|unable to lock database", re.I)
# Token: CSI-Sequenz | sonstige Escape-Sequenz | Steuerzeichen | normaler Text
# Fortschritt aus der pacman-Ausgabe: "( 3/12) installing foo [####]" bzw. deutsch "… wird installiert"
OP_LINE = re.compile(r"\(\s*(\d+)/(\d+)\)\s+([^\r\n]*)")
OP_VERB = re.compile(r"\b(installing|upgrading|removing|reinstalling|downgrading|installier\w*|aktualisier\w*|entfern\w*|wird (?:installiert|aktualisiert|entfernt))", re.I)
# Bauphasen von makepkg (AUR): "==> Erstelle Paket: php85 8.5.9-2", "==> Starte build()…", "==> Empfange Quellen …"
BUILD_PKG = re.compile(r"==>\s*(?:Making package|Erstelle Paket):\s*(\S+)")
BUILD_PHASE = re.compile(r"==>\s*(?:(?:Starting|Starte)\s+(prepare|build|check|package)\(\)|"
                         r"(Retrieving sources|Empfange Quellen|Extracting sources|Entpacke Quellen|Validating|Überprüfe))", re.I)
# Flatpak: "Installiere 3/8 … ████ 62% 69,1 KB/s" bzw. englisch "Installing 3/8… 62%"
FLATPAK_LINE = re.compile(r"(?:Installiere|Installing|Aktualisiere|Updating|Deinstalliere|Uninstalling)\s+(\d+)/(\d+)[^\r\n]*?(\d+)%")
PHASE_DE = {"prepare": "bereitet vor", "build": "kompiliert – das kann dauern", "check": "führt die Tests aus",
            "package": "packt das Paket", "src": "holt die Quellen"}
TOKEN = re.compile(r"\x1b\[([0-9;?]*)([ -/]*[@-~])|\x1b[\]PX^_].*?(?:\x07|\x1b\\)|\x1b[@-Z\\-_]|[\r\n\b\x07]|[^\x1b\r\n\b\x07]+")
ANSI = {0: "#000000", 1: "#cc3333", 2: "#33cc33", 3: "#cccc33", 4: "#3399ff", 5: "#cc33cc", 6: "#33cccc", 7: "#d0d0d0"}
ANSI_BRIGHT = {0: "#666666", 1: "#ff5555", 2: "#55ff55", 3: "#ffff55", 4: "#66b3ff", 5: "#ff77ff", 6: "#55ffff", 7: "#ffffff"}
DEFAULT_FG = "#d0d0d0"


class TerminalDialog(QDialog):
    """Führt einen Shell-Befehl in einem Pseudo-Terminal aus und zeigt die Ausgabe im Fenster."""
    finished_cmd = Signal(int)
    rerun = Signal(str)          # Befehl nach dem Entfernen einer verwaisten Sperre erneut ausführen

    def __init__(self, cmd, title="Terminal", parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self._cmd = cmd
        self.resize(900, 520)
        self._pid = None
        self._fd = None
        self._notifier = None
        self._decoder = codecs.getincrementaldecoder("utf-8")("replace")
        self._fmt = self._default_format()

        self.view = QPlainTextEdit(self)
        self.view.setReadOnly(True)
        self.view.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.view.setMaximumBlockCount(5000)
        font = QFont("monospace")
        font.setStyleHint(QFont.StyleHint.Monospace)
        font.setPointSize(10)
        self.view.setFont(font)
        self.view.setStyleSheet("QPlainTextEdit { background-color: #0b0b0b; color: %s; }" % DEFAULT_FG)

        self._cursor = self.view.textCursor()

        self.lbl = QLabel("Eingabe:", self)
        self.input = QLineEdit(self)
        self.input.returnPressed.connect(self._send_line)
        self.btn_stop = QPushButton("Abbrechen (Strg+C)", self)
        self.btn_stop.clicked.connect(self._interrupt)
        self.btn_close = QPushButton("Schließen", self)
        self.btn_close.clicked.connect(self.close)
        # Enter im Eingabefeld darf keinen Button auslösen (sonst sendet "Abbrechen" Strg+C)
        for b in (self.btn_stop, self.btn_close):
            b.setAutoDefault(False)
            b.setDefault(False)

        row = QHBoxLayout()
        row.addWidget(self.lbl)
        row.addWidget(self.input, 1)
        row.addWidget(self.btn_stop)
        row.addWidget(self.btn_close)
        # Pac-Man zeigt den Fortschritt (pacman-Schritt n von m) bzw. jagt die Geister, wenn die Dauer unbekannt ist
        self.bar = PacBar()
        self.bar.setRange(0, 0)
        self.bar.set_mode("run")
        self.state = QLabel("Starte …", self)
        self.state.setObjectName("status")
        self._pbuf = ""
        self._pkg = ""
        self._stops = 0
        lay = QVBoxLayout(self)
        lay.addWidget(self.bar)
        lay.addWidget(self.state)
        # Hinweis bei gesperrter pacman-Datenbank (nur sichtbar, wenn nötig)
        self.hint = QLabel("", self)
        self.hint.setWordWrap(True)
        self.hint.hide()
        self.hint_btn = QPushButton("", self)
        self.hint_btn.hide()
        lay.addWidget(self.hint)
        lay.addWidget(self.hint_btn, 0, Qt.AlignmentFlag.AlignLeft)
        lay.addWidget(self.view, 1)
        lay.addLayout(row)

        self._start(cmd)

    # --- Prozess ---
    def _start(self, cmd):
        pid, fd = pty.fork()
        if pid == 0:  # Kindprozess
            os.environ["TERM"] = "xterm-256color"
            os.environ["COLUMNS"] = str(COLS)
            os.environ["LINES"] = str(ROWS)
            try:
                os.execvp("bash", ["bash", "-c", cmd])
            finally:
                os._exit(127)
        fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", ROWS, COLS, 0, 0))
        self._pid, self._fd = pid, fd
        self.btn_close.setEnabled(False)
        self.input.setFocus()
        self._notifier = QSocketNotifier(fd, QSocketNotifier.Type.Read, self)
        self._notifier.activated.connect(self._on_readable)

    def _on_readable(self):
        try:
            data = os.read(self._fd, 65536)
        except OSError:
            data = b""
        if not data:
            self._finish()
            return
        text = self._decoder.decode(data)
        self._feed(text)
        self._progress(text)
        # Passwortabfrage erkennen: Terminal hat ECHO ausgeschaltet
        try:
            echo = bool(termios.tcgetattr(self._fd)[3] & termios.ECHO)
        except termios.error:
            echo = True
        self.input.setEchoMode(QLineEdit.EchoMode.Normal if echo else QLineEdit.EchoMode.Password)

    def _finish(self):
        self._notifier.setEnabled(False)
        try:
            _, status = os.waitpid(self._pid, 0)
            code = os.waitstatus_to_exitcode(status)
        except ChildProcessError:
            code = -1
        os.close(self._fd)
        self._fd = None
        self._pid = None
        self._feed("\r\n\x1b[1m[Beendet mit Exit-Code %d]\x1b[0m\r\n" % code)
        self.bar.set_mode("clear" if code == 0 else "over")
        self.state.setText("Fertig" if code == 0 else "Beendet mit Fehler (Exit-Code %d)" % code)
        if code != 0:
            self._check_lock()
        self.input.setEnabled(False)
        self.btn_stop.setEnabled(False)
        self.btn_close.setEnabled(True)
        self.btn_close.setFocus()
        self.finished_cmd.emit(code)

    def _progress(self, text):
        """Liest aus dem Ausgabestrom, welcher Paketschritt gerade läuft, und bewegt Pac-Man entsprechend."""
        self._pbuf = (self._pbuf + text)[-600:]
        last = None
        for m in OP_LINE.finditer(self._pbuf):
            if OP_VERB.search(m.group(3)):
                last = m
        # Bauphase (AUR): was zuletzt kam, gilt – beim Kompilieren erscheinen lange keine pacman-Zeilen mehr
        build = None
        for m in BUILD_PHASE.finditer(self._pbuf):
            build = m
        for m in BUILD_PKG.finditer(self._pbuf):
            self._pkg = m.group(1)
        flat = None
        for m in FLATPAK_LINE.finditer(self._pbuf):
            flat = m
        if flat is not None and (last is None or flat.start() > last.start()) and (build is None or flat.start() > build.start()):
            n, total, pct = int(flat.group(1)), max(1, int(flat.group(2))), min(100, int(flat.group(3)))
            self.bar.setRange(0, total * 100)
            self.bar.setValue((n - 1) * 100 + pct)
            self.state.setText("Flatpak %d/%d · %d %%" % (n, total, pct))
            return
        if build is not None and (last is None or build.start() > last.start()):
            phase = (build.group(1) or "src").lower()
            self.bar.setRange(0, 0)
            self.state.setText("Baut %s – %s" % (self._pkg or "Paket", PHASE_DE[phase]))
            return
        if last is None:
            return
        n, total = int(last.group(1)), int(last.group(2))
        what = last.group(3).split("[")[0].strip()          # Fortschrittsbalken abschneiden
        self.bar.setRange(0, total)
        self.bar.setValue(n)
        self.state.setText("%d/%d · %s" % (n, total, what[:90]))

    def _check_lock(self):
        """Scheitert der Befehl an der pacman-Sperre: prüfen, ob noch ein pacman läuft, und passend helfen."""
        if not LOCK_RX.search(self.view.toPlainText()[-3000:]):
            return
        running = sh("pgrep", "-x", "pacman").stdout.split()
        self.hint.show()
        if running:
            self.hint.setText("Ein anderer pacman läuft noch (Prozess %s). Warte, bis er fertig ist, und starte den Befehl dann erneut." % ", ".join(running))
            self.hint_btn.setText("Erneut versuchen")
            self.hint_btn.clicked.connect(lambda: self.rerun.emit(self._cmd))
        else:
            self.hint.setText("Die Datenbank ist gesperrt, aber es läuft kein pacman: Die Sperre ist verwaist (z. B. nach einem abgebrochenen "
                              "Vorgang) und kann gefahrlos entfernt werden.")
            self.hint_btn.setText("Verwaiste Sperre entfernen")
            self.hint_btn.clicked.connect(self._remove_lock)
        self.hint_btn.show()

    def _remove_lock(self):
        if sh("pgrep", "-x", "pacman").returncode == 0:        # nochmal prüfen: nie eine Sperre löschen, die jemand hält
            self.hint.setText("Inzwischen läuft ein pacman – die Sperre wird nicht entfernt.")
            return
        r = sh("pkexec", "rm", "-f", LOCK_FILE)
        self.hint_btn.clicked.disconnect()
        if r.returncode:
            self.hint.setText("Entfernen fehlgeschlagen: %s" % ((r.stderr or "abgebrochen").strip()[:120]))
            self.hint_btn.hide()
            return
        self.hint.setText("✓ Sperre entfernt. Du kannst den Befehl jetzt erneut ausführen.")
        self.hint_btn.setText("Befehl erneut ausführen")
        self.hint_btn.clicked.connect(lambda: self.rerun.emit(self._cmd))

    def _send_line(self):
        if self._fd is not None:
            os.write(self._fd, (self.input.text() + "\n").encode())
            self.input.clear()

    def _interrupt(self):
        """1. Klick: Strg+C. Weitere Klicks: SIGTERM an die Prozessgruppe (sudo reicht es an pacman weiter).
        Bewusst kein SIGKILL: das könnte einen Prozess hinterlassen, der als root weiterläuft."""
        if self._fd is None:
            return
        self._stops += 1
        if self._stops == 1:
            os.write(self._fd, b"\x03")
            self.btn_stop.setText("Beenden erzwingen")
            self.state.setText("Abbruch gesendet (Strg+C) …")
        else:
            try:
                os.killpg(self._pid, signal.SIGTERM)
            except OSError:
                pass
            self.state.setText("Beenden angefordert (SIGTERM) …")

    # --- Ausgabe (einfacher ANSI-Interpreter) ---
    def _default_format(self):
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(DEFAULT_FG))
        return fmt

    def _feed(self, text):
        cur = self._cursor
        for m in TOKEN.finditer(text):
            tok = m.group(0)
            if m.group(2) is not None:
                self._csi(cur, m.group(1), m.group(2))
            elif tok == "\r":
                cur.movePosition(QTextCursor.MoveOperation.StartOfBlock)
            elif tok == "\n":
                cur.movePosition(QTextCursor.MoveOperation.EndOfBlock)
                cur.insertBlock()
            elif tok == "\b":
                cur.movePosition(QTextCursor.MoveOperation.Left)
            elif tok[0] == "\x1b" or tok == "\x07":
                pass
            else:
                # Überschreiben statt Einfügen, damit "\r"-Fortschrittsbalken funktionieren
                n = min(len(tok), cur.block().length() - 1 - cur.positionInBlock())
                if n > 0:
                    cur.movePosition(QTextCursor.MoveOperation.Right, QTextCursor.MoveMode.KeepAnchor, n)
                    cur.removeSelectedText()
                cur.insertText(tok, self._fmt)
        self.view.setTextCursor(cur)
        self.view.ensureCursorVisible()

    def _csi(self, cur, params, final):
        if final == "m":
            codes = [int(p) if p.isdigit() else 0 for p in params.split(";")] if params else [0]
            i = 0
            while i < len(codes):
                c = codes[i]
                if c == 0:
                    self._fmt = self._default_format()
                elif c == 1:
                    self._fmt.setFontWeight(QFont.Weight.Bold)
                elif c == 22:
                    self._fmt.setFontWeight(QFont.Weight.Normal)
                elif 30 <= c <= 37:
                    self._fmt.setForeground(QColor(ANSI[c - 30]))
                elif 90 <= c <= 97:
                    self._fmt.setForeground(QColor(ANSI_BRIGHT[c - 90]))
                elif c == 39:
                    self._fmt.setForeground(QColor(DEFAULT_FG))
                elif c in (38, 48):  # 256-Farben / RGB: Parameter überspringen
                    i += 2 if i + 1 < len(codes) and codes[i + 1] == 5 else 4
                i += 1
        elif final == "K":  # Zeilenrest löschen
            cur.movePosition(QTextCursor.MoveOperation.EndOfBlock, QTextCursor.MoveMode.KeepAnchor)
            cur.removeSelectedText()
        elif final == "G":  # Spalte setzen
            col = int(params) - 1 if params.isdigit() else 0
            cur.movePosition(QTextCursor.MoveOperation.StartOfBlock)
            cur.movePosition(QTextCursor.MoveOperation.Right, QTextCursor.MoveMode.MoveAnchor, min(col, cur.block().length() - 1))
        elif final == "C":  # Cursor nach rechts
            cur.movePosition(QTextCursor.MoveOperation.Right, QTextCursor.MoveMode.MoveAnchor, int(params) if params.isdigit() else 1)
        elif final == "D":  # Cursor nach links
            cur.movePosition(QTextCursor.MoveOperation.Left, QTextCursor.MoveMode.MoveAnchor, int(params) if params.isdigit() else 1)

    # --- Schließen ---
    def closeEvent(self, event):
        if self._pid is not None:
            try:
                os.killpg(self._pid, signal.SIGTERM)
            except OSError:
                pass
            self._finish()
        super().closeEvent(event)

    def reject(self):
        # Esc nicht während des Laufs akzeptieren
        if self._pid is None:
            super().reject()
