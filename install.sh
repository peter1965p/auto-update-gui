#!/bin/bash
# Als root ausführen: sudo ./install.sh
set -e
[ "$(id -u)" = 0 ] || { echo "Bitte als root ausführen: sudo $0" >&2; exit 1; }
cd "$(dirname "$0")/files"

# Abhängigkeiten prüfen (nur Hinweis, installiert wird nichts automatisch)
python3 -c "import PyQt6" 2>/dev/null || echo "Hinweis: python-pyqt6 fehlt  ->  sudo pacman -S python-pyqt6" >&2
for c in git curl checkupdates arch-audit; do
    command -v "$c" >/dev/null || echo "Hinweis: '$c' fehlt (git/curl: Selbst-Update, checkupdates: pacman-contrib, arch-audit: Sicherheitsprüfung)" >&2
done
install -Dm755 auto-update-run auto-update-apply auto-update-self auto-update-gui -t /usr/local/bin/
# Python-Paket des SoftCenters (Software, System, Updates); das Programm in /usr/local/bin startet es
rm -rf /usr/local/lib/auto-update-gui
install -d /usr/local/lib/auto-update-gui
cp -r softcenter /usr/local/lib/auto-update-gui/
find /usr/local/lib/auto-update-gui -name __pycache__ -prune -exec rm -rf {} +
python3 -m compileall -q /usr/local/lib/auto-update-gui || true
install -Dm644 auto-update.service auto-update.timer -t /etc/systemd/system/
install -Dm644 auto-update-gui.desktop -t /usr/share/applications/
# Autostart im Systray bei jeder Anmeldung (Fenster bleibt dabei zu)
install -Dm644 auto-update-gui-autostart.desktop /etc/xdg/autostart/auto-update-gui.desktop
systemctl daemon-reload

# Cachy-Update (arch-update) ersetzen: Tray-Applet und Prüf-Timer des Benutzers abschalten
U=${SUDO_USER:-}
if [ -n "$U" ] && [ "$U" != root ] && [ -f /etc/xdg/autostart/arch-update-tray.desktop ]; then
    H=$(getent passwd "$U" | cut -d: -f6)
    install -d -o "$U" -m 755 "$H/.config/autostart"
    printf '[Desktop Entry]\nType=Application\nName=Cachy-Update Systray Applet\nHidden=true\n' > "$H/.config/autostart/arch-update-tray.desktop"
    chown "$U": "$H/.config/autostart/arch-update-tray.desktop"
    UID_=$(id -u "$U")
    runuser -u "$U" -- env XDG_RUNTIME_DIR=/run/user/$UID_ systemctl --user disable --now arch-update.timer 2>/dev/null || true
    pkill -u "$U" -f arch-update-tray 2>/dev/null || true
    echo "Cachy-Update-Tray und -Timer deaktiviert (rückgängig: rm ~/.config/autostart/arch-update-tray.desktop; systemctl --user enable --now arch-update.timer)"
fi
echo "Fertig. Starte 'SoftCenter' aus dem Anwendungsmenü (startet künftig automatisch im Systray und ersetzt Cachy-Update)."
