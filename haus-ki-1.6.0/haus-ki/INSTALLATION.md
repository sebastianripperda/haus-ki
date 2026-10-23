# Installationsleitfaden

Dieser Leitfaden führt Schritt für Schritt von einem Proxmox-Server mit Ollama bis zu einem laufenden Haus-KI,
das die ganze Familie nutzen kann. Rechne mit 30 bis 60 Minuten, je nach Internetleitung (die Modelle sind
zusammen 10 bis 30 GB groß).

**Inhalt**

1. [Vorbereitung](#1-vorbereitung)
2. [Paket herunterladen und prüfen](#2-paket-herunterladen-und-prüfen)
3. [Vorgaben hinterlegen (optional)](#3-vorgaben-hinterlegen-optional)
4. [Installationsskript ausführen](#4-installationsskript-ausführen)
5. [Zertifikat auf den Geräten installieren](#5-zertifikat-auf-den-geräten-installieren)
6. [Ersteinrichtung im Browser](#6-ersteinrichtung-im-browser)
7. [Microsoft 365 anbinden](#7-microsoft-365-anbinden)
8. [KNX anbinden](#8-knx-anbinden)
9. [Familie einrichten](#9-familie-einrichten)
10. [Als App auf dem Handy](#10-als-app-auf-dem-handy)
11. [Updates, Sicherung und Wiederherstellung](#11-updates-sicherung-und-wiederherstellung)
12. [Deinstallieren](#12-deinstallieren)
13. [Wenn etwas nicht klappt](#13-wenn-etwas-nicht-klappt)

---

## 1. Vorbereitung

### Checkliste

| | Was | Wie prüfen |
|---|---|---|
| ☐ | Proxmox VE 8 oder 9 | `pveversion` in der Shell des Knotens |
| ☐ | Ollama läuft in einem Container oder einer VM auf diesem Host | `curl http://<IP>:11434/api/version` liefert eine Versionsnummer |
| ☐ | Ollama ist im Netz erreichbar, nicht nur lokal | dieselbe Abfrage von einem anderen Gerät aus |
| ☐ | Freier Platz: 4 Kerne, 4 GB RAM, 12 GB Platte für Haus-KI | Proxmox › Knoten › Übersicht |
| ☐ | Internetzugang für den Host | `ping -c1 deb.debian.org` |
| ☐ | Root-Zugang zur Proxmox-Shell (Weboberfläche › Knoten › Shell oder SSH) | |

### Noch kein Ollama?

Am einfachsten ist das Community-Skript für einen Ollama-Container (https://community-scripts.org, Suche „Ollama“).
Es legt einen LXC-Container mit Ollama an, der im Netz erreichbar ist. Haus-KI braucht keine Grafikkarte.
Mit 16 GB RAM für den Ollama-Container laufen die Standardmodelle, mit 32 GB oder mehr auch größere.

Falls Ollama nur lokal lauscht, im Ollama-Gast:
```
mkdir -p /etc/systemd/system/ollama.service.d
printf '[Service]\nEnvironment="OLLAMA_HOST=0.0.0.0:11434"\n' > /etc/systemd/system/ollama.service.d/host.conf
systemctl daemon-reload && systemctl restart ollama
```

### Optional, aber hilfreich

Diese Angaben vorher heraussuchen, das Skript fragt danach:

- **Netzwerk:** eine freie IP-Adresse für Haus-KI im Heimnetz, oder DHCP. Mit fester Adresse zusätzlich Gateway und DNS-Server.
- **Paperless-ngx:**
  - Lege in Paperless einen eigenen Benutzer `haus-ki` an.
  - Gib ihm Leserechte auf die Dokumente und das Recht „Dokumente hinzufügen“.
  - Erzeuge dann in seinem Profil einen API-Token.
- **Jellyfin:** Dashboard › API-Schlüssel › „+“, Name „Haus-KI“.
- **Websuche:** ollama.com › Settings › Keys › neuen Schlüssel anlegen.

Tokens und Schlüssel bitte nirgends notieren, wo andere sie sehen. Das Skript fragt sie verdeckt ab.

---

## 2. Paket herunterladen und prüfen

In der Shell des Proxmox-Knotens (als root):

```
cd /root
wget https://github.com/<besitzer>/<repo>/releases/latest/download/haus-ki-<version>.tar.gz
wget https://github.com/<besitzer>/<repo>/releases/latest/download/haus-ki-<version>.tar.gz.sha256
sha256sum -c haus-ki-<version>.tar.gz.sha256
tar -xzf haus-ki-<version>.tar.gz && cd haus-ki
```

`sha256sum -c` muss „OK“ melden. Sonst ist das Paket beschädigt oder verändert, dann bitte nicht installieren.

Alternativ das Paket am PC herunterladen und mit `scp` oder WinSCP nach `/root` kopieren.

---

## 3. Vorgaben hinterlegen (optional)

Ohne Vorgaben fragt das Skript alles ab und macht sinnvolle Vorschläge. Wer mehrere Anläufe braucht oder die
Familie gleich mit anlegen möchte, hinterlegt sie vorher:

```
cp install/haus-ki-install.conf.example install/haus-ki-install.conf
nano install/haus-ki-install.conf
```

Jede Zeile ist kommentiert. Leere Werte bedeuten „Skript schlägt etwas vor“.

**Personen vorab anlegen:**
```
cp install/haus-ki-personen.example.json install/haus-ki-personen.json
nano install/haus-ki-personen.json
```

| Feld | Bedeutung |
|---|---|
| `name` | Anzeigename in Haus-KI |
| `role` | `admin` (Verwaltung, Einsicht in Chats) oder `member` |
| `email` | Microsoft-Konto für die Anmeldung. Wird bei der ersten Anmeldung verknüpft. |
| `jellyfin_user` | Jellyfin-Benutzername, damit „gesehen“ und Empfehlungen stimmen |
| `learn` | Lernmodus für Kinder: erklärt Schritt für Schritt statt fertiger Lösungen |
| `paperless` | `false`, wenn die Person keine Dokumente sehen soll |

Beide Dateien enthalten keine Geheimnisse und gehören trotzdem nicht in ein öffentliches Repository. Die `.gitignore` schließt sie aus.

---

## 4. Installationsskript ausführen

```
bash install/haus-ki-lxc.sh
```

In der ersten Zeile steht die Version, zum Beispiel „Haus-KI 1.6.0 – Installation auf pve“. Enter übernimmt
jeweils den Vorschlag in Klammern.

### Was das Skript fragt

| Abschnitt | Frage | Hinweis |
|---|---|---|
| Container | ID, Name, Speicher, Platte, RAM, Kerne | Vorschlag 4 Kerne, 4 GB, 12 GB |
| Netzwerk | Brücke, IP (oder `dhcp`), Gateway, DNS, Name im Heimnetz | IP ohne `/24` wird ergänzt |
| Ollama | ID des Ollama-Gasts, Adresse | wird meist automatisch gefunden |
| Modelle | fehlende Modelle laden | qwen3:8b, qwen3:4b, llama3.2:3b, bge-m3, bei ≥ 30 GB RAM auch qwen3:30b-a3b |
| Agent | Agent im Ollama-Gast installieren | empfohlen, sonst lassen sich Ollama-Einstellungen nicht aus Haus-KI ändern |
| Schutz | Port 11434 nur für Haus-KI öffnen, weitere erlaubte Adressen | weitere Adressen nur, wenn andere Programme Ollama direkt nutzen sollen |
| CPU | Ollama für die CPU einstellen | startet Ollama einmal neu |
| Paperless | Adresse und Token | Test zeigt Version und Anzahl sichtbarer Dokumente |
| Jellyfin | Adresse und API-Schlüssel | Test zeigt Version und Servername |
| Websuche | Schlüssel von ollama.com | Test mit einer echten Suche |
| Sicherung | nächtliche Proxmox-Sicherung des Containers, Speicher | besser NAS oder Proxmox Backup Server als `local` |

### Was im Hintergrund passiert

- Es legt einen unprivilegierten Debian-Container an. Die Vorlage wird passend zum Prozessor gewählt und vor dem Start geprüft.
- Es legt in Proxmox den Benutzer `hauski@pve` mit einem Token an. Das Token darf nur den Ollama-Gast sehen und starten, neu starten oder herunterfahren.
- Es installiert im Container Python, Caddy und Haus-KI und richtet die Systemdienste ein.
- Zum Schluss prüft es, ob Haus-KI Ollama erreicht und ob Ollama für andere Geräte gesperrt ist.

### Am Ende

```
Fertig. Haus-KI läuft.
  Adresse:          https://192.168.1.40
  Einrichtungscode: K7Q-4MX-P2R
```

**Den Einrichtungscode bitte notieren.** Er wird einmal für die Ersteinrichtung gebraucht.

---

## 5. Zertifikat auf den Geräten installieren

Haus-KI verschlüsselt mit einer eigenen Zertifizierungsstelle. Damit Browser der Verbindung vertrauen, und damit
Mikrofon, App-Installation und Push-Benachrichtigungen funktionieren, auf **jedem Gerät** einmal das Zertifikat
installieren: `http://<IP von Haus-KI>/ca.crt` öffnen.

| Gerät | Schritte |
|---|---|
| Windows | Datei öffnen › Zertifikat installieren › Lokaler Computer › „Vertrauenswürdige Stammzertifizierungsstellen“ |
| macOS | Datei öffnen › Schlüsselbundverwaltung › Zertifikat doppelklicken › Vertrauen › „Immer vertrauen“ |
| iPhone, iPad | in Safari öffnen › Profil laden › Einstellungen › Profil installieren › dann Einstellungen › Allgemein › Info › Zertifikatsvertrauenseinstellungen › einschalten |
| Android | Einstellungen › Sicherheit › Verschlüsselung und Anmeldedaten › Zertifikat installieren › CA-Zertifikat |
| Firefox | hat eigene Zertifikate: Einstellungen › Datenschutz › Zertifikate anzeigen › Importieren |
| Linux | `sudo cp haus-ki-ca.crt /usr/local/share/ca-certificates/ && sudo update-ca-certificates` |

Danach `https://<IP>` neu laden. Das Schloss im Browser ist geschlossen, ohne Warnung.

---

## 6. Ersteinrichtung im Browser

1. `https://<IP von Haus-KI>` öffnen.
2. Einrichtungscode eingeben.
3. Den ersten Administrator anlegen. Stehen Personen in `haus-ki-personen.json`, den Namen des ersten Administrators von dort verwenden.
4. Ein **Notfall-Passwort** festlegen. Damit kommst du auch ohne Microsoft-Anmeldung in Haus-KI, gut aufbewahren.
5. Die Einführung zeigt in drei Schritten das Wichtigste.

In der Administration (Benutzermenü › Administration) sind Proxmox, Ollama, Paperless, Jellyfin und die Websuche
bereits eingerichtet, sofern sie im Skript angegeben wurden. Die Übersicht zeigt, ob alles verbunden ist.

---

## 7. Microsoft 365 anbinden

Für die Anmeldung der Familie, Kalender, Mail-Entwürfe, OneDrive und To Do. Ohne Microsoft 365 funktioniert Haus-KI
auch, dann melden sich nur Administratoren mit dem Notfall-Passwort an.

### In Microsoft Entra (entra.microsoft.com)

1. **App-Registrierungen › Neue Registrierung:**
   - Name: `Haus-KI`
   - Kontotyp: „Nur Konten in diesem Organisationsverzeichnis“. Für zusätzliche Outlook.com-Postfächer: „… und persönliche Microsoft-Konten“.
   - Umleitungs-URI, Plattform Web: `https://<IP oder Name von Haus-KI>/auth/callback`
2. **Zertifikate & Geheimnisse › Neuer geheimer Clientschlüssel:** den Wert sofort kopieren, er wird nur einmal angezeigt. Ablaufdatum notieren.
3. **App-Rollen › App-Rolle erstellen**, zweimal, zulässige Mitgliedstypen „Benutzer/Gruppen“:
   - Anzeigename „Haus-KI Administrator“, Wert `HausKI.Admin`
   - Anzeigename „Haus-KI Mitglied“, Wert `HausKI.Member`
4. **API-Berechtigungen › Berechtigung hinzufügen › Microsoft Graph › Delegiert:**
   `User.Read`, `Mail.ReadWrite`, `Calendars.Read.Shared`, `Files.Read.All`, `Sites.Read.All`, `Tasks.ReadWrite`, `offline_access`.
   Danach „Administratorzustimmung erteilen“.
5. **Unternehmensanwendungen › Haus-KI › Benutzer und Gruppen › Benutzer/Gruppe hinzufügen:** jede Person einer der beiden Rollen zuweisen.

Kinder brauchen ein Konto im Tenant, aber **keine Microsoft-365-Lizenz**. Ohne Lizenz funktioniert die Anmeldung,
nur Mail und Kalender gibt es dann für sie nicht.

### In Haus-KI

Administration › Microsoft 365: Verzeichnis-ID (Tenant), Anwendungs-ID (Client) und den geheimen Clientschlüssel eintragen,
„Verbindung testen“. Danach erscheint auf der Anmeldeseite „Mit Microsoft anmelden“.

---

## 8. KNX anbinden

1. **ETS-Projekt exportieren:** in ETS › Projekt › Exportieren (`.knxproj`). Ist das Projekt mit Passwort geschützt, das Passwort bereithalten.
2. **Administration › Haus (KNX):**
   - IP der KNX-Schnittstelle eintragen.
   - Bei KNX Secure zusätzlich Keyring und Passwort hinterlegen.
   - Verbindung testen.
3. **ETS-Projekt importieren:** Haus-KI übernimmt Gruppenadressen, Räume und Datentypen.
   - **Haustür, Garagentor und Alarmanlage** werden erkannt und fest auf „nur lesen“ gesetzt.
   - Bitte die Liste trotzdem durchsehen und bei Bedarf weitere Geräte sperren.
4. **Rechte vergeben:** pro Gruppenadresse „nicht sichtbar“, „lesen“ oder „schalten“, pro Person die erlaubten Räume.
5. **Schnellsteuerung:** die Szenen und Geräte wählen, die im Haus-Menü oben erscheinen sollen.

Haus-KI braucht eine freie Tunnelverbindung an der Schnittstelle. Belegen andere Programme (Visualisierung, Home Assistant)
schon alle, eine weitere Tunnelverbindung in ETS anlegen.

**Ohne Rückfrage:** Unter Administration › Anfrage-Standards lässt sich erlauben, dass Personen Licht und Rollläden
für sich ohne Rückfrage schalten lassen. Haus-KI erkennt die Geräteart am Namen der Gruppenadresse. Geräte, die
es nicht sicher als Licht oder Rollladen erkennt, fragen immer nach.

---

## 9. Familie einrichten

- **Administration › Benutzer:**
  - Rolle, Quellen, Räume, Lernmodus und Sprache pro Person.
  - Wer vorab angelegt wurde, wird bei der ersten Microsoft-Anmeldung verknüpft.
  - Neue Personen entstehen automatisch bei ihrer ersten Anmeldung.
- **Einfache Ansicht:** Für Mitglieder ist sie voreingestellt. Jede Person kann unter „Einstellungen für mich“ umschalten.
- **Familienwissen:** Benutzermenü › Familienwissen, oder im Chat „Merke dir für alle, …“. Zum Beispiel Müllabfuhr, WLAN für Gäste, Termine, die immer gelten.
- **Sprache:** Administration › Sprache. Die Modelle lädt Haus-KI beim ersten Start. Der Stand steht dort, ebenso eine Stimme zum Probehören.

---

## 10. Als App auf dem Handy

Voraussetzung: Das Zertifikat aus Schritt 5 ist installiert.

- **iPhone, iPad:** Haus-KI in Safari öffnen › Teilen › „Zum Home-Bildschirm“.
- **Android:** Haus-KI in Chrome öffnen › Menü › „App installieren“.

Danach in Haus-KI › Benutzermenü › Einstellungen für mich › „Auch bei geschlossener App“ die Benachrichtigungen
für dieses Gerät einschalten. Fotos und PDFs lassen sich aus anderen Apps über „Teilen“ direkt an Haus-KI schicken
und in Paperless ablegen.

---

## 11. Updates, Sicherung und Wiederherstellung

### Updates

- **Automatisch:** Administration › Updates und Sicherung › Update-Quelle `github:<besitzer>/<repo>`. Haus-KI prüft täglich, Administratoren bekommen eine Benachrichtigung.
- **Von Hand:** neues Paket dort hochladen.
- **Ablauf:** Vor jedem Update wird gesichert. Startet die neue Version nicht, kehrt Haus-KI von selbst zurück.
- **Ollama** aktualisiert sich über den Agenten, ebenfalls dort.

### Sicherung

- **Datenbank:** Haus-KI sichert jede Nacht um 02:00 nach `/var/lib/haus-ki/backups` und behält 14 Stück.
- **Container:** Den ganzen Container sichert Proxmox jede Nacht, sofern im Skript eingerichtet. Zu sehen unter Rechenzentrum › Backup.
- **Schlüsseldatei:** Wichtig ist auch `/etc/haus-ki/haus-ki.env` mit dem Schlüssel für alle gespeicherten Geheimnisse. Ohne diese Datei lassen sich Tokens und Passwörter aus einer Datenbanksicherung nicht mehr lesen. Die Proxmox-Sicherung enthält sie.

### Wiederherstellen

**Ganzer Container:** Proxmox › Container › Backup › Sicherung wählen › Wiederherstellen.

**Nur die Datenbank** (zum Beispiel nach einem Bedienfehler), im Haus-KI-Container:
```
pct enter <ID>
systemctl stop haus-ki
ls /var/lib/haus-ki/backups/
cp /var/lib/haus-ki/haus-ki.db /root/haus-ki.db.vorher
gunzip -c /var/lib/haus-ki/backups/haus-ki-<datum>.db.gz > /var/lib/haus-ki/haus-ki.db
rm -f /var/lib/haus-ki/haus-ki.db-wal /var/lib/haus-ki/haus-ki.db-shm
chown hauski:hauski /var/lib/haus-ki/haus-ki.db
systemctl start haus-ki
```

Am besten einmal üben, solange nichts kaputt ist: Proxmox-Sicherung als neuen Container mit anderer ID wiederherstellen,
starten, prüfen, wieder löschen.

---

## 12. Deinstallieren

1. **Agent und Schutz im Ollama-Gast entfernen:**
   ```
   bash /opt/haus-ki-agent/install-agent.sh --uninstall
   ```
   Falls die Datei fehlt: `systemctl disable --now haus-ki-agent; rm -rf /opt/haus-ki-agent /etc/haus-ki-agent; nft delete table inet hauski_guard`
2. **Optional die Ollama-Einstellungen** von Haus-KI entfernen: `rm /etc/systemd/system/ollama.service.d/haus-ki.conf && systemctl daemon-reload && systemctl restart ollama`
3. **Auf dem Proxmox-Host:**
   ```
   pct stop <ID> && pct destroy <ID> --purge
   pveum user delete hauski@pve
   pveum role delete HausKI
   ```
   Den Sicherungsauftrag „Haus-KI“ unter Rechenzentrum › Backup löschen.
4. **In Microsoft Entra** die App-Registrierung „Haus-KI“ löschen.
5. **Auf den Geräten** das Haus-KI-Zertifikat entfernen.

---

## 13. Wenn etwas nicht klappt

| Problem | Lösung |
|---|---|
| Container startet nicht („Failed to spawn container“) | `bash install/haus-ki-diagnose.sh` probiert verschiedene Einstellungen mit Test-Containern aus und zeigt die Ursache |
| Skript zeigt eine alte Version | Ein alter Ordner `haus-ki` wurde nicht ersetzt: `rm -rf /root/haus-ki` und neu entpacken |
| Seite lädt nicht | `pct enter <ID>`, dann `systemctl status haus-ki caddy` und `journalctl -u haus-ki -n 50` |
| Browser warnt vor dem Zertifikat | Schritt 5, bei Firefox den eigenen Zertifikatsspeicher beachten |
| „Ollama antwortet nicht“ | Läuft der Ollama-Gast? Administration › Ollama-Server › Zugriff auf Ollama: Ist die Adresse von Haus-KI erlaubt? |
| Andere Programme erreichen Ollama nicht mehr | Ihre Adresse unter Administration › Ollama-Server › Zugriff auf Ollama ergänzen |
| Mikrofon grau | Zertifikat installiert? Mikrofon im Browser für Haus-KI erlaubt? |
| Microsoft-Anmeldung schlägt fehl | Umleitungs-URI exakt gleich? Rolle zugewiesen? Clientschlüssel abgelaufen? |
| KNX antwortet nicht | Freie Tunnelverbindung? Bei KNX Secure: Keyring und Passwort |
| Postfach lässt sich nicht verbinden | IMAP eingeschaltet? App-Passwort statt normalem Passwort? |
| Spracherkennung oder Suche nach Bedeutung fehlen | Administration › Sprache bzw. Antwortqualität: Modelle geladen? Container mit 4 Kernen und 4 GB? |

Hilft das alles nicht, bitte ein Issue auf GitHub eröffnen. Hilfreich sind die Haus-KI-Version und die Ausgabe des
Skripts bzw. `journalctl -u haus-ki -n 100`. **Vorher Adressen, Namen und Tokens daraus entfernen.**
Sicherheitslücken bitte vertraulich melden, siehe [SECURITY.md](SECURITY.md).
