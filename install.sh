#!/bin/bash
# Als root ausführen: sudo ./install.sh
set -e
cd "$(dirname "$0")/files"
install -Dm755 auto-update-run auto-update-apply auto-update-askpass auto-update-gui -t /usr/local/bin/
install -Dm644 auto-update.service auto-update.timer -t /etc/systemd/system/
install -Dm644 auto-update-gui.desktop -t /usr/share/applications/
# Autostart im Systray bei jeder Anmeldung (Fenster bleibt dabei zu)
install -Dm644 auto-update-gui-autostart.desktop /etc/xdg/autostart/auto-update-gui.desktop
systemctl daemon-reload

# Cachy-Update (arch-update) ersetzen: Tray-Applet und Prüf-Timer des Benutzers abschalten
U=${SUDO_USER:-}
if [ -n "$U" ] && [ "$U" != root ]; then
    H=$(getent passwd "$U" | cut -d: -f6)
    install -d -o "$U" -m 755 "$H/.config/autostart"
    printf '[Desktop Entry]\nType=Application\nName=Cachy-Update Systray Applet\nHidden=true\n' > "$H/.config/autostart/arch-update-tray.desktop"
    chown "$U": "$H/.config/autostart/arch-update-tray.desktop"
    UID_=$(id -u "$U")
    runuser -u "$U" -- env XDG_RUNTIME_DIR=/run/user/$UID_ systemctl --user disable --now arch-update.timer 2>/dev/null || true
    pkill -u "$U" -f arch-update-tray 2>/dev/null || true
    echo "Cachy-Update-Tray und -Timer deaktiviert (rückgängig: rm ~/.config/autostart/arch-update-tray.desktop; systemctl --user enable --now arch-update.timer)"
fi
echo "Fertig. Starte 'Automatische Updates' aus dem Anwendungsmenü (startet künftig automatisch im Systray und ersetzt Cachy-Update)."
