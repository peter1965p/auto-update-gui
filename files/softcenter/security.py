"""Sicherheit: Paket-Details, Dienste und Ports, Angaben des Arch-Sicherheitsteams und der Beheben-Plan.

Das Tool installiert hier nichts Fremdes und baut keine Entwicklungsstände. „Beheben“ heißt: ein vorhandenes Update
einspielen und, wo es keinen Fix gibt, die Gefahr verringern (unnötige Dienste stoppen, unnötige Pakete entfernen).
Jede Maßnahme wird einzeln mit Begründung gezeigt und läuft erst nach Bestätigung im Terminal."""
import json
import os
import re
import subprocess
import time
import urllib.request

from PyQt6.QtCore import QObject, Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (QCheckBox, QDialog, QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout,
                             QWidget)

from . import backend
from .common import Card, make_label, separator, set_state, sh

SEV_DE = {"critical": "kritisch", "high": "hoch", "medium": "mittel", "low": "niedrig"}
TRACKER_URL = "https://security.archlinux.org/issues/all.json"

# Kurze deutsche Erklärung häufiger Pakete (sonst die englische pacman-Beschreibung)
ROLE_DE = {
    "libxml2": "XML-Bibliothek (liest XML-Dateien)", "pam": "Anmeldung und Passwörter (PAM)",
    "openssl": "Verschlüsselung und HTTPS", "gnutls": "TLS-Verschlüsselung", "systemd": "Dienst- und Systemverwaltung",
    "coreutils": "Grundbefehle (ls, cp, mv …)", "perl": "Skriptsprache Perl", "python": "Skriptsprache Python",
    "libtiff": "TIFF-Bilder", "giflib": "GIF-Bilder", "libheif": "HEIF/AVIF-Bilder", "openjpeg2": "JPEG-2000-Bilder",
    "libpng": "PNG-Bilder", "libjpeg-turbo": "JPEG-Bilder", "apr": "Apache Portable Runtime (Basisbibliothek)",
    "cpio": "Archiv-Werkzeug cpio", "wget": "Dateien aus dem Web laden", "curl": "Dateien und URLs übertragen",
    "nginx": "Webserver", "postgresql": "Datenbankserver", "mariadb": "Datenbankserver", "openvpn": "VPN-Verbindungen",
    "lua51": "Skriptsprache Lua 5.1", "xdg-utils": "Desktop-Integration (Standardprogramme öffnen)",
    "glibc": "C-Standardbibliothek", "zlib": "Kompression", "sqlite": "Eingebettete Datenbank", "bash": "Shell",
    "sudo": "Rechte erhöhen", "openssh": "SSH (Fernzugriff)", "git": "Versionsverwaltung", "ffmpeg": "Audio und Video",
}
# Übliche Ports bekannter Server, um zu prüfen, ob sie von außen erreichbar sind
KNOWN_PORTS = {"nginx": [80, 443], "apache": [80, 443], "postgresql": [5432], "mariadb": [3306], "mysql": [3306],
               "redis": [6379], "openvpn": [1194], "openssh": [22], "docker": [2375], "mongodb": [27017]}


def run(*cmd):
    return subprocess.run(cmd, capture_output=True, text=True, env={"LC_ALL": "C", "PATH": "/usr/bin:/usr/local/bin"})


def role(name, info=None):
    """Kurze Erklärung, wozu ein Paket dient."""
    if name in ROLE_DE:
        return ROLE_DE[name]
    return (info or pkg_info(name)).get("desc", "") or "keine Beschreibung"


def pkg_info(name):
    """Angaben aus 'pacman -Qi': Beschreibung, Version, Installationsgrund, wer es braucht."""
    out = run("pacman", "-Qi", name).stdout
    d = {}
    for line in out.splitlines():
        k, sep, v = line.partition(":")
        if sep:
            d[k.strip()] = v.strip()

    def lst(key):
        v = d.get(key, "None")
        return [] if v == "None" else v.split()

    return dict(installed=bool(d), desc=d.get("Description", ""), version=d.get("Version", ""),
                explicit="explicit" in d.get("Install Reason", "").lower(),
                required=lst("Required By"), optional=lst("Optional For"), size=d.get("Installed Size", ""))


def pkg_services(name):
    """Systemd-Dienste, die ein Paket mitbringt, samt Zustand."""
    out = run("pacman", "-Ql", name).stdout
    units = sorted({m.group(1) for m in re.finditer(r"/usr/lib/systemd/system/([^/@]+\.service)$", out, re.M)})
    res = []
    for u in units:
        res.append(dict(unit=u, active=sh("systemctl", "is-active", u).stdout.strip(),
                        enabled=sh("systemctl", "is-enabled", u).stdout.strip()))
    return res


_LISTEN = [0.0, []]


def listeners():
    """Lauschende TCP-Ports: Liste (Adresse, Port, lokal?). Für wenige Sekunden zwischengespeichert."""
    if time.time() - _LISTEN[0] < 10:
        return _LISTEN[1]
    res = []
    for line in run("ss", "-tlnH").stdout.splitlines():
        f = line.split()
        if len(f) < 4 or ":" not in f[3]:
            continue
        addr, _, port = f[3].rpartition(":")
        local = addr.startswith("127.") or addr in ("[::1]", "::1") or "%lo" in addr
        if port.isdigit():
            res.append((addr, int(port), local))
    _LISTEN[0], _LISTEN[1] = time.time(), res
    return res


def exposure(name):
    """Bei bekannten Servern: (von außen erreichbare Ports, nur lokal erreichbare Ports)."""
    ports = KNOWN_PORTS.get(name, [])
    lst = listeners()
    ext = sorted({p for _a, p, loc in lst if p in ports and not loc})
    loc = sorted({p for _a, p, loc_ in lst if p in ports and loc_} - set(ext))
    return ext, loc


class TrackerWorker(QObject):
    """Holt die Liste des Arch-Sicherheitsteams im Hintergrund (rund 1 MB)."""
    finished = pyqtSignal(object)
    cache = None

    def run(self):
        if TrackerWorker.cache is None:
            try:
                with urllib.request.urlopen(TRACKER_URL, timeout=15) as r:
                    TrackerWorker.cache = json.load(r)
            except Exception:
                TrackerWorker.cache = []
        self.finished.emit(TrackerWorker.cache)


def tracker_entries(data, name):
    """Offene Meldungen zu einem Paket aus der Liste des Sicherheitsteams."""
    return [r for r in data if name in r.get("packages", []) and r.get("status") == "Vulnerable"]


def cve_links(cves, limit=8):
    shown = "".join(f'<a href="https://security.archlinux.org/{c}">{c}</a> ' for c in cves[:limit])
    return shown + (f"+{len(cves) - limit} weitere" if len(cves) > limit else "")


# ---------------------------------------------------------------- Beheben-Plan

def assess(item):
    """Bewertet ein verwundbares Paket: Rolle, Abhängige, Dienste, Erreichbarkeit und mögliche Maßnahmen."""
    name = item["name"]
    info = pkg_info(name)
    protected = backend.is_protected(name)
    needed = len(info["required"])
    svcs = pkg_services(name) if not (protected or needed) else []     # nur dort gibt es Maßnahmen; Details laden sonst nach
    ext, loc = exposure(name)
    a = dict(item=item, info=info, services=svcs, ext=ext, local=loc, protected=protected, needed=needed,
             role=role(name, info), actions=[], note="")
    unit_list = [s["unit"] for s in svcs]
    live = [s for s in svcs if s["active"] == "active" or s["enabled"] == "enabled"]
    if item["fix"]:
        a["note"] = "Für dieses Paket gibt es ein Update. Es wird mit „Sicherheits-Updates installieren“ eingespielt."
    elif protected or needed:
        a["note"] = ("Systembaustein: %d Paket%s brauchen es – es kann nicht entfernt werden. Hier hilft nur das Warten auf einen Fix."
                     % (needed, "e" if needed != 1 else "")) if needed else "Systemkritisch und geschützt – nicht entfernbar."
    elif live:
        exp = ("von außen erreichbar auf Port %s" % ", ".join(map(str, ext))) if ext else \
              ("läuft nur lokal (Port %s)" % ", ".join(map(str, loc)) if loc else "Erreichbarkeit unbekannt")
        a["note"] = "Der Dienst %s ist aktiv bzw. beim Start eingeschaltet und %s." % (", ".join(unit_list), exp)
        a["actions"].append(dict(key="stop:" + name, kind="stop", pkg=name, checked=False,
                                 title="Dienst %s stoppen und beim Start ausschalten" % ", ".join(unit_list),
                                 detail="Sinnvoll, wenn du ihn nicht brauchst. Läuft er für ein Programm von dir, lass ihn an.",
                                 cmd="sudo systemctl disable --now " + " ".join(unit_list)))
    elif svcs:      # Dienst vorhanden, aber aus und deaktiviert
        a["note"] = "Der Dienst %s ist aus und beim Start deaktiviert, niemand braucht das Paket." % ", ".join(unit_list)
        rec = info["explicit"] and not info["optional"]
        a["actions"].append(dict(key="remove:" + name, kind="remove", pkg=name, checked=rec,
                                 title="Paket „%s“ entfernen" % name,
                                 detail="Niemand braucht es und der Dienst läuft nicht." + (" Empfohlen." if rec else ""),
                                 cmd=None))
    else:
        a["note"] = "Niemand braucht dieses Paket."
        orphan = not info["explicit"] and not info["optional"]
        a["actions"].append(dict(key="remove:" + name, kind="remove", pkg=name, checked=orphan,
                                 title="Paket „%s“ entfernen" % name,
                                 detail=("Verwaiste Abhängigkeit – kann weg." if orphan else
                                         "Du hast es selbst installiert%s – nur entfernen, wenn du es nicht mehr nutzt."
                                         % (" (optional genutzt von %d Paket%s)" % (len(info["optional"]), "en" if len(info["optional"]) != 1 else "")
                                            if info["optional"] else "")),
                                 cmd=None))
    return a


def build_plan(items, assessments=None):
    """Alle Maßnahmen für die verwundbaren Pakete. Rückgabe: (Maßnahmen, Bewertungen)."""
    assessments = assessments or [assess(i) for i in items]
    actions = []
    fixable = [a for a in assessments if a["item"]["fix"]]
    if fixable:
        actions.append(dict(key="update", kind="update", pkg="", checked=True,
                            title="Sicherheits-Updates installieren (%d Paket%s mit Fix)" % (len(fixable), "e" if len(fixable) != 1 else ""),
                            detail="Spielt das vorhandene Update ein: " + ", ".join(a["item"]["name"] for a in fixable[:6]),
                            cmd="sudo pacman -Syu"))
    for a in assessments:
        actions.extend(a["actions"])
    # Entfernen: Vorschau, ob es überhaupt geht (wer braucht es noch?)
    rem = [x for x in actions if x["kind"] == "remove"]
    for x in rem:
        ok, targets, _m = backend.removal_preview([x["pkg"]])
        if not ok:
            x["blocked"] = "wird noch gebraucht von: " + ", ".join(targets[:6]) if targets else "kann nicht entfernt werden"
            x["checked"] = False
        else:
            extra = [t for t in targets if t != x["pkg"]]
            if extra:
                x["detail"] += " Mit entfernt würden: " + ", ".join(extra[:6])
    return actions, assessments


def plan_command(actions, selected):
    """Fügt die gewählten Maßnahmen zu einem Befehl zusammen (bricht beim ersten Fehler ab)."""
    parts = []
    chosen = [a for a in actions if a["key"] in selected and not a.get("blocked")]
    for a in chosen:
        if a["kind"] == "update":
            parts.append(a["cmd"])
    for a in chosen:
        if a["kind"] == "stop":
            parts.append(a["cmd"])
    rem = [a["pkg"] for a in chosen if a["kind"] == "remove"]
    if rem:
        parts.append("sudo pacman -Rns " + " ".join(rem))
    return " && ".join(parts)


# ---------------------------------------------------------------- Dialoge

def _scroll_body(dlg):
    outer = QVBoxLayout(dlg)
    outer.setContentsMargins(0, 0, 0, 0)
    sc = QScrollArea()
    sc.setWidgetResizable(True)
    sc.setFrameShape(QFrame.Shape.NoFrame)
    outer.addWidget(sc, 1)
    body = QWidget()
    body.setObjectName("content")
    sc.setWidget(body)
    lay = QVBoxLayout(body)
    lay.setContentsMargins(20, 18, 20, 16)
    lay.setSpacing(14)
    return outer, lay


def rich(text, name="value"):
    lbl = make_label(text, name, True)
    lbl.setTextFormat(Qt.TextFormat.RichText)
    lbl.setOpenExternalLinks(True)
    lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
    return lbl


class DetailDialog(QDialog):
    """Alles zu einem verwundbaren Paket: wozu, wer braucht es, Dienste, Erreichbarkeit, Meldungen des Sicherheitsteams."""

    def __init__(self, parent, a, host):
        super().__init__(parent)
        self.setObjectName("root")
        it, info = a["item"], a["info"]
        self.setWindowTitle("Sicherheit – %s" % it["name"])
        self.resize(640, 620)
        outer, lay = _scroll_body(self)
        lay.addWidget(make_label(it["name"], "h1"))
        lay.addWidget(make_label("%s · %s%s" % (a["role"], SEV_DE.get(it["sev"], "unbekannt"),
                                                 " · Fix: " + it["fix"] if it["fix"] else " · derzeit kein Fix"), "muted", True))

        c = Card("Was ist das, und wer braucht es?")
        lay.addWidget(c)
        rows = [("Beschreibung", info["desc"] or "–"), ("Version", info["version"] or "–"),
                ("Installiert", "von dir selbst ausgewählt" if info["explicit"] else "als Abhängigkeit mitgekommen")]
        for k, v in rows:
            r = QHBoxLayout()
            r.addWidget(make_label(k, "key"))
            r.addWidget(make_label(v, "value", True), 1)
            c.lay.addLayout(r)
        req = info["required"]
        c.lay.addWidget(make_label("Gebraucht von %d Paket%s%s" % (len(req), "en" if len(req) != 1 else "",
                                   (": " + ", ".join(req[:14]) + (" …" if len(req) > 14 else "")) if req else ""), "value", True))
        if info["optional"]:
            c.lay.addWidget(make_label("Optional genutzt von %d weiteren Paketen." % len(info["optional"]), "hint", True))
        c.lay.addWidget(make_label(a["note"], "detail", True))

        a["services"] = a["services"] or pkg_services(it["name"])
        if a["services"]:
            c = Card("Dienste und Erreichbarkeit")
            lay.addWidget(c)
            for s in a["services"]:
                c.lay.addWidget(make_label("%s: %s, beim Start %s" % (s["unit"], "aktiv" if s["active"] == "active" else "aus",
                                                                       "eingeschaltet" if s["enabled"] == "enabled" else "ausgeschaltet"), "value", True))
            if name_ports := KNOWN_PORTS.get(it["name"]):
                if a["ext"]:
                    c.lay.addWidget(make_label("⚠ Von außen erreichbar auf Port %s." % ", ".join(map(str, a["ext"])), "warnText", True))
                elif a["local"]:
                    c.lay.addWidget(make_label("Nur lokal erreichbar (Port %s) – nicht aus dem Netzwerk." % ", ".join(map(str, a["local"])), "hint", True))
                else:
                    c.lay.addWidget(make_label("Hört auf keinem der üblichen Ports (%s)." % ", ".join(map(str, name_ports)), "hint", True))

        c = Card("Meldungen des Arch-Sicherheitsteams")
        lay.addWidget(c)
        self.tracker_box = c.lay
        c.lay.addWidget(rich("CVEs: " + cve_links(it["cves"]) + (f"<br>Art: {it['type']}" if it["type"] else "")))
        self.wait = make_label("Lade Angaben …", "hint")
        c.lay.addWidget(self.wait)
        self._name = it["name"]
        row = QHBoxLayout()
        lay.addLayout(row)
        row.addStretch()
        b = QPushButton("Schließen")
        b.setObjectName("primary")
        b.clicked.connect(self.accept)
        row.addWidget(b)
        self._fetch()

    def _fetch(self):
        self._thread = QThread(self)
        self._worker = TrackerWorker()
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.finished.connect(self._done)
        self._thread.start()

    def _done(self, data):
        self._thread.quit()
        self._thread.wait()
        self.wait.hide()
        rec = tracker_entries(data, self._name)
        if not rec:
            self.tracker_box.addWidget(make_label("Keine Angaben erhalten (offline?)." if not data else "Keine offene Meldung gefunden.", "hint", True))
            return
        for r in rec[:6]:
            line = ('<a href="https://security.archlinux.org/%s">%s</a> · %s · betrifft ab %s · %s'
                    % (r["name"], r["name"], SEV_DE.get(r["severity"].lower(), r["severity"]), r["affected"] or "?",
                       "Fix: " + r["fixed"] if r["fixed"] else "noch kein Fix"))
            if r.get("ticket"):
                line += ' · <a href="https://gitlab.archlinux.org/archlinux/packaging/packages/%s/-/issues/%s">Ticket</a>' % (self._name, r["ticket"])
            self.tracker_box.addWidget(rich(line, "hint"))

    def done(self, r):
        if getattr(self, "_thread", None) is not None and self._thread.isRunning():
            self._thread.quit()
            self._thread.wait(2000)
        super().done(r)


class FixPlanDialog(QDialog):
    """„Beheben“: zeigt jede mögliche Maßnahme mit Begründung zum Ankreuzen; ausgeführt wird im Terminal."""

    def __init__(self, parent, actions, assessments, host):
        super().__init__(parent)
        self.host, self.actions = host, actions
        self.setObjectName("root")
        self.setWindowTitle("Sicherheitslücken beheben")
        self.resize(680, 640)
        outer, lay = _scroll_body(self)
        lay.addWidget(make_label("Beheben und Gefahr verringern", "h1"))
        lay.addWidget(make_label("Das Tool baut keine Entwicklungsstände und installiert nichts Fremdes. Es spielt vorhandene Updates ein "
                                 "und schlägt sonst nur Maßnahmen vor, die das Risiko senken. Kreuze an, was passieren soll – "
                                 "du siehst den Befehl, bevor etwas läuft.", "desc", True))
        self.boxes = {}
        c = Card("Maßnahmen")
        lay.addWidget(c)
        if not actions:
            c.lay.addWidget(make_label("Es gibt derzeit nichts, was sich sicher beheben ließe. Die betroffenen Pakete sind Systembausteine, "
                                       "die andere Programme brauchen – dafür muss ein Fix erscheinen. Das Tool meldet sich dann.", "value", True))
        for i, a in enumerate(actions):
            if i:
                c.lay.addWidget(separator())
            cb = QCheckBox(a["title"])
            cb.setChecked(a["checked"] and not a.get("blocked"))
            cb.setEnabled(not a.get("blocked"))
            cb.toggled.connect(self.refresh)
            self.boxes[a["key"]] = cb
            c.lay.addWidget(cb)
            c.lay.addWidget(make_label(a.get("blocked") and "Nicht möglich: " + a["blocked"] or a["detail"],
                                       "warnText" if a.get("blocked") else "desc", True))
        rest = [x for x in assessments if not x["actions"] and not x["item"]["fix"]]
        if rest:
            c = Card("Nichts zu tun (Systembausteine)")
            lay.addWidget(c)
            c.lay.addWidget(make_label("Diese %d Pakete brauchen andere Programme; sie lassen sich nicht entfernen. Sobald ein Fix erscheint, "
                                       "kommt er mit dem normalen Update: %s" % (len(rest), ", ".join(x["item"]["name"] for x in rest[:12]) +
                                                                                 (" …" if len(rest) > 12 else "")), "desc", True))
        self.cmd_label = make_label("", "mono", True)
        lay.addWidget(self.cmd_label)
        row = QHBoxLayout()
        lay.addLayout(row)
        row.addStretch()
        b = QPushButton("Abbrechen")
        b.clicked.connect(self.reject)
        row.addWidget(b)
        self.go = QPushButton("Ausgewählte ausführen")
        self.go.setObjectName("primary")
        self.go.clicked.connect(self.execute)
        row.addWidget(self.go)
        self.refresh()

    def selected(self):
        return {k for k, cb in self.boxes.items() if cb.isChecked()}

    def refresh(self, *_):
        cmd = plan_command(self.actions, self.selected())
        self.cmd_label.setText(("Befehl: " + cmd) if cmd else "Nichts ausgewählt.")
        self.go.setEnabled(bool(cmd))

    def execute(self):
        cmd = plan_command(self.actions, self.selected())
        if not cmd:
            return
        self.accept()
        self.host.run_in_terminal(cmd, "Diese Maßnahmen ausführen?\n\n%s" % cmd)


class SecurityDialog(QDialog):
    """Übersicht aller Pakete mit bekannten Lücken; von hier geht es zu den Details und zum Beheben."""

    def __init__(self, page, items):
        super().__init__(page)
        self.page, self.items = page, items
        self.setObjectName("root")
        self.setWindowTitle("Sicherheit")
        self.resize(760, 700)
        outer, lay = _scroll_body(self)
        lay.addWidget(make_label("Sicherheit", "h1"))
        fix = [i for i in items if i["fix"]]
        lay.addWidget(make_label(
            ("⚠ %d Paket%s mit verfügbarem Fix – bitte aktualisieren. " % (len(fix), "e" if len(fix) != 1 else "") if fix else "")
            + "%d Pakete haben bekannte Lücken. Wähle ein Paket für Details; „Beheben“ zeigt, was sich tun lässt." % len(items), "muted", True))
        self.assessments = [assess(i) for i in items]       # fragt pacman und systemd ab (wenige Sekunden)
        c = Card("Betroffene Pakete")
        lay.addWidget(c)
        order = sorted(self.assessments, key=lambda a: (not a["item"]["fix"], ["critical", "high", "medium", "low"].index(a["item"]["sev"])
                                                         if a["item"]["sev"] in SEV_DE else 9, a["item"]["name"]))
        for n, a in enumerate(order):
            it = a["item"]
            if n:
                c.lay.addWidget(separator())
            row = QHBoxLayout()
            col = QVBoxLayout()
            col.setSpacing(2)
            col.addWidget(make_label("%s  ·  %s" % (it["name"], SEV_DE.get(it["sev"], "?")), "rowTitle"))
            col.addWidget(make_label("%s · %s · %s" % (a["role"], "Fix " + it["fix"] if it["fix"] else "kein Fix",
                                                       "gebraucht von %d" % a["needed"] if a["needed"] else "von niemandem gebraucht"), "desc", True))
            row.addLayout(col, 1)
            b = QPushButton("Details")
            b.clicked.connect(lambda _=False, x=a: DetailDialog(self, x, page.host).exec())
            row.addWidget(b, 0, Qt.AlignmentFlag.AlignVCenter)
            c.lay.addLayout(row)
        row = QHBoxLayout()
        lay.addLayout(row)
        row.addStretch()
        b = QPushButton("Schließen")
        b.clicked.connect(self.accept)
        row.addWidget(b)
        fixb = QPushButton("Beheben …")
        fixb.setObjectName("primary")
        fixb.clicked.connect(self.fix)
        row.addWidget(fixb)

    def fix(self):
        actions, assessments = build_plan(self.items, self.assessments)
        FixPlanDialog(self, actions, assessments, self.page.host).exec()
