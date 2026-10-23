"""Push-Benachrichtigungen (Web Push), auch wenn Haus-KI geschlossen ist.

Der Browser vergibt pro Gerät eine Adresse beim Push-Dienst seines Herstellers (Google, Apple,
Mozilla). Haus-KI schickt dorthin nur einen verschlüsselten, kurzen Hinweistext; den Inhalt
kann der Push-Dienst nicht lesen.
"""
import asyncio
import base64
import json
import logging

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from . import db
from .config import config

log = logging.getLogger("hauski.push")


def _key_path():
    return config.data_dir / "vapid_private.pem"


def keys() -> tuple[str, str]:
    """(Pfad zum privaten Schlüssel, öffentlicher Schlüssel als base64url) – beim ersten Aufruf erzeugt."""
    path = _key_path()
    if not path.exists():
        key = ec.generate_private_key(ec.SECP256R1())
        path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                           serialization.NoEncryption()))
        path.chmod(0o600)
    key = serialization.load_pem_private_key(path.read_bytes(), password=None)
    raw = key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    return str(path), base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def subscribe(user_id: int, sub: dict, ua: str = "") -> None:
    ep, k = sub.get("endpoint", ""), sub.get("keys", {})
    if not ep.startswith("https://") or not k.get("p256dh") or not k.get("auth"):
        raise ValueError("Ungültige Anmeldung für Benachrichtigungen.")
    db.run("INSERT INTO push_subs(endpoint,user_id,p256dh,auth,ua,created) VALUES(?,?,?,?,?,?) "
           "ON CONFLICT(endpoint) DO UPDATE SET user_id=excluded.user_id, p256dh=excluded.p256dh, auth=excluded.auth",
           (ep, user_id, k["p256dh"], k["auth"], ua[:200], db.now()))


def unsubscribe(user_id: int, endpoint: str) -> None:
    db.run("DELETE FROM push_subs WHERE endpoint=? AND user_id=?", (endpoint, user_id))


def _send_sync(sub: dict, payload: dict) -> bool:
    from pywebpush import WebPushException, webpush
    key_path, _ = keys()
    try:
        webpush({"endpoint": sub["endpoint"], "keys": {"p256dh": sub["p256dh"], "auth": sub["auth"]}},
                data=json.dumps(payload, ensure_ascii=False), vapid_private_key=key_path,
                vapid_claims={"sub": "mailto:haus-ki@localhost"}, ttl=3600, timeout=10)
        return True
    except WebPushException as e:
        status = getattr(e.response, "status_code", 0)
        if status in (404, 410):  # Gerät hat die Anmeldung zurückgezogen
            db.run("DELETE FROM push_subs WHERE endpoint=?", (sub["endpoint"],))
        else:
            log.warning("Push an %s fehlgeschlagen: %s", sub["endpoint"][:40], e)
        return False
    except Exception as e:  # noqa: BLE001 – Push ist ein Zusatz, nie ein Grund für einen Fehler
        log.warning("Push fehlgeschlagen: %s", e)
        return False


async def send(user_id: int, title: str, body: str, link: str = "") -> int:
    subs = db.rows("SELECT * FROM push_subs WHERE user_id=?", (user_id,))
    payload = {"title": title, "body": body[:180], "link": link or "/"}
    results = await asyncio.gather(*(asyncio.to_thread(_send_sync, s, payload) for s in subs))
    return sum(1 for r in results if r)


def send_later(user_id: int, title: str, body: str, link: str = "") -> None:
    """Aus synchronem Code heraus: im Hintergrund senden, wenn eine Event-Loop läuft."""
    if not db.scalar("SELECT 1 FROM push_subs WHERE user_id=? LIMIT 1", (user_id,)):
        return
    try:
        asyncio.get_running_loop().create_task(send(user_id, title, body, link))
    except RuntimeError:
        pass
