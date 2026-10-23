# Verwendete Komponenten und Lizenzen

Der Code von Haus-KI steht unter der MIT-Lizenz (siehe `LICENSE`). Das Paket enthält außer eigenem Code nur die
Schriften unter `app/static/fonts`. Alles andere wird bei der Installation oder beim ersten Start aus dem Internet
geladen und steht unter der Lizenz seiner Herausgeber.

## Im Paket enthalten

| Komponente | Lizenz |
|---|---|
| Inter (Schrift) | SIL Open Font License 1.1, Lizenztext in `app/static/fonts` |
| JetBrains Mono (Schrift) | SIL Open Font License 1.1, Lizenztext in `app/static/fonts` |

## Bei der Installation von PyPI geladen (`app/requirements.txt`)

| Paket | Lizenz | Wofür |
|---|---|---|
| fastapi | MIT | Webserver |
| uvicorn | BSD-3-Clause | Webserver |
| httpx | BSD-3-Clause | Verbindungen zu Ollama, Paperless, Jellyfin, Microsoft |
| PyJWT | MIT | Microsoft-Anmeldung |
| cryptography | Apache-2.0 oder BSD-3-Clause | Verschlüsselung der Geheimnisse |
| python-multipart | Apache-2.0 | Datei-Uploads |
| xknx | MIT | KNX |
| **xknxproject** | **GPL-2.0-only** | nur ETS-Import (wird erst dann geladen) |
| faster-whisper, ctranslate2 | MIT | Spracherkennung |
| **piper-tts** | **GPL-3.0-or-later** | nur Vorlesen (wird erst dann geladen) |
| onnxruntime | MIT | Vorlesen |
| av | BSD-3-Clause | Audio lesen |
| num2words | LGPL | Zahlen ausschreiben beim Vorlesen |
| numpy | BSD-3-Clause u. a. | Suche nach Bedeutung |
| pywebpush, py-vapid | MPL-2.0 | Push-Benachrichtigungen |

Haus-KI enthält keinen Code dieser Pakete. Wer Haus-KI zusammen mit diesen Paketen weitergibt, etwa als fertiges
Container-Abbild, muss deren Lizenzen beachten, insbesondere die GPL von xknxproject und piper-tts. Das ist kein
Rechtsrat. Bei Fragen hilft eine fachkundige Stelle.

## Aus den Debian-Paketquellen

Caddy (Apache-2.0), Python, SQLite und weitere Systempakete im Container.

## Modelle (beim ersten Start oder vom Installationsskript geladen)

| Modell | Herkunft | Lizenz |
|---|---|---|
| qwen3 (8b, 4b, 30b-a3b) | Ollama-Bibliothek | Apache-2.0 |
| llama3.2:3b | Ollama-Bibliothek | Llama 3.2 Community License |
| bge-m3 | Ollama-Bibliothek | MIT |
| Whisper (faster-whisper) | Hugging Face | MIT |
| Piper-Stimmen | Hugging Face (rhasspy/piper-voices) | je Stimme verschieden, siehe Modellkarte der Stimme |

Die Lizenzen der Modelle gelten für ihre Nutzung. Bitte vor einer gewerblichen Nutzung die jeweilige Modellkarte lesen.
