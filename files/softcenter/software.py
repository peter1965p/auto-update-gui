"""Seite „Software“: Paketsuche (Repo + AUR), kuratierte Sammlungen, installierte Pakete."""
import shlex
import shutil

from PyQt6.QtCore import QSize, Qt, QThread, QTimer
from PyQt6.QtWidgets import (QAbstractItemView, QButtonGroup, QFrame, QHBoxLayout, QLabel, QLineEdit, QListWidget,
                             QListWidgetItem, QMessageBox, QPushButton, QVBoxLayout, QWidget)

from . import backend
from .catalog import GROUPS, PROFILES
from .common import repolish

PAGE_SIZE = 60  # so viele Karten werden auf einmal gebaut
CARD_HEIGHT = 88
SCOPES = (("Alle", "all"), ("Repo", "repo"), ("AUR", "aur"))
INSTALLED_SCOPES = (("Alle", "installed"), ("Selbst installiert", "explicit"), ("Fremd / AUR", "foreign"))


class PackageCard(QFrame):
    def __init__(self, source, name, version, desc, installed, on_install, on_remove):
        super().__init__()
        self.setObjectName("pcard")
        self.name = name

        title = QLabel(name)
        title.setObjectName("pkgTitle")
        version_lbl = QLabel(version)
        version_lbl.setObjectName("pkgMeta")
        self.badge = QLabel(source)
        self.badge.setObjectName("pkgBadge")
        self.badge.setProperty("source", "aur" if source == "aur" else "repo")
        self.desc = QLabel(desc or "Keine Beschreibung")
        self.desc.setObjectName("pkgDesc")
        self.desc.setWordWrap(False)
        self.desc.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        self.desc.setToolTip(desc)

        self.button = QPushButton()
        self.button.setObjectName("primary")
        self.button.setFixedWidth(130)
        self.button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.button.clicked.connect(lambda: on_remove(name) if self.installed else on_install(source, name))
        self.tag = QLabel("✓ installiert")
        self.tag.setObjectName("infoRight")
        self.set_installed(installed)

        top = QHBoxLayout()
        top.setSpacing(8)
        for w in (title, self.badge, version_lbl, self.tag):
            top.addWidget(w)
        top.addStretch()
        text = QVBoxLayout()
        text.setSpacing(4)
        text.addLayout(top)
        text.addWidget(self.desc)
        row = QHBoxLayout(self)
        row.setContentsMargins(16, 10, 16, 10)
        row.addLayout(text, 1)
        row.addWidget(self.button)

    def set_installed(self, installed):
        self.installed = installed
        self.tag.setVisible(installed)
        self.button.setText("Entfernen" if installed else "Installieren")
        self.button.setObjectName("danger" if installed else "primary")
        repolish(self.button)


class SoftwarePage(QWidget):
    """Suchfeld, Filter-Chips und die Kartenliste. Die Ansicht (Kategorie, Sammlung, Installiert) setzt das Hauptfenster."""

    def __init__(self, host):
        super().__init__()
        self.setObjectName("content")
        self.host = host
        self._thread = self._worker = None
        self._pending = False
        self._rows = []        # alle Treffer der aktuellen Ansicht
        self._shown = 0        # davon bereits als Karten gebaut
        self._cards = []
        self._set_aur = []
        self._view = ("group", "Alle Kategorien")

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(500)
        self._timer.timeout.connect(self.start_search)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Pakete suchen ...")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(lambda _: self._timer.start())
        self.search.returnPressed.connect(self.start_search_now)

        self.chips = QButtonGroup(self)
        chip_row = QHBoxLayout()
        chip_row.setSpacing(8)
        self.chip_widgets = []
        for i, (label, scope) in enumerate(SCOPES):
            b = QPushButton(label)
            b.setObjectName("chip")
            b.setCheckable(True)
            b.setChecked(i == 0)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setProperty("scope", scope)
            self.chips.addButton(b)
            self.chip_widgets.append(b)
            chip_row.addWidget(b)
        self.chips.buttonClicked.connect(lambda _: self.start_search_now())
        self.status = QLabel()
        self.status.setObjectName("status")
        chip_row.addSpacing(12)
        chip_row.addWidget(self.status, 1)
        self.install_profile_btn = QPushButton("Alle installieren")
        self.install_profile_btn.setObjectName("primary")
        self.install_profile_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.install_profile_btn.clicked.connect(self.install_profile)
        chip_row.addWidget(self.install_profile_btn)
        # Wartungsaktionen (nur in der Ansicht „Installiert“)
        self.maint_btns = []
        for text, action in (("Verwaiste entfernen", host.maint_orphans), ("Cache leeren", host.maint_cache)):
            b = QPushButton(text)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(action)
            chip_row.addWidget(b)
            self.maint_btns.append(b)

        self.cards = QListWidget()
        self.cards.setObjectName("cards")
        self.cards.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.cards.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.cards.setSpacing(5)
        self.cards.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.cards.verticalScrollBar().setSingleStep(24)

        pk = QVBoxLayout(self)
        pk.setContentsMargins(0, 0, 0, 0)
        pk.setSpacing(14)
        pk.addWidget(self.search)
        pk.addLayout(chip_row)
        pk.addWidget(self.cards, 1)

    # --- Ansicht wechseln ---
    def show_view(self, kind, name):
        """kind: 'group' | 'profile' | 'installed' (vom Hauptfenster nach einem Klick in der Seitenleiste)."""
        self._view = (kind, name)
        profile = kind == "profile"
        installed_view = kind == "installed"
        self.install_profile_btn.setVisible(profile)
        for b, (text, scope) in zip(self.chip_widgets, INSTALLED_SCOPES if installed_view else SCOPES):
            b.setText(text)
            b.setProperty("scope", scope)
            b.setVisible(not profile)
        self.chip_widgets[0].setChecked(True)
        for b in self.maint_btns:
            b.setVisible(installed_view)
        self.search.setVisible(not profile)
        self.start_search_now()

    def current_scope(self):
        return self.chips.checkedButton().property("scope")

    def start_search_now(self):
        self._timer.stop()
        self.start_search()

    def start_search(self):
        if self._view[0] == "profile":
            self.show_profile(self._view[1])
            return
        term = self.search.text().strip()
        if len(term) == 1:
            self.status.setText("min. 2 Zeichen")
            return
        if self._thread is not None:  # läuft noch -> danach erneut suchen
            self._pending = True
            return
        self.status.setText("Suche ...")
        keywords = GROUPS.get(self._view[1]) if self._view[0] == "group" else None
        self._thread = QThread(self)
        self._worker = backend.SearchWorker(term, self.current_scope(), keywords)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.finished.connect(self.on_results)
        self._thread.start()

    def on_results(self, rows, error):
        self._thread.quit()
        self._thread.wait()
        self._thread = self._worker = None
        if self._pending:
            self._pending = False
            self.start_search()
            return
        if self._view[0] == "profile":
            return
        self.set_rows(rows)
        text = "%d Pakete" % len(rows)
        self.status.setText(text + (" !" if error else ""))
        self.status.setToolTip(error)

    def show_profile(self, name):
        self._timer.stop()
        pkgs = PROFILES[name]
        info = backend.package_info(pkgs)
        installed = backend.installed_names()
        rows = []
        for p in pkgs:
            f = info.get(p, {})
            if f:
                rows.append((f["Repository"], p, f.get("Version", ""), f.get("Description", ""), p in installed))
            else:  # nicht in den Repos -> über den AUR-Helper versuchen
                rows.append(("aur", p, "", "Nicht in den Repos – Installation über das AUR", p in installed))
        self._set_aur = [p for p in pkgs if p not in info and p not in installed]
        self.set_rows(rows)
        missing = len(self._set_aur)
        self.status.setText("%d Pakete in der Auswahl" % len(pkgs) + (" (%d aus dem AUR)" % missing if missing else ""))
        self.status.setToolTip("")

    # --- Karten ---
    def set_rows(self, rows):
        self._rows, self._shown = rows, 0
        self._cards = []
        self.cards.clear()
        self.cards.verticalScrollBar().setValue(0)
        self.show_more()

    def show_more(self):
        # alten „Mehr“-Eintrag entfernen
        last = self.cards.count() - 1
        if last >= 0 and self.cards.item(last).data(Qt.ItemDataRole.UserRole) == "more":
            self.cards.takeItem(last)
        end = min(self._shown + PAGE_SIZE, len(self._rows))
        for row in self._rows[self._shown:end]:
            card = PackageCard(*row, self.install, self.remove)
            item = QListWidgetItem()
            item.setSizeHint(QSize(0, CARD_HEIGHT))
            self.cards.addItem(item)
            self.cards.setItemWidget(item, card)
            self._cards.append(card)
        self._shown = end
        if end < len(self._rows):
            btn = QPushButton("Weitere %d anzeigen" % (len(self._rows) - end))
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(self.show_more)
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, "more")
            item.setSizeHint(QSize(0, 52))
            self.cards.addItem(item)
            self.cards.setItemWidget(item, btn)

    # --- Installation (läuft im eingebetteten Terminal des Hauptfensters) ---
    def install(self, source, name):
        if source == "aur":
            helper = next((h for h in backend.AUR_HELPERS if shutil.which(h)), None)
            if helper is None:
                QMessageBox.warning(self, "AUR-Helper fehlt", "Zum Installieren aus dem AUR wird paru oder yay benötigt.")
                return
            cmd = "%s -S --needed %s" % (helper, shlex.quote(name))
        else:
            cmd = "sudo pacman -S --needed %s" % shlex.quote(name)
        self.host.run_in_terminal(cmd, None, install=True)

    def remove(self, name):
        self.host.remove_packages([name])

    def install_profile(self):
        name = self._view[1]
        pkgs = PROFILES.get(name)
        if not pkgs:
            return
        aur = [p for p in self._set_aur if p in pkgs]
        repo = [p for p in pkgs if p not in aur]
        parts = []
        if repo:
            parts.append("sudo pacman -S --needed %s" % " ".join(shlex.quote(p) for p in repo))
        if aur:
            helper = next((h for h in backend.AUR_HELPERS if shutil.which(h)), None)
            if helper is None:
                QMessageBox.warning(self, "AUR-Helper fehlt", "Für %s wird paru oder yay benötigt." % ", ".join(aur))
            else:
                parts.append("%s -S --needed %s" % (helper, " ".join(shlex.quote(p) for p in aur)))
        if not parts:
            return
        self.host.run_in_terminal(" ; ".join(parts), "„%s“ komplett installieren?\n\n%s" % (name, ", ".join(pkgs)), install=True)

    def refresh_installed(self):
        installed = backend.installed_names()
        for card in self._cards:
            card.set_installed(card.name in installed)

    def shutdown(self):
        """Laufende Suche beenden, bevor der QThread zerstört wird."""
        self._timer.stop()
        self._pending = False
        if self._thread is not None:
            self._worker.finished.disconnect(self.on_results)
            self._thread.quit()
            if not self._thread.wait(3000):  # Suche hängt (z. B. AUR-Timeout) -> hart beenden
                self._thread.terminate()
                self._thread.wait()
            self._thread = self._worker = None
