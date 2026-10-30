"""Erkennt Hardware, Session und installierte Desktops des laufenden Systems."""
import glob
import os
import platform
import re
import shlex
import shutil
import subprocess

from .backend import installed_names
from .desktops import DESKTOPS, DISPLAY_MANAGERS


def _read(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return ""


def _run(*cmd):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        return r.returncode, r.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return 1, ""


def _os_release():
    data = {}
    for line in _read("/etc/os-release").splitlines():
        k, sep, v = line.partition("=")
        if sep:
            data[k] = v.strip().strip('"')
    return data.get("PRETTY_NAME") or data.get("NAME") or platform.system()


def _cpu():
    m = re.search(r"model name\s*:\s*(.+)", _read("/proc/cpuinfo"))
    return (m.group(1).strip() if m else platform.processor() or "unbekannt"), os.cpu_count() or 1


def _ram_gb():
    m = re.search(r"MemTotal:\s*(\d+)", _read("/proc/meminfo"))
    return int(m.group(1)) / 1024 / 1024 if m else 0.0


def _gpus():
    """Liste (Vendor-Kurzname, Beschreibung)."""
    _, out = _run("lspci", "-mm")
    gpus = []
    for line in out.splitlines():
        try:
            f = shlex.split(line)
        except ValueError:
            continue
        if len(f) >= 4 and any(k in f[1] for k in ("VGA", "3D controller", "Display controller")):
            text = "%s %s" % (f[2], f[3])
            low = text.lower()
            vendor = ("nvidia" if "nvidia" in low else "amd" if ("amd" in low or "ati" in low)
                      else "intel" if "intel" in low else "other")
            gpus.append((vendor, text))
    return gpus


def _sessions():
    names = []
    for d, kind in (("/usr/share/wayland-sessions", "Wayland"), ("/usr/share/xsessions", "X11")):
        for p in sorted(glob.glob(d + "/*.desktop")):
            m = re.search(r"^Name=(.+)$", _read(p), re.M)
            names.append("%s (%s)" % (m.group(1) if m else os.path.basename(p), kind))
    return names


def gather():
    """Sammelt alle Infos. Dauert unter einer Sekunde, daher synchron nutzbar."""
    installed = installed_names()
    cpu, threads = _cpu()
    disk = shutil.disk_usage("/")
    virt_rc, virt = _run("systemd-detect-virt")
    explicit = len(_run("pacman", "-Qqe")[1].split())
    flatpaks = len(_run("flatpak", "list", "--app")[1].splitlines()) if shutil.which("flatpak") else 0
    current = os.environ.get("XDG_CURRENT_DESKTOP", "")
    return {
        "distro": _os_release(),
        "kernel": platform.release(),
        "cpu": cpu,
        "threads": threads,
        "ram_gb": _ram_gb(),
        "gpus": _gpus(),
        "disk_total_gb": disk.total / 1e9,
        "disk_free_gb": disk.free / 1e9,
        "session": os.environ.get("XDG_SESSION_TYPE", "unbekannt"),
        "current_desktop": current,
        "laptop": bool(glob.glob("/sys/class/power_supply/BAT*")),
        "vm": virt if virt_rc == 0 and virt != "none" else "",
        "packages": len(installed),
        "explicit": explicit,
        "flatpaks": flatpaks,
        "installed_desktops": [d["id"] for d in DESKTOPS if d["detect"] in installed],
        "installed_dms": [n for n, pkg in DISPLAY_MANAGERS.items() if pkg in installed],
        "sessions": _sessions(),
        "installed": installed,
    }
