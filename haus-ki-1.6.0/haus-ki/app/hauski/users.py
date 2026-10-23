"""Benutzer, Rollen und Freigaben."""
from . import db, security

COLORS = ["#3f4a5a", "#7c5cc4", "#1a7f37", "#b45309", "#c2417a", "#1f6fb2", "#0f766e"]
OLD_COLORS = ["#9db6c7", "#c4b5fd", "#86efac", "#fcd34d", "#f9a8d4", "#93c5fd", "#fdba74"]

ADMIN_PERMS = {"paperless": True, "jellyfin": True, "knx": True, "knx_rooms": ["*"], "m365": True,
               "mail": True, "web": True, "memory": True, "voice": True, "auto_actions": True, "learn": False, "jellyfin_user": ""}
MEMBER_PERMS = {"paperless": False, "jellyfin": True, "knx": True, "knx_rooms": [], "m365": True,
                "mail": True, "web": True, "memory": True, "voice": True, "auto_actions": True, "learn": False, "jellyfin_user": ""}


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
                    "paperless_token": bool(personal_secret(user["id"], "paperless_token"))})
    return out


def get(user_id: int) -> dict | None:
    return db.row("SELECT * FROM users WHERE id=?", (user_id,))


def create(name: str, role: str, email: str = "", oid: str | None = None, password: str | None = None) -> int:
    n = db.scalar("SELECT COUNT(*) FROM users") or 0
    return db.run(
        "INSERT INTO users(name,email,oid,role,color,pw_hash,created) VALUES(?,?,?,?,?,?,?)",
        (name, email, oid, role, COLORS[n % len(COLORS)],
         security.hash_password(password) if password else None, db.now()))


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
         "notify_schedules": True, "voice": "", "voice_speed": "normal", "voice_auto_send": False, "voice_read_talk": True,
         "simple_ui": user.get("role") != "admin",  # Mitglieder starten mit der einfachen Ansicht
         "auto_actions": [], "onboarded": False}
    p.update(db.jload(user.get("prefs"), {}) or {})
    return p
