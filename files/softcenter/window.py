"""Hauptfenster: Seitenleiste mit Bereichen, Kopfzeile und die Seiten (Updates, Software, Wartung, System)."""
import shlex

from PyQt6.QtCore import QEvent, QSize, Qt, QTimer
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import (QApplication, QFrame, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMessageBox, QPushButton,
                             QStackedWidget, QVBoxLayout, QWidget)

from . import backend, common, system_info
from .catalog import CURATED, GROUPS
from .common import apply_theme, cfg, make_label, set_state, theme
from .maintenance import MaintenancePage
from .pages import AdvisorPage, OverviewPage
from .software import SoftwarePage
from .terminal_dialog import TerminalDialog
from .updates import UpdatesPage

APP_NAME = "SoftCenter"
PAGE_UPDATES, PAGE_SOFTWARE, PAGE_MAINT, PAGE_OVERVIEW, PAGE_ADVISOR = range(5)


class PageHeader(QWidget):
    """Icon, Titel, Untertitel, Status-Pill und Hell/Dunkel-Schalter über jeder Seite."""

    def __init__(self):
        super().__init__()
        self.icon = QLabel()
        self.icon.setObjectName("headerIcon")
        self.icon.setFixedSize(44, 44)
        self.icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title = make_label("", "pageTitle")
        self.subtitle = make_label("", "pageSubtitle")
        self.pill = make_label("", "pill")
        self.pill.setMinimumWidth(120)
        self.pill.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.pill.setVisible(False)
        self.theme_btn = QPushButton()
        self.theme_btn.setObjectName("flat")
        self.theme_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        texts = QVBoxLayout()
        texts.setSpacing(0)
        texts.addWidget(self.title)
        texts.addWidget(self.subtitle)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(14)
        row.addWidget(self.icon)
        row.addLayout(texts, 1)
        row.addWidget(self.pill, 0, Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(self.theme_btn)

    def set(self, icon, title, subtitle, pill=None, state="on"):
        self.icon.setText(icon)
        self.title.setText(title)
        self.subtitle.setText(subtitle)
        self.pill.setVisible(bool(pill))
        if pill:
            self.pill.setText(pill)
            set_state(self.pill, state)


class MainWindow(QWidget):
    def __init__(self, app):
        super().__init__()
        self.app = app
        self.setObjectName("root")
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(QIcon.fromTheme("system-software-update"))
        self.resize(1320, 820)
        self.setMinimumSize(860, 560)
        self._sysinfo = None
        self._upd_header = ("", "", "off")
        self._build_ui()
        self.updates.refresh_header()
        self.nav.setCurrentRow(self._row_of(("updates", "")))
        app.aboutToQuit.connect(self.software.shutdown)

    # --- Aufbau ---
    def _build_ui(self):
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(240)
        logo = QLabel("◆ " + APP_NAME)
        logo.setObjectName("logo")
        sub = QLabel("Software · System · Updates")
        sub.setObjectName("logoSub")
        self.nav = QListWidget()
        self.nav.setObjectName("nav")
        self.nav.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        self._add_section("Updates & System")
        self.nav_updates = self._add_item("Updates", ("updates", ""))
        self._add_item("Installiert", ("installed", ""))
        self._add_item("Wartung", ("maintenance", ""))
        self._add_item("Systemübersicht", ("overview", ""))
        self._add_item("Desktop-Berater", ("advisor", ""))
        self._add_section("Entdecken")
        for g in GROUPS:
            self._add_item(g, ("group", g))
        for top, subs in CURATED.items():
            self._add_section(top)
            for s in subs:
                self._add_item(s, ("profile", "%s › %s" % (top, s)))
        self.nav.currentItemChanged.connect(self.on_nav_changed)

        settings_btn = QPushButton("⚙  Einstellungen")
        settings_btn.setObjectName("flat")
        settings_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        settings_btn.clicked.connect(lambda: self.updates.open_settings())
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(0, 0, 0, 12)
        side.setSpacing(0)
        side.addWidget(logo)
        side.addWidget(sub)
        side.addWidget(self.nav, 1)
        side.addWidget(settings_btn)

        content = QWidget()
        content.setObjectName("content")
        self.header = PageHeader()
        self.header.theme_btn.clicked.connect(self.toggle_theme)
        self._update_theme_btn()

        self.updates = UpdatesPage(self.app, self)
        self.software = SoftwarePage(self)
        self.maint = MaintenancePage(self)
        self.overview = OverviewPage(self)
        self.advisor = AdvisorPage()
        self.advisor.install_requested.connect(lambda cmd, q: self.run_in_terminal(cmd, q, install=True))
        self.stack = QStackedWidget()
        for page in (self.updates, self.software, self.maint, self.overview, self.advisor):
            self.stack.addWidget(page)
        self.updates.header_changed.connect(self.on_updates_header)
        self.updates.badge_changed.connect(self.on_badge)

        c = QVBoxLayout(content)
        c.setContentsMargins(28, 22, 28, 12)
        c.setSpacing(16)
        c.addWidget(self.header)
        c.addWidget(self.stack, 1)

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(sidebar)
        root.addWidget(content, 1)

    def _add_section(self, text):
        it = QListWidgetItem(text.upper())
        it.setFlags(Qt.ItemFlag.NoItemFlags)
        f = it.font()
        f.setPointSize(8)
        f.setBold(True)
        it.setFont(f)
        it.setSizeHint(QSize(0, 34))
        self.nav.addItem(it)

    def _add_item(self, text, data):
        it = QListWidgetItem(text)
        it.setData(Qt.ItemDataRole.UserRole, data)
        it.setSizeHint(QSize(0, 36))
        self.nav.addItem(it)
        return it

    def _row_of(self, data):
        for i in range(self.nav.count()):
            if self.nav.item(i).data(Qt.ItemDataRole.UserRole) == data:
                return i
        return 1

    # --- Fenster / Tray ---
    def bring_to_front(self):
        self.show()
        self.raise_()
        self.activateWindow()

    def closeEvent(self, event):  # X schließt nur ins Systray
        if self.updates.tray.isVisible():
            event.ignore()
            self.hide()
        else:
            event.accept()

    def changeEvent(self, event):
        # Beim Zurückkehren ins Fenster den Installiert-Stand neu prüfen (z. B. nach einer Installation im Terminal)
        if event.type() == QEvent.Type.ActivationChange and self.isActiveWindow():
            self.software.refresh_installed()
        super().changeEvent(event)

    # --- Theme ---
    def _update_theme_btn(self):
        self.header.theme_btn.setText("☀ Hell" if theme.get("dark") else "☾ Dunkel")

    def toggle_theme(self):
        cfg.setValue("theme", "light" if theme.get("dark") else "dark")
        apply_theme(self.app)
        self.updates.update_tray_badge()
        self._update_theme_btn()

    # --- Navigation ---
    def on_nav_changed(self, item, _prev):
        if item is None or item.data(Qt.ItemDataRole.UserRole) is None:
            return
        kind, name = item.data(Qt.ItemDataRole.UserRole)
        if kind == "updates":
            self.stack.setCurrentIndex(PAGE_UPDATES)
            self.show_updates_header()
        elif kind == "maintenance":
            self.header.set("✚", "Wartung", "Aufräumen und Nacharbeiten nach Updates")
            self.maint.refresh()
            self.stack.setCurrentIndex(PAGE_MAINT)
        elif kind in ("overview", "advisor"):
            self.show_system_page(kind)
        else:
            icons = {"group": "▦", "profile": "★", "installed": "✓"}
            subtitle = {"group": "Pakete aus Repo und AUR durchsuchen",
                        "profile": "Kuratierte Auswahl – einzeln oder komplett installieren",
                        "installed": "Alle Pakete auf diesem System"}[kind]
            self.header.set(icons[kind], name or "Installierte Pakete", subtitle)
            self.stack.setCurrentIndex(PAGE_SOFTWARE)
            self.software.show_view(kind, name)

    def on_updates_header(self, subtitle, pill, state):
        self._upd_header = (subtitle, pill, state)
        if self.stack.currentIndex() == PAGE_UPDATES:
            self.show_updates_header()

    def show_updates_header(self):
        subtitle, pill, state = self._upd_header
        self.header.set("⟳", "Updates", subtitle, pill or None, state)

    def on_badge(self, n):
        self.nav_updates.setText("Updates  (%d)" % n if n else "Updates")

    def show_system_page(self, kind):
        if self._sysinfo is None:
            self._sysinfo = system_info.gather()
        info = self._sysinfo
        if kind == "overview":
            self.header.set("◉", "Systemübersicht", "%s · %s" % (info["distro"], info["kernel"]),
                            "Session: %s" % info["session"], "on")
            self.overview.show_info(info)
            self.stack.setCurrentIndex(PAGE_OVERVIEW)
        else:
            self.header.set("✦", "Desktop-Berater", "Welche Desktop-Umgebung passt zu dir und deinem Rechner?")
            self.advisor.show_info(info)
            self.stack.setCurrentIndex(PAGE_ADVISOR)

    # --- Befehle im eingebetteten Terminal ---
    def run_in_terminal(self, cmd, question=None, install=False):
        """Führt einen Befehl im Pseudo-Terminal aus (Passwort- und Rückfragen funktionieren). Installationen
        warnen vorher, wenn noch Updates offen sind: auf Arch sollte man zuerst aktualisieren (keine Teil-Updates)."""
        pending = self.updates.counts.get("repo", 0)
        if install and pending:
            box = QMessageBox(self)
            box.setWindowTitle("Erst aktualisieren?")
            box.setIcon(QMessageBox.Icon.Question)
            box.setText("Es warten %d Systemupdates.\n\nAuf Arch sollte man vor dem Installieren aktualisieren, sonst "
                        "können Teil-Updates Probleme machen." % pending)
            b_first = box.addButton("Erst aktualisieren, dann installieren", QMessageBox.ButtonRole.AcceptRole)
            b_now = box.addButton("Trotzdem installieren", QMessageBox.ButtonRole.ActionRole)
            box.addButton("Abbrechen", QMessageBox.ButtonRole.RejectRole)
            box.exec()
            clicked = box.clickedButton()
            if clicked is b_first:
                cmd = "sudo pacman -Syu && { %s ; }" % cmd
            elif clicked is not b_now:
                return
        if QMessageBox.question(self, "Ausführen", question or "Ausführen?\n\n%s" % cmd) != QMessageBox.StandardButton.Yes:
            return
        dlg = TerminalDialog(cmd, "SoftCenter – Terminal", self)
        dlg.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        if QApplication.activeModalWidget() is not None:
            # Läuft gerade ein modaler Dialog (z. B. "Sicherheit"), würde er Tastatur und Maus des Terminals sperren
            dlg.setWindowModality(Qt.WindowModality.ApplicationModal)
        dlg.finished_cmd.connect(lambda *_: self.after_command())
        dlg.rerun.connect(lambda c, d=dlg: (d.close(), QTimer.singleShot(0, lambda: self.run_in_terminal(c, "Befehl erneut ausführen?\n\n%s" % c))))
        dlg.show()

    def after_command(self):
        self.software.refresh_installed()
        self._sysinfo = None
        QTimer.singleShot(1500, lambda: self.updates.check_updates(True))
        if self.stack.currentIndex() == PAGE_MAINT:
            self.maint.refresh()

    def go_to(self, data):
        """Eine Seite der Seitenleiste per Daten ansteuern, z. B. ("installed", "")."""
        self.nav.setCurrentRow(self._row_of(data))

    def remove_packages(self, names, label=None):
        """Deinstallation mit Schutz und Vorschau: was würde alles entfernt, und wer braucht die Pakete noch?"""
        label = label or ", ".join(names)
        blocked = [n for n in names if backend.is_protected(n)]
        names = [n for n in names if n not in blocked]
        if not names:
            QMessageBox.warning(self, "Geschützt", "Diese Pakete sind systemkritisch und werden hier nicht entfernt:\n\n%s" % ", ".join(blocked))
            return
        ok, targets, _msg = backend.removal_preview(names)
        if not ok:
            who = ", ".join(targets[:12]) + (" …" if len(targets) > 12 else "")
            QMessageBox.warning(self, "Kann nicht entfernt werden",
                                "„%s“ wird noch gebraucht%s." % (label, (" von:\n\n" + who) if who else ""))
            return
        extra = [t for t in targets if t not in names]
        text = "„%s“ entfernen?\n\nEntfernt werden %d Pakete" % (label, len(targets))
        text += (", davon %d als nicht mehr benötigte Abhängigkeiten:\n%s" % (len(extra), ", ".join(extra[:20]) + (" …" if len(extra) > 20 else ""))
                 if extra else ".")
        if blocked:
            text += "\n\nÜbersprungen (systemkritisch, geschützt): %s" % ", ".join(blocked)
        self.run_in_terminal("sudo pacman -Rns " + " ".join(shlex.quote(n) for n in names), text)

    def maint_orphans(self):
        cmd = ('orphans=$(pacman -Qtdq); if [ -n "$orphans" ]; then echo "Verwaist:"; echo "$orphans"; '
               'sudo pacman -Rns $orphans; else echo "Keine verwaisten Pakete."; fi')
        self.run_in_terminal(cmd, "Verwaiste Pakete (nicht mehr benötigte Abhängigkeiten) suchen und entfernen?")

    def maint_cache(self):
        self.run_in_terminal("sudo pacman -Sc", "Paket-Cache nicht mehr installierter Pakete leeren?")

    def maint_cache_keep(self):
        self.run_in_terminal("sudo paccache -rk2", "Alte Paketversionen aus dem Cache entfernen (die letzten 2 bleiben)?")
