# 🔄 auto-update-gui

Moderne Qt6-Oberfläche für automatische Systemupdates unter Arch Linux / CachyOS.
Man sieht jederzeit, **was** das Tool gerade tut – und es ersetzt das Cachy-Update-Tray-Applet.

<p align="center">
  <img src="docs/screenshot-running.png" width="360" alt="Update läuft (dunkles Theme)">
  &nbsp;
  <img src="docs/screenshot-light.png" width="360" alt="Letzter Lauf (helles Theme)">
</p>

## Features

- **Zeitplan** per systemd-Timer: täglich, wöchentlich oder 5 Min. nach dem Start – läuft auch nachts ohne Login,
  weckt den Rechner aus dem Standby (`WakeSystem`), verhindert Standby während des Updates und holt
  verpasste Läufe nach dem nächsten Start nach (`Persistent`)
- **Btrfs-Snapshot** mit Snapper vor jedem Update (optional)
- **AUR-Updates** über paru (optional, mit Sicherheitshinweis)
- **Ablaufanzeige** Snapshot → pacman → AUR mit Live-Status, Fortschrittsbalken und Live-Log
- **Systray** mit Update-Zähler als Badge und Benachrichtigung; Check alle 3 Stunden
- Animierte Switches, Karten-Layout, passt sich dem hellen/dunklen Theme an
- **Selbst-Update:** prüft GitHub-Releases; bei neuer Version erscheint ein Hinweis mit Knopf „Jetzt aktualisieren“
  (Passwortabfrage via `pkexec`, danach Neustart der GUI)
- Startet beim Login automatisch im Tray (`--tray`)

## Installation

```bash
sudo ./install.sh
```

Benötigt: `python-pyqt6`, `git`, `curl`, `pacman-contrib` (checkupdates), optional `snapper` und `paru`.

`install.sh` deaktiviert zusätzlich Tray-Applet und Timer von Cachy-Update (`arch-update`) für den
aufrufenden Benutzer. Rückgängig:

```bash
rm ~/.config/autostart/arch-update-tray.desktop
systemctl --user enable --now arch-update.timer
```

## Aufbau

| Datei | Zweck |
|---|---|
| `files/auto-update-gui` | Qt6-Oberfläche + Systray |
| `files/auto-update-run` | vom systemd-Service ausgeführt: Snapshot, `pacman -Syu`, AUR |
| `files/auto-update-apply` | schreibt Konfiguration und Timer (via `pkexec`) |
| `files/auto-update-self` | holt einen Release-Tag von GitHub und installiert ihn (via `pkexec`) |
| `files/auto-update.{service,timer}` | systemd-Units |

Optionen der GUI: `--tray` (ohne Fenster starten), `--theme=dark|light`.

## Releases

Die Versionsnummer steht in `files/auto-update-gui` (`VERSION`). Neue Version veröffentlichen:

```bash
# VERSION im Skript erhöhen, committen, dann:
git tag v1.1.0 && git push --tags
gh release create v1.1.0 --notes "Was ist neu"
```

Die GUI vergleicht den neuesten Release-Tag mit `VERSION`. Die Prüfung funktioniert nur, wenn das Repo öffentlich ist.
