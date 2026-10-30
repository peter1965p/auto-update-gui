"""Seite „Wartung“: Aufräumen und Nacharbeiten nach Updates (Verwaiste, Cache, .pacnew, Dienste, Flatpak)."""
import os
import shlex
import shutil

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QPushButton

from .common import Card, make_label, sh
from .pages import ColumnsPage, InfoRow, hline

CACHE_DIR = "/var/cache/pacman/pkg"
PACNEW_CMD = ("found=0; for f in $(find /etc -xdev \\( -name '*.pacnew' -o -name '*.pacsave' \\) 2>/dev/null); do found=1; "
              "echo \"=== $f\"; base=\"${f%.pacnew}\"; base=\"${base%.pacsave}\"; "
              "if [ -f \"$base\" ]; then diff -u \"$base\" \"$f\"; else echo '(Original fehlt)'; fi; echo; done; "
              "[ $found = 0 ] && echo 'Keine .pacnew/.pacsave-Dateien.'; "
              "echo 'Einarbeiten: sudo pacdiff in einem normalen Terminal (öffnet einen Diff-Editor).'")


def gather():
    """Sammelt den Wartungsstand. Alles lokale, schnelle Abfragen."""
    orphans = sh("pacman", "-Qtdq").stdout.split()
    size = ""
    if os.path.isdir(CACHE_DIR):
        out = sh("du", "-sh", CACHE_DIR).stdout.split()
        size = out[0] if out else ""
    pacnew = sh("find", "/etc", "-xdev", "(", "-name", "*.pacnew", "-o", "-name", "*.pacsave", ")").stdout.split()
    failed = [l.split()[0] for l in sh("systemctl", "--failed", "--no-legend", "--plain").stdout.splitlines() if l.strip()]
    flatpaks = 0
    if shutil.which("flatpak"):
        flatpaks = len(sh("flatpak", "list", "--app").stdout.splitlines())
    return dict(orphans=orphans, cache_size=size, pacnew=pacnew, failed=failed, flatpaks=flatpaks,
                paccache=bool(shutil.which("paccache")))


class MaintenancePage(ColumnsPage):
    def __init__(self, host):
        super().__init__()
        self.host = host

    def _button(self, text, fn, primary=False):
        b = QPushButton(text)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        if primary:
            b.setObjectName("primary")
        b.clicked.connect(fn)
        return b

    def refresh(self):
        info = gather()
        self.reset()
        h = self.host

        orph = Card("Verwaiste Pakete")
        n = len(info["orphans"])
        orph.lay.addWidget(make_label("Abhängigkeiten, die nichts mehr braucht. Entfernen spart Platz und hält das System sauber.", "hint", True))
        orph.lay.addWidget(InfoRow("✓" if not n else str(n), "ok" if not n else "warn",
                                   "Keine verwaisten Pakete" if not n else "%d verwaiste Pakete" % n,
                                   ", ".join(info["orphans"][:8]) + (" …" if n > 8 else "")))
        if n:
            orph.lay.addWidget(self._button("Verwaiste entfernen", h.maint_orphans, True))

        cache = Card("Paket-Cache")
        cache.lay.addWidget(make_label("Heruntergeladene Pakete bleiben in %s liegen und wachsen mit der Zeit." % CACHE_DIR, "hint", True))
        cache.lay.addWidget(InfoRow("▤", "", "Größe: %s" % (info["cache_size"] or "unbekannt")))
        row_btns = []
        if info["paccache"]:
            row_btns.append(self._button("Alte Versionen entfernen (letzte 2 behalten)", h.maint_cache_keep))
        row_btns.append(self._button("Cache leeren", h.maint_cache))
        for b in row_btns:
            cache.lay.addWidget(b)

        conf = Card("Konfigurationsdateien (.pacnew)")
        conf.lay.addWidget(make_label("Neue Standard-Konfigurationen nach Updates. Sie sollten mit deinen Einstellungen abgeglichen werden.", "hint", True))
        pn = len(info["pacnew"])
        conf.lay.addWidget(InfoRow("✓" if not pn else str(pn), "ok" if not pn else "warn",
                                   "Nichts abzugleichen" if not pn else "%d Datei(en) warten" % pn,
                                   "\n".join(info["pacnew"][:6]) + ("\n…" if pn > 6 else "")))
        if pn:
            conf.lay.addWidget(self._button("Unterschiede anzeigen", lambda: h.run_in_terminal(PACNEW_CMD, "Unterschiede der .pacnew-Dateien anzeigen?"), True))

        svc = Card("Systemdienste")
        svc.lay.addWidget(make_label("Dienste, die nach dem Start oder einem Update fehlgeschlagen sind.", "hint", True))
        nf = len(info["failed"])
        svc.lay.addWidget(InfoRow("✓" if not nf else str(nf), "ok" if not nf else "warn",
                                  "Alle Dienste laufen" if not nf else "%d fehlgeschlagen" % nf, ", ".join(info["failed"][:6])))
        if nf:
            svc.lay.addWidget(self._button("Details anzeigen", lambda: h.run_in_terminal("systemctl --failed --no-pager", "Fehlgeschlagene Dienste anzeigen?")))

        left, right = [orph, cache], [conf, svc]
        if info["flatpaks"]:
            fp = Card("Flatpak")
            fp.lay.addWidget(InfoRow("▣", "", "%d Flatpak-Anwendungen installiert" % info["flatpaks"]))
            fp.lay.addWidget(self._button("Flatpaks aktualisieren", lambda: h.run_in_terminal("flatpak update", "Flatpaks aktualisieren?")))
            right.append(fp)
        self.add_column(*left)
        self.add_column(*right)
