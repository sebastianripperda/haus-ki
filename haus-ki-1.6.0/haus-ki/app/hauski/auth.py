"""Anmeldung: Microsoft Entra ID (OIDC mit PKCE), Notfall-Zugang und Ersteinrichtung."""
import base64
import hashlib
import time
from urllib.parse import urlencode

import httpx
import jwt
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from . import db, security, settings, users
from .config import config
from .events import audit

router = APIRouter()
COOKIE = "hk_session"
MAX_AGE = 30 * 24 * 3600
ROLE_ADMIN, ROLE_MEMBER = "HausKI.Admin", "HausKI.Member"
_jwks: dict[str, jwt.PyJWKClient] = {}


# ---------------------------------------------------------------- Sitzungen
def start_session(resp: Response, request: Request, user: dict, method: str) -> None:
    sid = security.token()
    db.run("INSERT INTO sessions(id,user_id,created,last_seen,ip,ua,method) VALUES(?,?,?,?,?,?,?)",
           (sid, user["id"], db.now(), db.now(), request.client.host if request.client else "",
            request.headers.get("user-agent", "")[:200], method))
    resp.set_cookie(COOKIE, sid, max_age=MAX_AGE, httponly=True, secure=not config.dev, samesite="lax", path="/")
    db.run("UPDATE users SET failed_logins=0, locked_until=0 WHERE id=?", (user["id"],))
    audit(user["name"], "Anmeldung", f"Angemeldet über {method}")


def session_user(request: Request) -> dict | None:
    sid = request.cookies.get(COOKIE)
    if not sid:
        return None
    s = db.row("SELECT * FROM sessions WHERE id=?", (sid,))
    if not s:
        return None
    idle = float(settings.get("session.idle_hours")) * 3600
    if db.now() - s["last_seen"] > idle or db.now() - s["created"] > MAX_AGE:
        db.run("DELETE FROM sessions WHERE id=?", (sid,))
        return None
    if db.now() - s["last_seen"] > 60:
        db.run("UPDATE sessions SET last_seen=? WHERE id=?", (db.now(), sid))
    user = users.get(s["user_id"])
    if not user or user["disabled"]:
        return None
    return user


def current_user(request: Request) -> dict:
    user = session_user(request)
    if not user:
        raise HTTPException(401, "Bitte melde dich an.")
    # Schutz vor Cross-Site-Anfragen: schreibende Aufrufe müssen aus unserer App kommen.
    if request.method not in ("GET", "HEAD", "OPTIONS") and request.headers.get("x-haus-ki") != "1":
        raise HTTPException(403, "Ungültige Anfrage.")
    return user


def require_admin(user: dict = Depends(current_user)) -> dict:
    if not users.is_admin(user):
        raise HTTPException(403, "Nur für Administratoren.")
    return user


@router.post("/auth/logout")
def logout(request: Request, response: Response):
    sid = request.cookies.get(COOKIE)
    if sid:
        db.run("DELETE FROM sessions WHERE id=?", (sid,))
    response.delete_cookie(COOKIE, path="/")
    return {"ok": True}


# ---------------------------------------------------------------- Ersteinrichtung
class SetupIn(BaseModel):
    code: str
    name: str
    password: str


def setup_done() -> bool:
    return bool(db.kv_get("setup_done")) or bool(db.scalar("SELECT COUNT(*) FROM users WHERE pw_hash IS NOT NULL OR oid IS NOT NULL"))


@router.get("/api/setup/status")
def setup_status():
    n = db.scalar("SELECT COUNT(*) FROM users") or 0
    return {"needs_setup": not setup_done(), "sso": sso_ready(),
            "recent": [users.public(u) | {"emergency": bool(u["pw_hash"])} for u in db.rows(
                "SELECT * FROM users WHERE disabled=0 ORDER BY id LIMIT 8")] if n else []}


@router.post("/api/setup")
def setup(body: SetupIn, request: Request, response: Response):
    if setup_done():
        raise HTTPException(409, "Haus-KI ist bereits eingerichtet.")
    if not config.setup_code or not security.same(body.code.strip(), config.setup_code):
        raise HTTPException(403, "Der Einrichtungscode stimmt nicht. Er steht am Ende der Ausgabe des Installationsskripts.")
    if len(body.password) < 12:
        raise HTTPException(400, "Das Passwort für den Notfall-Zugang braucht mindestens 12 Zeichen.")
    name = body.name.strip() or "Administrator"
    pre = db.row("SELECT * FROM users WHERE lower(name)=lower(?)", (name,))
    if pre:  # vom Installationsskript vorab angelegt
        db.run("UPDATE users SET role='admin', pw_hash=? WHERE id=?", (security.hash_password(body.password), pre["id"]))
        uid = pre["id"]
    else:
        uid = users.create(name, "admin", password=body.password)
    db.kv_set("setup_done", True)
    user = users.get(uid)
    audit(user["name"], "System", "Ersteinrichtung abgeschlossen, Notfall-Zugang angelegt")
    start_session(response, request, user, "Ersteinrichtung")
    return {"ok": True}


# ---------------------------------------------------------------- Notfall-Zugang
class EmergencyIn(BaseModel):
    user_id: int
    password: str


@router.post("/auth/emergency")
def emergency(body: EmergencyIn, request: Request, response: Response):
    user = users.get(body.user_id)
    generic = HTTPException(401, "Name oder Passwort stimmt nicht.")
    if not user or user["disabled"] or user["role"] != "admin":
        security.verify_password(body.password, None)
        raise generic
    if user["locked_until"] > db.now():
        mins = int((user["locked_until"] - db.now()) / 60) + 1
        raise HTTPException(429, f"Zu viele Fehlversuche. Versuche es in {mins} Minuten erneut.")
    if not security.verify_password(body.password, user["pw_hash"]):
        failed = user["failed_logins"] + 1
        lock = db.now() + settings.get("login.lock_minutes") * 60 if failed >= settings.get("login.max_failed") else 0
        db.run("UPDATE users SET failed_logins=?, locked_until=? WHERE id=?", (failed if not lock else 0, lock, user["id"]))
        audit(user["name"], "Anmeldung", "Notfall-Zugang: falsches Passwort" + (", Konto vorübergehend gesperrt" if lock else ""))
        raise generic
    start_session(response, request, user, "Notfall-Zugang")
    return {"ok": True}


# ---------------------------------------------------------------- Microsoft Entra ID
def sso_ready() -> bool:
    return bool(settings.get("ms.enabled") and settings.get("ms.tenant_id") and settings.get("ms.client_id")
                and settings.get("ms.client_secret"))


def graph_scopes() -> list[str]:
    s = ["User.Read"]
    if settings.get("ms.mail"):
        s.append("Mail.ReadWrite" if settings.get("ms.mail_drafts") else "Mail.Read")
    if settings.get("ms.calendar") or settings.get("ms.cal_check"):
        s.append("Calendars.Read.Shared" if settings.get("ms.cal_check") else "Calendars.Read")
    if settings.get("ms.files"):
        s += ["Files.Read.All", "Sites.Read.All"]
    if settings.get("ms.todo"):
        s.append("Tasks.ReadWrite")
    return s


def _authority(tenant: str | None = None) -> str:
    return f"https://login.microsoftonline.com/{tenant or settings.get('ms.tenant_id')}/oauth2/v2.0"


def _pkce() -> tuple[str, str]:
    verifier = security.token(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


def authorize_url(purpose: str, scopes: list[str], tenant: str | None = None, prompt: str = "") -> str:
    state, nonce = security.token(16), security.token(16)
    verifier, challenge = _pkce()
    db.kv_set(f"oidc:{state}", {"v": verifier, "n": nonce, "p": purpose, "t": time.time(), "tenant": tenant})
    params = {"client_id": settings.get("ms.client_id"), "response_type": "code",
              "redirect_uri": config.base_url + "/auth/callback", "response_mode": "query",
              "scope": " ".join(scopes), "state": state, "nonce": nonce,
              "code_challenge": challenge, "code_challenge_method": "S256"}
    if prompt:
        params["prompt"] = prompt
    return _authority(tenant) + "/authorize?" + urlencode(params)


@router.get("/auth/login")
def login(prompt: str = ""):
    if not sso_ready():
        return RedirectResponse("/?fehler=sso")
    scopes = ["openid", "profile", "email", "offline_access"] + graph_scopes()
    return RedirectResponse(authorize_url("login", scopes, prompt=prompt))


async def exchange(code: str, verifier: str, tenant: str | None = None) -> dict:
    data = {"client_id": settings.get("ms.client_id"), "client_secret": settings.get("ms.client_secret"),
            "grant_type": "authorization_code", "code": code, "code_verifier": verifier,
            "redirect_uri": config.base_url + "/auth/callback"}
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.post(_authority(tenant) + "/token", data=data)
    if r.status_code != 200:
        raise HTTPException(400, "Microsoft hat die Anmeldung abgelehnt: " + r.json().get("error_description", r.text)[:200])
    return r.json()


def validate_id_token(id_token: str, nonce: str) -> dict:
    tenant = settings.get("ms.tenant_id")
    if tenant not in _jwks:
        _jwks[tenant] = jwt.PyJWKClient(f"https://login.microsoftonline.com/{tenant}/discovery/v2.0/keys")
    key = _jwks[tenant].get_signing_key_from_jwt(id_token)
    claims = jwt.decode(id_token, key.key, algorithms=["RS256"], audience=settings.get("ms.client_id"),
                        issuer=f"https://login.microsoftonline.com/{tenant}/v2.0")
    if claims.get("nonce") != nonce:
        raise HTTPException(400, "Ungültige Anmeldung (nonce).")
    return claims


def store_tokens(user_id: int, audience: str, tok: dict) -> None:
    db.run("INSERT INTO ms_tokens(user_id,audience,refresh,access,expires) VALUES(?,?,?,?,?) "
           "ON CONFLICT(user_id,audience) DO UPDATE SET refresh=COALESCE(excluded.refresh, refresh), "
           "access=excluded.access, expires=excluded.expires",
           (user_id, audience, security.encrypt(tok.get("refresh_token")), security.encrypt(tok.get("access_token")),
            db.now() + int(tok.get("expires_in", 3600)) - 60))


@router.get("/auth/callback")
async def callback(request: Request, code: str = "", state: str = "", error: str = "", error_description: str = ""):
    if error:
        return RedirectResponse("/?fehler=" + ("abgebrochen" if error == "access_denied" else "microsoft"))
    st = db.kv_get(f"oidc:{state}")
    db.run("DELETE FROM kv WHERE key=?", (f"oidc:{state}",))
    if not st or time.time() - st["t"] > 600:
        return RedirectResponse("/?fehler=abgelaufen")
    tok = await exchange(code, st["v"], st.get("tenant"))

    if st["p"].startswith("outlookcom:"):
        account_id = int(st["p"].split(":")[1])
        acc = db.row("SELECT * FROM accounts WHERE id=?", (account_id,))
        if acc:
            store_tokens(acc["user_id"], f"outlookcom:{account_id}", tok)
            db.run("UPDATE accounts SET secret=? WHERE id=?", (security.encrypt("oauth"), account_id))
        return RedirectResponse("/#konten")

    claims = validate_id_token(tok["id_token"], st["n"])
    roles = claims.get("roles", [])
    role = "admin" if ROLE_ADMIN in roles else "member" if ROLE_MEMBER in roles else None
    oid = claims.get("oid")
    name = claims.get("name") or claims.get("preferred_username", "")
    email = claims.get("email") or claims.get("preferred_username", "")
    if not role:
        audit(email or name, "Anmeldung", "Microsoft-Konto ohne Haus-KI-Rolle abgewiesen")
        return RedirectResponse("/?fehler=keine-rolle&konto=" + email)
    user = db.row("SELECT * FROM users WHERE oid=?", (oid,))
    if not user:
        # Ein vorhandenes Konto ohne Microsoft-Verknüpfung (z. B. Notfall-Admin) per E-Mail verknüpfen.
        user = db.row("SELECT * FROM users WHERE oid IS NULL AND lower(email)=lower(?)", (email,)) if email else None
        if user:
            db.run("UPDATE users SET oid=? WHERE id=?", (oid, user["id"]))
        else:
            uid = users.create(name.split(" ")[0] if name else email, role, email=email, oid=oid)
            user = users.get(uid)
            audit(user["name"], "Anmeldung", f"Konto beim ersten Microsoft-Login angelegt ({role})")
    if user["disabled"]:
        return RedirectResponse("/?fehler=gesperrt")
    if user["role"] != role:
        db.run("UPDATE users SET role=? WHERE id=?", (role, user["id"]))
        audit(user["name"], "Einstellung", f"Rolle aus Entra übernommen: {role}")
    db.run("UPDATE users SET email=? WHERE id=?", (email, user["id"]))
    store_tokens(user["id"], "graph", tok)
    resp = RedirectResponse("/")
    start_session(resp, request, users.get(user["id"]), "Microsoft")
    return resp


async def access_token(user_id: int, audience: str = "graph") -> str:
    """Gültiges Zugriffstoken, bei Bedarf über das Refresh-Token erneuert."""
    t = db.row("SELECT * FROM ms_tokens WHERE user_id=? AND audience=?", (user_id, audience))
    if not t:
        raise PermissionError("Microsoft ist für dieses Konto nicht verbunden.")
    if t["expires"] > db.now() and t["access"]:
        return security.decrypt(t["access"])
    refresh = security.decrypt(t["refresh"])
    if not refresh:
        raise PermissionError("Die Microsoft-Verbindung ist abgelaufen. Bitte neu anmelden.")
    tenant = "consumers" if audience.startswith("outlookcom:") else None
    data = {"client_id": settings.get("ms.client_id"), "client_secret": settings.get("ms.client_secret"),
            "grant_type": "refresh_token", "refresh_token": refresh}
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.post(_authority(tenant) + "/token", data=data)
    if r.status_code != 200:
        db.run("UPDATE ms_tokens SET access=NULL, expires=0 WHERE user_id=? AND audience=?", (user_id, audience))
        raise PermissionError("Die Microsoft-Verbindung ist abgelaufen. Bitte neu anmelden.")
    store_tokens(user_id, audience, r.json())
    return r.json()["access_token"]
