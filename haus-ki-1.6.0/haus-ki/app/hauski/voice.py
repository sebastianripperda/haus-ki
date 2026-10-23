"""Sprache: Spracheingabe mit Whisper (faster-whisper), Vorlesen mit Piper.

Beides läuft lokal im Haus-KI-Container auf der CPU. Aufnahmen werden nur im
Arbeitsspeicher bzw. in einer temporären Datei verarbeitet und sofort gelöscht.
Die Modelle werden beim ersten Bedarf (oder beim Start) von Hugging Face geladen.
"""
import asyncio
import io
import logging
import os
import re
import tempfile
import threading
import time
import wave
from pathlib import Path

import httpx

from . import db, settings
from .config import config

log = logging.getLogger("hauski.voice")

WHISPER_MODELS = {
    "tiny": {"size": "75 MB", "speed": "unter 1 s", "quality": "für Deutsch zu ungenau"},
    "base": {"size": "142 MB", "speed": "etwa 1 s", "quality": "brauchbar, Namen oft falsch"},
    "small": {"size": "466 MB", "speed": "etwa 2–3 s", "quality": "gut, empfohlen"},
    "medium": {"size": "1,5 GB", "speed": "etwa 8–10 s", "quality": "sehr gut, aber träge"},
}
PIPER_BASE = "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/"
KNOWN_VOICES = {
    "de_DE-kerstin-low": ("Kerstin", "Weiblich, ruhig und klar", "de/de_DE/kerstin/low"),
    "de_DE-thorsten-high": ("Thorsten", "Männlich, sehr natürlich, etwas langsamer", "de/de_DE/thorsten/high"),
    "de_DE-eva_k-x_low": ("Eva", "Weiblich, lebhaft", "de/de_DE/eva_k/x_low"),
}
SPEEDS = {"slow": 1.18, "normal": 1.0, "fast": 0.85}

_stt_lock = threading.Lock()
_tts_lock = threading.Lock()
_whisper = None
_whisper_name = ""
_voices: dict = {}
state = {"stt_busy": False, "prefetch": "", "error": ""}


class NothingHeard(Exception):
    pass


def voice_dir() -> Path:
    d = config.data_dir / "voice"
    d.mkdir(parents=True, exist_ok=True)
    return d


# ------------------------------------------------------------------ Spracherkennung
def _load_whisper():
    global _whisper, _whisper_name
    name = settings.get("voice.stt_model")
    if _whisper is None or _whisper_name != name:
        from faster_whisper import WhisperModel
        _whisper = WhisperModel(name, device="cpu", compute_type="int8", cpu_threads=int(settings.get("voice.threads") or 4),
                                download_root=str(voice_dir() / "whisper"))
        _whisper_name = name
    return _whisper


def transcribe_sync(data: bytes, suffix: str) -> dict:
    """Blockierend; läuft in einem eigenen Thread. Gibt Text und Dauer zurück."""
    global _whisper
    started = time.time()
    with _stt_lock:
        state["stt_busy"] = True
        fd, path = tempfile.mkstemp(suffix=suffix or ".webm", dir=str(voice_dir()))
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(data)
            model = _load_whisper()
            segments, info = model.transcribe(path, language="de", beam_size=1, vad_filter=True,
                                              condition_on_previous_text=False)
            text = " ".join(s.text.strip() for s in segments).strip()
            duration = float(getattr(info, "duration", 0) or 0)
        finally:
            os.unlink(path)  # Aufnahme sofort löschen
            state["stt_busy"] = False
            if not settings.get("voice.keep_loaded"):
                _whisper = None
    if not text or duration < 0.4 or len(re.sub(r"\W", "", text)) < 2:
        raise NothingHeard()
    return {"text": text, "audio_seconds": round(duration, 1), "seconds": round(time.time() - started, 1)}


async def transcribe(data: bytes, suffix: str) -> dict:
    result = await asyncio.to_thread(transcribe_sync, data, suffix)
    _count("stt", result["seconds"])
    return result


# ------------------------------------------------------------------ Vorlesen
def installed_voices() -> list[str]:
    d = voice_dir() / "piper"
    if not d.exists():
        return []
    return sorted(p.stem for p in d.glob("*.onnx") if (p.parent / (p.name + ".json")).exists())


def voice_info(name: str) -> dict:
    label, desc, _ = KNOWN_VOICES.get(name, (name.split("-")[1].split("_")[0].capitalize() if "-" in name else name, "", ""))
    return {"id": name, "name": label, "desc": desc, "installed": name in installed_voices()}


async def download_voice(name: str, path_hint: str = "") -> None:
    rel = path_hint or (KNOWN_VOICES[name][2] if name in KNOWN_VOICES else "")
    if not rel or not re.fullmatch(r"[a-z]{2}/[a-z]{2}_[A-Z]{2}/[\w-]+/[\w-]+", rel):
        raise ValueError("Unbekannte Stimme.")
    d = voice_dir() / "piper"
    d.mkdir(parents=True, exist_ok=True)
    async with httpx.AsyncClient(timeout=httpx.Timeout(20, read=300), follow_redirects=True) as c:
        for ext in (".onnx.json", ".onnx"):
            target = d / (name + ext)
            if target.exists() and target.stat().st_size > 0:
                continue
            tmp = target.with_suffix(target.suffix + ".part")
            async with c.stream("GET", f"{PIPER_BASE}{rel}/{name}{ext}") as r:
                r.raise_for_status()
                with open(tmp, "wb") as f:
                    async for chunk in r.aiter_bytes(1 << 16):
                        f.write(chunk)
            tmp.rename(target)


async def catalog() -> list[dict]:
    """Deutsche Stimmen aus dem Piper-Katalog."""
    async with httpx.AsyncClient(timeout=20, follow_redirects=True) as c:
        r = await c.get(PIPER_BASE + "voices.json")
        r.raise_for_status()
    out = []
    for key, v in r.json().items():
        if v.get("language", {}).get("code") == "de_DE":
            onnx = next((f for f in v.get("files", {}) if f.endswith(".onnx")), "")
            out.append({"id": key, "quality": v.get("quality"), "path": onnx.rsplit("/", 1)[0],
                        "size": v.get("files", {}).get(onnx, {}).get("size_bytes", 0)})
    return sorted(out, key=lambda x: x["id"])


def _load_voice(name: str):
    if name not in _voices:
        from piper import PiperVoice
        path = voice_dir() / "piper" / (name + ".onnx")
        if not path.exists():
            raise FileNotFoundError(name)
        _voices[name] = PiperVoice.load(str(path))
    return _voices[name]


def synth_sync(text: str, voice: str, speed: str) -> bytes:
    from piper import SynthesisConfig
    with _tts_lock:
        v = _load_voice(voice)
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            v.synthesize_wav(text, w, syn_config=SynthesisConfig(length_scale=SPEEDS.get(speed, 1.0)))
        return buf.getvalue()


async def synthesize(text: str, voice: str, speed: str) -> bytes:
    voice = voice if voice in installed_voices() else settings.get("voice.default_voice")
    if voice not in installed_voices():
        await download_voice(voice)
    started = time.time()
    audio = await asyncio.to_thread(synth_sync, text, voice, speed)
    _count("tts", time.time() - started, audio_seconds=_wav_seconds(audio))
    return audio


def _wav_seconds(audio: bytes) -> float:
    try:
        with wave.open(io.BytesIO(audio)) as w:
            return w.getnframes() / float(w.getframerate())
    except Exception:  # noqa: BLE001
        return 0.0


# ------------------------------------------------------------------ Text zum Vorlesen aufbereiten
def _num_words(n: float | int) -> str:
    from num2words import num2words
    return num2words(n, lang="de")


def _amount(m: re.Match) -> str:
    euros = int(m.group(1).replace(".", ""))
    cents = int((m.group(2) or "0").ljust(2, "0"))
    out = f"{_num_words(euros)} Euro"
    if cents:
        out += f" {_num_words(cents)}"
    return out


def prepare_speech(md: str, skip_cites: bool = True, numbers: bool = True) -> str:
    """Markdown in vorlesbaren Text verwandeln."""
    t = md or ""
    t = re.sub(r"```.*?```", " Ein Codebeispiel steht im Chat. ", t, flags=re.S)
    lines, out, table_rows = t.split("\n"), [], 0
    for line in lines:
        if re.match(r"^\s*\|.*\|\s*$", line):
            if not re.match(r"^\s*\|?\s*:?-{2,}", line):
                table_rows += 1
            continue
        if table_rows:
            out.append(f"Es folgt eine Tabelle mit {max(table_rows - 1, 1)} Zeilen, die Details stehen im Chat.")
            table_rows = 0
        out.append(line)
    if table_rows:
        out.append(f"Es folgt eine Tabelle mit {max(table_rows - 1, 1)} Zeilen, die Details stehen im Chat.")
    t = "\n".join(out)
    t = re.sub(r"\[([^\]]+)\]\((https?://[^)]+)\)", r"\1", t)          # Links: nur der Text
    t = re.sub(r"https?://\S+", "(Link im Chat)", t)
    if skip_cites:
        t = re.sub(r"\s?\[\d{1,2}\]", "", t)                            # Quellenverweise [1]
    t = re.sub(r"^\s{0,3}#{1,6}\s*", "", t, flags=re.M)                  # Überschriften
    t = re.sub(r"^\s*([-*•]|\d+[.)])\s+", "", t, flags=re.M)             # Aufzählungszeichen
    t = re.sub(r"[*_`>]+", "", t)
    if numbers:
        t = re.sub(r"(\d{1,3}(?:\.\d{3})+|\d+)(?:,(\d{1,2}))?\s?(?:€|EUR\b|Euro\b)", _amount, t)
        t = re.sub(r"(\d+),(\d+)\s?%", lambda m: f"{_num_words(float(m[1] + '.' + m[2]))} Prozent", t)
        t = re.sub(r"(\d+)\s?%", lambda m: f"{_num_words(int(m[1]))} Prozent", t)
        t = re.sub(r"(\d+),(\d+)\s?°C", lambda m: f"{_num_words(float(m[1] + '.' + m[2]))} Grad", t)
        t = re.sub(r"(\d+)\s?°C", lambda m: f"{_num_words(int(m[1]))} Grad", t)
        # Tausenderpunkte, aber keine Datumsangaben wie 12.02.2026
        t = re.sub(r"(?<![\d.])(\d{1,3}(?:\.\d{3})+)(?![\d.])", lambda m: _num_words(int(m[1].replace(".", ""))), t)
        t = re.sub(r"(?<![\d.,])(\d+),(\d+)(?![\d.,])", lambda m: _num_words(float(m[1] + "." + m[2])), t)
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r"\n{2,}", "\n", t).strip()
    return t[:4000]


# ------------------------------------------------------------------ Ja oder Nein
_YES = {"ja", "jawohl", "jo", "jap", "jep", "genau", "ok", "okay", "bitte", "mach", "machs", "ausführen", "ausfuehren",
        "klar", "richtig", "gerne", "gern", "einverstanden", "los", "bestätigt", "bestätige"}
_NO = {"nein", "nee", "ne", "nö", "nicht", "abbrechen", "abbruch", "stopp", "stop", "halt", "warte", "falsch", "niemals", "keinesfalls"}


def interpret_yes_no(text: str) -> str:
    """„yes“, „no“ oder „unclear“. Im Zweifel nie „yes“."""
    words = re.findall(r"[a-zäöüß]+", (text or "").lower())
    if not words:
        return "unclear"
    if any(w in _NO for w in words):
        return "no"
    if len(words) > 5:
        return "unclear"  # lange Sätze sind keine klare Bestätigung
    if words[0] in _YES or (len(words) <= 3 and any(w in _YES for w in words)):
        return "yes"
    return "unclear"


# ------------------------------------------------------------------ Vorbereitung und Statistik
async def prefetch() -> None:
    """Beim Start: Whisper-Modell und Standardstimme laden, falls Sprache eingeschaltet ist."""
    if not settings.get("voice.enabled"):
        return
    try:
        state["prefetch"] = "läuft"
        await download_voice(settings.get("voice.default_voice"))
        if settings.get("voice.keep_loaded"):
            await asyncio.to_thread(_load_whisper)
        else:
            from faster_whisper.utils import download_model
            await asyncio.to_thread(download_model, settings.get("voice.stt_model"), cache_dir=str(voice_dir() / "whisper"))
        state.update(prefetch="fertig", error="")
    except Exception as e:  # noqa: BLE001 – ohne Internet beim Start einfach später erneut versuchen
        log.warning("Sprachmodelle konnten nicht geladen werden: %s", e)
        state.update(prefetch="fehler", error=str(e)[:200])


def stt_ready() -> bool:
    if _whisper is not None:
        return True
    d = voice_dir() / "whisper"
    name = settings.get("voice.stt_model")
    return d.exists() and any(name in p.name for p in d.glob("*"))


def _count(kind: str, seconds: float, audio_seconds: float = 0.0) -> None:
    key = f"voice:{kind}:{time.strftime('%Y-%m-%d')}"
    v = db.kv_get(key, {"n": 0, "s": 0.0, "a": 0.0})
    v.update(n=v["n"] + 1, s=v["s"] + seconds, a=v.get("a", 0.0) + audio_seconds)
    db.kv_set(key, v)


def stats_today() -> dict:
    day = time.strftime("%Y-%m-%d")
    stt = db.kv_get(f"voice:stt:{day}", {"n": 0, "s": 0.0})
    tts = db.kv_get(f"voice:tts:{day}", {"n": 0, "s": 0.0, "a": 0.0})
    return {"stt_count": stt["n"], "stt_avg": round(stt["s"] / stt["n"], 1) if stt["n"] else 0,
            "tts_count": tts["n"], "tts_minutes": round(tts.get("a", 0) / 60, 1),
            "tts_avg": round(tts["s"] / tts["n"], 1) if tts["n"] else 0}
