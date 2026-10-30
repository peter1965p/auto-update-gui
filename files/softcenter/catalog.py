"""Kategorien und Profile."""

# Kategorie -> Stichwörter, die in Name oder Beschreibung vorkommen (Arch hat keine echten Kategorien)
GROUPS = {
    "Alle Kategorien": None,
    "Office": ["office", "libreoffice", "pdf", "spreadsheet", "word processor", "calendar", "ebook", "note-taking"],
    "Entwicklung": ["compiler", "debugger", "ide", "devel", "programming", "git", "cmake", "interpreter", "sdk"],
    "Grafik": ["graphic", "image", "photo", "draw", "paint", "3d", "svg", "vector", "raster"],
    "Multimedia": ["video", "audio", "music", "player", "media", "codec", "ffmpeg", "streaming"],
    "Internet": ["browser", "web", "mail", "email", "chat", "torrent", "ftp", "messenger"],
    "Spiele": ["game", "emulator", "steam", "arcade"],
    "System": ["system", "monitor", "backup", "partition", "disk", "driver", "kernel", "firmware"],
    "Server": ["server", "database", "daemon", "proxy", "docker", "nginx", "apache", "ssh"],
    "Netzwerk": ["network", "vpn", "wifi", "firewall", "dns", "wireguard"],
    "Sicherheit": ["security", "encryption", "password", "gpg", "antivirus"],
    "Werkzeuge": ["editor", "terminal", "archive", "utility", "file manager", "shell"],
}

# Kuratierte Sammlungen: Oberkategorie -> Unterkategorie -> Repo-Pakete.
# Jede Unterkategorie ist einzeln durchstöber- und mit einem Klick komplett installierbar.
CURATED = {
    "Entwicklung": {
        "Sprachen": ["python", "python-pip", "nodejs", "go", "rustup", "jdk-openjdk", "ruby", "lua",
                     "dotnet-sdk", "php", "perl", "kotlin", "typescript"],
        "Web": ["nodejs", "npm", "yarn", "typescript", "php", "composer", "sqlite", "firefox-developer-edition"],
        "Desktop": ["qt6-base", "qt6-declarative", "qt6-tools", "qt6-svg", "qtcreator", "pyside6",
                    "python-pyqt6", "gtk4", "gtk3", "wxwidgets-gtk3"],
        "Mobile": ["android-tools", "android-udev", "jdk-openjdk", "kotlin", "gradle", "scrcpy"],
        "System & Compiler": ["base-devel", "git", "cmake", "meson", "ninja", "gdb", "lldb", "clang", "valgrind",
                              "strace", "make"],
        "Datenbanken": ["postgresql", "mariadb", "sqlite", "redis", "dbeaver"],
        "Container": ["docker", "docker-compose", "podman", "kubectl", "k9s"],
        "Editoren & IDEs": ["code", "neovim", "vim", "emacs", "kate", "qtcreator"],
    },
    "Server": {
        "Webserver": ["nginx", "apache", "caddy", "certbot"],
        "Dienste": ["openssh", "postgresql", "mariadb", "docker", "docker-compose", "rsync"],
        "Absicherung": ["fail2ban", "ufw", "clamav", "gnupg"],
        "Admin-Tools": ["htop", "tmux", "btop", "ncdu", "iotop"],
    },
    "Office": {
        "Büro": ["libreoffice-fresh", "calibre", "thunderbird"],
        "Dokumente": ["okular", "evince", "pdfarranger", "xournalpp"],
        "Notizen": ["obsidian", "joplin", "zim"],
    },
    "Grafik": {
        "Bildbearbeitung": ["gimp", "krita", "darktable"],
        "Vektor & Layout": ["inkscape", "scribus"],
        "3D": ["blender", "freecad"],
    },
    "Multimedia": {
        "Video": ["vlc", "mpv", "obs-studio", "kdenlive", "handbrake"],
        "Audio": ["audacity", "ardour", "lmms", "pavucontrol"],
        "Codecs": ["ffmpeg", "gst-plugins-good", "gst-plugins-bad", "gst-libav"],
    },
    "Spiele": {
        "Launcher": ["steam", "lutris", "heroic-games-launcher-bin"],
        "Kompatibilität": ["wine", "winetricks", "proton-ge-custom-bin"],
        "Leistung": ["gamemode", "mangohud", "goverlay"],
    },
    "Netzwerk & Sicherheit": {
        "Netzwerk": ["wireguard-tools", "networkmanager", "nmap", "wireshark-qt", "traceroute"],
        "Passwörter & Verschlüsselung": ["keepassxc", "gnupg", "veracrypt"],
    },
}

# Flache Sicht "Oberkategorie › Unterkategorie" -> Pakete (für Anzeige und Installation)
PROFILES = {"%s › %s" % (top, sub): pkgs for top, subs in CURATED.items() for sub, pkgs in subs.items()}
