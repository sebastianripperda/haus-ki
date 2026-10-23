# Änderungen

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
