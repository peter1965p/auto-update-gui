# auto-update-gui

Moderne Qt6-Oberfläche für automatische Systemupdates unter Arch/CachyOS.

- Zeitplan (täglich / wöchentlich / nach dem Start) per systemd-Timer
- Optional: Btrfs-Snapshot mit Snapper vor jedem Update
- Optional: AUR-Updates über paru
- Ablaufanzeige (Snapshot → pacman → AUR) mit Live-Status und Live-Log
- Systray-Icon mit Update-Zähler und Benachrichtigung (ersetzt Cachy-Update)

## Installation

    sudo ./install.sh

Benötigt: `python-pyqt6`, `pacman-contrib` (checkupdates), optional `snapper`, `paru`.
Das Skript deaktiviert außerdem das Cachy-Update-Tray-Applet des aufrufenden Benutzers.
