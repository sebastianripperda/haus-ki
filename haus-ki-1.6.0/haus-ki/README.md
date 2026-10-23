# Haus-KI

**Ein lokaler KI-Assistent für die Familie, auf dem eigenen Proxmox-Server.**
Die Antworten rechnet [Ollama](https://ollama.com) im eigenen Heimnetz, Chats und Dokumente bleiben im Haus.
Haus-KI verbindet das Sprachmodell mit Paperless-ngx, Jellyfin, KNX, Microsoft 365, IMAP-Postfächern und
(nur auf Wunsch) dem Internet. Die Oberfläche ist deutsch und läuft im Browser und als App auf dem Handy.

*English summary: Haus-KI is a self-hosted, German-language family assistant for Proxmox. It runs next to an
existing Ollama instance and connects it to Paperless-ngx, Jellyfin, KNX, Microsoft 365 and IMAP mailboxes,
with per-person permissions, confirmations for every action and local speech recognition (Whisper) and
text-to-speech (Piper).*

> **Status:** Haus-KI ist ein Hobbyprojekt ohne Gewähr. Es ist gut getestet, aber jede Installation ist anders.
> Prüfe vor allem die Rechte für KNX sorgfältig, bevor Haus-KI Geräte schalten darf.

## Was Haus-KI kann

- **Fragen an eure Daten:** „Was haben wir 2025 für Strom bezahlt?“ (Paperless), „Was steht morgen an?“ (Kalender),
  „Wie warm ist es im Bad?“ (KNX), „Welchen Film haben wir noch nicht gesehen?“ (Jellyfin). Jede Antwort nennt ihre Quellen.
- **Handeln nur nach Bestätigung:** Licht, Rollläden, Wiedergabe, To-Do-Einträge und Mail-Entwürfe schlägt Haus-KI vor.
  Ausgeführt wird erst nach einem Klick oder einem klaren „Ja“. Harmloses kann jede Person für sich freigeben.
- **Für die ganze Familie:** Microsoft-Anmeldung, Rollen, Rechte pro Person und Raum, eine einfache Ansicht und ein Lernmodus für Kinder,
  gemeinsames Familienwissen und ein persönliches Gedächtnis.
- **Sprache:** Spracheingabe mit Whisper, Vorlesen mit Piper, Gesprächsmodus. Alles lokal, Aufnahmen werden nie gespeichert.
- **Nachts:** Sicherung, Fristen aus Paperless, Abgleich des Familienkalenders, geplante Prompts, Suchindex.
- **Als App:** installierbar auf dem Handy, Push-Benachrichtigungen, „Teilen an Haus-KI“ für Fotos und PDFs.
- **Betrieb:** Installationsskript für Proxmox, Updates mit Prüfsumme und automatischer Rückkehr, Ollama-Verwaltung über einen kleinen Agenten.

## Voraussetzungen

- **Proxmox VE 8 oder 9** auf einem amd64-Rechner (arm64-Ports von Proxmox sind ungetestet).
- **Ollama** in einem LXC-Container oder einer VM auf demselben Host. Eine Grafikkarte ist nicht nötig.
  Empfohlen sind mindestens 16 GB RAM für Ollama, für größere Modelle 32 GB oder mehr.
- **Platz für den Haus-KI-Container:** 4 Kerne, 4 GB RAM, 12 GB Platte (mit Spracherkennung).
- **Internet** während der Installation (Debian-Pakete, Python-Pakete, Modelle).
- **Optional:** Paperless-ngx, Jellyfin, eine KNX-IP-Schnittstelle, ein Microsoft-365-Tenant mit Entra ID.

## Aufbau

```
Proxmox-Host
├── LXC haus-ki        (neu, dieses Paket)
│   ├── Caddy          HTTPS mit eigener Zertifizierungsstelle, Port 80/443
│   ├── Haus-KI        Python/FastAPI, Warteschlange, Nachtplan, Whisper und Piper
│   └── SQLite         Datenbank mit nächtlicher Sicherung
└── LXC/VM ollama      (vorhanden)
    ├── Ollama         Port 11434, nur für Haus-KI geöffnet
    └── Haus-KI-Agent  Port 8765, verwaltet Ollama-Einstellungen und den Zugriffsschutz
```

## Installation

Kurzfassung. Die ausführliche Anleitung mit Vorbereitung, Zertifikaten für alle Geräte, Microsoft 365, KNX,
Wiederherstellung und Deinstallation steht im **[Installationsleitfaden](INSTALLATION.md)**.

1. **Paket auf den Proxmox-Host kopieren** und dort als root entpacken:
   ```
   tar -xzf haus-ki-<version>.tar.gz && cd haus-ki
   sha256sum -c ../haus-ki-<version>.tar.gz.sha256   # optional: Paket prüfen
   ```
2. **Optional Vorgaben hinterlegen,** damit das Skript weniger fragt:
   ```
   cp install/haus-ki-install.conf.example install/haus-ki-install.conf          # Netzwerk, Ollama, Quellen
   cp install/haus-ki-personen.example.json install/haus-ki-personen.json        # Personen vorab anlegen
   ```
   Beide Dateien enthalten keine Geheimnisse. Ohne sie fragt das Skript alles ab.
3. **Installationsskript starten:**
   ```
   bash install/haus-ki-lxc.sh
   ```
   Das Skript erledigt der Reihe nach:
   - Es fragt Container, Netzwerk und den Ollama-Gast ab, jeweils mit Vorschlag.
   - Es fragt Paperless-Token, Jellyfin-Schlüssel und den Schlüssel für die Websuche verdeckt ab und prüft jede Verbindung sofort.
   - Es legt einen unprivilegierten Debian-Container an und prüft vor dem Start, ob die Vorlage zum Prozessor passt.
   - Es legt in Proxmox den Benutzer `hauski@pve` mit einem Token an, das nur den Ollama-Gast sehen und neu starten darf.
   - Es installiert den Agenten im Ollama-Gast und öffnet den Ollama-Port auf Wunsch nur noch für Haus-KI.
   - Es stellt Ollama für die CPU ein (Flash Attention, kompakter Kontextspeicher).
   - Es lädt fehlende Modelle: qwen3:8b, qwen3:4b, llama3.2:3b, bge-m3, bei viel RAM zusätzlich qwen3:30b-a3b.
   - Es richtet auf Wunsch eine nächtliche Proxmox-Sicherung des Containers ein.
   - Zum Schluss prüft es alle Verbindungen und zeigt Adresse und Einrichtungscode.
4. **Zertifikat auf jedem Gerät vertrauen:** `http://<IP des Containers>/ca.crt` öffnen und installieren.
   Erst dann funktionieren Mikrofon, App-Installation und Push-Benachrichtigungen.
5. **Ersteinrichtung:** die angezeigte Adresse öffnen, den Einrichtungscode eingeben und den ersten Administrator mit Notfall-Passwort anlegen.
   Stehen Personen in `haus-ki-personen.json`, den Namen des ersten Administrators von dort verwenden.
6. **In der Administration ergänzen:** Microsoft 365 und Haus (KNX).

Startet der Container nicht, hilft `bash install/haus-ki-diagnose.sh`. Es probiert verschiedene Einstellungen mit
Test-Containern durch und zeigt, woran es liegt. Bestehende Container fasst es nicht an.

## Microsoft 365 (Entra ID)

Anmeldung, Kalender, Mail-Entwürfe, Dateien und To Do laufen über eine eigene App-Registrierung:

1. Entra Admin Center › App-Registrierungen › Neue Registrierung „Haus-KI“.
   Für Outlook.com-Postfächer als Kontotyp „Konten in einem beliebigen Organisationsverzeichnis und persönliche Microsoft-Konten“ wählen.
2. Umleitungs-URI (Web): `https://<haus-ki>/auth/callback`
3. Einen geheimen Clientschlüssel anlegen und das Ablaufdatum notieren.
4. App-Rollen anlegen: `HausKI.Admin` und `HausKI.Member`.
5. Unternehmensanwendungen › Haus-KI › Benutzer und Gruppen: Personen den Rollen zuweisen.
   Kinder ohne Lizenz brauchen nur ein Entra-Konto, keine Microsoft-365-Lizenz.
6. Delegierte Berechtigungen für Microsoft Graph: `User.Read`, `Mail.ReadWrite`, `Calendars.Read.Shared`,
   `Files.Read.All`, `Sites.Read.All`, `Tasks.ReadWrite`, `offline_access`. Administratorzustimmung erteilen.

Die Schritte stehen auch in der Administration unter Microsoft 365.

## Sicherheit und Datenschutz

- **Aktionen nur nach Bestätigung.** Ohne Rückfrage läuft nur, was ein Administrator erlaubt und die Person selbst freigegeben hat.
- **Keine Aktionen nach Webinhalten.** Hat eine Antwort Internetinhalte gelesen, sind darin keine Aktionen und keine Gedächtnis-Einträge möglich.
- **Haustür, Garagentor und Alarmanlage** werden beim ETS-Import erkannt und sind fest nur lesbar.
- **Mails werden nie gesendet,** nur als Entwurf gespeichert. Spam-Ordner werden nie gelesen.
- **Rechte gelten überall:** Paperless-Treffer werden mit dem Zugang der fragenden Person geprüft, auch bei der Suche nach Bedeutung.
  In alten Chats findet jede Person nur ihre eigenen.
- **Geheimnisse liegen verschlüsselt** in der Datenbank. Der Schlüssel steht in `/etc/haus-ki/haus-ki.env`, die Datei gehört in die Sicherung.
- **Ollama ist geschützt:** Port 11434 ist nur für Haus-KI offen. Der Agent nimmt nur Anfragen mit Token und von Haus-KI an.
- **Protokoll:** Jede Anmeldung, Änderung und Aktion sowie jede Einsicht in fremde Chats steht im Protokoll (365 Tage).
- **Was das Heimnetz verlässt:**
  - Anfragen an Microsoft 365 und eingebundene Postfächer.
  - Suchbegriffe der Websuche, aber nur, wenn jemand „Internet“ einschaltet.
  - Push-Hinweise über den Dienst des Geräteherstellers, verschlüsselt.
  - Beim ersten Start einmalig die Modelle für Sprache und Suche (Hugging Face).

Sicherheitslücken bitte nicht öffentlich melden, siehe [SECURITY.md](SECURITY.md).

## Bedienung im Überblick

- **„/“ im Eingabefeld** zeigt alle Funktionen: `/merken`, `/familie`, `/suche`, `/planen`, `/paperless`, `/gespräch`, `/hilfe` und mehr.
- **Einfache Ansicht** für Kinder und alle, die es schlicht mögen. Für Mitglieder voreingestellt, umschaltbar unter „Einstellungen für mich“.
- **Gesprächsmodus:** sprechen, zuhören, weitersprechen. Haus-KI liest Satz für Satz vor und versteht „Ja“ und „Nein“ als Bestätigung.
- **Antwortqualität** (Administration): Werkzeugfehler, schlecht bewertete Antworten und ein Vergleich zweier Modelle mit denselben Fragen.

## Updates

- **Von Hand:** neues Paket unter Administration › Updates und Sicherung hochladen.
- **Automatisch:** eine Update-Quelle eintragen, entweder `github:<besitzer>/<repo>` oder die https-Adresse einer `latest.json`.
  Haus-KI prüft täglich und installiert nur, wenn die Prüfsumme (sha256) stimmt.
- Vor jedem Update wird gesichert. Startet die neue Version nicht, kehrt Haus-KI von selbst zurück.
  Im Container geht das auch von Hand: `haus-ki-update --rollback`.

**Eigene Version veröffentlichen:** `bash install/build-package.sh <zielordner>` baut `haus-ki-<version>.tar.gz` und die
passende `.sha256`. Beides als Release auf GitHub hochladen. Persönliche Vorgaben (`haus-ki-install.conf`,
`haus-ki-personen.json`) schließt das Bauskript immer aus.

## Fehlersuche

| Problem | Prüfen |
|---|---|
| Container startet nicht | `bash install/haus-ki-diagnose.sh` |
| Seite lädt nicht | `pct enter <ID>`, dann `systemctl status haus-ki caddy` und `journalctl -u haus-ki -n 50` |
| „Ollama antwortet nicht“ | Läuft der Ollama-Gast? Administration › Ollama-Server › Zugriff auf Ollama: Ist die Adresse von Haus-KI erlaubt? |
| Mikrofon grau, keine App-Installation | Zertifikat (`/ca.crt`) auf dem Gerät installiert und vertraut? |
| Microsoft-Anmeldung schlägt fehl | Umleitungs-URI exakt? Rolle zugewiesen? Clientschlüssel abgelaufen? |
| KNX antwortet nicht | Freie Tunnelverbindung an der Schnittstelle? Bei KNX Secure: Keyring und Passwort |
| Postfach lässt sich nicht verbinden | IMAP eingeschaltet? App-Passwort statt normalem Passwort? |
| Sprache oder Suche nach Bedeutung fehlen | Administration › Sprache bzw. Antwortqualität: Sind die Modelle geladen? |

## Entwicklung

```
cd app
pip install -r requirements.txt pytest
HAUSKI_DEV=1 python3 -m pytest -q tests
HAUSKI_DEV=1 HAUSKI_DATA=/tmp/hk HAUSKI_SETUP_CODE=TEST HAUSKI_BASE_URL=http://localhost:8080 uvicorn hauski.main:app --port 8080
```

- **Backend:** `app/hauski` (FastAPI, SQLite, eine Datei pro Thema, Werkzeuge für das Modell unter `tools/`).
- **Oberfläche:** `app/static`, ohne Build-Schritt und ohne externe Bibliotheken. Die Dateien werden in fester Reihenfolge geladen
  (siehe `index.html`): `core`, `login`, `shell`, `knx`, `pages`, `chat`, `composer`, `commands`, `dialogs`, `voice`, `admin`.
- **Installation:** `install/` (Proxmox-Skript, Einrichtung im Container, Update-Skript, Agent).

Änderungen bitte mit Tests. Neue Werkzeuge, die etwas verändern, müssen über eine Bestätigung laufen.

## Lizenz

Haus-KI steht unter der MIT-Lizenz, siehe [LICENSE](LICENSE). © 2026 Sebastian Ripperda, [www.ripperda.tech](https://www.ripperda.tech). Verwendete Komponenten und Modelle haben eigene Lizenzen,
siehe [NOTICE.md](NOTICE.md).
