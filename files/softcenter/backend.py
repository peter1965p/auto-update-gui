"""Paketsuche und -abfragen (pacman, AUR)."""
import json
import os
import subprocess
import urllib.parse
import urllib.request

from PyQt6.QtCore import QObject, pyqtSignal as Signal

AUR_HELPERS = ("paru", "yay")


def search_repo(term):
    """Sucht in den pacman-Repos. Rückgabe: Liste (quelle, name, version, beschreibung, installiert)."""
    if not term:  # ohne Suchbegriff alle Repo-Pakete auflisten
        out = subprocess.run(["pacman", "-Sl"], capture_output=True, text=True).stdout
        result = []
        for line in out.splitlines():
            parts = line.split()
            if len(parts) >= 3:
                result.append((parts[0], parts[1], parts[2], "", "[installed" in line))
        return result
    out = subprocess.run(["pacman", "-Ss", term], capture_output=True, text=True).stdout
    result = []
    lines = out.splitlines()
    for i in range(0, len(lines) - 1, 2):
        head, desc = lines[i].split(), lines[i + 1].strip()
        if len(head) < 2 or "/" not in head[0]:
            continue
        repo, name = head[0].split("/", 1)
        result.append((repo, name, head[1], desc, "[installed" in lines[i]))
    return result


def search_aur(term):
    """Sucht über die AUR-RPC-Schnittstelle."""
    url = "https://aur.archlinux.org/rpc/v5/search/%s?by=name-desc" % urllib.parse.quote(term)
    with urllib.request.urlopen(url, timeout=15) as r:
        data = json.load(r)
    return [("aur", p["Name"], p["Version"], p.get("Description") or "", False)
            for p in data.get("results", [])]


def search_installed(term, mode="installed"):
    """mode: 'installed' (alle) | 'explicit' (selbst installiert) | 'foreign' (nicht aus den Repos, z. B. AUR)."""
    only = None
    if mode in ("explicit", "foreign"):
        flag = "-Qqe" if mode == "explicit" else "-Qqm"
        only = set(subprocess.run(["pacman", flag], capture_output=True, text=True).stdout.split())
    out = subprocess.run(["pacman", "-Qs", term], capture_output=True, text=True).stdout
    result = []
    lines = out.splitlines()
    for i in range(0, len(lines) - 1, 2):
        head = lines[i].split()
        if len(head) < 2 or "/" not in head[0]:
            continue
        repo, name = head[0].split("/", 1)
        if only is None or name in only:
            result.append((repo, name, head[1], lines[i + 1].strip(), True))
    return result


def installed_names():
    out = subprocess.run(["pacman", "-Qq"], capture_output=True, text=True).stdout
    return set(out.split())


def package_info(names):
    """Details zu Repo-Paketen. Rückgabe: {name: {Repository, Name, Version, Description}}."""
    info = {}
    out = subprocess.run(["pacman", "-Si"] + list(names), capture_output=True, text=True,
                         env=dict(os.environ, LC_ALL="C")).stdout
    for block in out.split("\n\n"):
        f = {}
        for line in block.splitlines():
            key, sep, val = line.partition(":")
            if sep and key.strip() in ("Repository", "Name", "Version", "Description"):
                f[key.strip()] = val.strip()
        if "Name" in f:
            info[f["Name"]] = f
    return info


class SearchWorker(QObject):
    """Sucht im Hintergrund. scope: 'all' | 'repo' | 'aur' | 'installed'."""
    finished = Signal(list, str)

    def __init__(self, term, scope, keywords):
        super().__init__()
        self.term, self.scope, self.keywords = term, scope, keywords

    def run(self):
        rows, error = [], ""
        kw = self.keywords
        # Ohne Suchbegriff mit Kategorie: nach den Stichwörtern der Kategorie suchen
        term = self.term or ("|".join(kw) if kw else "")
        try:
            if self.scope in ("installed", "explicit", "foreign"):
                rows = search_installed(term, self.scope)
            else:
                if self.scope in ("all", "repo"):
                    rows += search_repo(term)
                if self.scope in ("all", "aur"):
                    try:
                        if self.term and len(self.term) >= 2:
                            rows += search_aur(self.term)
                        elif kw:
                            for k in kw[:5]:
                                rows += search_aur(k)
                    except Exception as e:  # AUR offline soll Repo-Treffer nicht verhindern
                        error = "AUR: %s" % e
        except Exception as e:
            error = str(e)
        if kw:
            rows = [r for r in rows if any(k in (r[1] + " " + r[3]).lower() for k in kw)]
        seen, unique = set(), []
        for r in rows:
            if (r[0], r[1]) not in seen:
                seen.add((r[0], r[1]))
                unique.append(r)
        self.finished.emit(unique, error)


# Pakete, die man nicht über die Oberfläche entfernen darf (System würde nicht mehr starten oder sich nicht mehr pflegen lassen)
PROTECTED = {"base", "base-devel", "linux", "linux-lts", "linux-zen", "linux-hardened", "linux-firmware", "systemd", "pacman",
             "glibc", "bash", "coreutils", "filesystem", "sudo", "shadow", "util-linux", "grub", "systemd-boot", "limine",
             "efibootmgr", "mkinitcpio", "dracut", "btrfs-progs", "e2fsprogs", "dbus", "networkmanager", "iwd", "paru", "yay",
             "python", "python-pyqt6", "polkit", "cachyos-keyring", "archlinux-keyring"}
PROTECTED_PREFIXES = ("linux-cachyos", "systemd-", "cachyos-settings", "cachyos-kernel")


def is_protected(name):
    return name in PROTECTED or name.startswith(PROTECTED_PREFIXES)


def removal_preview(names):
    """Trockenlauf von 'pacman -Rs': Was würde alles entfernt? Rückgabe: (ok, Ziele, Hinweis).
    Bei ok=False steht in Ziele die Liste der Pakete, die das Gewünschte noch brauchen."""
    r = subprocess.run(["pacman", "-Rsp", "--print-format", "%n"] + list(names), capture_output=True, text=True)
    if r.returncode == 0:
        return True, [l.strip() for l in r.stdout.splitlines() if l.strip()], ""
    needed_by = []
    for line in (r.stdout + "\n" + r.stderr).splitlines():
        if "benötigt von" in line or "required by" in line:
            needed_by.append(line.rsplit(" ", 1)[-1].strip(" »«"))
    first = r.stderr.splitlines()[0] if r.stderr.strip() else "Unbekannter Fehler"
    return False, sorted(set(needed_by)), first
