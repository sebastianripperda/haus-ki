# Änderungen

## 1.9.0

- **Postfächer:**
  - **Ganze Mails lesen:** Haus-KI kann eine gefundene Mail vollständig lesen, mit Liste der Anhänge, auch bei Outlook.com.
  - **Mehr Ordner:** Gesucht wird in Posteingang, Gesendet und Archiv (bei Gmail in „Alle Nachrichten“). Spam und Papierkorb nie.
  - **Schneller:** Alle Postfächer werden gleichzeitig durchsucht. Pro Treffer lädt Haus-KI nur Kopfzeilen und Textanfang, nie die Anhänge. Im Test mit großen Anhängen etwa zehnmal schneller, über das Internet noch deutlicher.
  - **Morgens im Blick:** Der Nachtplan prüft neue Mails auf Rechnungen, Mahnungen und Fristen und zeigt sie mit Fälligkeit und Betrag auf der Startseite. Benachrichtigung abschaltbar unter „Einstellungen für mich“, die ganze Prüfung unter Administration › Quellen. Die Mails verlassen dabei nicht den Haus-KI-Server.
- **iPhone-App und Microsoft-Anmeldung:** Kommt die Anmeldung nach Microsoft nicht in der App an, erklärt die Anmeldeseite jetzt, was zu tun ist, statt einfach neu zu beginnen. Jeder solche Fall steht im Protokoll (mit Hinweis, ob es die App vom Home-Bildschirm war).
- **Abgelaufene Sitzungen** werden nachts gelöscht.
- **Tests:** Postfach-Tests gegen einen echten Mailserver (Dovecot) gehören jetzt fest zur Testsammlung.
- **Wartung:** Die Administration ist in fünf thematische Dateien aufgeteilt. Wiederkehrende Layout-Angaben stehen als CSS-Klassen statt im Code. Optisch ist alles gleich geblieben (Bildvergleich aller 14 Bereiche vorher und nachher).

## 1.8.0

- **Private Postfächer mit Benutzername und Passwort:** neben GMX und Gmail jetzt auch WEB.DE, T-Online, iCloud, Yahoo und jeder andere Anbieter mit IMAP (Server, Port, SSL/TLS oder STARTTLS frei wählbar).
  - Eigener Benutzername, wenn er von der E-Mail-Adresse abweicht.
  - Jede Anmeldung wird sofort geprüft. Fehler werden verständlich erklärt: falsches Passwort, App-Passwort nötig, falscher Server oder Port, Zertifikat nicht vertrauenswürdig.
  - „Testen“ und „Zugangsdaten ändern“ pro Postfach. Neue Angaben werden erst gespeichert, wenn die Anmeldung klappt.
  - Meine Konten zeigt, wann ein Postfach zuletzt funktioniert hat und welches Problem es gerade gibt.
  - Neuer Schalter in der Administration: „Weitere Anbieter mit Benutzername und Passwort erlauben“.
- **Fehler behoben:**
  - Passwörter mit Umlauten, ß oder € führten zum Abbruch. Die Anmeldung läuft jetzt über AUTH=PLAIN mit UTF-8.
  - Leerzeichen wurden aus jedem Passwort entfernt, das ist jetzt nur noch bei Google-App-Passwörtern so.
  - Gmail-Konten auf Deutsch ließen sich nicht durchsuchen (Ordner „Alle Nachrichten“ statt „All Mail“). Ordner werden jetzt über ihre Kennzeichen gefunden, unabhängig von Sprache und Trennzeichen.
  - Die Suche fand nur die exakte Wortfolge. Jetzt muss jedes Wort vorkommen, auch mit Umlauten.
  - Entwürfe landeten bei Anbietern mit „.“ als Ordner-Trennzeichen im falschen Ordner.
  - Outlook.com ohne eingetragene Microsoft-App-Registrierung gibt jetzt einen klaren Hinweis, statt zu einer fehlerhaften Microsoft-Seite zu leiten.

## 1.7.1

- **iPhone und iPad: Anmeldung nach Updates repariert.** Safari hat Skripte ohne Cache-Angabe tagelang aus dem Speicher geladen. Nach dem Update auf 1.7.0 lief auf iOS deshalb noch die alte Anmeldeseite ohne lokale Anmeldung, und in der App auf dem Home-Bildschirm half nicht einmal Neuladen.
  - Skripte und Stile tragen jetzt die Versionsnummer in der Adresse. Nach jedem Update lädt jedes Gerät sofort die neue Oberfläche.
  - Klare Cache-Regeln für alle Dateien, Service Worker mit eigenem Speicher pro Version.
  - Die Anmeldeseite zeigt unten die Versionsnummer.
- **iOS zoomt nicht mehr in Eingabefelder hinein** (Schriftgröße 16 px auf Touch-Geräten), der Anmelde-Knopf bleibt sichtbar.

## 1.7.0

- **Anmeldung ohne Microsoft-Konto:** Administratoren legen unter Benutzer pro Person fest, ob sie sich über Microsoft 365, lokal mit Haus-KI-Passwort oder auf beiden Wegen anmeldet.
  - Neue Benutzer werden direkt mit Rolle, Anmeldeart und Passwort angelegt.
  - Auf der Anmeldeseite wählt man sich aus und gibt das Passwort ein. Fehlversuche sperren wie beim Notfall-Zugang.
  - Jede Person mit lokaler Anmeldung ändert ihr Passwort selbst unter „Einstellungen für mich“.
  - Wechselt die Anmeldeart, enden Sitzungen über den nicht mehr erlaubten Weg. Bei „nur lokal“ wird Microsoft 365 getrennt und die Microsoft-Anmeldung abgewiesen.
  - Der Notfall-Zugang für Administratoren bleibt unverändert und getrennt.
  - `haus-ki-personen.json` kennt das Feld `login` (`m365`, `local`, `both`).

## 1.6.0 – erste öffentliche Version

- **Weniger Rückfragen:** Harmlose Aktionen (Licht, Rollläden, Wiedergabe, Sollwerte, To Do) kann jede Person für sich ohne Rückfrage freigeben. Administratoren legen fest, was überhaupt erlaubt ist.
- **Einführung:** drei kurze Schritte beim ersten Anmelden, passend zu Rolle, Quellen und Sprache.
- **Modelle vergleichen:** dieselben Fragen an zwei Modelle, Ergebnis mit Dauer, Tempo und Bewertungen. Das Installationsskript bietet bei viel RAM ein MoE-Modell an.
- **Veröffentlichung:** Beispielvorgaben statt persönlicher Dateien. Das Bauskript schließt persönliche Vorgaben immer aus. Lizenz, Hinweise zu Komponenten und ein Installationsleitfaden liegen bei.
- **Deinstallation:** Der Agent entfernt beim Deinstallieren auch den Schutz für Ollama, und `--uninstall` funktioniert ohne Paket.

## 1.5.0

- **Einfache Ansicht** für Mitglieder (ohne Modellwahl, Antwortstil, Fachbegriffe).
- **Befehlssuche** mit „/“ im Eingabefeld.
- **Gemeinsames Familienwissen** und Suche in alten Chats nach Bedeutung, immer nur in den eigenen.

## 1.4.x

- **Schneller antworten:**
  - Gleichbleibende Systemanweisung für den Zwischenspeicher von Ollama.
  - Schnelles Modell für einfache Fragen.
  - Satzweises Vorlesen.
  - CPU-Einstellungen für Ollama.
- **Bessere Antworten:** Paperless-Suche nach Bedeutung (bge-m3), Werkzeugprotokoll, Kommentare zu schlechten Bewertungen.
- **Sicherheit:** Ollama-Port nur für Haus-KI, nächtliche Proxmox-Sicherung des Containers.
- **Als App installierbar:** Push-Benachrichtigungen, „Teilen an Haus-KI“.
- **Updates aus GitHub oder eigener Quelle** mit Prüfsumme.
- **Oberfläche** in thematische Dateien aufgeteilt.
- **Websuche:** Das Installationsskript fragt den Schlüssel ab und prüft ihn.

## 1.3.0

- **Sprache:** Spracheingabe (Whisper), Vorlesen (Piper), Gesprächsmodus, Bestätigung von Aktionen per Sprache.

## 1.2.x

- **Installationsskript:**
  - Vorgaben aus einer Datei, Personen vorab anlegen.
  - Paperless, Jellyfin und Modelle gleich mit einrichten.
  - Ollama im Container oder in der VM.
  - Prüfung des Prozessortyps der Vorlage, Diagnose-Skript.

## 1.0 und 1.1

- **Erste Fassung:**
  - Chat mit Quellen.
  - Paperless, Jellyfin, KNX, Microsoft 365, Postfächer, Websuche.
  - Nachtplan, geplante Prompts, Projekte, Vorlagen, Administration, Installation auf Proxmox.
