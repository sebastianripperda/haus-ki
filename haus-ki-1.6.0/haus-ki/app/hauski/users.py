"""Benutzer, Rollen und Freigaben."""
from . import db, security

COLORS = ["#3f4a5a", "#7c5cc4", "#1a7f37", "#b45309", "#c2417a", "#1f6fb2", "#0f766e"]
OLD_COLORS = ["#9db6c7", "#c4b5fd", "#86efac", "#fcd34d", "#f9a8d4", "#93c5fd", "#fdba74"]

ADMIN_PERMS = {"paperless": True, "jellyfin": True, "knx": True, "knx_rooms": ["*"], "m365": True,
               "mail": True, "web": True, "memory": True, "voice": True, "auto_actions": True, "learn": False, "jellyfin_user": ""}
MEMBER_PERMS = {"paperless": False, "jellyfin": True, "knx": True, "knx_rooms": [], "m365": True,
                "mail": True, "web": True, "memory": True, "voice": True, "auto_actions": True, "learn": False, "jellyfin_user": ""}


# Anmeldearten pro Person: nur Microsoft 365, nur lokal (Haus-KI-Passwort) oder beides.
LOGIN_MODES = ("m365", "local", "both")
LOGIN_LABELS = {"m365": "Microsoft 365", "local": "Lokal", "both": "Microsoft 365 und lokal"}


def login_mode(user: dict) -> str:
    m = user.get("login") or "m365"
    return m if m in LOGIN_MODES else "m365"


def allows_m365(user: dict) -> bool:
    return login_mode(user) in ("m365", "both")


def allows_local(user: dict) -> bool:
    return login_mode(user) in ("local", "both")


def check_local_password(password: str) -> None:
    """Mindestlänge für lokale Passwörter (Administration › Benutzer › Für alle Benutzer)."""
    from . import settings
    n = int(settings.get("login.local_min_length") or 8)
    if len(password or "") < n:
        raise ValueError(f"Das Passwort braucht mindestens {n} Zeichen.")


def set_local_password(user_id: int, password: str | None) -> None:
    db.run("UPDATE users SET local_pw=?, failed_logins=0, locked_until=0 WHERE id=?",
           (security.hash_password(password) if password else None, user_id))


def perms(user: dict) -> dict:
    base = dict(ADMIN_PERMS if user["role"] == "admin" else MEMBER_PERMS)
    base.update(db.jload(user.get("perms"), {}) or {})
    return base


def is_admin(user: dict) -> bool:
    return user["role"] == "admin"


def public(user: dict, full: bool = False) -> dict:
    out = {"id": user["id"], "name": user["name"], "role": user["role"], "color": user["color"],
           "initial": (user["name"] or "?")[:1].upper()}
    if full:
        out.update({"email": user["email"], "oid": user["oid"], "perms": perms(user),
                    "prefs": db.jload(user.get("prefs"), {}) or {}, "disabled": bool(user["disabled"]),
                    "has_password": bool(user["pw_hash"]),
                    "login": login_mode(user), "has_local_password": bool(user.get("local_pw")),
                    "paperless_token": bool(personal_secret(user["id"], "paperless_token"))})
    return out


def get(user_id: int) -> dict | None:
    return db.row("SELECT * FROM users WHERE id=?", (user_id,))


def create(name: str, role: str, email: str = "", oid: str | None = None, password: str | None = None,
           login: str = "m365", local_password: str | None = None) -> int:
    n = db.scalar("SELECT COUNT(*) FROM users") or 0
    return db.run(
        "INSERT INTO users(name,email,oid,role,color,pw_hash,login,local_pw,created) VALUES(?,?,?,?,?,?,?,?,?)",
        (name, email, oid, role, COLORS[n % len(COLORS)],
         security.hash_password(password) if password else None,
         login if login in LOGIN_MODES else "m365",
         security.hash_password(local_password) if local_password else None, db.now()))


def personal_secret(user_id: int, kind: str) -> str:
    r = db.row("SELECT secret FROM accounts WHERE user_id=? AND kind=?", (user_id, kind))
    return security.decrypt(r["secret"]) if r else ""


def set_personal_secret(user_id: int, kind: str, value: str) -> None:
    db.run("DELETE FROM accounts WHERE user_id=? AND kind=?", (user_id, kind))
    if value:
        db.run("INSERT INTO accounts(user_id,kind,address,secret,created) VALUES(?,?,?,?,?)",
               (user_id, kind, "", security.encrypt(value), db.now()))


def prefs(user: dict) -> dict:
    p = {"notify_done": True, "suggestions": True, "notify_deadlines": True, "notify_calendar": True,
         "notify_schedules": True, "notify_mail": True, "voice": "", "voice_speed": "normal", "voice_auto_send": False, "voice_read_talk": True,
         "simple_ui": user.get("role") != "admin",  # Mitglieder starten mit der einfachen Ansicht
         "auto_actions": [], "onboarded": False}
    p.update(db.jload(user.get("prefs"), {}) or {})
    return p
