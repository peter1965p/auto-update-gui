"""Autorenkarte in der Seitenleiste und der Dialog „Über SoftCenter“."""
import os

from PyQt6.QtCore import QRectF, Qt, QUrl
from PyQt6.QtGui import QDesktopServices, QPainter, QPainterPath, QPixmap
from PyQt6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from .common import REPO, VERSION, make_label

AUTHOR = "Peter Päffgen"
ROLE = "System & Development"
SITE = "https://paeffgen-it.de"
AVATAR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "peter.jpg")


def avatar(size):
    """Rundes Profilbild (Logo von GitHub, im Projekt abgelegt). Fehlt die Datei: Initialen-Kreis."""
    pm = QPixmap(AVATAR)
    out = QPixmap(size, size)
    out.fill(Qt.GlobalColor.transparent)
    p = QPainter(out)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    path = QPainterPath()
    path.addEllipse(QRectF(0, 0, size, size))
    p.setClipPath(path)
    if pm.isNull():
        p.fillRect(out.rect(), Qt.GlobalColor.darkGray)
        p.setPen(Qt.GlobalColor.white)
        p.drawText(out.rect(), Qt.AlignmentFlag.AlignCenter, "PP")
    else:
        p.drawPixmap(0, 0, pm.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                     Qt.TransformationMode.SmoothTransformation))
    p.end()
    return out


class AuthorCard(QPushButton):
    """Kleine Karte unten in der Seitenleiste: Bild, Name, Rolle. Klick öffnet „Über SoftCenter“."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("about")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Über SoftCenter")
        self.setMinimumHeight(54)
        pic = QLabel()
        pic.setPixmap(avatar(36))
        pic.setFixedSize(36, 36)
        name = make_label(AUTHOR, "aboutName")
        role = make_label(ROLE, "aboutRole")
        for w in (pic, name, role):
            w.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        text = QVBoxLayout()
        text.setSpacing(0)
        text.addWidget(name)
        text.addWidget(role)
        row = QHBoxLayout(self)
        row.setContentsMargins(12, 8, 12, 8)
        row.setSpacing(10)
        row.addWidget(pic)
        row.addLayout(text, 1)
        self.clicked.connect(lambda: AboutDialog(self.window()).exec())


class AboutDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("root")
        self.setWindowTitle("Über SoftCenter")
        self.setMinimumWidth(420)
        pic = QLabel()
        pic.setPixmap(avatar(96))
        pic.setFixedSize(96, 96)
        head = QVBoxLayout()
        head.setSpacing(2)
        head.addWidget(make_label("SoftCenter", "h1"))
        head.addWidget(make_label("Version %s" % VERSION, "hint"))
        head.addSpacing(6)
        head.addWidget(make_label(AUTHOR, "infoTitle"))
        head.addWidget(make_label(ROLE, "hint"))
        top = QHBoxLayout()
        top.setSpacing(16)
        top.addWidget(pic, 0, Qt.AlignmentFlag.AlignTop)
        top.addLayout(head, 1)
        about = make_label("Software suchen und installieren, System überwachen, Updates und Sicherheit an einem Ort – "
                           "für Arch Linux und CachyOS. Open Source.", "hint", wrap=True)
        links = QHBoxLayout()
        for text, url in (("GitHub", "https://github.com/%s" % REPO), ("Webseite", SITE)):
            b = QPushButton(text)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _=False, u=url: QDesktopServices.openUrl(QUrl(u)))
            links.addWidget(b)
        links.addStretch()
        close = QPushButton("Schließen")
        close.clicked.connect(self.accept)
        links.addWidget(close)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 20, 22, 18)
        lay.setSpacing(14)
        lay.addLayout(top)
        lay.addWidget(about)
        lay.addLayout(links)
