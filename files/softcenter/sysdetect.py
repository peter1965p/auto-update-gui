"""Erkennung des Arch-Systems (Distribution, Repos, CPU-Stufe) und passender Werkzeuge."""
import os, re, shutil
from types import SimpleNamespace
from .common import sh

DISTROS = {
    "cachyos": ("CachyOS", "Arch-Basis mit für x86-64-v3/v4 optimierten Repos, eigenem Kernel und eigenem Mirror-Dienst."),
    "arch": ("Arch Linux", "Das Original: rollende Releases, kein Zusatz-Repo. Mirror-Pflege über reflector."),
    "endeavouros": ("EndeavourOS", "Fast reines Arch mit einem kleinen eigenen Repo. Mirror-Pflege über reflector."),
    "garuda": ("Garuda Linux", "Arch-Basis mit Btrfs-/Snapper-Voreinstellung und vorkonfiguriertem Chaotic-AUR."),
    "manjaro": ("Manjaro", "Eigene, verzögerte Repos. Nicht mit Arch-Repos oder dem AUR mischen – die AUR-Automatik ist hier riskant."),
    "blackarch": ("BlackArch", "Arch mit tausenden Sicherheits- und Pentest-Werkzeugen."),
    "artix": ("Artix Linux", "Arch ohne systemd (OpenRC/runit/s6) – dieses Tool braucht systemd und läuft hier nicht."),
}
SOURCES = [  # (Schlüssel, Titel, Beschreibung, Link)
    ("cachyos", "CachyOS-Repos & Kernel", "Für x86-64-v3/v4 optimierte Pakete, CachyOS-Kernel (BORE-Scheduler), eigene Mirror-Pflege.", "https://wiki.cachyos.org/"),
    ("chaotic", "Chaotic-AUR", "Fertig gebaute AUR-Pakete: spart Compile-Zeit, vor allem bei großen Paketen (z. B. docker-desktop oder Browser).", "https://aur.chaotic.cx/"),
    ("blackarch", "BlackArch-Repo", "Sammlung von Sicherheits- und Pentest-Werkzeugen, nur für autorisierte Tests. Einzelne Pakete installieren, nicht die ganze Gruppe.", "https://blackarch.org/downloads.html"),
]

def read_os_release(path="/etc/os-release"):
    d = {}
    try:
        for line in open(path):
            if "=" in line: k, v = line.strip().split("=", 1); d[k] = v.strip('"')
    except OSError:
        pass
    return d

def cpu_level(flags=None):
    """x86-64-Mikroarchitektur-Stufe (1–4) aus den CPU-Flags."""
    if flags is None:
        try: flags = set(next(l for l in open("/proc/cpuinfo") if l.startswith("flags")).split(":", 1)[1].split())
        except (OSError, StopIteration): flags = set()
    v2 = {"cx16", "popcnt", "ssse3", "sse4_2"}
    v3 = v2 | {"avx", "avx2", "bmi1", "bmi2", "f16c", "fma", "abm", "movbe", "xsave"}
    v4 = v3 | {"avx512f", "avx512bw", "avx512cd", "avx512dq", "avx512vl"}
    return 4 if v4 <= flags else 3 if v3 <= flags else 2 if v2 <= flags else 1

def detect_system(osr=None, repos=None, flags=None, has_pacman=None):
    osr = read_os_release() if osr is None else osr
    repos = sh("pacman-conf", "--repo-list").stdout.split() if repos is None else repos
    ident = osr.get("ID", "").lower(); like = osr.get("ID_LIKE", "").lower().split()
    kind = ident if ident in DISTROS else ("arch" if "arch" in like else "other")
    if kind == "arch" and ident not in ("", "arch"): kind = "other"
    if not (shutil.which("pacman") if has_pacman is None else has_pacman): kind = "foreign"
    has = {"cachyos": any(r.startswith("cachyos") for r in repos), "chaotic": "chaotic-aur" in repos,
           "blackarch": "blackarch" in repos, "multilib": "multilib" in repos}
    return SimpleNamespace(kind=kind, id=ident, name=osr.get("PRETTY_NAME") or osr.get("NAME") or "Unbekannt",
                           repos=repos, has=has, cpu=cpu_level(flags))

def mirror_backend(kind):
    """(Dienst, Timer, Name) zum Neubewerten der Mirrors – passend zum System; None, wenn es keinen sicheren gibt."""
    if kind == "manjaro": return None            # Manjaro nutzt pacman-mirrors; Arch-Mirrors würden es zerschießen
    cands = [("cachyos-rate-mirrors.service", "cachyos-rate-mirrors.timer", "cachyos-rate-mirrors"),
             ("reflector.service", "reflector.timer", "reflector")]
    if kind != "cachyos": cands.reverse()
    for svc, tim, name in cands:
        if sh("systemctl", "cat", svc).returncode == 0: return svc, tim, name
    return None

def source_state(sysi, key):
    """('ok'|'info'|'warn'|'no', Text) zu einer möglichen Zusatzquelle für dieses System."""
    if sysi.kind == "foreign": return "no", "⛔ kein Arch-System (kein pacman)"
    if sysi.kind == "manjaro": return "no", "⛔ nicht mit Manjaro mischen – eigene Repos, bricht leicht"
    if sysi.kind == "artix": return "no", "⛔ Artix hat eigene Repos"
    if key == "cachyos":
        if sysi.has["cachyos"] or sysi.kind == "cachyos": return "ok", "✓ eingerichtet"
        lvl = sysi.cpu
        return ("info", f"nicht eingerichtet · deine CPU kann x86-64-v{min(lvl, 4)} → v3-Repo möglich") if lvl >= 3 else \
               ("warn", f"nicht eingerichtet · deine CPU kann nur x86-64-v{lvl} → optimierte v3-Pakete laufen nicht")
    if key == "chaotic": return ("ok", "✓ eingerichtet") if sysi.has["chaotic"] else ("info", "nicht eingerichtet")
    if key == "blackarch": return ("ok", "✓ eingerichtet") if sysi.has["blackarch"] or sysi.kind == "blackarch" else ("info", "nicht eingerichtet")
    return "info", ""

