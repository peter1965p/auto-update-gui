"""Seite „Updates“: Zeitplan, Ablauf, Protokoll, Sicherheitsprüfung, Mirrors, Tray und Selbst-Update."""
import html, json, math, os, re, shutil, subprocess, sys, time
from collections import Counter
from datetime import datetime as DT
from types import SimpleNamespace
from PyQt6.QtCore import (QEasingCurve, QDateTime, QLocale, QPointF, QProcess, QRectF, QSettings, Qt, QTime,
    QTimer, QVariantAnimation, pyqtSignal)
from PyQt6.QtGui import QAction, QColor, QFont, QIcon, QFontMetrics, QPainter, QPainterPath, QPalette, QPen, QPixmap
from PyQt6.QtWidgets import (QAbstractButton, QApplication, QCheckBox, QComboBox, QDialog, QFrame, QGridLayout,
    QHBoxLayout, QLabel, QMenu, QMessageBox, QPlainTextEdit, QProgressBar, QPushButton, QScrollArea,
    QSizePolicy, QSystemTrayIcon, QTextEdit, QTimeEdit, QVBoxLayout, QWidget)
import html, json, math, os, re, shutil, subprocess, sys, time
from collections import Counter
from datetime import datetime as DT
from types import SimpleNamespace
from . import common
from .common import *
from .sysdetect import *
from .pacbar import PacBar

DAYS = [("Montag","Mon"),("Dienstag","Tue"),("Mittwoch","Wed"),("Donnerstag","Thu"),
        ("Freitag","Fri"),("Samstag","Sat"),("Sonntag","Sun")]
MODES = [("Täglich","daily"),("Wöchentlich","weekly"),("5 Min. nach dem Start","boot")]
STEP = re.compile(r"\((\d+)/(\d+)\) (\w+)")
PHASE = re.compile(r"\[auto-update\] Phase: (\w+)")
RESULTS = {"success": "Erfolgreich", "exit-code": "Fehlgeschlagen", "timeout": "Zeitüberschreitung",
           "signal": "Abgebrochen", "core-dump": "Abgestürzt"}

# (Schlüssel, Titel, Beschreibung)
STEPS = [
    ("snapshot", "Snapshot anlegen",
     "Btrfs-Snapshot der Root-Partition mit Snapper – zum Zurückrollen, falls ein Update Probleme macht."),
    ("pacman", "System aktualisieren",
     "pacman -Syu: Paketdatenbank synchronisieren, offizielle Pakete laden und installieren."),
    ("aur", "AUR-Pakete aktualisieren",
     "paru -Sua: AUR-Pakete bauen und installieren (ohne PKGBUILD-Prüfung)."),
]

RX_PKGNAME = re.compile(r"^[A-Za-z0-9@._+-]+$")

def norm_ignore(text):
    """'a, b  c' -> 'a,b,c': nur gültige Paketnamen, ohne Doppelte (so erwartet es auto-update-apply)."""
    names = [n for n in re.split(r"[,\s;]+", text or "") if n and RX_PKGNAME.match(n)]
    return ",".join(dict.fromkeys(names))

def system_ignored():
    """Pakete, die schon in /etc/pacman.conf (IgnorePkg) ignoriert werden."""
    return [x for x in sh("pacman-conf", "IgnorePkg").stdout.split() if x]

def failed_pkgs(r):
    """Namen der AUR-Pakete, die im Lauf nicht gebaut werden konnten (aus 'Pakete konnten nicht erstellt werden: …')."""
    out = []
    for e in r.events:
        if e[2] != "err": continue
        m = re.search(r"nicht erstellt werden:\s*(.+)$", e[3]) or re.search(r"[Ff]ailed to build[^:]*:\s*(.+)$", e[3])
        for n in re.split(r"[,\s]+", m.group(1).strip()) if m else []:
            n = re.sub(r"-\d[^-]*-\d+$", "", n)           # Version und Release abschneiden
            if n and n not in out: out.append(n)
    return out

def load_conf():
    c = {"ENABLED":"0","MODE":"daily","DAY":"Mon","TIME":"04:00","SNAPSHOT":"1","IGNORE":""}
    try:
        for line in open(CONF):
            if "=" in line:
                k, v = line.strip().split("=", 1); c[k] = v
    except OSError:
        pass
    return c

# ---------------------------------------------------------------- Lauf-Protokoll auswerten
LINE = re.compile(r"^(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)\S*\s+\S+\s+[^\s\[:]+(?:\[\d+\])?:\s?(.*)$")
PHASE_TITLES = {"snapshot": "Snapshot anlegen", "pacman": "System aktualisieren (pacman)", "aur": "AUR-Pakete aktualisieren (paru)"}
PHASE_TAGS = {"start": "Start", "snapshot": "Snap", "pacman": "pacman", "aur": "AUR"}
RX_PKG_DE = re.compile(r"^(\S+) wird (aktualisiert|installiert|neu installiert|entfernt|herabgestuft)\b")
RX_PKG_EN = re.compile(r"^(?:\(\s*\d+/\d+\)\s+)?(upgrading|installing|reinstalling|removing|downgrading) (\S+?)\.*\s*$", re.I)
EN_VERBS = {"upgrading": "aktualisiert", "installing": "installiert", "reinstalling": "neu installiert",
            "removing": "entfernt", "downgrading": "herabgestuft"}
PKG_ICON = {"aktualisiert": "↑", "installiert": "+", "neu installiert": "↻", "entfernt": "−", "herabgestuft": "↓"}
RX_DL = re.compile(r"^(\S+) wird heruntergeladen|^(?:\(\s*\d+/\d+\)\s+)?downloading (\S+?)\.*\s*$", re.I)
RX_HOOK = re.compile(r"^\(\s*(\d+)/(\d+)\)\s+(.*)$")
RX_TOTAL = re.compile(r"^(?:Pakete?|Packages?|Aur|AUR) \((\d+)\)")
RX_SIZE = re.compile(r"^(?:Gesamtgröße des Downloads|Total Download Size):\s+(.+)$")
RX_ROW = re.compile(r"^(?:aur|[\w.+-]+)/(\S+)\s+(\S+)\s+(\S+)\s+(?:-?[\d.,]+ [KMG]iB|Nein|Ja|No|Yes)")
RX_BAD = re.compile(r"^(?:==>\s*)?(?:fehler|error)\b|^curl: \(\d+\)|(?:fehlgeschlagen|failed)", re.I)
RX_BUILT = re.compile(r"^==>\s*(?:Beendete Erstellung|Finished making):\s+(\S+)")
RX_WARN = re.compile(r"^(?:warnung|warning)\b", re.I)
RX_NOTHING = re.compile(r"nichts zu tun|nothing to do", re.I)
NOISE = ("->", "  ->", "Copied:", "Updated:", "Saved:", "Building initramfs", "==> Using", "==> Starting build",
         "==> Generating", "==> Creating", "==> WARNING: Possibly missing", "pam_unix")
STAGES = [("sync", r"Paketdatenbanken werden synchronisiert|Synchronizing package databases", "Paketdatenbanken synchronisieren"),
          ("resolve", r"Abhängigkeiten werden aufgelöst|Resolving dependencies", "Abhängigkeiten auflösen"),
          ("download", r"Pakete werden empfangen|Retrieving packages", "Pakete herunterladen"),
          ("check", r"Schlüsselbund wird geprüft|Checking keyring|Paketintegrität wird geprüft|Checking package integrity", "Schlüssel und Paketintegrität prüfen"),
          ("pre", r"Pre-transaction-Hooks|pre-transaction hooks", "Pre-Transaction-Hooks ausführen"),
          ("install", r"Paketänderungen werden verarbeitet|Processing package changes", "Pakete installieren"),
          ("post", r"Post-transaction-Hooks|post-transaction hooks", "Post-Transaction-Hooks ausführen")]
STAGES = [(k, re.compile(rx, re.I), t) for k, rx, t in STAGES]

SEV_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3}
SEV_DE = {"critical": "kritisch", "high": "hoch", "medium": "mittel", "low": "niedrig"}

def parse_audit(out):
    """Ausgabe von: arch-audit -f '%n|%s|%v|%c|%t'  ->  Liste von Dicts (Fix verfügbar zuerst, dann nach Schwere)."""
    res = []
    for line in (out or "").splitlines():
        f = [x.strip() for x in line.split("|")]
        if len(f) < 4 or not f[0]: continue
        sev = next((k for k in SEV_RANK if k in f[1].lower()), "")
        res.append(dict(name=f[0], sev=sev, fix=f[2], cves=[c for c in re.split(r"[,\s]+", f[3]) if c], type=f[4] if len(f) > 4 else ""))
    res.sort(key=lambda a: (not a["fix"], SEV_RANK.get(a["sev"], 9), a["name"]))
    return res

def audit_text(items):
    if not items: return "Sicherheit (arch-audit): ✓ keine bekannten Lücken"
    fixable = [a for a in items if a["fix"]]
    n = len(items); open_ = n - len(fixable)
    if fixable:
        head = f"Sicherheit (arch-audit): ⚠ {len(fixable)} {'Paket hat' if len(fixable) == 1 else 'Pakete haben'} eine Lücke mit verfügbarem Fix – bitte aktualisieren"
        if open_: head += f"\n   (dazu {open_} ohne Fix)"
        show = fixable
    else:
        sev = Counter(a["sev"] for a in items)
        breakdown = ", ".join(f"{sev[k]} {SEV_DE[k]}" for k in ("critical", "high", "medium", "low") if sev.get(k))
        head = (f"Sicherheit (arch-audit): ℹ {n} {'Paket' if n == 1 else 'Pakete'} mit bekannten Lücken"
                + (f" ({breakdown})" if breakdown else "") + " – für keines gibt es derzeit ein Update.\n"
                "   Du kannst gerade nichts tun. Sobald ein Fix erscheint, wirst du hier und im Tray gewarnt.")
        show = sorted(items, key=lambda a: (SEV_RANK.get(a["sev"], 9), a["name"]))[:3]
    rows = []
    for a in show[:5]:
        cve = ", ".join(a["cves"][:2]) + (f" +{len(a['cves']) - 2}" if len(a["cves"]) > 2 else "")
        rows.append(f"   {a['name']} · {SEV_DE.get(a['sev'], 'unbekannt')} · " + (f"Fix {a['fix']}" if a["fix"] else "kein Fix") + (f" · {cve}" if cve else ""))
    more = len(show) - 5 if fixable else n - 3
    return head + "\n" + "\n".join(rows) + (f"\n   … und {more} weitere" if more > 0 else "")

def journal_last_run():
    """(InvocationID, Ergebnis) des letzten Laufs aus dem Journal. Nach einem Neustart hat systemd den Zustand des
    Dienstes vergessen, das Journal kennt den Lauf aber noch."""
    out = sh("journalctl", "-u", "auto-update.service", "-o", "json", "-r", "-n", "400", "--no-pager").stdout
    inv = res = ""
    for line in out.splitlines():                       # neueste zuerst
        try: e = json.loads(line)
        except ValueError: continue
        inv = inv or e.get("_SYSTEMD_INVOCATION_ID", "")
        msg = e.get("MESSAGE", "")
        if not res and isinstance(msg, str):
            if "Failed with result" in msg:
                m = re.search(r"result '([^']+)'", msg); res = m.group(1) if m else "exit-code"
            elif "Deactivated successfully" in msg or msg.startswith("Finished"): res = "success"
        if inv and res: break
    return inv, res

def last_run_state():
    """(InvocationID, Ergebnis) – aus systemd, nach einem Neustart aus dem Journal."""
    inv = sh("systemctl", "show", "auto-update.service", "-p", "InvocationID", "--value").stdout.strip()
    res = sh("systemctl", "show", "auto-update.service", "-p", "Result", "--value").stdout.strip()
    if not inv:
        jinv, jres = journal_last_run()
        inv, res = jinv, jres or res
    return inv, res

def fmt_dur(secs):
    secs = max(0, int(secs))
    if secs < 60: return f"{secs} s"
    if secs < 3600: return f"{secs // 60} Min {secs % 60:02d} s"
    return f"{secs // 3600} Std {secs % 3600 // 60:02d} Min"

def parse_size(txt):
    """'140,98 MiB' / '1.234,5 KiB' -> Bytes"""
    m = re.match(r"([\d.,]+)\s*([KMGT]?i?B)", txt.strip())
    if not m: return 0
    num = m.group(1)
    num = num.replace(".", "").replace(",", ".") if "," in num else num
    mult = {"B": 1, "KiB": 1024, "MiB": 1024 ** 2, "GiB": 1024 ** 3, "TiB": 1024 ** 4}.get(m.group(2), 1)
    try: return int(float(num) * mult)
    except ValueError: return 0

def fmt_size(b):
    return (f"{b / 1024 ** 3:.2f}".replace(".", ",") + " GiB") if b >= 1024 ** 3 else (f"{b / 1024 ** 2:.1f}".replace(".", ",") + " MiB")

_cache_dir = []
def download_progress(since):
    """Bytes, die seit 'since' im pacman-Cache liegen (fertige + wachsende .part-Dateien) und die Namen der aktiven Downloads."""
    if not _cache_dir:
        out = sh("pacman-conf", "CacheDir").stdout.split()
        _cache_dir.append(out[0] if out else "/var/cache/pacman/pkg/")
    total, active = 0, []
    try:
        for e in os.scandir(_cache_dir[0]):
            if ".pkg.tar" not in e.name or e.name.endswith(".sig"): continue
            st = e.stat()
            if st.st_mtime >= since:
                total += st.st_size
                if e.name.endswith(".part"): active.append(e.name.split(".pkg.tar")[0].rsplit("-", 3)[0])
    except OSError:
        pass
    return total, active

def aur_activity(since):
    """Fortschritt des AUR-Schritts aus dem paru-Cache: fertig gebaute Pakete und wachsende Quell-Downloads (.part).
    paru/makepkg schreiben beim Laden und Bauen oft minutenlang nichts ins Journal."""
    base = os.path.expanduser("~/.cache/paru/clone")
    built, parts = set(), []
    try:
        for d in os.scandir(base):
            if not d.is_dir(): continue
            try: entries = list(os.scandir(d.path))
            except OSError: continue
            for e in entries:
                if not e.is_file(follow_symlinks=False): continue
                st = e.stat()
                if st.st_mtime < since: continue
                if e.name.endswith(".part"): parts.append((d.name, e.name[:-5], st.st_size))
                elif ".pkg.tar" in e.name and not e.name.endswith(".sig") and "-debug-" not in e.name: built.add(d.name)
    except OSError:
        pass
    return sorted(built), parts

def new_counter():
    return SimpleNamespace(total=0, dl=0, inst=0, stage=None, last_dl="", last_pkg="", hook="", size="",
                           verbs=Counter(), nothing=False, rows=[], last_info="", events=0, stage_at={}, size_bytes=0, dl_live="", built=[])

def parse_run(raw):
    """Wertet das Journal eines Update-Laufs (short-iso) aus: Phasen, Zeiten, Ereignisse, Zähler."""
    r = SimpleNamespace(phases=[], start={}, end={}, done=None, events=[], raw=[], first=None, last=None,
                        c={k: new_counter() for k in ("start", "snapshot", "pacman", "aur")})
    phase = "start"
    def ev(dt, kind, text): r.events.append((dt, phase, kind, text)); r.c[phase].events += 1
    for line in raw.splitlines():
        m = LINE.match(line)
        if not m: continue
        dt = DT.strptime(m.group(1), "%Y-%m-%dT%H:%M:%S"); msg = m.group(2).strip()
        if not msg.strip(): continue
        r.first = r.first or dt; r.last = dt
        pm = PHASE.search(msg)
        if pm:
            if phase in r.start: r.end[phase] = dt
            if pm.group(1) == "done":
                if phase == "aur" and not r.c["aur"].rows and not r.c["aur"].nothing and r.c["aur"].events == 0:
                    r.events.append((dt, "aur", "ok", "✓ Im AUR sind derzeit keine Updates vorhanden"))
                r.done = dt; r.events.append((dt, "done", "phase", "■ Update beendet")); continue   # Zeilen danach gehören noch zum letzten Schritt
            phase = pm.group(1); r.phases.append(phase); r.start[phase] = dt
            r.c.setdefault(phase, new_counter())
            r.events.append((dt, phase, "phase", "▶ " + PHASE_TITLES.get(phase, phase))); continue
        r.raw.append((dt, phase, msg))
        if msg.startswith("[auto-update] Ausnahmeliste"): r.events.append((dt, phase, "info", "ℹ " + msg[14:])); continue
        c = r.c.get(phase) or r.c["start"]
        if msg.startswith(NOISE) or "[J/n]" in msg or "[Y/n]" in msg: continue
        st = next(((k, t) for k, rx, t in STAGES if rx.search(msg)), None) if phase == "pacman" else None
        if st:
            if c.stage != st[0]:
                c.stage = st[0]; c.stage_at[st[0]] = dt; extra = ""
                if st[0] == "download" and c.total: extra = f" ({c.total} Pakete{', ' + c.size if c.size else ''})"
                ev(dt, "stage", f"▸ {st[1]}{extra}")
            continue
        mt = RX_TOTAL.match(msg)
        if mt: c.total = int(mt.group(1)); continue
        ms = RX_SIZE.match(msg)
        if ms: c.size = ms.group(1).strip(); c.size_bytes = parse_size(c.size); continue
        mr = RX_ROW.match(msg)
        if mr:
            c.rows.append(mr.groups()); ev(dt, "plan", f"• {mr.group(1)}  {mr.group(2)} → {mr.group(3)}"); continue
        mp = RX_PKG_DE.match(msg)
        if mp: name, verb = mp.groups()
        else:
            me = RX_PKG_EN.match(msg)
            name, verb = (me.group(2), EN_VERBS[me.group(1).lower()]) if me else (None, None)
        if name:
            c.inst += 1; c.last_pkg = name; c.verbs[verb] += 1
            ev(dt, "pkg", f"{PKG_ICON.get(verb, '•')} {name} wird {verb}"); continue
        md = RX_DL.match(msg)
        if md:
            name = md.group(1) or md.group(2)
            if c.stage == "download": c.dl += 1; c.last_dl = name; ev(dt, "dl", f"⬇ {name}")
            else: ev(dt, "dl", f"⬇ {name}  (Paketdatenbank)")
            continue
        mb = RX_BUILT.match(msg)
        if mb and phase == "aur": c.built.append(mb.group(1))
        if RX_NOTHING.search(msg):
            c.nothing = True
            ev(dt, "ok", "✓ Im AUR sind derzeit keine Updates vorhanden" if phase == "aur" else "✓ Nichts zu tun – das System ist aktuell"); continue
        if RX_BAD.search(msg): ev(dt, "err", "✕ " + msg[:200]); continue
        if RX_WARN.search(msg): ev(dt, "warn", "⚠ " + msg[:200]); continue
        mh = RX_HOOK.match(msg)
        if mh and phase == "pacman" and not mh.group(3).startswith(("Herunterladen", "Downloading")):
            c.hook = f"{mh.group(1)}/{mh.group(2)} {mh.group(3)}"; ev(dt, "hook", f"⚙ ({mh.group(1)}/{mh.group(2)}) {mh.group(3)[:150]}"); continue
        if msg.startswith("==> ") and phase == "pacman":
            if msg[4:].startswith(("INFO", "WARNING", "ERROR", "root:")): ev(dt, "info", "ℹ " + msg[4:][:160])
            continue
        if phase == "aur":
            t = msg[4:] if msg.startswith("==> ") else msg.lstrip(": ").strip() if msg.startswith("::") else msg
            if mh or msg.startswith(("==>", "::")) or re.match(r"^[\w.+-]+: ", msg) or msg.endswith(("…", "...")):
                c.last_info = t[:140]; ev(dt, "aur", "📦 " + t[:160])
            continue
        if msg.startswith("::"):
            ev(dt, "info", "ℹ " + msg.lstrip(": ").strip()[:160])
    return r

def run_summary(r, ph):
    """Kurzfassung eines abgeschlossenen Schritts."""
    c = r.c[ph]
    if ph == "snapshot": return "Snapshot angelegt"
    if ph == "pacman":
        if c.nothing and not c.inst: return "System ist aktuell – nichts zu aktualisieren"
        parts = [f"{n} {v}" for v, n in c.verbs.items()]
        return f"{c.inst} {'Paket' if c.inst == 1 else 'Pakete'}: " + ", ".join(parts) if parts else ""
    if ph == "aur":
        if c.nothing and not c.rows: return "Im AUR sind derzeit keine Updates vorhanden"
        if c.rows: return f"{len(c.rows)} Paket(e): " + ", ".join(f"{n} {o}→{v}" for n, o, v in c.rows[:4]) + (" …" if len(c.rows) > 4 else "")
        return "Im AUR sind derzeit keine Updates vorhanden"
    return ""

def fail_text(r, ph):
    """Warum ist ein Schritt fehlgeschlagen? Teilerfolg (z. B. '2 von 3 gebaut') plus erste und letzte Fehlermeldung."""
    errs = [e[3].lstrip("✕ ").strip() for e in r.events if e[1] == ph and e[2] == "err"]
    c = r.c[ph]
    lines = []
    if ph == "aur" and c.rows: lines.append(f"{len(c.built)} von {len(c.rows)} AUR-Paketen gebaut")
    uniq = list(dict.fromkeys(errs))
    for e in ([uniq[0], uniq[-1]] if len(uniq) > 1 else uniq):
        lines.append("✕ " + e[:170])
    return "\n".join(lines) if lines else "mit Fehlern beendet – siehe Protokoll"

def run_activity(r, ph):
    """Was passiert gerade in diesem Schritt (für laufende Schritte)."""
    c = r.c[ph]
    if ph == "snapshot": return "Snapper legt einen Snapshot an …"
    if ph == "pacman":
        t = c.total
        return {"sync": "Paketdatenbanken werden synchronisiert …",
                "resolve": "Abhängigkeiten werden aufgelöst …",
                "download": c.dl_live or f"Lade herunter {c.dl}/{t}" + (f" · {c.last_dl}" if c.last_dl else ""),
                "check": "Schlüssel und Paketintegrität werden geprüft …",
                "pre": "Pre-Transaction-Hooks …", "post": f"Post-Transaction-Hooks · {c.hook}",
                "install": f"Installiere {c.inst}/{t}" + (f" · {c.last_pkg}" if c.last_pkg else "")}.get(c.stage, "Starte pacman …")
    if ph == "aur":
        return c.dl_live or c.last_info or "Starte paru …"
    return ""

def timeline_html(r, raw_mode=False):
    col = {"snapshot": theme["warn"], "pacman": theme["accent"], "aur": "#b57bee", "start": theme["muted"], "done": theme["ok"]}
    kcol = {"err": theme["err"], "warn": theme["warn"], "ok": theme["ok"], "dl": theme["muted"], "plan": theme["muted"], "hook": theme["muted"]}
    rows = []
    items = [(dt, ph, "raw", msg) for dt, ph, msg in r.raw] if raw_mode else r.events
    for dt, ph, kind, text in items[-500:]:
        tag = PHASE_TAGS.get(ph, ph)
        txt = html.escape(text).replace(" ", "&nbsp;") if raw_mode else html.escape(text)
        style = f"color:{kcol[kind]}" if kind in kcol else ("font-weight:bold" if kind in ("phase", "stage") else "")
        rows.append(f'<span style="color:{theme["muted"]}">{dt:%H:%M:%S}</span>&nbsp;&nbsp;'
                    f'<span style="color:{col.get(ph, theme["muted"])}">{tag.ljust(6).replace(" ", "&nbsp;")}</span>&nbsp;'
                    f'<span style="{style}">{txt}</span>')
    return "<br>".join(rows) or f'<span style="color:{theme["muted"]}">Noch keine Ereignisse.</span>'


class StepRow(QWidget):
    def __init__(self, num, title, desc):
        super().__init__()
        self.num = str(num)
        lay = QHBoxLayout(self); lay.setContentsMargins(0, 0, 0, 0); lay.setSpacing(14)
        self.badge = make_label(self.num, "badge"); self.badge.setFixedSize(34, 34)
        self.badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self.badge, 0, Qt.AlignmentFlag.AlignTop)
        col = QVBoxLayout(); col.setSpacing(2)
        col.addWidget(make_label(title, "rowTitle"))
        self.desc = make_label(desc, "desc", True); col.addWidget(self.desc)
        self.detail = make_label("", "detail", True); self.detail.hide(); col.addWidget(self.detail)
        self.act = QPushButton(); self.act.hide(); col.addWidget(self.act, 0, Qt.AlignmentFlag.AlignLeft)   # z. B. "Paket überspringen"
        lay.addLayout(col, 1)
        self.state = make_label("", "stState"); self.state.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
        lay.addWidget(self.state, 0, Qt.AlignmentFlag.AlignTop)

    def set(self, state, text, detail=""):
        glyph = {"done": "✓", "failed": "✕", "off": "–", "active": "●"}.get(state, self.num)
        self.badge.setText(glyph); set_state(self.badge, state)
        self.state.setText(text); set_state(self.state, state)
        self.detail.setText(detail); self.detail.setVisible(bool(detail)); set_state(self.detail, state)
        self.act.hide()
        self.setEnabled(state != "off")

    def set_action(self, text, fn):
        try: self.act.clicked.disconnect()
        except TypeError: pass
        self.act.setText(text); self.act.clicked.connect(fn); self.act.show()

class SystemDialog(QDialog):
    """Zeigt das erkannte System, aktive Repos und mögliche Zusatzquellen (nur Info, trägt nichts automatisch ein)."""
    def __init__(self, win):
        super().__init__(win)
        si = win.sys
        self.setObjectName("root"); self.setWindowTitle("System & Quellen"); self.resize(660, 720)
        outer = QVBoxLayout(self); outer.setContentsMargins(0, 0, 0, 0)
        sc = QScrollArea(); sc.setWidgetResizable(True); sc.setFrameShape(QFrame.Shape.NoFrame); outer.addWidget(sc)
        body = QWidget(); sc.setWidget(body)
        lay = QVBoxLayout(body); lay.setContentsMargins(20, 18, 20, 16); lay.setSpacing(14)
        lay.addWidget(make_label("System & Quellen", "h1"))

        nm, desc = DISTROS.get(si.kind, (si.name, "Kein Arch-System erkannt – dieses Tool braucht pacman und systemd." if si.kind == "foreign"
                                         else "Unbekanntes Arch-Derivat – das Tool läuft auf Arch-Basis (pacman)."))
        c = Card("Dein System"); lay.addWidget(c)
        c.lay.addWidget(make_label(f"{si.name}  ·  erkannt als: {nm}", "rowTitle"))
        c.lay.addWidget(make_label(desc, "desc", True))
        g = QGridLayout(); g.setHorizontalSpacing(14); g.setVerticalSpacing(6); g.setColumnStretch(1, 1); c.lay.addLayout(g)
        mb = win.mir
        rows = [("Kernel", os.uname().release), ("Repositories", ", ".join(si.repos) or "–"),
                ("CPU-Stufe", f"x86-64-v{si.cpu}" + ("  (v3-Pakete möglich)" if si.cpu >= 3 else "  (v3-Pakete laufen nicht)")),
                ("Mirror-Werkzeug", mb[2] if mb else "keines gefunden")]
        for i, (k, v) in enumerate(rows):
            g.addWidget(make_label(k, "muted"), i, 0, Qt.AlignmentFlag.AlignTop); g.addWidget(make_label(v, wrap=True), i, 1)

        c = Card("Was sich dazu nutzen lässt"); lay.addWidget(c)
        c.lay.addWidget(make_label("Zusatzquellen sind optional. Jede fremde Quelle vergrößert die Angriffsfläche: nur einrichten, wenn "
                                   "du sie brauchst und nur nach der offiziellen Anleitung. Das Tool trägt nichts automatisch ein.", "desc", True))
        for key, title, text, url in SOURCES:
            c.lay.addWidget(separator())
            st, label = source_state(si, key)
            c.lay.addWidget(make_label(title, "rowTitle")); c.lay.addWidget(make_label(text, "desc", True))
            lb = make_label(label, "detail", True); set_state(lb, {"ok": "done", "warn": "failed", "no": "failed"}.get(st, "idle"))
            c.lay.addWidget(lb)
            if st != "no":
                b = QPushButton("Anleitung öffnen"); b.clicked.connect(lambda _, u=url: subprocess.Popen(["xdg-open", u]))
                c.lay.addWidget(b, 0, Qt.AlignmentFlag.AlignLeft)

        c = Card("Wechsel zu einem anderen Arch-System"); lay.addWidget(c)
        c.lay.addWidget(make_label("Alle diese Systeme teilen pacman, PKGBUILDs und das AUR. Ein Umbau im laufenden Betrieb ist aber riskant: "
                                   "eine Neuinstallation ist fast immer sauberer.", "desc", True))
        for k, (n, d) in DISTROS.items():
            if k == si.kind: continue
            c.lay.addWidget(make_label(f"<b>{n}</b> – {d}", wrap=True))
        row = QHBoxLayout(); lay.addLayout(row); row.addStretch()
        b = QPushButton("Fertig"); b.setObjectName("primary"); b.clicked.connect(self.accept); row.addWidget(b)

class SettingsDialog(QDialog):
    def __init__(self, win):
        super().__init__(win)
        self.win = win
        self.setObjectName("root"); self.setWindowTitle("Einstellungen"); self.setMinimumWidth(540)
        lay = QVBoxLayout(self); lay.setContentsMargins(20, 18, 20, 16); lay.setSpacing(14)
        lay.addWidget(make_label("Einstellungen", "h1"))

        c = Card("Design"); lay.addWidget(c)
        g = QGridLayout(); g.setHorizontalSpacing(14); g.setVerticalSpacing(10); g.setColumnStretch(1, 1); c.lay.addLayout(g)
        self.theme_box = QComboBox()
        for n, v in THEMES: self.theme_box.addItem(n, v)
        self.theme_box.setCurrentIndex(max(0, self.theme_box.findData(str(cfg.value("theme", "system")))))
        self.accent_box = QComboBox()
        for n, v in ACCENTS:
            pm = QPixmap(16, 16); pm.fill(QColor(common.ORIG_PAL.color(QPalette.ColorRole.Highlight) if v == "system" else QColor(v)))
            self.accent_box.addItem(QIcon(pm), n, v)
        self.accent_box.setCurrentIndex(max(0, self.accent_box.findData(str(cfg.value("accent", "system")))))
        g.addWidget(make_label("Farbschema", "muted"), 0, 0); g.addWidget(self.theme_box, 0, 1)
        g.addWidget(make_label("Akzentfarbe", "muted"), 1, 0); g.addWidget(self.accent_box, 1, 1)
        c.lay.addWidget(make_label("Änderungen werden sofort übernommen.", "desc"))
        self.theme_box.currentIndexChanged.connect(self.design_changed)
        self.accent_box.currentIndexChanged.connect(self.design_changed)

        c = Card("Verhalten"); lay.addWidget(c)
        g = QGridLayout(); g.setHorizontalSpacing(14); g.setColumnStretch(1, 1); c.lay.addLayout(g)
        self.interval_box = QComboBox()
        for n, v in INTERVALS: self.interval_box.addItem(n, v)
        self.interval_box.setCurrentIndex(max(0, self.interval_box.findData(int(cfg.value("interval", 3)))))
        g.addWidget(make_label("Auf verfügbare Updates prüfen", "muted"), 0, 0); g.addWidget(self.interval_box, 0, 1)
        self.interval_box.currentIndexChanged.connect(lambda *_: (cfg.setValue("interval", self.interval_box.currentData()), win.apply_cfg()))
        c.lay.addWidget(separator())
        for key, default, title, desc in (
                ("audit", True, "Auf Sicherheitslücken prüfen", "Gleicht installierte Pakete mit der Arch-Sicherheitsdatenbank ab (arch-audit, braucht Internet)."),
                ("notify", True, "Benachrichtigungen anzeigen", "Hinweis im Systray bei neuen Updates und nach einem Lauf."),
                ("selfcheck", True, "Nach neuen Tool-Versionen suchen", "Fragt alle 12 Stunden GitHub nach einem neuen Release dieses Tools.")):
            r = OptionRow(title, desc); r.toggle.setChecked(flag(key, default))
            r.toggle.toggled.connect(lambda on, k=key: (cfg.setValue(k, on), win.apply_cfg()))
            c.lay.addWidget(r)
        r = OptionRow("Beim Anmelden im Systray starten", "Das Tool startet unsichtbar im Systray und prüft im Hintergrund.")
        r.toggle.setChecked(autostart_enabled()); r.toggle.toggled.connect(set_autostart); c.lay.addWidget(r)

        c = Card("Info"); lay.addWidget(c)
        c.lay.addWidget(make_label(f"Automatische Updates · Version {VERSION}"))
        link = make_label(f'<a href="https://github.com/{REPO}" style="color:{theme["accent"]}">github.com/{REPO}</a>')
        link.setOpenExternalLinks(True); c.lay.addWidget(link)
        row = QHBoxLayout(); c.lay.addLayout(row)
        sb_ = QPushButton("System && Quellen …"); sb_.clicked.connect(win.open_system); row.addWidget(sb_)
        self.chk_btn = QPushButton("Jetzt nach Tool-Update suchen"); self.chk_btn.clicked.connect(self.check_tool)
        row.addWidget(self.chk_btn)
        self.inst_btn = QPushButton("Jetzt installieren"); self.inst_btn.setObjectName("primary"); self.inst_btn.hide()
        self.inst_btn.clicked.connect(win.self_update); row.addWidget(self.inst_btn); row.addStretch()
        self.chk_msg = make_label("", "desc", True); c.lay.addWidget(self.chk_msg)
        win.ver_cb = self.show_result            # Ergebnis der Prüfung hier im Dialog anzeigen
        self.finished.connect(lambda *_: setattr(win, "ver_cb", None))

        row = QHBoxLayout(); lay.addLayout(row); row.addStretch()
        b = QPushButton("Fertig"); b.setObjectName("primary"); b.clicked.connect(self.accept); row.addWidget(b)
        self.setFixedHeight(self.layout().totalHeightForWidth(540) if self.layout().hasHeightForWidth() else self.sizeHint().height())

    def check_tool(self):
        self.chk_btn.setEnabled(False); self.chk_btn.setText("Suche …"); self.inst_btn.hide()
        self.chk_msg.setText("Frage GitHub nach der neuesten Version …")
        self.win.check_self_update(True)
        if not self.win.selfproc: self.show_result("Prüfung nicht möglich.", False)   # Prüfung lief nicht an

    def show_result(self, text, new=False):
        self.chk_btn.setEnabled(True); self.chk_btn.setText("Jetzt nach Tool-Update suchen")
        self.chk_msg.setText(text); self.inst_btn.setVisible(new)

    def design_changed(self, *_):
        cfg.setValue("theme", self.theme_box.currentData()); cfg.setValue("accent", self.accent_box.currentData())
        apply_theme(self.win.app); self.win.update_tray_badge()

# ---------------------------------------------------------------- Hauptfenster

class UpdatesPage(QWidget):
    """Die frühere Hauptansicht der Update-App, jetzt eine Seite im SoftCenter-Fenster."""
    header_changed = pyqtSignal(str, str, str)   # Untertitel, Pill-Text, Pill-Zustand
    badge_changed = pyqtSignal(int)              # Anzahl verfügbarer Updates (für die Seitenleiste)

    def __init__(self, app, host):
        super().__init__()
        self.app = app
        self.host = host
        self.setObjectName("content")
        self.was_active = False
        self.ticks = 0
        self.conf = load_conf()
        self.saved = None
        self.last = None           # (log, result) des letzten Laufs
        self.procs = {}
        self.counts = {}
        self.notified = 0
        self.selfproc = None
        self.mir_running = False
        self.manual = False
        self.ver_cb = None
        self.upd_tag = self.upd_url = ""
        self.notified_ver = ""

        outer = QVBoxLayout(self); outer.setContentsMargins(0, 0, 0, 0); outer.setSpacing(0)
        self.scroll = scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setFrameShape(QFrame.Shape.NoFrame)
        outer.addWidget(scroll, 1)
        body = QWidget(); scroll.setWidget(body)
        lay = QVBoxLayout(body); lay.setContentsMargins(22, 20, 22, 14); lay.setSpacing(14)

        # Die Kopfzeile zeigt das Hauptfenster; hier liegen nur die Werte (siehe header_changed)
        self.subtitle = make_label(""); self.pill = make_label("", "pill")

        # Hinweis auf neue Tool-Version
        self.upd_card = Card(); self.upd_card.hide(); lay.addWidget(self.upd_card)
        self.upd_title = make_label("", "cardTitle"); self.upd_card.lay.addWidget(self.upd_title)
        self.upd_notes = make_label("", "desc", True); self.upd_card.lay.addWidget(self.upd_notes)
        urow = QHBoxLayout(); self.upd_card.lay.addLayout(urow)
        self.upd_btn = QPushButton("Jetzt aktualisieren"); self.upd_btn.setObjectName("primary")
        self.upd_btn.clicked.connect(self.self_update); urow.addWidget(self.upd_btn)
        b = QPushButton("Release ansehen"); b.clicked.connect(lambda: subprocess.Popen(["xdg-open", self.upd_url])); urow.addWidget(b)
        urow.addStretch()

        # Karte: Zeitplan & Optionen
        self.card_set = c = Card("Einstellungen")
        self.opt_enable = OptionRow("Automatische Updates aktivieren",
                                    "Das System aktualisiert sich selbstständig im Hintergrund nach dem Zeitplan unten.")
        c.lay.addWidget(self.opt_enable)
        c.lay.addWidget(separator())
        grid = QGridLayout(); grid.setHorizontalSpacing(14); grid.setVerticalSpacing(8)
        self.mode = QComboBox(); [self.mode.addItem(n, v) for n, v in MODES]
        self.day = QComboBox(); [self.day.addItem(n, v) for n, v in DAYS]
        self.time = QTimeEdit(); self.time.setDisplayFormat("HH:mm")
        self.time.setFixedWidth(100)
        self.day_l, self.time_l = make_label("Wochentag", "muted"), make_label("Uhrzeit", "muted")
        grid.addWidget(make_label("Intervall", "muted"), 0, 0); grid.addWidget(self.mode, 0, 1)
        grid.addWidget(self.day_l, 1, 0); grid.addWidget(self.day, 1, 1)
        grid.addWidget(self.time_l, 2, 0); grid.addWidget(self.time, 2, 1, Qt.AlignmentFlag.AlignLeft)
        grid.setColumnStretch(1, 1)
        c.lay.addLayout(grid)
        self.summary = make_label("", "desc", True); c.lay.addWidget(self.summary)
        c.lay.addWidget(separator())
        self.opt_snap = OptionRow("Vorher Btrfs-Snapshot anlegen",
                                  "Legt vor jedem Update mit Snapper einen Wiederherstellungspunkt an.")
        c.lay.addWidget(self.opt_snap)
        self.opt_aur = OptionRow("AUR-Pakete mitaktualisieren",
                                 "⚠ Risiko: erlaubt passwortloses 'sudo pacman' und überspringt die PKGBUILD-Prüfung.",
                                 "Erlaubt deinem Benutzer passwortloses 'sudo pacman' und überspringt die PKGBUILD-Prüfung.\n"
                                 "Ein kompromittiertes AUR-Paket würde ungeprüft installiert.")
        c.lay.addWidget(self.opt_aur)
        self.enable, self.snap, self.aur = self.opt_enable.toggle, self.opt_snap.toggle, self.opt_aur.toggle
        c.lay.addWidget(separator())
        c.lay.addWidget(make_label("Beim automatischen Update überspringen", "rowTitle"))
        self.ignore = QLineEdit(); self.ignore.setPlaceholderText("Paketnamen, durch Komma getrennt – z. B. pgadmin4-server")
        c.lay.addWidget(self.ignore)
        self.ignore_info = make_label("", "desc", True); c.lay.addWidget(self.ignore_info)
        c.lay.addStretch()      # Inhalt oben halten, auch wenn die rechte Spalte höher ist

        # Karte: Ablauf
        self.flow_title = make_label("", "muted")
        self.card_flow = c = Card("Ablauf eines Updates", self.flow_title)
        self.rows = {}
        for i, (key, title, desc) in enumerate(STEPS, 1):
            self.rows[key] = StepRow(i, title, desc); c.lay.addWidget(self.rows[key])
        self.bar = PacBar(); c.lay.addWidget(self.bar)   # Platz wird in reflow() gewählt
        self.live = make_label("", "mono", True); self.live.hide(); c.lay.addWidget(self.live)
        lrow = QHBoxLayout(); c.lay.addLayout(lrow)
        self.logbtn = QPushButton("Ablaufprotokoll anzeigen ▾"); self.logbtn.setObjectName("flat")
        self.logbtn.clicked.connect(self.toggle_live); lrow.addWidget(self.logbtn)
        self.rawbtn = QPushButton("Rohausgabe"); self.rawbtn.setObjectName("flat"); self.rawbtn.setCheckable(True)
        self.rawbtn.setToolTip("Alle Zeilen unverändert (an) oder ausgewertete Ereignisse mit Symbolen (aus)"); self.rawbtn.hide()
        self.rawbtn.setChecked(flag("rawview", True))      # Standard: Rohausgabe, Auswahl wird gemerkt
        self.rawbtn.toggled.connect(lambda on: (cfg.setValue("rawview", on), self.refresh_liveview()))
        lrow.addWidget(self.rawbtn); lrow.addStretch()
        self.liveview = QTextEdit(); self.liveview.setReadOnly(True); self.liveview.setMinimumHeight(200)
        self.liveview.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)   # füllt freie Höhe
        self.liveview.setFont(QFont("monospace", 9)); self.liveview.hide(); c.lay.addWidget(self.liveview)
        self.cur_run = None; self.dl_hist = []; self._live_text = ""; self._spin = 0
        self.spinner = QTimer(self); self.spinner.timeout.connect(self.spin_tick); self.spinner.start(110)

        # Karte: Status
        self.card_status = c = Card("Status")
        sg = QGridLayout(); sg.setHorizontalSpacing(14); sg.setVerticalSpacing(6); c.lay.addLayout(sg)
        self.st_next, self.st_last = make_label("–", wrap=True), make_label("–", wrap=True)
        sg.addWidget(make_label("Nächster Lauf", "muted"), 0, 0, Qt.AlignmentFlag.AlignTop); sg.addWidget(self.st_next, 0, 1)
        sg.addWidget(make_label("Letzter Lauf", "muted"), 1, 0, Qt.AlignmentFlag.AlignTop); sg.addWidget(self.st_last, 1, 1)
        self.st_ver = make_label(f"{VERSION}", wrap=True)
        sg.addWidget(make_label("Tool-Version", "muted"), 2, 0, Qt.AlignmentFlag.AlignTop); sg.addWidget(self.st_ver, 2, 1)
        self.sys = detect_system(); self.mir = mirror_backend(self.sys.kind)
        self.st_sys = make_label(f"{self.sys.name}", wrap=True)
        sysbtn = QPushButton("Details && Vorschläge"); sysbtn.setObjectName("flat"); sysbtn.clicked.connect(self.open_system)
        sg.addWidget(make_label("System", "muted"), 3, 0, Qt.AlignmentFlag.AlignTop)
        sgs = QHBoxLayout(); sgs.addWidget(self.st_sys); sgs.addWidget(sysbtn); sgs.addStretch(); sg.addLayout(sgs, 3, 1)
        self.st_mir = make_label("–", wrap=True)
        sg.addWidget(make_label("Mirrors", "muted"), 4, 0, Qt.AlignmentFlag.AlignTop); sg.addWidget(self.st_mir, 4, 1)
        self.mirbtn = QPushButton("Mirrors jetzt aktualisieren"); self.mirbtn.clicked.connect(self.mirrors_now)
        self.mirbtn.setToolTip("Bewertet die schnellsten Mirrors neu (je nach System cachyos-rate-mirrors oder reflector, dauert 1–2 Minuten).\n"
                               "Die alten Listen bleiben als *-backup in /etc/pacman.d erhalten.")
        sg.addWidget(self.mirbtn, 5, 1, Qt.AlignmentFlag.AlignLeft)
        sg.setColumnStretch(1, 1); c.lay.addStretch()

        # Karte: Verfügbare Updates
        self.card_upd = c = Card("Verfügbare Updates")
        self.repolabel = make_label("System (pacman): nicht geprüft", wrap=True)
        self.aurlabel = make_label("AUR: nicht geprüft", wrap=True)
        self.auditlabel = make_label("Sicherheit (arch-audit): nicht geprüft", wrap=True); self.audit = []
        c.lay.addWidget(self.repolabel); c.lay.addWidget(self.aurlabel); c.lay.addWidget(self.auditlabel)
        arow = QHBoxLayout(); c.lay.addLayout(arow)
        self.checkbtn = QPushButton("Jetzt prüfen"); self.checkbtn.clicked.connect(self.check_updates); arow.addWidget(self.checkbtn)
        self.aurbtn = QPushButton("AUR im Terminal installieren"); self.aurbtn.clicked.connect(self.install_aur)
        self.aurbtn.setEnabled(False); arow.addWidget(self.aurbtn); arow.addStretch(); c.lay.addStretch()

        # Anordnung: breit = Einstellungen links, Status + Updates rechts, Ablauf darunter; schmal = eine Spalte
        self.grid = QGridLayout(); self.grid.setSpacing(14); lay.addLayout(self.grid, 1)
        self._wide = None; self._log_pref = None; self.reflow()

        # Fußleiste
        foot = QFrame(); foot.setObjectName("content"); outer.addWidget(foot)
        fl = QHBoxLayout(foot); fl.setContentsMargins(22, 8, 22, 16); fl.setSpacing(8)
        b = QPushButton("Schließen"); b.setObjectName("flat"); b.setToolTip("Fenster schließen, das Tool läuft im Systray weiter")
        b.clicked.connect(lambda: self.host.hide()); fl.addWidget(b)
        self.feedback = make_label("", "muted"); self.feedback.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred); fl.addWidget(self.feedback, 1)
        b = QPushButton("Log anzeigen"); b.clicked.connect(self.show_log); b.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed); fl.addWidget(b)
        b = QPushButton("Jetzt ausführen"); b.clicked.connect(self.run_now); b.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed); fl.addWidget(b)
        self.applybtn = QPushButton("Anwenden"); self.applybtn.setObjectName("primary")
        self.applybtn.clicked.connect(self.apply); self.applybtn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed); fl.addWidget(self.applybtn)

        # Systray
        self.tray = QSystemTrayIcon(QIcon.fromTheme("system-software-update"), self)
        menu = QMenu()
        def add(text, fn):
            a = QAction(text, menu); a.triggered.connect(fn); menu.addAction(a); return a
        add("Öffnen", self.show_window)
        menu.addSeparator()
        add("Auf Systemupdates prüfen", lambda: self.check_updates(True))
        add("Jetzt aktualisieren", self.run_now)
        menu.addSeparator()
        add("Nach Tool-Update suchen", lambda: self.check_self_update(True))
        self.act_upd = add("", self.self_update); self.act_upd.setVisible(False)   # nur bei neuer Version
        add("Einstellungen", self.open_settings)
        menu.addSeparator()
        add("Verlassen", self.quit)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(lambda r: self.show_window() if r == QSystemTrayIcon.ActivationReason.Trigger else None)
        self.tray.setToolTip("SoftCenter")
        self.tray.show()
        self.tray.messageClicked.connect(self.show_window)
        self._menu = menu

        for w in (self.mode, self.day):
            w.currentIndexChanged.connect(self.changed)
        self.time.timeChanged.connect(self.changed)
        for t in (self.enable, self.snap, self.aur):
            t.toggled.connect(self.changed)
        self.ignore.textChanged.connect(self.changed)
        self.load()
        self.timer = QTimer(self); self.timer.timeout.connect(self.poll); self.timer.start(2000)
        self.checker = QTimer(self); self.checker.timeout.connect(lambda: self.check_updates(True)); self.checker.start(int(cfg.value("interval", 3)) * 3600 * 1000)
        QTimer.singleShot(8000, lambda: self.check_updates(True))
        self.vchecker = QTimer(self); self.vchecker.timeout.connect(self.check_self_update); self.vchecker.start(12 * 3600 * 1000)
        QTimer.singleShot(20000, self.check_self_update)
        self.apply_cfg()
        self.poll()

    # ---- Fenster
    def notify(self, title, text, icon=QSystemTrayIcon.MessageIcon.Information):
        if flag("notify"): self.tray.showMessage(title, text, icon)

    def apply_cfg(self):
        self.auditlabel.setVisible(flag("audit", True))
        self.checker.start(int(cfg.value("interval", 3)) * 3600 * 1000)
        if flag("selfcheck"): self.vchecker.start(12 * 3600 * 1000)
        else: self.vchecker.stop()

    def open_system(self):
        SystemDialog(self).exec()

    def open_settings(self):
        SettingsDialog(self).exec()

    def show_window(self):
        self.host.bring_to_front()

    def quit(self):
        # Tray-Icon sofort entfernen, Timer/Prozesse stoppen, notfalls hart beenden
        self.tray.setVisible(False)
        for t in (self.timer, self.checker, self.vchecker, self.spinner): t.stop()
        for p in list(self.procs.values()) + [self.selfproc, self.aurproc if hasattr(self, "aurproc") else None]:
            if p: p.kill(); p.waitForFinished(500)
        self.app.quit()
        QTimer.singleShot(1500, lambda: os._exit(0))

    def reflow(self):
        """Drei Stufen: breit (3 Spalten, alles auf einer Seite), mittel (2 Spalten + Ablauf darunter), schmal (1 Spalte)."""
        mode = "triple" if self.width() >= 1140 else "double" if self.width() >= 700 else "single"
        if mode == self._wide: return
        self._wide = mode
        g = self.grid
        for cd in (self.card_set, self.card_flow, self.card_status, self.card_upd): g.removeWidget(cd)
        self.bar.parentWidget().layout().removeWidget(self.bar)
        if mode != "single": self.card_upd.lay.insertWidget(self.card_upd.lay.count() - 1, self.bar)   # unten, in der freien Fläche
        else: self.card_flow.lay.insertWidget(4, self.bar)                                                # direkt unter den Schritten
        for i in range(4): g.setRowStretch(i, 0)
        for i in range(3): g.setColumnStretch(i, 0)
        if mode == "triple":
            g.addWidget(self.card_set, 0, 0, 2, 1); g.addWidget(self.card_status, 0, 1); g.addWidget(self.card_upd, 1, 1)
            g.addWidget(self.card_flow, 0, 2, 2, 1)
            g.setColumnStretch(0, 4); g.setColumnStretch(1, 4); g.setColumnStretch(2, 7); g.setRowStretch(1, 1)
            if not self.liveview.isVisible() and self._log_pref is not False: self.set_live(True)   # Platz ist da: Protokoll gleich zeigen
        elif mode == "double":
            g.addWidget(self.card_set, 0, 0, 2, 1); g.addWidget(self.card_status, 0, 1); g.addWidget(self.card_upd, 1, 1)
            g.addWidget(self.card_flow, 2, 0, 1, 2)
            g.setColumnStretch(0, 1); g.setColumnStretch(1, 1); g.setRowStretch(1, 1); g.setRowStretch(2, 1)
        else:
            for i, cd in enumerate((self.card_set, self.card_flow, self.card_status, self.card_upd)): g.addWidget(cd, i, 0)
            g.setColumnStretch(0, 1); g.setRowStretch(1, 1)

    def resizeEvent(self, e):
        super().resizeEvent(e); self.reflow()

    def toggle_live(self):
        self._log_pref = not self.liveview.isVisible()      # Wunsch des Benutzers merken (wird nicht mehr automatisch überstimmt)
        self.set_live(self._log_pref)

    def set_live(self, show):
        self.liveview.setVisible(show); self.rawbtn.setVisible(show)
        self.logbtn.setText("Ablaufprotokoll verbergen ▴" if show else "Ablaufprotokoll anzeigen ▾")
        if show: self.refresh_liveview()

    def spin_tick(self):
        """Kleiner Spinner vor der Statuszeile: zeigt, dass das Tool lebt, auch wenn pacman gerade nichts ausgibt."""
        if not self.live.isVisible(): return
        self._spin = (self._spin + 1) % 10
        self.live.setText("⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"[self._spin] + "  " + self._live_text)

    def refresh_liveview(self):
        if not self.liveview.isVisible(): return
        sb = self.liveview.verticalScrollBar(); at_end = sb.value() >= sb.maximum() - 4; pos = sb.value()
        h = f'<span style="color:{theme["muted"]}">Noch kein Lauf aufgezeichnet.</span>' if self.cur_run is None \
            else timeline_html(self.cur_run, self.rawbtn.isChecked())
        if h == getattr(self, "_lv_html", None): return      # unverändert: nicht neu setzen (Scroll/Auswahl erhalten)
        self._lv_html = h; self.liveview.setHtml(h)
        sb.setValue(sb.maximum() if at_end else pos)

    # ---- Einstellungen
    def ui_state(self):
        return (self.enable.isChecked(), self.mode.currentData(), self.day.currentData(),
                self.time.time().toString("HH:mm"), self.snap.isChecked(), self.aur.isChecked(), norm_ignore(self.ignore.text()))

    def refresh_ignore_info(self):
        sysign = system_ignored()
        self.ignore_info.setText("Diese Pakete aktualisieren weder pacman noch paru im automatischen Lauf, bis du sie hier entfernst."
                                 + (f"\nZusätzlich in /etc/pacman.conf (IgnorePkg) eingetragen: {', '.join(sysign)}" if sysign else ""))

    def load(self):
        c = self.conf = load_conf()
        for w in (self.mode, self.day, self.time, self.enable, self.snap, self.aur, self.ignore): w.blockSignals(True)
        self.ignore.setText(", ".join(n for n in c.get("IGNORE", "").split(",") if n)); self.refresh_ignore_info()
        self.enable.setChecked(sh("systemctl", "is-enabled", "auto-update.timer").stdout.strip() == "enabled")
        self.mode.setCurrentIndex(max(0, self.mode.findData(c["MODE"])))
        self.day.setCurrentIndex(max(0, self.day.findData(c["DAY"])))
        self.time.setTime(QTime.fromString(c["TIME"], "HH:mm"))
        self.snap.setChecked(c["SNAPSHOT"] == "1")
        self.aur.setChecked(c.get("AUR") == "1")
        for w in (self.mode, self.day, self.time, self.enable, self.snap, self.aur, self.ignore): w.blockSignals(False)
        self.saved = self.ui_state()
        self.changed(); self.refresh_status(); self.load_last()

    def changed(self, *_):
        on = self.enable.isChecked(); m = self.mode.currentData()
        for w in (self.mode, self.snap, self.aur, self.ignore): w.setEnabled(on)
        self.day.setEnabled(on and m == "weekly"); self.time.setEnabled(on and m != "boot")
        self.day_l.setEnabled(self.day.isEnabled()); self.time_l.setEnabled(self.time.isEnabled())
        t = self.time.time().toString("HH:mm")
        if not on: s = "Automatische Updates sind ausgeschaltet."
        elif m == "daily": s = f"Das System wird jeden Tag um {t} Uhr aktualisiert."
        elif m == "weekly": s = f"Das System wird jeden {self.day.currentText()} um {t} Uhr aktualisiert."
        else: s = "Das System wird 5 Minuten nach jedem Start aktualisiert."
        self.summary.setText(s)
        dirty = self.saved is not None and self.ui_state() != self.saved
        self.applybtn.setEnabled(dirty)
        self.feedback.setText("● Ungespeichert" if dirty else self.feedback.text() if self.feedback.property("keep") else "")
        self.refresh_header()
        self.render_steps(self.was_active, self.cur_run if self.was_active else (self.last[0] if self.last else None), None if self.was_active or not self.last else self.last[1])

    # ---- Anzeige
    def refresh_header(self, running=None):
        running = self.was_active if running is None else running
        if running:
            self.pill.setText("● Update läuft"); set_state(self.pill, "run"); self.subtitle.setText("Das System wird gerade aktualisiert")
        elif self.saved and self.saved[0]:
            self.pill.setText("● Aktiv"); set_state(self.pill, "on")
            self.subtitle.setText(self.schedule_text(self.saved))
        else:
            self.pill.setText("Deaktiviert"); set_state(self.pill, "off"); self.subtitle.setText("Keine automatischen Updates geplant")
        self.header_changed.emit(self.subtitle.text(), self.pill.text(), self.pill.property("state") or "off")

    def schedule_text(self, s):
        _, m, d, t, *_ = s
        if m == "daily": return f"Täglich um {t} Uhr"
        if m == "weekly": return f"Jeden {dict((v, n) for n, v in DAYS)[d]} um {t} Uhr"
        return "5 Min. nach dem Systemstart"

    def refresh_status(self):
        mode = self.conf.get("MODE")
        nxt = parse_ts(sh("systemctl", "show", "auto-update.timer", "-p", "NextElapseUSecRealtime", "--value").stdout)
        if self.saved and not self.saved[0]: self.st_next.setText("– (deaktiviert)")
        elif nxt: self.st_next.setText(f"{fmt_dt(nxt)}  ({fmt_delta(QDateTime.currentDateTime().secsTo(nxt))})")
        elif mode == "boot": self.st_next.setText("5 Minuten nach dem nächsten Systemstart")
        else: self.st_next.setText("–")
        ts = parse_ts(sh("systemctl", "show", "auto-update.service", "-p", "ExecMainExitTimestamp", "--value").stdout)
        _inv, res = last_run_state()
        if not ts:       # nach einem Neustart kennt systemd den Zeitpunkt nicht mehr -> aus dem Journal lesen
            run = self.fetch_run(); t = run.done or run.last
            if t: ts = QDateTime.fromSecsSinceEpoch(int(t.timestamp()))
        if ts:
            ok = res == "success"
            self.st_last.setText(f"{fmt_dt(ts)}\n{'✓' if ok else '✕'} {RESULTS.get(res, res or '–')}")
        else:
            self.st_last.setText("Noch nie ausgeführt")
        self.refresh_mirrors()

    def fetch_run(self):
        """Journal des aktuellen/letzten Laufs holen und auswerten (None, wenn es keinen gibt)."""
        inv, _res = last_run_state()
        raw = sh("journalctl", f"_SYSTEMD_INVOCATION_ID={inv}", "-o", "short-iso", "--no-pager").stdout if inv else ""
        r = parse_run(raw)
        # Ältere Läufe: paru lief in einer eigenen Login-Session (anderes Journal-Feld) -> Zeilen nachladen
        if "aur" in r.phases and r.c["aur"].events <= 1:
            since = r.start["aur"].strftime("%Y-%m-%d %H:%M:%S")
            cmd = ["journalctl", "--since", since, "-o", "short-iso", "--no-pager", f"_UID={os.getuid()}", "SYSLOG_IDENTIFIER=systemd-inhibit"]
            if r.done: cmd[3:3] = ["--until", DT.fromtimestamp(r.done.timestamp() + 3).strftime("%Y-%m-%d %H:%M:%S")]   # +3 s: die letzte Zeile liegt oft in derselben Sekunde
            extra = sh(*cmd).stdout
            if extra.strip():
                lines = list(dict.fromkeys(l for l in (raw + "\n" + extra).splitlines() if l.strip()))   # ohne Doppelte
                lines.sort(key=lambda l: l[:19])
                r = parse_run("\n".join(lines))
        return r

    def refresh_mirrors(self):
        """Mirror-Stand: Alter der Mirrorlist und nächste automatische Bewertung (Timer des Mirror-Werkzeugs)."""
        if not self.mir:
            self.st_mir.setText("kein Mirror-Dienst gefunden" + (" (Manjaro: pacman-mirrors nutzen)" if self.sys.kind == "manjaro"
                                else " – z. B. 'sudo pacman -S reflector'"))
            self.mirbtn.setEnabled(False); return
        svc, tim, name = self.mir
        try: mt = os.path.getmtime("/etc/pacman.d/mirrorlist"); age = (time.time() - mt) / 86400; when = DT.fromtimestamp(mt)
        except OSError: self.st_mir.setText("keine Mirrorlist gefunden"); self.mirbtn.setEnabled(False); return
        if self.mir_running: self.st_mir.setText("wird gerade neu bewertet …"); return
        days = int(age)
        txt = f"zuletzt bewertet: {when:%d.%m.%Y %H:%M} ({'heute' if days == 0 else 'vor 1 Tag' if days == 1 else f'vor {days} Tagen'})"
        if sh("systemctl", "is-enabled", tim).stdout.strip() == "enabled":
            nxt = parse_ts(sh("systemctl", "show", tim, "-p", "NextElapseUSecRealtime", "--value").stdout)
            txt += f"\nautomatisch wieder: {nxt.toString('dd.MM.yyyy')}" if nxt else f"\nautomatische Bewertung aktiv ({name})"
        else:
            txt += "\nautomatische Bewertung ist aus" + (" – Mirrors sind veraltet" if days > 45 else "")
        self.st_mir.setText(txt); self.mirbtn.setEnabled(True)

    def mirrors_now(self):
        if self.mir_running or not self.mir: return
        svc, tim, name = self.mir
        extra = "" if name == "cachyos-rate-mirrors" else "\n\nHinweis: reflector überschreibt die Mirrorlist; ich lege vorher eine Sicherung mirrorlist-backup an."
        if QMessageBox.question(self, "Mirrors aktualisieren", f"Die schnellsten Mirrors mit {name} neu bewerten?\n\n"
                                f"Das dauert ein bis zwei Minuten. Die bisherigen Listen bleiben als *-backup in /etc/pacman.d erhalten.{extra}") \
                != QMessageBox.StandardButton.Yes: return
        if name == "cachyos-rate-mirrors": r = sh("pkexec", "/usr/bin/systemctl", "start", "--no-block", svc)
        else: r = sh("pkexec", "/bin/sh", "-c", f"cp -a /etc/pacman.d/mirrorlist /etc/pacman.d/mirrorlist-backup && /usr/bin/systemctl start --no-block {svc}")
        if r.returncode: QMessageBox.warning(self, "Fehler", r.stderr or "Abgebrochen"); return
        self.mir_running = True; self.mirbtn.setEnabled(False); self.mirbtn.setText("Bewerte Mirrors …"); self.refresh_mirrors()

    def mirrors_finished(self):
        res = sh("systemctl", "show", self.mir[0], "-p", "Result", "--value").stdout.strip()
        self.mir_running = False; self.mirbtn.setText("Mirrors jetzt aktualisieren"); self.refresh_mirrors()
        ok = res == "success"
        self.flash("✓ Mirrors aktualisiert" if ok else f"✕ Mirror-Bewertung fehlgeschlagen ({res})", 8000)
        self.notify("Mirrors", "Mirrors wurden neu bewertet." if ok else f"Mirror-Bewertung fehlgeschlagen ({res}).",
                    QSystemTrayIcon.MessageIcon.Information if ok else QSystemTrayIcon.MessageIcon.Warning)

    def render_steps(self, running, r, result=None):
        """Zeigt den Ablauf: live (running), letzter Lauf (result) oder Vorschau."""
        have = r is not None and bool(r.phases)
        keys = [k for k, _, _ in STEPS]
        info = {}; now = DT.now()
        enabled = {"snapshot": self.conf.get("SNAPSHOT", "1") == "1", "pacman": True, "aur": self.conf.get("AUR") == "1"}
        def times(k):
            a = r.start.get(k); b = r.end.get(k) or (r.done if r.done else None)
            return a, b
        self.bar.set_mode("run" if running else ("over" if result not in (None, "success") and have else
                                                 "clear" if have and result is not None else "ready"))
        if running and r is not None:
            cur = r.phases[-1] if r.phases else next((k for k in keys if enabled[k]), "pacman")
            self.flow_title.setText(f"Läuft seit {r.first:%H:%M:%S} · {fmt_dur((now - r.first).total_seconds())}" if r.first else "Läuft gerade")
            for k in keys:
                a, b = times(k)
                if k in r.phases and k != cur:
                    info[k] = ("done", f"Fertig · {fmt_dur((b - a).total_seconds())}" if a and b else "Fertig",
                               f"{a:%H:%M:%S} – {b:%H:%M:%S} · {run_summary(r, k)}".rstrip(" ·") if a and b else "")
                elif k == cur:
                    el = fmt_dur((now - a).total_seconds()) if a else ""
                    info[k] = ("active", f"Läuft · {el}" if el else "Läuft …", (f"seit {a:%H:%M:%S} · " if a else "") + run_activity(r, k))
                elif not enabled[k] and k not in r.phases: info[k] = ("off", "Übersprungen", "")
                else: info[k] = ("idle", "Wartet", "")
        elif have and result is not None:
            fail = result != "success"
            bad = next((k for k in r.phases if any(e[1] == k and e[2] == "err" for e in r.events)), r.phases[-1]) if fail else None
            end = r.done or r.last
            self.flow_title.setText(f"Letzter Lauf · {r.first:%d.%m. %H:%M} · {fmt_dur((end - r.first).total_seconds())}")
            for k in keys:
                a, b = times(k)
                if k not in r.phases: info[k] = ("off", "Nicht ausgeführt", ""); continue
                dur = f" · {fmt_dur((b - a).total_seconds())}" if a and b else ""
                span = f"{a:%H:%M:%S} – {b:%H:%M:%S} · " if a and b else ""
                info[k] = ("failed", "Fehler" + dur, span.rstrip(" ·") + "\n" + fail_text(r, k)) if k == bad else \
                          ("done", "Fertig" + dur, (span + run_summary(r, k)).rstrip(" ·"))
        else:
            self.flow_title.setText("Geplanter Ablauf")
            on = self.enable.isChecked()
            for k in keys:
                en = {"snapshot": self.snap.isChecked(), "pacman": True, "aur": self.aur.isChecked()}[k]
                info[k] = ("idle", "Geplant", "") if on and en else ("off", "Aus", "")
        for k, (st, text, detail) in info.items(): self.rows[k].set(st, text, detail)
        if have and not running and result not in (None, "success") and info.get("aur", ("",))[0] == "failed":
            skip = set(norm_ignore(self.ignore.text()).split(","))
            names = [n for n in failed_pkgs(r) if n not in skip]
            if names:
                self.rows["aur"].set_action("„%s“ künftig überspringen" % ", ".join(names[:2]), lambda _=False, n=names: self.add_ignore(n))

    def add_ignore(self, names):
        """Pakete in die Ausnahmeliste eintragen (gespeichert wird mit 'Anwenden')."""
        cur = [n for n in norm_ignore(self.ignore.text()).split(",") if n]
        self.ignore.setText(", ".join(cur + [n for n in names if n not in cur]))
        self.flash("Eingetragen – mit „Anwenden“ speichern", 8000)

    def load_last(self):
        _inv, res = last_run_state()
        r = self.fetch_run()
        self.last = (r, res)
        if not self.was_active:
            self.cur_run = r if r.phases else None
            self.render_steps(False, r, res); self.refresh_liveview()

    def poll(self, force=False):
        if self.mir_running and sh("systemctl", "is-active", self.mir[0]).stdout.strip() not in ("active", "activating"):
            self.mirrors_finished()
        active = sh("systemctl", "is-active", "auto-update.service").stdout.strip() in ("active", "activating")
        if active:
            r = self.fetch_run(); self.cur_run = r
            if not self.was_active: self.conf = load_conf(); self.refresh_header(True); self.dl_hist = []
            self.bar.set_mode("run"); self.live.show()
            cur = r.phases[-1] if r.phases else None
            c = r.c[cur] if cur else None
            progressing = False
            if cur == "pacman" and c.stage == "download" and c.size_bytes:
                # pacman schreibt beim Download nichts ins Journal -> Fortschritt aus dem Paket-Cache lesen
                got, active = download_progress(c.stage_at["download"].timestamp() - 3)
                nowt = time.monotonic(); self.dl_hist = [(t, b) for t, b in self.dl_hist if nowt - t < 12] + [(nowt, got)]
                (t0, b0) = self.dl_hist[0]; speed = (got - b0) / (nowt - t0) if nowt - t0 >= 2 else 0
                progressing = speed > 0 or got > b0
                pct = min(100, int(got * 100 / c.size_bytes))
                eta = f" · noch ca. {fmt_dur((c.size_bytes - got) / speed)}" if speed > 1024 and got < c.size_bytes else ""
                c.dl_live = (f"Lade herunter {fmt_size(got)} / {c.size} ({pct} %)"
                             + (f" · {fmt_size(speed)}/s" if speed > 1024 else "") + eta
                             + (f" · lädt: {', '.join(active[:3])}{' …' if len(active) > 3 else ''}" if active else "")
                             if got else f"Verbindung zum Server … ({c.total} Pakete, {c.size})")
                self.bar.setRange(0, 1000); self.bar.setValue(got * 1000 // c.size_bytes)
            elif cur == "pacman" and c.total and c.stage == "install":
                self.bar.setRange(0, c.total); self.bar.setValue(c.inst)
            elif cur == "aur" and r.start.get("aur"):
                # AUR: fertig gebaute Pakete zählen (Pac-Man frisst pro Paket) und wachsende Quell-Downloads anzeigen
                built, parts = aur_activity(r.start["aur"].timestamp() - 3)
                total = len(c.rows)
                psize = sum(sz for _d, _f, sz in parts)
                nowt = time.monotonic(); self.dl_hist = [(t, b) for t, b in self.dl_hist if nowt - t < 15] + [(nowt, psize)]
                (t0, b0) = self.dl_hist[0]; speed = (psize - b0) / (nowt - t0) if nowt - t0 >= 3 else 0
                progressing = bool(parts) and (speed > 0 or psize > b0)
                bits = []
                if total: bits.append(f"{len(built)}/{total} gebaut")
                if built: bits.append("fertig: " + ", ".join(built[:3]) + (" …" if len(built) > 3 else ""))
                if parts:
                    pk, fn, sz = parts[0]
                    bits.append(f"lädt Quellen: {fn} {fmt_size(sz)}" + (f" · {fmt_size(speed)}/s" if speed > 1024 else ""))
                c.dl_live = " · ".join(bits)
                if total: self.bar.setRange(0, total); self.bar.setValue(len(built))
                else: self.bar.setRange(0, 0)
            else:
                self.bar.setRange(0, 0)  # unbestimmt: Pac-Man jagt die Geister
            if not ((cur == "pacman" and c.stage == "download") or cur == "aur"): self.dl_hist = []
            self.render_steps(True, r)
            act = run_activity(r, cur) if cur else "Starte …"
            age = (DT.now() - r.last).total_seconds() if r.last else 0
            quiet = f"  ·  letzte Ausgabe vor {fmt_dur(age)}" if age >= 10 and not progressing else ""
            self._live_text = f"{PHASE_TAGS.get(cur, 'Start')}: {act}{quiet}"
            self.refresh_liveview()
            self.tray.setToolTip(f"Update läuft – {PHASE_TAGS.get(cur, 'Start')}: {act}"[:120]); self.spin_tick()
        elif self.was_active:
            self.live.hide()
            self.was_active = False          # vor load_last(), sonst wird die Schritt-Anzeige nicht aktualisiert
            self.load_last(); self.refresh_status()
            ok = self.last[1] == "success"
            self.refresh_header(False)
            self.notify("Automatische Updates", "Update abgeschlossen." if ok else f"Update fehlgeschlagen ({self.last[1]}).",
                                  QSystemTrayIcon.MessageIcon.Information if ok else QSystemTrayIcon.MessageIcon.Warning)
            QTimer.singleShot(5000, lambda: self.check_updates(True))
            self.cur_run = self.last[0] if self.last[0].phases else None; self.refresh_liveview()
        self.was_active = active
        self.ticks += 1
        if not active and self.ticks % 15 == 0: self.refresh_status()

    def flash(self, text, ms=4000):
        self.feedback.setProperty("keep", True); self.feedback.setText(text)
        def clear():
            self.feedback.setProperty("keep", False); self.changed()
        QTimer.singleShot(ms, clear)

    # ---- Aktionen
    def apply(self):
        aur = self.aur.isChecked() and self.enable.isChecked()
        args = ["pkexec", "/usr/local/bin/auto-update-apply", "1" if self.enable.isChecked() else "0",
                self.mode.currentData(), self.day.currentData(), self.time.time().toString("HH:mm"),
                "1" if self.snap.isChecked() else "0", "1" if aur else "0", norm_ignore(self.ignore.text())]
        if aur and QMessageBox.warning(
                self, "AUR automatisch", "Damit darf dein Benutzer ohne Passwort 'sudo pacman' ausführen, und AUR-Pakete "
                "werden ohne PKGBUILD-Prüfung gebaut.\n\nWirklich aktivieren?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        r = sh(*args)
        if r.returncode: QMessageBox.warning(self, "Fehler", r.stderr or "Abgebrochen")
        self.load()
        if not r.returncode: self.flash("✓ Einstellungen gespeichert")

    def run_now(self):
        if QMessageBox.question(self, "Update", "Update jetzt im Hintergrund starten?") == QMessageBox.StandardButton.Yes:
            r = sh("pkexec", "/usr/bin/systemctl", "start", "--no-block", "auto-update.service")
            if r.returncode: QMessageBox.warning(self, "Fehler", r.stderr or "Abgebrochen")
            self.poll()

    def check_updates(self, silent=False):
        if self.procs: return
        self.checkbtn.setEnabled(False); self.checkbtn.setText("Prüfe …")
        self.repolabel.setText("System (pacman): prüfe …"); self.aurlabel.setText("AUR: prüfe …")
        checks = [("repo", "checkupdates", []), ("aur", "paru", ["-Qua"])]
        if flag("audit", True):
            self.auditlabel.setText("Sicherheit (arch-audit): prüfe …")
            checks.append(("audit", "arch-audit", ["-f", "%n|%s|%v|%c|%t"]))
        for name, cmd, args in checks:
            if not shutil.which(cmd):
                self.done_check(name, None, None); continue
            p = QProcess(self); self.procs[name] = p
            p.finished.connect(lambda code, _s, n=name: self.done_check(n, code, bytes(self.procs[n].readAllStandardOutput()).decode(),
                                                                       bytes(self.procs[n].readAllStandardError()).decode()))
            p.start(cmd, args)

    def done_audit(self, code, out, err):
        if code is None:
            self.audit = []; self.auditlabel.setText("Sicherheit: arch-audit fehlt  →  sudo pacman -S arch-audit"); return
        items = parse_audit(out)
        if code not in (0, 1) or (not items and err.strip()):
            self.audit = []; self.auditlabel.setText("Sicherheit (arch-audit): Prüfung fehlgeschlagen – keine Verbindung zu security.archlinux.org?"); return
        self.audit = items; self.auditlabel.setText(audit_text(items))

    def done_check(self, name, code, out, err=""):
        self.procs.pop(name, None)
        if name == "audit": self.done_audit(code, out, err)
        else:
            lines = [l for l in (out or "").splitlines() if l.strip()]
            ign = {n for n in self.conf.get("IGNORE", "").split(",") if n} | set(system_ignored())
            skipped = lambda l: "[ignoriert]" in l or "[ignored]" in l or l.split()[0] in ign
            active = [l for l in lines if not skipped(l)]
            n_skip = len(lines) - len(active)
            lines = [l if not skipped(l) or "[ignor" in l else l + "  [übersprungen]" for l in lines]
            label = self.repolabel if name == "repo" else self.aurlabel
            title = "System (pacman)" if name == "repo" else "AUR"
            if code is None:
                label.setText(f"{title}: Werkzeug fehlt ({'pacman-contrib' if name == 'repo' else 'paru'})")
            elif code not in (0, 1, 2) or (name == "repo" and code == 1):
                label.setText(f"{title}: Prüfung fehlgeschlagen")
            elif active:
                label.setText(f"{title}: {len(active)} verfügbar" + (f" ({n_skip} übersprungen)" if n_skip else "") + "\n"
                              + "\n".join(f"   {l}" for l in lines[:8]) + ("\n   …" if len(lines) > 8 else ""))
            elif lines:
                label.setText(f"{title}: ✓ alles aktuell ({n_skip} übersprungen)\n" + "\n".join(f"   {l}" for l in lines[:4]))
            else:
                label.setText(f"{title}: ✓ alles aktuell")
            if code in (0, 2): self.counts[name] = len(active)
            else: self.counts.pop(name, None)
            if name == "aur": self.aurbtn.setEnabled(bool(active))
        if not self.procs:
            self.checkbtn.setEnabled(True); self.checkbtn.setText("Jetzt prüfen")
            self.update_tray_badge()

    def update_tray_badge(self):
        n = sum(self.counts.values())
        self.badge_changed.emit(n)
        base = QIcon.fromTheme("system-software-update")
        if n:
            pm = base.pixmap(64, 64)
            p = QPainter(pm); p.setRenderHint(QPainter.RenderHint.Antialiasing)
            p.setPen(Qt.PenStyle.NoPen); p.setBrush(QColor(theme["err"])); p.drawEllipse(QRectF(28, 0, 36, 36))
            p.setPen(QColor("white")); f = QFont(); f.setBold(True); f.setPixelSize(22 if n < 100 else 17); p.setFont(f)
            p.drawText(QRectF(28, 0, 36, 36), Qt.AlignmentFlag.AlignCenter, str(n)); p.end()
            self.tray.setIcon(QIcon(pm))
            parts = [f"{self.counts.get('repo', 0)} System", f"{self.counts.get('aur', 0)} AUR"]
            self.tray.setToolTip(f"{n} Updates verfügbar ({', '.join(parts)})")
            if n != self.notified and not self.was_active:
                self.notify("Updates verfügbar", f"{n} Updates warten ({', '.join(parts)}). Klick zum Öffnen.",
                                      QSystemTrayIcon.MessageIcon.Information)
        else:
            self.tray.setIcon(base); self.tray.setToolTip("SoftCenter – alles aktuell")
        self.notified = n
        fixable = [a for a in self.audit if a["fix"]]
        if fixable:
            self.tray.setToolTip(self.tray.toolTip() + f"\n⚠ {len(fixable)} Paket(e) mit Sicherheitslücke und verfügbarem Fix")
            key = ",".join(a["name"] for a in fixable)
            if key != getattr(self, "notified_sec", "") and not self.was_active:
                top = fixable[0]
                self.notify("Sicherheitslücken", f"{len(fixable)} Paket(e) mit bekannter Lücke haben ein Update, z. B. {top['name']} "
                            f"({SEV_DE.get(top['sev'], 'unbekannt')}). Klick zum Öffnen.", QSystemTrayIcon.MessageIcon.Warning)
            self.notified_sec = key
        else:
            self.notified_sec = ""

    # ---- Selbst-Update des Tools (GitHub-Releases)
    def check_self_update(self, force=False):
        if self.selfproc:
            if force is True and self.ver_cb: self.ver_cb("Eine Prüfung läuft bereits …", False)
            return
        if not (force is True or flag("selfcheck")): return
        self.manual = force is True
        p = self.selfproc = QProcess(self)
        p.finished.connect(lambda code, _s: self.self_check_done(code, bytes(p.readAllStandardOutput()).decode()))
        p.start("curl", ["-fsS", "-m", "15", "-H", "Accept: application/vnd.github+json",
                         f"https://api.github.com/repos/{REPO}/releases/latest"])

    def self_check_done(self, code, out):
        self.selfproc = None
        try:
            d = json.loads(out) if code == 0 else {}
        except ValueError:
            d = {}
        tag = d.get("tag_name", "")
        manual, self.manual = self.manual, False
        if not tag:
            self.st_ver.setText(f"{VERSION} (Update-Prüfung nicht möglich)")
            if self.ver_cb: self.ver_cb("✕ Prüfung nicht möglich – keine Verbindung zu GitHub oder noch kein Release.", False)
            if manual: self.tray.showMessage("Tool-Update", "Prüfung nicht möglich (keine Verbindung zu GitHub?).", QSystemTrayIcon.MessageIcon.Warning)
            return
        if vtuple(tag) > vtuple(VERSION):
            self.upd_tag, self.upd_url = tag, d.get("html_url", f"https://github.com/{REPO}/releases")
            self.upd_title.setText(f"🎉 Neue Version {tag} verfügbar (installiert: {VERSION})")
            notes = (d.get("body") or "").strip()
            self.upd_notes.setText(notes[:400] + ("…" if len(notes) > 400 else "") or "Keine Versionshinweise.")
            self.upd_card.show()
            self.act_upd.setText(f"⬆ Tool auf {tag} aktualisieren"); self.act_upd.setVisible(True)
            if self.ver_cb: self.ver_cb(f"🎉 Neue Version {tag} verfügbar (installiert: {VERSION}).", True)
            self.st_ver.setText(f"{VERSION} → {tag} verfügbar")
            if self.notified_ver != tag:
                self.notified_ver = tag
                self.notify("Neue Version von Automatische Updates", f"{tag} ist verfügbar. Klick zum Öffnen.",
                                      QSystemTrayIcon.MessageIcon.Information)
        else:
            self.upd_card.hide(); self.act_upd.setVisible(False); self.st_ver.setText(f"{VERSION} (aktuell)")
            if self.ver_cb: self.ver_cb(f"✓ Du hast die aktuelle Version ({VERSION}).", False)
            if manual: self.tray.showMessage("Tool-Update", f"Du nutzt die aktuelle Version {VERSION}.", QSystemTrayIcon.MessageIcon.Information)

    def self_update(self):
        if self.selfproc or not self.upd_tag: return
        if QMessageBox.question(self, "Tool aktualisieren", f"Version {self.upd_tag} von GitHub holen und installieren?\n"
                                "Das Fenster startet danach neu.") != QMessageBox.StandardButton.Yes:
            return
        self.upd_btn.setEnabled(False); self.upd_btn.setText("Installiere …")
        p = self.selfproc = QProcess(self)
        p.finished.connect(lambda code, _s: self.self_update_done(code, bytes(p.readAllStandardError()).decode()))
        p.start("pkexec", ["/usr/local/bin/auto-update-self", self.upd_tag])

    def self_update_done(self, code, err):
        self.selfproc = None
        if code:
            self.upd_btn.setEnabled(True); self.upd_btn.setText("Jetzt aktualisieren")
            QMessageBox.warning(self, "Update fehlgeschlagen", err.strip() or "Abgebrochen"); return
        self.tray.hide()
        args = [sys.executable, "/usr/local/bin/auto-update-gui"] + ([] if self.isVisible() else ["--tray"])
        os.execv(sys.executable, args)

    def install_aur(self):
        for term, flag in (("konsole", "-e"), ("kitty", ""), ("alacritty", "-e")):
            if shutil.which(term):
                cmd = [term] + ([flag] if flag else []) + ["bash", "-c", "paru -Sua; echo; read -p 'Fertig, Enter zum Schließen'"]
                subprocess.Popen(cmd)
                return
        QMessageBox.warning(self, "Fehler", "Kein Terminal gefunden.")

    def show_log(self):
        d = QDialog(self); d.setWindowTitle("Update-Log"); d.resize(860, 520)
        v = QVBoxLayout(d); t = QPlainTextEdit(); t.setReadOnly(True); v.addWidget(t)
        r = self.fetch_run()      # derselbe Weg wie das Ablaufprotokoll: Dienst-Journal plus paru-Zeilen aus der Benutzer-Session
        text = "\n".join(f"{dt:%d.%m. %H:%M:%S}  {PHASE_TAGS.get(ph, ph):6} {msg}" for dt, ph, msg in r.raw)
        t.setPlainText(text or sh("journalctl", "-u", "auto-update.service", "-n", "400", "--no-pager").stdout or "Keine Einträge.")
        t.verticalScrollBar().setValue(t.verticalScrollBar().maximum())
        d.exec()
