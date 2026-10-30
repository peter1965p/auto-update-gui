"""Pac-Man als Fortschrittsanzeige (frisst Punkte und Geister) – für Updates und Installationen."""
import math
import time

from PyQt6.QtCore import QPointF, QRectF, Qt, QTimer
from PyQt6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QWidget


class PacBar(QWidget):
    """Fortschrittsanzeige im Arcade-Stil: Pac-Man frisst Punkte und Geister. Gleiche API wie QProgressBar."""
    GHOSTS = ["#ff4d4d", "#ffb8ff", "#19e3ff", "#ffb852"]
    SCORES = ["200", "400", "800", "1600"]
    FRACS = [0.30, 0.52, 0.74, 0.96]

    def __init__(self):
        super().__init__()
        self.sc = .78                       # Anzeige-Maßstab (kompakt); gezeichnet wird in 50 px Höhe
        self.setFixedHeight(round(50 * self.sc))
        self.lo, self.hi, self.val, self.shown = 0, 100, 0, 0.0
        self.t0 = time.monotonic(); self.eaten = {}
        self.mode = "ready"
        self.tm = QTimer(self); self.tm.setInterval(90); self.tm.timeout.connect(self._tick)

    def set_mode(self, mode):
        """'run' = Update läuft, 'ready' = bereit, 'clear' = Lauf erfolgreich, 'over' = Lauf mit Fehler."""
        if mode == self.mode: return
        self.mode = mode; self.tm.setInterval(33 if mode == "run" else 90)
        if mode == "run": self.eaten.clear(); self.shown = 0.0
        self.update()

    def setRange(self, lo, hi): self.lo, self.hi = lo, hi
    def setValue(self, v): self.val = v
    def indeterminate(self): return self.hi <= self.lo
    def showEvent(self, e): self.tm.start()
    def hideEvent(self, e): self.tm.stop()

    def _tick(self):
        target = 0.0 if self.indeterminate() else min(1.0, max(0.0, (self.val - self.lo) / (self.hi - self.lo)))
        if target < self.shown - .3: self.eaten.clear()
        self.shown += (target - self.shown) * .12
        if abs(target - self.shown) < .001: self.shown = target
        self.update()

    def _ghost(self, p, x, cy, col, scared, look, blink=False):
        r = 12
        path = QPainterPath(); path.moveTo(x - r, cy + r); path.lineTo(x - r, cy)
        path.arcTo(QRectF(x - r, cy - r, 2 * r, 2 * r), 180, -180); path.lineTo(x + r, cy + r)
        seg = 2 * r / 3
        for i in range(3):
            xr = x + r - i * seg
            path.lineTo(xr - seg / 2, cy + r - 6); path.lineTo(xr - seg, cy + r)
        path.closeSubpath()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#f4f4ff" if scared and blink else "#2a3cff" if scared else col)); p.drawPath(path)
        if scared:
            p.setBrush(QColor("#ffd0c8" if not blink else "#ff4d4d"))
            for dx in (-4.5, 2.5): p.drawRect(QRectF(x + dx, cy - 5, 2.4, 2.4))
            p.setPen(QPen(QColor("#ffd0c8" if not blink else "#ff4d4d"), 1.4)); p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPolyline(*[QPointF(x - 6 + i * 3, cy + 3 + (2 if i % 2 else 0)) for i in range(5)])
        else:
            p.setBrush(QColor("white"))
            for dx in (-4.5, 4.5): p.drawEllipse(QPointF(x + dx, cy - 3), 3.6, 4.3)
            p.setBrush(QColor("#1a2cff"))
            for dx in (-4.5, 4.5): p.drawEllipse(QPointF(x + dx + look * 1.6, cy - 3), 1.8, 1.8)

    def _idle(self, p, w, cy, R, lo, hi, now):
        """Ruhebild: bereit (alles da), Level geschafft (alles gefressen) oder Game over."""
        mode = self.mode
        px = hi if mode == "clear" else lo if mode == "ready" else lo + (hi - lo) * .12
        p.setPen(Qt.PenStyle.NoPen)
        if mode != "clear":
            p.setBrush(QColor("#f1d9a0"))
            for x in range(int(lo), int(hi) + 1, 18):
                if abs(x - px) > R + 2: p.drawEllipse(QPointF(x, cy), 2.2, 2.2)
            for f, col in zip(self.FRACS, self.GHOSTS): self._ghost(p, lo + f * (hi - lo), cy, col, False, -1)
        mh = 38 if mode == "over" else 4 + 36 * abs(math.sin(now * (3 if mode == "ready" else 10)))
        p.setBrush(QColor("#ffd400"))
        p.drawPie(QRectF(px - R, cy - R, 2 * R, 2 * R), int(mh * 16), int((360 - 2 * mh) * 16))
        p.setBrush(QColor("#0d0f17")); p.drawEllipse(QPointF(px + 1.5, cy - R * .5), 1.8, 1.8)
        txt, col = {"ready": ("READY!", "#ffd400"), "clear": ("LEVEL CLEAR", "#2ecc71"), "over": ("GAME OVER", "#ff4d4d")}[mode]
        f = QFont("monospace"); f.setBold(True); f.setPixelSize(13); f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 2); p.setFont(f)
        tw = QFontMetrics(f).horizontalAdvance(txt) + 26
        p.setPen(Qt.PenStyle.NoPen); p.setBrush(QColor("#0d0f17")); p.drawRoundedRect(QRectF(w / 2 - tw / 2, cy - 12, tw, 24), 6, 6)
        p.setPen(QColor(col)); p.drawText(QRectF(w / 2 - tw / 2, cy - 12, tw, 24), Qt.AlignmentFlag.AlignCenter, txt)

    def paintEvent(self, _):
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        sc = self.sc; w, h = self.width() / sc, 50; p.scale(sc, sc); cy = h / 2; R = 13; x0, x1 = 24, w - 24
        now = time.monotonic() - self.t0
        # Spielfeld
        p.setPen(QPen(QColor(40, 60, 255, 190), 2)); p.setBrush(QColor("#0d0f17"))
        p.drawRoundedRect(QRectF(3, 3, w - 6, h - 6), 12, 12)
        lo, hi = x0 + R, x1 - R
        if self.mode != "run": return self._idle(p, w, cy, R, lo, hi, now)
        ind = self.indeterminate()
        if ind:
            ph = (now / 7.0) % 1.0; tri = 1 - abs(2 * ph - 1); dirn = 1 if ph < .5 else -1
            px = lo + tri * max(0, hi - lo - 130)
        else:
            px, dirn = lo + self.shown * (hi - lo), 1
        # Punkte
        p.setPen(Qt.PenStyle.NoPen); p.setBrush(QColor("#f1d9a0"))
        for x in range(int(lo), int(hi) + 1, 18):
            if abs(x - px) > R + 2 and (ind or x > px): p.drawEllipse(QPointF(x, cy), 2.2, 2.2)
        # Geister
        if ind:
            chase = dirn > 0
            for i, col in enumerate(self.GHOSTS):
                self._ghost(p, px + 34 + i * 30, cy, col, chase, 1)
        else:
            for i, (f, col) in enumerate(zip(self.FRACS, self.GHOSTS)):
                gx = lo + f * (hi - lo)
                if px >= gx - 2:
                    t0 = self.eaten.setdefault(i, now)
                    if now - t0 < .9:      # Punkte-Anzeige nach dem Fressen
                        p.setPen(QColor(25, 227, 255, int(255 * (1 - (now - t0) / .9)))); f2 = QFont(); f2.setBold(True); f2.setPixelSize(11)
                        p.setFont(f2); p.drawText(QPointF(gx - 10, cy + 5 - (now - t0) * 6), self.SCORES[i])
                    continue
                near = gx - px
                self._ghost(p, gx, cy, col, near < 110, -1, blink=near < 40 and int(now * 8) % 2 == 0)
        # Pac-Man
        mh = 4 + 36 * abs(math.sin(now * 10))
        p.setPen(Qt.PenStyle.NoPen); p.setBrush(QColor("#ffd400"))
        start = mh if dirn > 0 else 180 + mh
        p.drawPie(QRectF(px - R, cy - R, 2 * R, 2 * R), int(start * 16), int((360 - 2 * mh) * 16))
        p.setBrush(QColor("#0d0f17")); p.drawEllipse(QPointF(px + dirn * 1.5, cy - R * .5), 1.8, 1.8)
