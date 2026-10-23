#!/bin/bash
# Als root ausführen: sudo ./uninstall.sh   (Konfiguration in /etc/auto-update.conf bleibt erhalten)
set -e
[ "$(id -u)" = 0 ] || { echo "Bitte als root ausführen: sudo $0" >&2; exit 1; }
systemctl disable --now auto-update.timer 2>/dev/null || true
rm -f /usr/local/bin/auto-update-{run,apply,self,gui} /etc/systemd/system/auto-update.{service,timer} \
      /usr/share/applications/auto-update-gui.desktop /etc/xdg/autostart/auto-update-gui.desktop \
      /etc/sudoers.d/auto-update-aur
rm -rf /etc/systemd/system/auto-update.timer.d
systemctl daemon-reload
pkill -f /usr/local/bin/auto-update-gui 2>/dev/null || true
echo "Entfernt. Cachy-Update wieder aktivieren (als normaler Benutzer):"
echo "  rm ~/.config/autostart/arch-update-tray.desktop; systemctl --user enable --now arch-update.timer"
