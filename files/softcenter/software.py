"""Seite „Software“: Paketsuche (Repo + AUR), kuratierte Sammlungen, installierte Pakete."""
import shlex
import shutil

import urllib.parse

from PyQt6.QtCore import QSize, Qt, QThread, QTimer, QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (QAbstractItemView, QButtonGroup, QFrame, QHBoxLayout, QLabel, QLineEdit, QListWidget,
                             QListWidgetItem, QMenu, QMessageBox, QPushButton, QVBoxLayout, QWidget)

from . import backend
from .catalog import GROUPS, PROFILES
from .common import repolish

PAGE_SIZE = 60  # so viele Karten werden auf einmal gebaut
CARD_HEIGHT = 88
SCOPES = (("Alle", "all"), ("Repo", "repo"), ("AUR", "aur"), ("Flathub", "flatpak"))
INSTALLED_SCOPES = (("Alle", "installed"), ("Selbst installiert", "explicit"), ("Fremd / AUR", "foreign"))


class PackageCard(QFrame):
    def __init__(self, source, name, version, desc, installed, on_install, on_remove):
        super().__init__()
        self.setObjectName("pcard")
        self.name = name
        self.source = source

        title = QLabel(name)
        title.setObjectName("pkgTitle")
        version_lbl = QLabel(version)
        version_lbl.setObjectName("pkgMeta")
        self.badge = QLabel(source)
        self.badge.setObjectName("pkgBadge")
        self.badge.setProperty("source", source if source in ("aur", "flatpak") else "repo")
        self.desc = QLabel(desc or "Keine Beschreibung")
        self.desc.setObjectName("pkgDesc")
        self.desc.setWordWrap(False)
        self.desc.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        self.desc.setToolTip(desc)

        self.button = QPushButton()
        self.button.setObjectName("primary")
        self.button.setFixedWidth(130)
        self.button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.button.clicked.connect(lambda: on_remove(name, source) if self.installed else on_install(source, name))
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
        self._running = []     # laufende Suchen (Thread, Worker)
        self._gen = 0          # Nummer der aktuellen Suche
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

        self.web_btn = QPushButton("Nichts Passendes? Im Web suchen …")
        self.web_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.web_btn.clicked.connect(self.web_search)
        self.web_btn.hide()

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
        pk.addWidget(self.web_btn)

    # --- Ansicht wechseln ---
    def show_view(self, kind, name):
        """kind: 'group' | 'profile' | 'installed' (vom Hauptfenster nach einem Klick in der Seitenleiste)."""
        self._view = (kind, name)
        profile = kind == "profile"
        installed_view = kind == "installed"
        self.install_profile_btn.setVisible(profile)
        self.web_btn.hide()
        scopes = INSTALLED_SCOPES if installed_view else SCOPES
        for i, b in enumerate(self.chip_widgets):
            if i < len(scopes):
                b.setText(scopes[i][0])
                b.setProperty("scope", scopes[i][1])
            b.setVisible(not profile and i < len(scopes))
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
        # Jede Suche läuft in einem eigenen Thread; alte Suchen (z. B. mit langsamem AUR) werden einfach ignoriert,
        # damit ein neuer Suchbegriff nie auf sie warten muss.
        self._gen += 1
        gen = self._gen
        keywords = GROUPS.get(self._view[1]) if self._view[0] == "group" else None
        thread = QThread(self)
        worker = backend.SearchWorker(term, self.current_scope(), keywords)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(lambda rows, error, g=gen: self.on_results(rows, error, g))
        worker.partial.connect(lambda rows, g=gen: self.on_partial(rows, g))
        worker.finished.connect(thread.quit)
        thread.finished.connect(lambda t=thread: self._running.remove((t, worker)) if (t, worker) in self._running else None)
        thread.finished.connect(thread.deleteLater)
        self._running.append((thread, worker))
        self.status.setText("Suche ...")
        thread.start()

    def on_partial(self, rows, gen):
        """Repo-Treffer zeigen, während das AUR noch antwortet."""
        if gen != self._gen or self._view[0] == "profile":
            return
        self.set_rows(rows)
        self.status.setText("%d Pakete – AUR/Flathub werden noch durchsucht ..." % len(rows))

    def on_results(self, rows, error, gen):
        if gen != self._gen or self._view[0] == "profile":
            return
        self.set_rows(rows)
        self.web_btn.setVisible(bool(self.search.text().strip()) and self._view[0] != "installed")
        text = "%d Pakete" % len(rows)
        if self.current_scope() == "flatpak" and not backend.flatpak_available():
            text = "flatpak ist nicht installiert (sudo pacman -S flatpak)"
        self.status.setText(text + (" !" if error else ""))
        self.status.setToolTip(error)

    def show_profile(self, name):
        self._timer.stop()
        pkgs = PROFILES[name]
        info = backend.package_info(pkgs)
        installed = backend.installed_names()
        rows, resolved = [], set()
        for p in pkgs:
            f = info.get(p, {})
            if f:
                rows.append((f["Repository"], p, f.get("Version", ""), f.get("Description", ""), p in installed))
            else:  # nicht unter diesem Namen im Repo -> ersetzt ihn ein anderes Paket (redis -> valkey)?
                prov = None if p in installed else backend.resolve_provider(p)
                if prov:
                    rows.append((prov[0], prov[1], prov[2], "ersetzt %s – %s" % (p, prov[3]), prov[4] or prov[1] in installed))
                    resolved.add(p)
                else:  # sonst über den AUR-Helper versuchen
                    rows.append(("aur", p, "", "Nicht in den Repos – Installation über das AUR", p in installed))
        self._set_aur = [p for p in pkgs if p not in info and p not in installed and p not in resolved]
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
        if source == "flatpak":
            self.host.run_in_terminal("flatpak install -y flathub %s" % shlex.quote(name), None, install=True)
            return
        if source == "aur":
            helper = next((h for h in backend.AUR_HELPERS if shutil.which(h)), None)
            if helper is None:
                QMessageBox.warning(self, "AUR-Helper fehlt", "Zum Installieren aus dem AUR wird paru oder yay benötigt.")
                return
            cmd = "%s -S --needed %s" % (helper, shlex.quote(name))
        else:
            cmd = "sudo pacman -S --needed %s" % shlex.quote(name)
        self.host.run_in_terminal(cmd, None, install=True)

    def remove(self, name, source="repo"):
        if source == "flatpak":
            self.host.run_in_terminal("flatpak uninstall -y %s" % shlex.quote(name),
                                      "Flatpak „%s“ entfernen?" % name)
            return
        self.host.remove_packages([name])

    def web_search(self):
        """Nichts Passendes gefunden: im Web weitersuchen (im Browser – nichts wird automatisch installiert)."""
        term = urllib.parse.quote(self.search.text().strip())
        menu = QMenu(self)
        for label, url in (("GitHub durchsuchen", "https://github.com/search?type=repositories&q=%s" % term),
                           ("Flathub im Browser", "https://flathub.org/apps/search?q=%s" % term),
                           ("AUR im Browser", "https://aur.archlinux.org/packages?K=%s" % term),
                           ("Im Web suchen", "https://duckduckgo.com/?q=%s+linux+install" % term)):
            menu.addAction(label, lambda u=url: QDesktopServices.openUrl(QUrl(u)))
        menu.exec(self.web_btn.mapToGlobal(self.web_btn.rect().bottomLeft()))

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
        """Laufende Suchen beenden, bevor die QThreads zerstört werden."""
        self._timer.stop()
        self._gen += 1
        for thread, _worker in list(self._running):
            thread.quit()
            if not thread.wait(3000):  # Suche hängt (z. B. AUR-Timeout) -> hart beenden
                thread.terminate()
                thread.wait()
        self._running.clear()
