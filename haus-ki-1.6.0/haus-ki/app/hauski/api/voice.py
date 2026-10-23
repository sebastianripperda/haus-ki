"""Endpunkte für Spracheingabe, Vorlesen und Bestätigung per Sprache."""
import asyncio

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

from .. import chat, db, settings, users, voice
from ..auth import current_user, require_admin
from ..events import audit

router = APIRouter(prefix="/api")
MAX_AUDIO = 12_000_000  # etwa 3 Minuten Opus


def _allowed(user: dict) -> None:
    if not settings.get("voice.enabled") or not users.perms(user).get("voice", True):
        raise HTTPException(403, "Sprache ist für dich nicht freigegeben.")


@router.get("/voice/info")
def info(user=Depends(current_user)):
    _allowed(user)
    p = users.prefs(user)
    return {"voices": [voice.voice_info(v) for v in voice.installed_voices()] or [voice.voice_info(settings.get("voice.default_voice"))],
            "default_voice": settings.get("voice.default_voice"), "my_voice": p.get("voice") or settings.get("voice.default_voice"),
            "speed": p.get("voice_speed", "normal"), "auto_send": p.get("voice_auto_send"), "read_talk": p.get("voice_read_talk"),
            "vad": settings.get("voice.vad"), "talk": settings.get("voice.talk"), "confirm": settings.get("voice.confirm"),
            "stt_model": settings.get("voice.stt_model"), "ready": voice.stt_ready()}


@router.post("/voice/stt")
async def stt(file: UploadFile = File(...), user=Depends(current_user)):
    _allowed(user)
    data = await file.read()
    if len(data) > MAX_AUDIO:
        raise HTTPException(413, "Die Aufnahme ist zu lang. Bitte kürzer sprechen.")
    if len(data) < 1500:
        raise HTTPException(422, "Ich habe nichts verstanden, die Aufnahme war zu kurz.")
    suffix = ".mp4" if "mp4" in (file.content_type or "") else ".ogg" if "ogg" in (file.content_type or "") else ".webm"
    try:
        return await voice.transcribe(data, suffix)
    except voice.NothingHeard:
        raise HTTPException(422, "Ich habe nichts verstanden. Sprich etwas näher am Gerät oder tippe deine Frage.")
    except Exception as e:  # noqa: BLE001
        raise HTTPException(503, f"Die Spracherkennung ist gerade nicht verfügbar: {e}"[:300])
    finally:
        del data  # Aufnahme nicht aufbewahren


class TtsIn(BaseModel):
    text: str
    voice: str = ""
    speed: str = ""
    raw: bool = False


@router.post("/voice/tts")
async def tts(body: TtsIn, user=Depends(current_user)):
    _allowed(user)
    p = users.prefs(user)
    text = body.text if body.raw else voice.prepare_speech(body.text, settings.get("voice.skip_cites"), settings.get("voice.numbers"))
    if not text.strip():
        raise HTTPException(400, "Nichts zum Vorlesen.")
    try:
        audio = await voice.synthesize(text, body.voice or p.get("voice") or settings.get("voice.default_voice"),
                                       body.speed or p.get("voice_speed", "normal"))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(503, f"Vorlesen ist gerade nicht möglich: {e}"[:300])
    return Response(audio, media_type="audio/wav", headers={"Cache-Control": "no-store"})


class ConfirmIn(BaseModel):
    text: str


@router.post("/actions/{aid}/voice")
async def confirm_by_voice(aid: int, body: ConfirmIn, user=Depends(current_user)):
    _allowed(user)
    if not settings.get("voice.confirm"):
        raise HTTPException(403, "Aktionen per Sprache zu bestätigen ist ausgeschaltet. Bitte den Knopf benutzen.")
    verdict = voice.interpret_yes_no(body.text)
    if verdict == "unclear":
        return {"status": "unclear", "heard": body.text[:120]}
    try:
        r = await chat.decide(user, aid, verdict == "yes", via=f"per Sprache: „{body.text[:40]}“")
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {**r, "heard": body.text[:120]}


# ------------------------------------------------------------------ Administration
def _resources() -> dict:
    import os
    mem = 0
    try:
        for line in open("/proc/meminfo"):
            if line.startswith("MemTotal:"):
                mem = int(line.split()[1]) * 1024
    except OSError:
        pass
    return {"cpus": os.cpu_count() or 0, "mem": mem}


@router.get("/admin/voice")
def admin_status(user=Depends(require_admin)):
    return {"resources": _resources(),"models": voice.WHISPER_MODELS, "stt_model": settings.get("voice.stt_model"), "stt_ready": voice.stt_ready(),
            "loaded": voice._whisper is not None, "busy": voice.state["stt_busy"], "prefetch": voice.state["prefetch"],
            "error": voice.state["error"], "voices": [voice.voice_info(v) for v in voice.installed_voices()],
            "known": [voice.voice_info(k) for k in voice.KNOWN_VOICES], "default_voice": settings.get("voice.default_voice"),
            "stats": voice.stats_today()}


@router.post("/admin/voice/prepare")
async def admin_prepare(user=Depends(require_admin)):
    asyncio.create_task(voice.prefetch())
    audit(user["name"], "System", "Sprachmodelle werden geladen")
    return {"ok": True}


@router.get("/admin/voice/catalog")
async def admin_catalog(user=Depends(require_admin)):
    try:
        return await voice.catalog()
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"Der Stimmen-Katalog ist nicht erreichbar: {e}"[:200])


@router.post("/admin/voice/install")
async def admin_install(body: dict, user=Depends(require_admin)):
    try:
        await voice.download_voice(body.get("id", ""), body.get("path", ""))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"Die Stimme ließ sich nicht laden: {e}"[:200])
    audit(user["name"], "Einstellung", f"Stimme {body.get('id')} installiert")
    return {"ok": True}
