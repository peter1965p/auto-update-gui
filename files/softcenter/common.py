"""Gemeinsame Bausteine: Einstellungen, Hilfsfunktionen, Theme und kleine Widgets."""
import html, json, math, os, re, shutil, subprocess, sys, time
from collections import Counter
from datetime import datetime as DT
from types import SimpleNamespace
from PyQt6.QtCore import (QEasingCurve, QDateTime, QLocale, QPointF, QProcess, QRectF, QSettings, Qt, QTime,
    QTimer, QVariantAnimation, pyqtSignal)
from PyQt6.QtGui import QAction, QColor, QFont, QIcon, QFontMetrics, QPainter, QPainterPath, QPalette, QPen, QPixmap
from PyQt6.QtWidgets import (QAbstractButton, QApplication, QCheckBox, QComboBox, QDialog, QFrame, QGridLayout,
    QHBoxLayout, QLabel, QLineEdit, QMenu, QMessageBox, QPlainTextEdit, QProgressBar, QPushButton, QScrollArea,
    QSizePolicy, QSystemTrayIcon, QTextEdit, QTimeEdit, QVBoxLayout, QWidget)

VERSION = "3.2.0"
REPO = "peter1965p/auto-update-gui"
CONF = "/etc/auto-update.conf"
THEMES = [("Wie das System", "system"), ("Hell", "light"), ("Dunkel", "dark")]
ACCENTS = [("Wie das System", "system"), ("Bernstein", "#f59e0b"), ("Blau", "#3daee9"), ("Grün", "#2ecc71"), ("Violett", "#9b59b6"),
           ("Orange", "#f5a623"), ("Rot", "#e5534b"), ("Rosa", "#e84393")]
INTERVALS = [("Jede Stunde", 1), ("Alle 3 Stunden", 3), ("Alle 6 Stunden", 6), ("Alle 12 Stunden", 12), ("Täglich", 24)]
AUTOSTART = os.path.expanduser("~/.config/autostart/auto-update-gui.desktop")
cfg = QSettings("auto-update-gui", "auto-update-gui")   # ~/.config/auto-update-gui/auto-update-gui.conf

def flag(key, default=True):
    return str(cfg.value(key, default)).lower() in ("true", "1")

def autostart_enabled():
    try:
        return "Hidden=true" not in open(AUTOSTART).read()
    except OSError:
        return os.path.exists("/etc/xdg/autostart/auto-update-gui.desktop")

def set_autostart(on):
    os.makedirs(os.path.dirname(AUTOSTART), exist_ok=True)
    body = ("[Desktop Entry]\nType=Application\nName=SoftCenter\nIcon=system-software-update\n"
            + ("Exec=/usr/local/bin/auto-update-gui --tray\n" if on else "Hidden=true\n"))
    open(AUTOSTART, "w").write(body)


theme = {}          # wird von apply_theme() in-place gefüllt, damit alle Module dasselbe Objekt sehen
ORIG_PAL = None     # System-Palette, setzt die App beim Start

def sh(*cmd):
    return subprocess.run(cmd, capture_output=True, text=True)

def vtuple(v):
    return tuple(int(x) for x in re.findall(r"\d+", v or ""))

def parse_ts(s):
    """'Sat 2026-10-24 05:00:00 CEST' -> QDateTime oder None"""
    m = re.search(r"(\d{4}-\d\d-\d\d) (\d\d:\d\d:\d\d)", s or "")
    if not m or m.group(1) == "0000-00-00": return None
    dt = QDateTime.fromString(f"{m.group(1)} {m.group(2)}", "yyyy-MM-dd HH:mm:ss")
    return dt if dt.isValid() else None

def fmt_dt(dt):
    return f"{QLocale().dayName(dt.date().dayOfWeek(), QLocale.FormatType.ShortFormat)}, " \
           f"{dt.toString('dd.MM.yyyy')} um {dt.toString('HH:mm')} Uhr"

def fmt_delta(secs):
    if secs < 0: return ""
    d, r = divmod(secs, 86400); h, r = divmod(r, 3600); m = r // 60
    if d: return f"in {d} Tg. {h} Std."
    if h: return f"in {h} Std. {m} Min."
    return f"in {max(m, 1)} Min."



# ---------------------------------------------------------------- Theme

def palette_for(base):
    mode = str(cfg.value("theme", "system"))
    for a in sys.argv:  # --theme=dark|light überschreibt die Einstellung (z. B. für Screenshots)
        if a.startswith("--theme="): mode = a.split("=", 1)[1]
    dark = base.color(QPalette.ColorRole.Window).lightness() < 128 if mode == "system" else mode == "dark"
    acc = str(cfg.value("accent", "system"))
    t = dict(dark=dark, accent=base.color(QPalette.ColorRole.Highlight).name() if acc == "system" else acc,
             ok="#2ecc71", warn="#f5a623", err="#e5534b")
    if dark:
        t.update(bg="#1a1c22", card="#252830", border="#353946", text="#e8eaf0", muted="#98a0b2",
                 hover="#2f3340", input="#1f2229", sidebar="#14161b")
    else:
        t.update(bg="#f2f3f7", card="#ffffff", border="#dde0ea", text="#1c1e26", muted="#6a7082",
                 hover="#eceef5", input="#f7f8fb", sidebar="#ffffff")
    return t

def apply_theme(app):
    """Wendet Farbschema + Akzentfarbe auf die ganze Anwendung an (auch Dialoge), live."""
    t = palette_for(ORIG_PAL)
    theme.clear(); theme.update(t)
    R = QPalette.ColorRole; G = QPalette.ColorGroup
    pal = QPalette()
    for role, col in ((R.Window, t["bg"]), (R.WindowText, t["text"]), (R.Base, t["input"]), (R.AlternateBase, t["card"]),
                      (R.Text, t["text"]), (R.Button, t["card"]), (R.ButtonText, t["text"]), (R.ToolTipBase, t["card"]),
                      (R.ToolTipText, t["text"]), (R.Highlight, t["accent"]), (R.HighlightedText, "#ffffff"),
                      (R.PlaceholderText, t["muted"]), (R.Link, t["accent"])):
        pal.setColor(role, QColor(col))
    for role in (R.WindowText, R.Text, R.ButtonText): pal.setColor(G.Disabled, role, QColor(t["muted"]))
    app.setPalette(pal)
    Toggle.accent = QColor(t["accent"]); Toggle.off = QColor("#5c6272" if t["dark"] else "#b4b9c6")
    app.setStyleSheet(make_qss(t))
    for wd in app.allWidgets():
        if isinstance(wd, Toggle): wd.update()

def make_qss(t):
    return f"""
    QWidget#root, QScrollArea, QScrollArea > QWidget > QWidget {{ background: {t['bg']}; }}
    QWidget {{ color: {t['text']}; font-size: 13px; }}
    QFrame#card {{ background: {t['card']}; border: 1px solid {t['border']}; border-radius: 14px; }}
    QFrame#card QLabel {{ background: transparent; }}
    QFrame#sep {{ background: {t['border']}; max-height: 1px; border: none; }}
    QLabel {{ background: transparent; }}
    QLabel#h1 {{ font-size: 21px; font-weight: 700; }}
    QLabel#cardTitle {{ font-size: 14px; font-weight: 700; }}
    QLabel#rowTitle {{ font-weight: 600; }}
    QLabel#muted, QLabel#desc {{ color: {t['muted']}; }}
    QLabel#desc {{ font-size: 12px; }}
    QLabel#mono {{ font-family: monospace; font-size: 12px; color: {t['muted']}; }}
    QLabel#pill {{ border-radius: 11px; padding: 4px 14px; font-weight: 600; font-size: 12px;
                  background: {t['hover']}; color: {t['muted']}; }}
    QLabel#pill[state="on"]  {{ background: rgba(46,204,113,.18); color: {t['ok']}; }}
    QLabel#pill[state="run"] {{ background: {t['accent']}; color: white; }}
    QLabel#pill[state="err"] {{ background: rgba(229,83,75,.18); color: {t['err']}; }}
    QLabel#badge {{ border-radius: 17px; font-weight: 700; font-size: 14px;
                   background: {t['hover']}; color: {t['muted']}; border: 1px solid {t['border']}; }}
    QLabel#badge[state="active"] {{ background: {t['accent']}; color: white; border: none; }}
    QLabel#badge[state="done"]   {{ background: {t['ok']}; color: white; border: none; }}
    QLabel#badge[state="failed"] {{ background: {t['err']}; color: white; border: none; }}
    QLabel#detail {{ font-size: 12px; color: {t['text']}; }}
    QLabel#detail[state="active"] {{ color: {t['accent']}; font-weight: 600; }}
    QLabel#detail[state="failed"] {{ color: {t['err']}; }}
    QLabel#stState {{ font-size: 12px; font-weight: 600; color: {t['muted']}; }}
    QLabel#stState[state="active"] {{ color: {t['accent']}; }}
    QLabel#stState[state="done"]   {{ color: {t['ok']}; }}
    QLabel#stState[state="failed"] {{ color: {t['err']}; }}
    QPushButton {{ padding: 8px 16px; border-radius: 9px; border: 1px solid {t['border']}; background: {t['card']}; }}
    QPushButton:hover {{ background: {t['hover']}; }}
    QPushButton:disabled {{ color: {t['muted']}; background: {t['bg']}; }}
    QPushButton#primary {{ background: {t['accent']}; color: white; border: none; font-weight: 600; }}
    QPushButton#primary:hover {{ background: {t['accent']}; }}
    QPushButton#primary:disabled {{ background: {t['border']}; color: {t['muted']}; }}
    QPushButton#flat {{ border: none; background: transparent; color: {t['muted']}; padding: 6px 10px; }}
    QPushButton#flat:hover {{ color: {t['text']}; background: {t['hover']}; }}
    QComboBox, QTimeEdit {{ background: {t['input']}; border: 1px solid {t['border']}; border-radius: 8px;
                           padding: 4px 10px; min-height: 22px; }}
    QComboBox:disabled, QTimeEdit:disabled {{ color: {t['muted']}; }}
    QTimeEdit::up-button, QTimeEdit::down-button {{ width: 0px; border: none; }}
    QComboBox::drop-down {{ border: none; width: 22px; }}
    QComboBox QAbstractItemView {{ background: {t['card']}; border: 1px solid {t['border']};
                                   selection-background-color: {t['accent']}; selection-color: white; outline: none; }}
    QProgressBar {{ background: {t['border']}; border: none; border-radius: 4px; max-height: 8px; min-height: 8px; }}
    QProgressBar::chunk {{ background: {t['accent']}; border-radius: 4px; }}
    QPlainTextEdit, QTextEdit {{ background: {t['input']}; border: 1px solid {t['border']}; border-radius: 8px;
                     font-family: monospace; font-size: 12px; padding: 6px; }}
    QScrollArea {{ border: none; }}
    QToolTip {{ background: {t['card']}; color: {t['text']}; border: 1px solid {t['border']}; padding: 6px; }}

    /* ---- SoftCenter: Seitenleiste, Kopf, Paketkarten ---- */
    QWidget#content {{ background: {t['bg']}; }}
    QFrame#sidebar {{ background: {t['sidebar']}; border-right: 1px solid {t['border']}; }}
    QLabel#logo {{ font-size: 20px; font-weight: 700; padding: 18px 16px 6px 16px; background: transparent; }}
    QLabel#logoSub {{ color: {t['muted']}; font-size: 11px; padding: 0 16px 8px 16px; background: transparent; }}
    QListWidget#nav {{ background: transparent; border: none; outline: none; padding: 0 8px; }}
    QListWidget#nav::item {{ padding: 8px 12px; border-radius: 8px; color: {t['muted']}; margin: 1px 0; }}
    QListWidget#nav::item:hover {{ background: {t['hover']}; color: {t['text']}; }}
    QListWidget#nav::item:selected {{ background: {t['hover']}; color: {t['accent']}; font-weight: 600; }}
    QLabel#headerIcon {{ background: {t['hover']}; color: {t['accent']}; border: 2px solid {t['accent']};
                        border-radius: 22px; font-size: 20px; font-weight: 700; }}
    QLabel#pageTitle {{ font-size: 22px; font-weight: 700; background: transparent; }}
    QLabel#pageSubtitle {{ color: {t['muted']}; background: transparent; }}
    QLabel#key {{ color: {t['muted']}; background: transparent; }}
    QLabel#value, QLabel#hint {{ background: transparent; }}
    QLabel#hint {{ color: {t['muted']}; font-size: 12px; }}
    QLabel#warnText {{ color: {t['warn']}; font-size: 12px; background: transparent; }}
    QFrame#hline {{ background: {t['border']}; max-height: 1px; min-height: 1px; border: none; }}
    QFrame#infoRow {{ background: transparent; border-radius: 10px; }}
    QFrame#infoRow:hover {{ background: {t['hover']}; }}
    QLabel#infoIcon {{ background: {t['hover']}; color: {t['muted']}; border-radius: 18px; font-weight: 700; }}
    QLabel#infoIcon[state="ok"] {{ background: rgba(46,204,113,.18); color: {t['ok']}; }}
    QLabel#infoIcon[state="warn"] {{ background: rgba(245,166,35,.18); color: {t['warn']}; }}
    QLabel#infoTitle {{ font-weight: 600; background: transparent; }}
    QLabel#infoRight {{ color: {t['ok']}; font-size: 12px; background: transparent; }}
    QLineEdit {{ background: {t['input']}; border: 1px solid {t['border']}; border-radius: 9px; padding: 8px 12px;
                selection-background-color: {t['accent']}; selection-color: white; }}
    QLineEdit:focus {{ border: 1px solid {t['accent']}; }}
    QPushButton#chip {{ border-radius: 15px; padding: 6px 14px; color: {t['muted']}; }}
    QPushButton#chip:checked {{ background: {t['accent']}; border-color: {t['accent']}; color: white; font-weight: 600; }}
    QPushButton#danger {{ color: {t['err']}; }}
    QListWidget#cards {{ background: transparent; border: none; outline: none; }}
    QListWidget#cards::item {{ background: transparent; border: none; }}
    QFrame#pcard {{ background: {t['card']}; border: 1px solid {t['border']}; border-radius: 12px; }}
    QFrame#pcard:hover {{ border: 1px solid {t['accent']}; }}
    QLabel#pkgTitle {{ font-size: 15px; font-weight: 600; background: transparent; }}
    QLabel#pkgDesc, QLabel#pkgMeta {{ color: {t['muted']}; background: transparent; }}
    QLabel#pkgBadge {{ background: {t['hover']}; color: {t['muted']}; border-radius: 6px; padding: 2px 8px; font-size: 11px; }}
    QLabel#pkgBadge[source="aur"] {{ color: {t['warn']}; }}
    QLabel#status {{ color: {t['muted']}; background: transparent; }}
    QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
    QScrollBar::handle:vertical {{ background: {t['border']}; border-radius: 4px; min-height: 30px; }}
    QScrollBar::handle:vertical:hover {{ background: {t['muted']}; }}
    QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {{ height: 0; background: none; }}
    """

class Toggle(QAbstractButton):
    accent, off = QColor("#3daee9"), QColor("#7a8090")

    def __init__(self):
        super().__init__()
        self.setCheckable(True); self.setFixedSize(46, 26)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.pos_ = 0.0
        self.anim = QVariantAnimation(self, duration=160, easingCurve=QEasingCurve.Type.InOutCubic)
        self.anim.valueChanged.connect(self._step)
        self.toggled.connect(self._start)

    def _step(self, v):
        self.pos_ = v; self.update()

    def _start(self, on):
        self.anim.stop(); self.anim.setStartValue(self.pos_); self.anim.setEndValue(1.0 if on else 0.0)
        if self.isVisible(): self.anim.start()
        else: self._step(1.0 if on else 0.0)

    def setChecked(self, on):
        super().setChecked(on); self.pos_ = 1.0 if on else 0.0; self.update()

    def paintEvent(self, _):
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setOpacity(1 if self.isEnabled() else .4); p.setPen(Qt.PenStyle.NoPen)
        t = self.pos_
        mix = lambda a, b: int(a + (b - a) * t)
        p.setBrush(QColor(mix(self.off.red(), self.accent.red()), mix(self.off.green(), self.accent.green()),
                          mix(self.off.blue(), self.accent.blue())))
        p.drawRoundedRect(QRectF(0, 0, 46, 26), 13, 13)
        p.setBrush(QColor(0, 0, 0, 40)); p.drawEllipse(QRectF(3 + 20 * t, 3.8, 20, 20))  # Schatten
        p.setBrush(QColor("white")); p.drawEllipse(QRectF(3 + 20 * t, 3, 20, 20))
        if t > .5:  # Häkchen im Knopf
            p.setPen(QPen(self.accent, 2, cap=Qt.PenCapStyle.RoundCap, join=Qt.PenJoinStyle.RoundJoin))
            x = 3 + 20 * t
            p.drawPolyline(QPointF(x + 6, 13.5), QPointF(x + 9, 16.5), QPointF(x + 14.5, 10))

def repolish(w):
    w.style().unpolish(w); w.style().polish(w)

def make_label(text="", name=None, wrap=False):
    l = QLabel(text)
    if name: l.setObjectName(name)
    l.setWordWrap(wrap)
    return l

def set_state(w, state):
    w.setProperty("state", state); repolish(w)

class Card(QFrame):
    def __init__(self, title=None, right=None):
        super().__init__()
        self.setObjectName("card")
        self.lay = self.body = QVBoxLayout(self); self.lay.setContentsMargins(18, 16, 18, 16); self.lay.setSpacing(12)
        if title:
            head = QHBoxLayout(); head.addWidget(make_label(title, "cardTitle")); head.addStretch()
            if right: head.addWidget(right)
            self.lay.addLayout(head)

def separator():
    s = QFrame(); s.setObjectName("sep"); s.setFixedHeight(1); return s

class OptionRow(QWidget):
    """Titel + Erklärung links, Schalter rechts."""
    def __init__(self, title, desc, tooltip=None):
        super().__init__()
        lay = QHBoxLayout(self); lay.setContentsMargins(0, 0, 0, 0); lay.setSpacing(14)
        col = QVBoxLayout(); col.setSpacing(2)
        col.addWidget(make_label(title, "rowTitle")); col.addWidget(make_label(desc, "desc", True))
        lay.addLayout(col, 1)
        self.toggle = Toggle(); lay.addWidget(self.toggle, 0, Qt.AlignmentFlag.AlignVCenter)
        if tooltip: self.setToolTip(tooltip)

