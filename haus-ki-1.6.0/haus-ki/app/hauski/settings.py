"""Einstellungen, die Administratoren in der Oberfläche ändern.

Alle Werte liegen als JSON in der Tabelle `settings`. Geheimnisse werden verschlüsselt
gespeichert und nie an den Browser zurückgegeben.
"""
import json

from . import db, security
from .config import config

DEFAULTS: dict = {
    # Ollama und Modelle
    "ollama.url": "http://ollama:11434",
    "ollama.default_model": "qwen3:8b",
    "ollama.helper_model": "llama3.2:3b",
    "ollama.member_models": ["qwen3:8b"],
    "ollama.parallel": 1,
    "ollama.route_simple": True,
    "ollama.fast_model": "",
    # Anfrage-Standards
    "req.temperature": 0.6,
    "req.top_p": 0.9,
    "req.top_k": 40,
    "req.repeat_penalty": 1.1,
    "req.num_ctx": 8192,
    "req.num_predict": 1024,
    "req.seed": 0,
    "req.think": False,
    "req.keep_alive": "-1",
    "req.num_thread": 0,
    # Chats und Datenschutz
    "chat.retention_days": 90,
    "chat.keep_pinned": True,
    "chat.admin_read": True,
    "chat.followups": True,
    "suggestions.mode": "night",
    "night.start": "02:00",
    "session.idle_hours": 8,
    "login.max_failed": 5,
    "login.lock_minutes": 15,
    "schedules.max_per_user": 5,
    # Paperless
    "paperless.enabled": False,
    "paperless.url": "",
    "paperless.token": "",
    "paperless.personal_tokens": True,
    "paperless.deadlines": True,
    "paperless.deadline_days": 14,
    "paperless.upload": True,
    "paperless.write_tags": False,
    "paperless.semantic": True,
    "paperless.embed_model": "bge-m3",
    "history.semantic": True,
    # Was Personen ohne Rückfrage ausführen lassen dürfen (jede Person wählt daraus selbst)
    "actions.auto_allowed": ["knx_light", "knx_blind", "jellyfin_play"],
    # Jellyfin
    "jellyfin.enabled": False,
    "jellyfin.url": "",
    "jellyfin.api_key": "",
    "jellyfin.playback": True,
    # Weitere Postfächer
    "mail.allow_gmx": True,
    "mail.allow_gmail": True,
    "mail.allow_outlookcom": True,
    "mail.drafts": True,
    # Internet
    "web.enabled": False,
    "web.provider": "ollama",
    "web.ollama_key": "",
    "web.searxng_url": "",
    "web.max_results": 5,
    # KNX
    "knx.enabled": False,
    "knx.mode": "tunnel",
    "knx.gateway_ip": "",
    "knx.gateway_port": 3671,
    "knx.local_ip": "",
    "knx.secure": False,
    "knx.keyring_password": "",
    "knx.scenes": [],
    "knx.trip_check": [],
    # Microsoft 365
    "ms.enabled": False,
    "ms.tenant_id": "",
    "ms.client_id": "",
    "ms.client_secret": "",
    "ms.mail": True,
    "ms.mail_drafts": True,
    "ms.calendar": True,
    "ms.files": True,
    "ms.todo": True,
    "ms.cal_check": True,
    "ms.family_calendar_owner": "",
    "ms.family_calendar_name": "Familie",
    "ms.todo_list": "Einkauf",
    # Proxmox und Agent
    "proxmox.url": "",
    "proxmox.token_id": "",
    "proxmox.token_secret": "",
    "proxmox.node": "",
    "proxmox.vmid": 0,
    "proxmox.kind": "lxc",  # lxc = Container, qemu = VM
    "proxmox.verify_tls": False,
    "agent.url": "",
    "agent.token": "",
    "agent.fingerprint": "",
    # Sprache
    "voice.enabled": True,
    "voice.stt_model": "small",
    "voice.threads": 4,
    "voice.keep_loaded": True,
    "voice.vad": True,
    "voice.default_voice": "de_DE-kerstin-low",
    "voice.skip_cites": True,
    "voice.numbers": True,
    "voice.talk": True,
    "voice.confirm": True,
    # Sicherung
    "backup.enabled": True,
    "backup.keep": 14,
    # Updates
    "update.source": "",
    "update.auto_check": True,
}

SECRETS = {
    "paperless.token", "jellyfin.api_key", "web.ollama_key", "knx.keyring_password",
    "ms.client_secret", "proxmox.token_secret", "agent.token",
}

_cache: dict | None = None


def _load() -> dict:
    global _cache
    if _cache is None:
        values = dict(DEFAULTS)
        for r in db.rows("SELECT key, value FROM settings"):
            v = db.jload(r["value"])
            if r["key"] in SECRETS:
                v = security.decrypt(v) if v else ""
            values[r["key"]] = v
        _cache = values
    return _cache


def get(key: str):
    return _load().get(key, DEFAULTS.get(key))


def all_public() -> dict:
    """Für die Administration: Geheimnisse nur als „gesetzt / nicht gesetzt“."""
    out = {}
    for k, v in _load().items():
        out[k] = {"set": bool(v)} if k in SECRETS else v
    return out


def set_many(values: dict) -> list[str]:
    global _cache
    changed = []
    with db.tx() as conn:
        for key, value in values.items():
            if key not in DEFAULTS:
                continue
            if key in SECRETS:
                if value is None or value == {"set": True}:
                    continue  # unverändert
                stored = json.dumps(security.encrypt(value) if value else "")
            else:
                stored = json.dumps(_coerce(key, value), ensure_ascii=False)
            conn.execute("INSERT INTO settings(key,value) VALUES(?,?) "
                         "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, stored))
            changed.append(key)
    _cache = None
    return changed


def _coerce(key: str, value):
    default = DEFAULTS[key]
    try:
        if isinstance(default, bool):
            return bool(value)
        if isinstance(default, int):
            return int(value)
        if isinstance(default, float):
            return float(value)
        if isinstance(default, list):
            return [str(x)[:60] for x in (value if isinstance(value, list) else [])]
    except (TypeError, ValueError):
        return default
    return value


def import_bootstrap() -> None:
    """Werte, die das Installationsskript ermittelt hat (Proxmox-Token, Agent, Ollama-URL)."""
    path = config.bootstrap_file
    if not path.exists() or db.kv_get("bootstrap_done"):
        return
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return
    set_many({k: v for k, v in data.items() if k in DEFAULTS})
    from . import users
    for person in data.get("users", []):
        name = (person.get("name") or "").strip()
        if not name or db.row("SELECT id FROM users WHERE lower(name)=lower(?)", (name,)):
            continue
        uid = users.create(name, "admin" if person.get("role") == "admin" else "member", email=person.get("email") or "")
        perms = {k: person[k] for k in ("learn", "jellyfin_user", "paperless", "m365") if k in person}
        if perms:
            db.run("UPDATE users SET perms=? WHERE id=?", (json.dumps(perms), uid))
    db.kv_set("bootstrap_done", True)
