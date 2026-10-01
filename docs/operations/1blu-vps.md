# 1blu-VPS einrichten: Ubuntu, OpenVZ, Tailnet und OpenSSH

Belegter Einrichtungsfall vom 01.10.2026. Keine Bindung an einen Tarif,
Hostnamen, Schlüssel oder eine feste IP. Zugriffsdaten bleiben außerhalb
dieses öffentlichen Repositories. Befehle auf dem VPS als root ausführen,
sofern ausdrücklich nichts anderes dabeisteht. Bei Fehlern stoppen.

## 1. Ist-Zustand und Wiederherstellungsweg

Im eigenen 1blu-Konto Zielserver und Wiederherstellungskonsole prüfen.
OS-Auswahl Ubuntu bedeutet nicht automatisch KVM. Im belegten Fall ergab
`systemd-detect-virt` OpenVZ mit einem geteilten Hostkernel.

```bash
cat /etc/os-release
systemd-detect-virt
uname -srm
nproc
free -h
df -h /
df -i /
dpkg --audit
readlink -f /etc/localtime
cat /etc/timezone
ls -l /dev/net/tun
```

`/dev/net/tun` war vorhanden und Tailscale funktionierte tatsächlich. Docker
wurde später mit einem echten Container geprüft. Diese Ergebnisse gelten nur
für den gemessenen Server; aus dem Gerät oder dem Kernelnamen allein keine
Funktionszusage ableiten. Systemd und cgroup-Mounts ebenfalls prüfen.

## 2. curl und Locale

`curl: command not found` bedeutet: Installer wurde nicht heruntergeladen.
`setlocale: LC_ALL ... de_DE.UTF-8` bedeutet: gewünschte Locale fehlt; kein
Nachweis einer VPS-Einschränkung. Für die aktuelle Sitzung:

```bash
export LC_ALL=C.UTF-8
apt-get update
apt-get install -y curl ca-certificates
```

Erst nach sauberer Paketverwaltung gewünschte Locales erzeugen:

```bash
apt-get install -y locales
locale-gen de_DE.UTF-8 en_US.UTF-8
locale -a
```

Shell-Locale, Serverzeitzone und die Locale einer Anwendung sind getrennt.

## 3. tzdata Exit 10 und Folgefehler

Ein Fehler an tzdata kann Python, Vim und andere Pakete unkonfiguriert lassen.
Diese Abhängigkeiten nicht einzeln neu installieren. `tzdat` wäre nur ein
Tippfehler; der Paketname lautet `tzdata`.

```bash
DEBCONF_DEBUG=developer DEBIAN_FRONTEND=noninteractive dpkg --configure tzdata
```

Im belegten Defekt: `/etc/timezone` = `Etc/UTC`, Linkziel von `/etc/localtime`
= `/usr/share/zoneinfo/Host`; `FSET tzdata/Zones/Host seen true` scheiterte mit
`10 ... doesn't exist`. Die Konfiguration wertet den Link aus. Nur den Text
in `/etc/timezone` zu ändern behebt diesen konkreten Defekt nicht.

Vorlagen und Link prüfen. Den folgenden Fix **nur bei diesem bestätigten
Linkfehler** anwenden. UTC war bereits die gewünschte Serverzeitzone. Eine
andere gewünschte Zone muss installiert und bewusst gewählt werden.

```bash
test -f /usr/share/zoneinfo/Etc/UTC
cp -a --update=none /etc/localtime /etc/localtime.before-tzdata-fix
ls -l /etc/localtime.before-tzdata-fix
ln -sfn /usr/share/zoneinfo/Etc/UTC /etc/localtime
DEBIAN_FRONTEND=noninteractive dpkg --configure -a
dpkg --audit
```

`--update=none` ist hier für Ubuntu-24.04-Coreutils belegt; auf anderen Systemen
vorher prüfen. `cp -n` funktionierte, meldete aber eine Portabilitätswarnung.
Bei Mount-/Rechtefehlern nicht Hostdateien oder Containerrechte umgehen, sondern
Provider-Konfiguration klären. Sicherung behalten. Ein leeres `dpkg --audit`
belegt keine vollständige Serversicherheit.

## 4. Tailnet-Zugang vorbereiten

Entwicklungsserver zuerst mit `tailscale status` und `tailscale ip -4` prüfen.
Auf dem neuen VPS:

```bash
curl -fsSL https://tailscale.com/install.sh | sh
tailscale up --hostname=print-server
tailscale ip -4
ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub
```

Den Loginlink selbst öffnen und das gewünschte bestehende Tailnet wählen.
Tailnet-IP und Host-Fingerabdruck aus der eigenen Konsole übermitteln; keine
Passwörter, Auth-Keys oder privaten Schlüssel im Chat. `ssh-keyscan` allein
belegt keine vertrauenswürdige Serveridentität. Erst gegen den übermittelten
Fingerprint vergleichen und dann gezielt in `known_hosts` aufnehmen.

Standardweg: normaler OpenSSH-Dienst über die Tailnet-IP und ein eigener
Ed25519-Schlüssel. Dafür ist `tailscale set --ssh` nicht nötig. Diese Option
aktiviert einen anderen SSH-Server samt Tailscale-SSH-Policy und gehört nur in
einen bewusst gewählten alternativen Zugangsweg.

Auf dem Entwicklungsserver einen eigenen Schlüssel erzeugen; vorhandene
Dateien nicht überschreiben. Private Schlüssel auf Modus 600 prüfen, auch
wenn ein früherer `ssh-keygen`-Lauf korrekte Rechte setzte. Modus 640 wurde
hier von OpenSSH abgelehnt. Öffentliches `.pub` und privater Schlüssel sind
unterschiedliche Dateien; nur `.pub` darf auf den Zielserver.

Auf dem VPS mit den **tatsächlichen** Werten:

```bash
read -r -p 'Tailnet-IPv4 des Entwicklungsservers: ' ADMIN_TAILNET_IP
read -r -p 'Öffentlicher Ed25519-Schlüssel: ' ADMIN_PUBLIC_KEY
install -d -m 700 /root/.ssh
printf '\n%s\n' "from=\"$ADMIN_TAILNET_IP\" $ADMIN_PUBLIC_KEY" >> /root/.ssh/authorized_keys
chmod 600 /root/.ssh/authorized_keys
```

Neue SSH-Verbindung mit `IdentitiesOnly=yes`, `BatchMode=yes` und
`StrictHostKeyChecking=yes` vom freigegebenen Entwicklungsserver aus testen.
`Permission denied` kann ein fehlender Schlüssel, falsche Quell-IP oder eine
lokale Schlüsselberechtigung sein. Zuerst den konkreten Fehler prüfen.

## 5. Serverbasis härten und messen

- Bestandskonfiguration sichern. Bei Remote-Firewall-/SSH-Änderungen einen
  unabhängigen systemd-Rücknahme-Timer vor dem Eingriff setzen. Vorher eine
  zweite Verbindung prüfen; anschließend mit einer **neuen** Verbindung testen.
- Provider- und Host-Firewall getrennt prüfen; IPv4 und IPv6 berücksichtigen.
  Administration über Tailnet. Öffentlicher SFTP-Port erst nach bestätigter
  Gegenstellen-IP-Liste und Auth-Vereinbarung. Keine pauschale SFTP-Freigabe.
- Nach funktionierendem Schlüsselzugang PasswordAuthentication und
  KbdInteractiveAuthentication deaktivieren; Root nur mit Schlüssel erlauben.
  `sshd -t` vor Reload, wirksame Werte mit `sshd -T` prüfen. Ubuntu nutzt ggf.
  `ssh.socket`; Dienststatus allein belegt keine tatsächlichen Listen-Adressen.
- Apache im gemessenen Fall war nur die Defaultseite. Erst Inhalt/Dienste
  prüfen, dann unbenötigte Dienste reversibel stoppen und deaktivieren.
- Docker aus dem signierten offiziellen Ubuntu-Repository installieren.
  Dienst und CLI reichen nicht: echten `hello-world`-Container, ausgehendes
  Netz, Volumes, Memory-/CPU-Limits und Restart-Verhalten testen.
- OpenVZ-Funktionen nicht still mit privilegierten Containern oder deaktivierter
  Sicherheitsisolation umgehen. Der belegte Host lief mit Docker 29, cgroup v1
  und dem normalen Storage-Treiber; keine Zusage für andere Tarife/Container.
- Keine Docker-Ports öffentlich veröffentlichen. Docker-Portfreigaben können
  ufw umgehen; gezielt über die öffentliche IP messen. Kein Docker-TCP-Socket.
- Automatische Sicherheitsupdates und Loggrenzen einrichten; Dienste müssen
  aktiviert sein. Voller Datenträger, Quoten, Retention, Alarme und echte
  Backup-/Restore-Prüfung sind gesonderte Betriebsgates.
- Öffentliche SSH-/HTTP-Ports extern prüfen. Rücknahme-Timer erst nach den
  erfolgreichen Zugangsgates stoppen. Ein Neustart bleibt ein eigenes Gate.
- Anwendung, Queue, SFTP-Abholung und bezahlte Aufträge nicht als eingerichtet
  melden, wenn nur die Serverbasis geprüft wurde. Keine fremden Projekt-Secrets
  übernehmen; notwendige Minimalrechte gezielt provisionieren.

## 6. Offline-Check in Ruttla

Collector explizit auf dem Zielhost ausführen. Er liest nur OS-, Link-,
Vorlagen-, Geräte- und Paketmetadaten; kein Hostname, keine IP, keine Keys.
Die Erhebung gehört zum freigegebenen Live-Zugriff und wird vom normalen
Ruttla-Scan niemals automatisch gestartet.

```bash
python3 scripts/collect_host_snapshot.py > host-preflight.json
ruttla . --check linux.tzdata_host_timezone --strict --format agent
```

Für einen Remotehost den Collector über die bereits verifizierte SSH-Verbindung
auf dem Zielsystem ausführen und JSON lokal außerhalb öffentlicher Quellen
speichern. Veraltete Snapshots sind keine aktuelle Servermessung.

Der Check misst ausschließlich die belegte `Host`-/Template-Kombination.
Ein eigenes registriertes Host-Template bleibt gesund. Fehlende, unvollständige
oder ungültige Snapshots bleiben `UNMEASURED`. Tailscale, Docker, Firewall,
Providerrechte und Restore werden dadurch nicht offline bewiesen.

## Primärquellen

- [Tailscale Linux-Installation](https://tailscale.com/docs/install/linux)
- [OpenSSH über Tailscale](https://tailscale.com/docs/reference/ssh-over-tailscale)
- [Tailscale und Ubuntu-Firewall](https://tailscale.com/docs/how-to/secure-ubuntu-server-with-ufw)
- [Docker Engine auf Ubuntu](https://docs.docker.com/engine/install/ubuntu/)
- [OpenVZ-Grundlagen](https://wiki.openvz.org/User_Guide/OpenVZ_Philosophy)
- [debconf-Protokoll und Fehlercodes](https://manpages.debian.org/testing/debconf-doc/debconf-devel.7.en.html)
