"""Hinweise nach der Installation: viele Pakete sind erst mit einem Dienst oder einer Einrichtung nutzbar."""
import shlex

from .common import sh

# Paket -> Titel, Erklärung, Befehl zum Einrichten, Prüfbefehl (Exit-Code 0 = schon eingerichtet, Hinweis entfällt)
HINTS = {
    "ausweisapp": ("AusweisApp: Kartenleser", "Damit dein Kartenleser (USB-Leser oder NFC) erkannt wird, braucht die AusweisApp den "
                   "Smartcard-Dienst pcscd. Außerdem muss die Online-Ausweisfunktion deines Ausweises aktiviert sein.",
                   "sudo pacman -S --needed pcsclite ccid && sudo systemctl enable --now pcscd.socket",
                   "systemctl is-enabled pcscd.socket"),
    "postgresql": ("PostgreSQL einrichten", "Die Datenbank muss einmal initialisiert und dann gestartet werden. Sie lauscht danach nur "
                   "auf localhost.",
                   "sudo -iu postgres initdb -D /var/lib/postgres/data && sudo systemctl enable --now postgresql",
                   "test -f /var/lib/postgres/data/PG_VERSION"),
    "mariadb": ("MariaDB einrichten", "Die Datenbank muss einmal initialisiert und dann gestartet werden.",
                "sudo mariadb-install-db --user=mysql --basedir=/usr --datadir=/var/lib/mysql && sudo systemctl enable --now mariadb",
                "test -d /var/lib/mysql/mysql"),
    "valkey": ("Valkey (Redis) starten", "Der Server läuft erst, wenn der Dienst aktiviert ist. Er lauscht standardmäßig nur auf localhost.",
               "sudo systemctl enable --now valkey", "systemctl is-enabled valkey"),
    "docker": ("Docker starten", "Der Dienst muss aktiviert werden. Achtung: Wer in der Gruppe „docker“ ist, hat praktisch Root-Rechte. "
               "Für dich selbst wird die Gruppe nicht gesetzt; mit sudo docker funktioniert es sofort.",
               "sudo systemctl enable --now docker.service", "systemctl is-enabled docker.service"),
    "bluez": ("Bluetooth aktivieren", "Der Bluetooth-Dienst muss laufen, damit Geräte gefunden werden.",
              "sudo systemctl enable --now bluetooth.service", "systemctl is-enabled bluetooth.service"),
    "cups": ("Druckdienst starten", "Der Druckdienst muss laufen, damit Drucker eingerichtet werden können.",
             "sudo systemctl enable --now cups.socket", "systemctl is-enabled cups.socket"),
    "libvirt": ("Virtualisierung starten", "Der libvirt-Dienst muss laufen, damit virt-manager Maschinen verwalten kann.",
                "sudo systemctl enable --now libvirtd.socket", "systemctl is-enabled libvirtd.socket"),
    "openssh": ("SSH-Server starten", "Das öffnet Port 22 für andere Rechner im Netz. Aktiviere es nur, wenn du dich von außen anmelden willst.",
                "sudo systemctl enable --now sshd.service", "systemctl is-enabled sshd.service"),
    "ufw": ("Firewall einschalten", "ufw blockiert eingehende Verbindungen erst, wenn der Dienst läuft und die Regeln aktiv sind.",
            "sudo systemctl enable --now ufw.service && sudo ufw enable", "systemctl is-enabled ufw.service"),
    "php-redis": ("PHP-Redis aktivieren", "Die Erweiterung ist installiert, aber in der PHP-Konfiguration meist noch auskommentiert.",
                  "sudo sed -i 's/^;extension=redis/extension=redis/' /etc/php/conf.d/redis.ini",
                  "! test -f /etc/php/conf.d/redis.ini || grep -q '^extension=redis' /etc/php/conf.d/redis.ini"),
}
HINTS["redis"] = HINTS["valkey"]  # redis wird auf Arch durch valkey bereitgestellt


def find_hints(cmd, run=None):
    """Hinweise zu den in einem Installationsbefehl genannten Paketen, ohne die schon erledigten."""
    run = run or (lambda c: sh("bash", "-c", c).returncode == 0)
    try:
        words = shlex.split(cmd.replace(";", " ; ").replace("&&", " && "))
    except ValueError:
        words = cmd.split()
    found = []
    for w in words:
        if w in HINTS and w not in [f["pkg"] for f in found]:
            title, text, fix, check = HINTS[w]
            if not run(check):
                found.append({"pkg": w, "title": title, "text": text, "cmd": fix})
    return found
