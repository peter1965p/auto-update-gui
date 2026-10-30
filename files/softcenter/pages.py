"""Systemseiten: Übersicht und Desktop-Berater (aus dem früheren SoftCenter übernommen)."""
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (QComboBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QScrollArea,
                             QVBoxLayout, QWidget)

from . import desktops, sysdetect
from .catalog import PROFILES
from .common import Card, make_label, repolish, set_state


def clear_layout(layout):
    while layout.count():
        item = layout.takeAt(0)
        if item.widget():
            item.widget().deleteLater()
        elif item.layout():
            clear_layout(item.layout())


def add_rows(card, rows):
    """Schlüssel/Wert-Zeilen in eine Karte schreiben."""
    grid = QGridLayout()
    grid.setHorizontalSpacing(16)
    grid.setVerticalSpacing(8)
    grid.setColumnStretch(1, 1)
    for i, (k, v) in enumerate(rows):
        key = make_label(k, "key")
        val = make_label(v, "value", wrap=True)
        val.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        grid.addWidget(key, i, 0, Qt.AlignmentFlag.AlignTop)
        grid.addWidget(val, i, 1)
    card.lay.addLayout(grid)


def hline():
    f = QFrame()
    f.setObjectName("hline")
    f.setFrameShape(QFrame.Shape.NoFrame)
    return f


class InfoRow(QFrame):
    """Zeile mit rundem Status-Icon (grüner Haken, gelb, grau)."""

    def __init__(self, icon, state, title, desc="", extra=None, right=None):
        super().__init__()
        self.setObjectName("infoRow")
        ic = QLabel(icon)
        ic.setObjectName("infoIcon")
        ic.setProperty("state", state)
        ic.setFixedSize(36, 36)
        ic.setAlignment(Qt.AlignmentFlag.AlignCenter)
        text = QVBoxLayout()
        text.setSpacing(2)
        text.addWidget(make_label(title, "infoTitle"))
        if desc:
            text.addWidget(make_label(desc, "hint", wrap=True))
        if extra:
            text.addWidget(make_label(extra, "warnText", wrap=True))
        row = QHBoxLayout(self)
        row.setContentsMargins(8, 8, 8, 8)
        row.setSpacing(12)
        row.addWidget(ic, 0, Qt.AlignmentFlag.AlignTop)
        row.addLayout(text, 1)
        if right is not None:
            row.addWidget(right, 0, Qt.AlignmentFlag.AlignVCenter)


class ColumnsPage(QScrollArea):
    """Scrollbare Seite, die ihren Inhalt in Spalten anordnet."""

    def __init__(self):
        super().__init__()
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self._holder = QWidget()
        self._holder.setObjectName("content")
        self.setWidget(self._holder)
        self.columns = QHBoxLayout(self._holder)
        self.columns.setContentsMargins(0, 0, 8, 0)
        self.columns.setSpacing(16)

    def reset(self):
        clear_layout(self.columns)

    def add_column(self, *cards, stretch=1):
        col = QVBoxLayout()
        col.setSpacing(16)
        for c in cards:
            col.addWidget(c)
        col.addStretch()
        self.columns.addLayout(col, stretch)


def fmt_gb(v):
    return "%.0f GB" % v if v >= 10 else "%.1f GB" % v


class OverviewPage(ColumnsPage):
    def __init__(self, host):
        super().__init__()
        self.host = host

    def _remove_button(self, names, label):
        b = QPushButton("Entfernen")
        b.setObjectName("danger")
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.clicked.connect(lambda: self.host.remove_packages(names, label))
        return b

    def _cpu_card(self):
        """Kachel „CPU-Optimierung“ – nur auf CachyOS sinnvoll."""
        try:
            state, title, text = sysdetect.cpu_optimization()
        except Exception:
            return None
        if state == "none":
            return None
        card = Card("CPU-Optimierung")
        right = None
        if state == "upgrade":
            right = QPushButton("Umstellen …")
            right.setObjectName("primary")
            right.setCursor(Qt.CursorShape.PointingHandCursor)
            right.clicked.connect(self._switch_repos)
        card.lay.addWidget(InfoRow("✓" if state == "ok" else "!", "ok" if state == "ok" else "warn", title, text, right=right))
        return card

    def _switch_repos(self):
        cmd = ("cd \"$(mktemp -d)\" && curl -fsSL https://mirror.cachyos.org/cachyos-repo.tar.xz -o r.tar.xz && "
               "tar xf r.tar.xz && cd cachyos-repo && sudo ./cachyos-repo.sh")
        self.host.run_in_terminal(cmd, "Auf die optimierten CachyOS-Repos umstellen?\n\nDas offizielle Skript von CachyOS ändert die "
                                       "pacman-Quellen und installiert danach Pakete neu. Mach vorher ein Backup oder einen Snapshot.\n\n%s" % cmd)

    def show_info(self, info):
        self.reset()
        gpus = [t for _, t in info["gpus"]] or ["nicht erkannt"]
        kind = "Virtuelle Maschine (%s)" % info["vm"] if info["vm"] else ("Laptop" if info["laptop"] else "Desktop-PC")

        hw = Card("Hardware")
        add_rows(hw, [("CPU", info["cpu"]), ("Threads", str(info["threads"])), ("RAM", fmt_gb(info["ram_gb"])),
                      ("Grafik", "\n".join(gpus)),
                      ("Speicher", "%s frei von %s" % (fmt_gb(info["disk_free_gb"]), fmt_gb(info["disk_total_gb"]))),
                      ("Gerät", kind)])

        sysp = Card("System")
        dms = ", ".join(info["installed_dms"]) or "keiner erkannt"
        add_rows(sysp, [("Distribution", info["distro"]), ("Kernel", info["kernel"]),
                        ("Session", info["session"]),
                        ("Aktueller Desktop", info["current_desktop"] or "unbekannt"),
                        ("Anmeldemanager", dms)])
        soft = Card("Software")
        add_rows(soft, [("Pakete", str(info["packages"])), ("Explizit", str(info["explicit"])),
                        ("Flatpaks", str(info["flatpaks"]))])
        show_all = QPushButton("Alle installierten Pakete ansehen und entfernen")
        show_all.setCursor(Qt.CursorShape.PointingHandCursor)
        show_all.clicked.connect(lambda: self.host.go_to(("installed", "")))
        soft.lay.addWidget(show_all)

        de = Card("Installierte Desktops")
        current = (info["current_desktop"] or "").lower()
        found = False
        for d in desktops.DESKTOPS:
            if d["id"] not in info["installed_desktops"]:
                continue
            found = True
            active = d["id"] in current or d["name"].lower() in current
            have = [p for p in d["pkgs"] if p in info["installed"]]
            right = make_label("aktiv – läuft gerade", "infoRight") if active else self._remove_button(have, d["name"])
            de.lay.addWidget(InfoRow("✓", "ok", d["name"], d["desc"], right=right))
        if not found:
            de.lay.addWidget(make_label("Keine bekannte Desktop-Umgebung gefunden.", "hint"))
        if info["sessions"]:
            de.lay.addWidget(hline())
            de.lay.addWidget(make_label("Sessions: " + ", ".join(info["sessions"]), "hint", wrap=True))

        # Was von den kuratierten Sammlungen (Entwicklung, Office, Spiele …) wirklich installiert ist
        coll = Card("Installierte Sammlungen")
        coll.lay.addWidget(make_label("Welche Auswahlen aus dem Katalog bei dir wirklich installiert sind. Beim Entfernen siehst du "
                                      "vorher eine Vorschau; Pakete, die andere noch brauchen, bleiben geschützt.", "hint", wrap=True))
        found = []
        for name, pkgs in PROFILES.items():
            have = [p for p in pkgs if p in info["installed"]]
            if have:
                found.append((len(have) / len(pkgs), name, have, pkgs))
        found.sort(key=lambda t: (-t[0], t[1]))
        for ratio, name, have, pkgs in found[:14]:
            desc = "%d von %d installiert: %s" % (len(have), len(pkgs), ", ".join(have[:8]) + (" …" if len(have) > 8 else ""))
            coll.lay.addWidget(InfoRow("%d/%d" % (len(have), len(pkgs)) if len(pkgs) < 10 else str(len(have)),
                                       "ok" if ratio == 1 else "warn" if ratio >= .5 else "", name, desc,
                                       right=self._remove_button(have, name)))
        if not found:
            coll.lay.addWidget(make_label("Keine Sammlung aus dem Katalog installiert.", "hint"))
        elif len(found) > 14:
            coll.lay.addWidget(make_label("… und %d weitere" % (len(found) - 14), "hint"))

        cpu_card = self._cpu_card()
        self.add_column(*([hw, cpu_card, soft, sysp] if cpu_card else [hw, soft, sysp]))
        self.add_column(de, coll, stretch=2)


class AdvisorPage(ColumnsPage):
    install_requested = pyqtSignal(str, str)  # Befehl, Rückfrage

    def __init__(self):
        super().__init__()
        self._info = None
        self.exp = QComboBox()
        self.exp.addItems(desktops.EXPERIENCE)
        self.exp.setCurrentIndex(1)
        self.use = QComboBox()
        self.use.addItems(desktops.USAGE)
        self.style_box = QComboBox()
        for text, _ in desktops.STYLE:
            self.style_box.addItem(text)
        for box in (self.exp, self.use, self.style_box):
            box.currentIndexChanged.connect(self.recalc)

    def show_info(self, info):
        self._info = info
        self.recalc()

    def recalc(self):
        if self._info is None:
            return
        info = self._info
        # Die Comboboxen leben in einer Karte, die beim Neuaufbau zerstört würde -> herauslösen
        for box in (self.exp, self.use, self.style_box):
            box.setParent(None)
        self.reset()

        profile = Card("Dein Profil")
        for text, box in (("Erfahrung", self.exp), ("Verwendung", self.use), ("Stil", self.style_box)):
            profile.lay.addWidget(make_label(text, "key"))
            profile.lay.addWidget(box)
        profile.lay.addWidget(make_label("Die Bewertung berücksichtigt außerdem RAM, CPU, Grafikkarte, "
                                         "Laptop/VM und die aktuelle Session.", "hint", wrap=True))

        gpus = ", ".join(t for _, t in info["gpus"]) or "unbekannt"
        machine = Card("Dein Rechner")
        add_rows(machine, [("RAM", fmt_gb(info["ram_gb"])), ("Threads", str(info["threads"])),
                           ("Grafik", gpus), ("Session", info["session"]),
                           ("Aktuell", info["current_desktop"] or "unbekannt")])

        style = desktops.STYLE[self.style_box.currentIndex()][1]
        ranking = desktops.recommend(info, self.exp.currentText(), self.use.currentText(), style)
        result = Card("Empfehlung")
        for i, (d, score, reasons, warnings) in enumerate(ranking):
            installed = d["id"] in info["installed_desktops"]
            btn = QPushButton("✓ Installiert" if installed else "Installieren")
            btn.setEnabled(not installed)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            if i == 0 and not installed:
                btn.setObjectName("primary")
            cmd = desktops.install_command(d, info["installed_dms"])
            btn.clicked.connect(lambda _=False, c=cmd, n=d["name"]:
                                self.install_requested.emit(c, "%s installieren?\n\n%s" % (n, c)))
            state = "ok" if score >= 70 else "warn" if score >= 45 else ""
            title = "%s%s" % (d["name"], "  ·  Beste Wahl" if i == 0 else "")
            desc = d["desc"] + ("\n+ " + ", ".join(reasons) if reasons else "")
            row = InfoRow(str(score), state, title, desc,
                          extra=("! " + ", ".join(warnings)) if warnings else None, right=btn)
            result.lay.addWidget(row)
            if i < len(ranking) - 1:
                result.lay.addWidget(hline())

        self.add_column(profile, machine)
        self.add_column(result, stretch=3)
