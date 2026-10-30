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

from .pacbar import PacBar

COLS, ROWS = 110, 30
# Token: CSI-Sequenz | sonstige Escape-Sequenz | Steuerzeichen | normaler Text
# Fortschritt aus der pacman-Ausgabe: "( 3/12) installing foo [####]" bzw. deutsch "… wird installiert"
OP_LINE = re.compile(r"\(\s*(\d+)/(\d+)\)\s+([^\r\n]*)")
OP_VERB = re.compile(r"\b(installing|upgrading|removing|reinstalling|downgrading|installier\w*|aktualisier\w*|entfern\w*|wird (?:installiert|aktualisiert|entfernt))", re.I)
TOKEN = re.compile(r"\x1b\[([0-9;?]*)([ -/]*[@-~])|\x1b[\]PX^_].*?(?:\x07|\x1b\\)|\x1b[@-Z\\-_]|[\r\n\b\x07]|[^\x1b\r\n\b\x07]+")
ANSI = {0: "#000000", 1: "#cc3333", 2: "#33cc33", 3: "#cccc33", 4: "#3399ff", 5: "#cc33cc", 6: "#33cccc", 7: "#d0d0d0"}
ANSI_BRIGHT = {0: "#666666", 1: "#ff5555", 2: "#55ff55", 3: "#ffff55", 4: "#66b3ff", 5: "#ff77ff", 6: "#55ffff", 7: "#ffffff"}
DEFAULT_FG = "#d0d0d0"


class TerminalDialog(QDialog):
    """Führt einen Shell-Befehl in einem Pseudo-Terminal aus und zeigt die Ausgabe im Fenster."""
    finished_cmd = Signal(int)

    def __init__(self, cmd, title="Terminal", parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
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
        self._stops = 0
        lay = QVBoxLayout(self)
        lay.addWidget(self.bar)
        lay.addWidget(self.state)
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
        if last is None:
            return
        n, total = int(last.group(1)), int(last.group(2))
        what = last.group(3).split("[")[0].strip()          # Fortschrittsbalken abschneiden
        self.bar.setRange(0, total)
        self.bar.setValue(n)
        self.state.setText("%d/%d · %s" % (n, total, what[:90]))

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
