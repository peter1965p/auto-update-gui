"""Katalog der Desktop-Umgebungen und die Bewertung (Berater)."""

DISPLAY_MANAGERS = {"SDDM": "sddm", "GDM": "gdm", "LightDM": "lightdm", "greetd": "greetd", "COSMIC Greeter": "cosmic-greeter"}

# Attribute 1-5: light = ressourcenschonend, easy = einsteigerfreundlich, custom = anpassbar,
# modern = zeitgemäß/Wayland-reif, gaming = VRR/HDR/Spiele-Reife.
# style: "classic" (Startmenü + Taskleiste), "modern" (aufgeräumt/Dock), "tiling"
DESKTOPS = [
    dict(id="kde", name="KDE Plasma", detect="plasma-desktop", pkgs=["plasma-meta", "konsole", "dolphin"], dm="sddm",
         light=3, easy=4, custom=5, modern=4, gaming=5, styles=("classic", "modern"), x11=True, wayland=True,
         desc="Vollständiger, sehr anpassbarer Desktop. Vertraut für Windows-Umsteiger, bester Spiele-Support."),
    dict(id="gnome", name="GNOME", detect="gnome-shell", pkgs=["gnome"], dm="gdm",
         light=2, easy=4, custom=2, modern=5, gaming=4, styles=("modern",), x11=True, wayland=True,
         desc="Aufgeräumt und konsequent durchdacht, Touch/Gesten stark. Wenige Einstellungen, dafür Erweiterungen."),
    dict(id="xfce", name="Xfce", detect="xfce4-session", pkgs=["xfce4", "xfce4-goodies"], dm="lightdm",
         light=5, easy=4, custom=3, modern=2, gaming=3, styles=("classic",), x11=True, wayland=False,
         desc="Schlank, stabil, klassisch. Ideal für ältere Rechner."),
    dict(id="cinnamon", name="Cinnamon", detect="cinnamon", pkgs=["cinnamon", "gnome-terminal", "nemo"], dm="lightdm",
         light=3, easy=5, custom=3, modern=3, gaming=3, styles=("classic",), x11=True, wayland=False,
         desc="Klassisches Layout mit modernem Unterbau, sehr einsteigerfreundlich."),
    dict(id="mate", name="MATE", detect="mate-session-manager", pkgs=["mate", "mate-extra"], dm="lightdm",
         light=4, easy=4, custom=3, modern=1, gaming=3, styles=("classic",), x11=True, wayland=False,
         desc="Traditioneller Desktop im GNOME-2-Stil. Genügsam und bewährt."),
    dict(id="lxqt", name="LXQt", detect="lxqt-session", pkgs=["lxqt", "breeze-icons"], dm="sddm",
         light=5, easy=3, custom=3, modern=2, gaming=3, styles=("classic",), x11=True, wayland=False,
         desc="Extrem leicht auf Qt-Basis. Für sehr schwache Hardware."),
    dict(id="budgie", name="Budgie", detect="budgie-desktop", pkgs=["budgie", "gnome-terminal", "nautilus"], dm="lightdm",
         light=3, easy=4, custom=3, modern=4, gaming=3, styles=("modern",), x11=True, wayland=False,
         desc="Elegant und schlicht, Panel + Raven-Seitenleiste."),
    dict(id="cosmic", name="COSMIC", detect="cosmic-session", pkgs=["cosmic"], dm="cosmic-greeter",
         light=3, easy=3, custom=4, modern=5, gaming=3, styles=("modern", "tiling"), x11=False, wayland=True,
         desc="Neuer Rust-Desktop von System76 mit optionalem Tiling."),
    dict(id="hyprland", name="Hyprland", detect="hyprland", pkgs=["hyprland", "kitty", "waybar", "wofi"], dm=None,
         light=4, easy=1, custom=5, modern=5, gaming=4, styles=("tiling",), x11=False, wayland=True,
         desc="Animierter Tiling-Compositor. Alles per Textdatei – maximale Freiheit, hoher Lernaufwand."),
    dict(id="sway", name="Sway", detect="sway", pkgs=["sway", "foot", "waybar", "wmenu"], dm=None,
         light=5, easy=1, custom=4, modern=2, gaming=3, styles=("tiling",), x11=False, wayland=True,
         desc="i3-kompatibler Tiling-Compositor für Wayland. Schnell und minimal."),
    dict(id="i3", name="i3", detect="i3-wm", pkgs=["i3-wm", "i3status", "dmenu", "xterm"], dm="lightdm",
         light=5, easy=1, custom=4, modern=1, gaming=3, styles=("tiling",), x11=True, wayland=False,
         desc="Der Klassiker unter den Tiling-Window-Managern (nur X11)."),
]

EXPERIENCE = ["Einsteiger", "Fortgeschritten", "Profi"]
USAGE = ["Alltag & Office", "Entwicklung", "Gaming", "Multimedia"]
STYLE = [("Egal", None), ("Klassisch (Startmenü, Taskleiste)", "classic"),
         ("Modern & aufgeräumt", "modern"), ("Tastatur & Tiling", "tiling")]


def recommend(info, experience, usage, style):
    """Bewertet alle Desktops. Rückgabe: Liste (desktop, score 0-100, gründe), beste zuerst."""
    ram, threads = info["ram_gb"], info["threads"]
    vendors = {v for v, _ in info["gpus"]}

    # Gewichte der Attribute
    w_light = 3.0 if (ram and ram < 4) or threads <= 2 else 2.0 if ram < 8 else 0.7 if ram < 16 else 0.0
    if info["vm"]:
        w_light += 1.0
    w_easy = {"Einsteiger": 3.0, "Fortgeschritten": 1.5, "Profi": 0.0}[experience]
    w_custom = {"Einsteiger": 0.5, "Fortgeschritten": 1.5, "Profi": 3.0}[experience]
    w_modern = 1.0
    w_gaming = 3.0 if usage == "Gaming" else 0.5
    if usage == "Entwicklung":
        w_custom += 1.0

    weights = dict(light=w_light, easy=w_easy, custom=w_custom, modern=w_modern, gaming=w_gaming)
    total_w = sum(weights.values())
    results = []
    for d in DESKTOPS:
        reasons, warnings = [], []
        base = sum(weights[k] * d[k] for k in weights) / (5 * total_w) * 85
        if style is None:
            bonus = 7.5
        elif style in d["styles"]:
            bonus, _ = 15.0, reasons.append("passt zu deinem Stil")
        else:
            bonus = 0.0

        if w_light >= 2 and d["light"] >= 4:
            reasons.append("sparsam – passt zu %.0f GB RAM / %d Threads" % (ram, threads))
        elif w_light >= 2 and d["light"] <= 2:
            warnings.append("recht ressourcenhungrig für %.0f GB RAM" % ram)
        if experience == "Einsteiger" and d["easy"] >= 4:
            reasons.append("einsteigerfreundlich")
        if experience == "Einsteiger" and d["easy"] <= 1:
            base -= 15
            warnings.append("hoher Lernaufwand")
        if experience == "Profi" and d["custom"] >= 4:
            reasons.append("sehr anpassbar")
        if usage == "Gaming" and d["gaming"] >= 4:
            reasons.append("gute Gaming-Unterstützung (VRR/HDR)")
        if usage == "Entwicklung" and "tiling" in d["styles"]:
            reasons.append("Tiling beschleunigt Entwickler-Workflows")
        if info["laptop"] and d["id"] in ("gnome", "kde"):
            base += 4
            reasons.append("gute Touchpad-Gesten/Energieverwaltung (Laptop)")
        if "nvidia" in vendors:
            if d["id"] in ("hyprland", "sway"):
                base -= 8
                warnings.append("NVIDIA: braucht bei Wayland-Compositoren Feinarbeit")
            elif d["wayland"] and info["session"] == "wayland":
                reasons.append("läuft mit aktuellen NVIDIA-Treibern unter Wayland")
        if not d["wayland"] and info["session"] == "wayland":
            warnings.append("nur X11 – kein natives Wayland")

        score = max(0, min(100, round(base + bonus)))
        results.append((d, score, reasons, warnings))
    results.sort(key=lambda r: -r[1])
    return results


def install_command(desktop, installed_dms):
    pkgs = list(desktop["pkgs"])
    if desktop["dm"] and not installed_dms and desktop["dm"] not in pkgs and desktop["id"] != "gnome":
        pkgs.append(desktop["dm"])
    return "sudo pacman -S --needed " + " ".join(pkgs)
