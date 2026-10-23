# Sicherheitslücken melden

Bitte Sicherheitslücken **nicht** als öffentliches Issue melden, sondern vertraulich:

- auf GitHub über „Security › Report a vulnerability“ im Repository, oder
- per E-Mail an Sebastian Ripperda: [sebastian@ripperda.tech](mailto:sebastian@ripperda.tech) ([www.ripperda.tech](https://www.ripperda.tech))

Hilfreich sind die Version (`/health` oder Administration › Updates), eine kurze Beschreibung und Schritte zum Nachvollziehen.
Eine erste Antwort gibt es in der Regel innerhalb einer Woche. Behobene Lücken stehen im `CHANGELOG.md`.

## Was als Sicherheitslücke zählt

- Zugriff auf Chats, Dokumente oder Geheimnisse ohne entsprechende Rechte
- Aktionen (KNX, Wiedergabe, Entwürfe) ohne Bestätigung, sofern die Person sie nicht selbst freigegeben hat
- Aktionen oder Gedächtnis-Einträge, die durch Webinhalte ausgelöst werden
- Umgehen der Anmeldung, des Ollama-Schutzes oder der Prüfsumme bei Updates

Haus-KI ist für das Heimnetz gedacht. Bitte nicht ohne zusätzliche Absicherung (VPN, Reverse Proxy mit Anmeldung) ins Internet stellen.
