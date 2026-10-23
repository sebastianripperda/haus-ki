"""Endpunkte für alle angemeldeten Personen."""
import asyncio
import json
import time

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from .. import auth, chat, db, ollama, scheduler, settings, system, users
from ..auth import current_user
from ..events import audit, hub
from ..jobs import queue
from ..tools import knx, mailbox

router = APIRouter(prefix="/api")


# ------------------------------------------------------------ Ich
@router.get("/me")
def me(user=Depends(current_user)):
    out = users.public(user, full=True)
    out["prefs"] = users.prefs(user)
    out["features"] = {
        "paperless": bool(settings.get("paperless.enabled") and out["perms"]["paperless"]),
        "paperless_upload": bool(settings.get("paperless.enabled") and settings.get("paperless.upload") and out["perms"]["paperless"]),
        "jellyfin": bool(settings.get("jellyfin.enabled") and out["perms"]["jellyfin"]),
        "knx": bool(settings.get("knx.enabled") and out["perms"]["knx"]),
        "m365": bool(settings.get("ms.enabled") and out["perms"]["m365"]),
        "mail": bool(out["perms"]["mail"] and mailbox.accounts(user["id"])),
        "web": bool(settings.get("web.enabled") and out["perms"]["web"]),
        "memory": bool(out["perms"]["memory"]),
        "admin_read": bool(settings.get("chat.admin_read")),
        "voice": bool(settings.get("voice.enabled") and out["perms"].get("voice", True)),
    }
    labels = {"knx_light": "Licht schalten und dimmen", "knx_blind": "Rollläden und Jalousien", "knx_climate": "Heizung: Solltemperatur",
              "jellyfin_play": "Filme und Musik abspielen", "todo_add": "Einträge in To Do anlegen"}
    need = {"knx_light": "knx", "knx_blind": "knx", "knx_climate": "knx", "jellyfin_play": "jellyfin", "todo_add": "m365"}
    out["auto_allowed"] = [{"id": k, "label": labels.get(k, k)} for k in settings.get("actions.auto_allowed")
                           if out["features"].get(need.get(k, ""), False)] if out["perms"].get("auto_actions", True) else []
    out["voice"] = {"vad": settings.get("voice.vad"), "talk": settings.get("voice.talk"), "confirm": settings.get("voice.confirm"),
                    "default_voice": settings.get("voice.default_voice"), "model": settings.get("voice.stt_model")}
    out["models"] = chat.allowed_models(user)
    out["default_model"] = settings.get("ollama.default_model")
    out["helper_model"] = settings.get("ollama.helper_model")
    out["num_ctx"] = settings.get("req.num_ctx")
    out["retention_days"] = settings.get("chat.retention_days")
    out["mail_allowed"] = {k: settings.get(f"mail.allow_{k}") for k in ("gmx", "gmail", "outlookcom")}
    out["family"] = [users.public(u) for u in db.rows("SELECT * FROM users WHERE disabled=0 ORDER BY id")]
    return out


@router.put("/me/prefs")
def set_prefs(body: dict, user=Depends(current_user)):
    p = users.prefs(user)
    for k, v in body.items():
        if k not in p:
            continue
        if k == "voice":
            p[k] = str(v)[:60]
        elif k == "voice_speed":
            p[k] = v if v in ("slow", "normal", "fast") else "normal"
        elif k == "auto_actions":
            allowed = settings.get("actions.auto_allowed")
            p[k] = [x for x in (v if isinstance(v, list) else []) if x in allowed]
        else:
            p[k] = bool(v)
    db.run("UPDATE users SET prefs=? WHERE id=?", (db.jdump(p), user["id"]))
    return p


# ------------------------------------------------------------ Gedächtnis
class MemIn(BaseModel):
    text: str


@router.get("/memory")
def memory_list(user=Depends(current_user)):
    return db.rows("SELECT id, text, enabled, created FROM memory WHERE user_id=? ORDER BY id DESC", (user["id"],))


@router.post("/memory")
def memory_add(body: MemIn, user=Depends(current_user)):
    if not body.text.strip():
        raise HTTPException(400, "Bitte einen Text eingeben.")
    return {"id": db.run("INSERT INTO memory(user_id,text,created) VALUES(?,?,?)", (user["id"], body.text.strip()[:300], db.now()))}


@router.patch("/memory/{mid}")
def memory_toggle(mid: int, body: dict, user=Depends(current_user)):
    db.run("UPDATE memory SET enabled=? WHERE id=? AND user_id=?", (1 if body.get("enabled") else 0, mid, user["id"]))
    return {"ok": True}


@router.delete("/memory/{mid}")
def memory_delete(mid: int, user=Depends(current_user)):
    db.run("DELETE FROM memory WHERE id=? AND user_id=?", (mid, user["id"]))
    return {"ok": True}


# ------------------------------------------------------------ Meine Konten
class AccIn(BaseModel):
    kind: str
    address: str
    password: str = ""


@router.get("/accounts")
def accounts(user=Depends(current_user)):
    out = [{"id": a["id"], "kind": a["kind"], "address": a["address"], "drafts": bool(a["drafts"]),
            "connected": bool(a["secret"])} for a in mailbox.accounts(user["id"])]
    ms = db.row("SELECT expires FROM ms_tokens WHERE user_id=? AND audience='graph'", (user["id"],))
    return {"accounts": out, "m365": {"connected": bool(ms), "email": user["email"]}}


@router.post("/accounts")
async def account_add(body: AccIn, user=Depends(current_user)):
    if body.kind not in ("gmx", "gmail", "outlookcom") or not mailbox.allowed(body.kind):
        raise HTTPException(400, "Dieser Anbieter ist nicht freigegeben.")
    if body.kind != "outlookcom":
        acc = {"kind": body.kind, "address": body.address.strip(), "secret": None}
        from .. import security
        acc["secret"] = security.encrypt(body.password.replace(" ", ""))
        try:
            await mailbox.test_login(acc)
        except Exception as e:  # noqa: BLE001
            raise HTTPException(400, f"Anmeldung bei {mailbox.LABEL[body.kind]} fehlgeschlagen: {e}. "
                                     "Prüfe Adresse und App-Passwort und ob IMAP im Postfach eingeschaltet ist.")
        aid = db.run("INSERT INTO accounts(user_id,kind,address,secret,created) VALUES(?,?,?,?,?)",
                     (user["id"], body.kind, acc["address"], acc["secret"], db.now()))
        audit(user["name"], "Einstellung", f"Postfach {mailbox.LABEL[body.kind]} verbunden")
        return {"id": aid}
    aid = db.run("INSERT INTO accounts(user_id,kind,address,created) VALUES(?,?,?,?)",
                 (user["id"], "outlookcom", body.address.strip(), db.now()))
    url = auth.authorize_url(f"outlookcom:{aid}", ["offline_access", "User.Read", "Mail.ReadWrite"], tenant="consumers",
                             prompt="select_account")
    return {"id": aid, "redirect": url}


@router.patch("/accounts/{aid}")
def account_update(aid: int, body: dict, user=Depends(current_user)):
    db.run("UPDATE accounts SET drafts=? WHERE id=? AND user_id=?", (1 if body.get("drafts") else 0, aid, user["id"]))
    return {"ok": True}


@router.delete("/accounts/{aid}")
def account_delete(aid: int, user=Depends(current_user)):
    db.run("DELETE FROM accounts WHERE id=? AND user_id=? AND kind IN ('gmx','gmail','outlookcom')", (aid, user["id"]))
    db.run("DELETE FROM ms_tokens WHERE user_id=? AND audience=?", (user["id"], f"outlookcom:{aid}"))
    audit(user["name"], "Einstellung", "Postfach entfernt")
    return {"ok": True}


# ------------------------------------------------------------ Geplante Prompts
class SchedIn(BaseModel):
    name: str
    prompt: str
    freq: str = "weekly"
    day: str = "Mo"
    time: str = "07:00"
    deliver: str = "notify"
    options: dict = {}


@router.get("/schedules")
def schedules(user=Depends(current_user)):
    out = []
    for s in db.rows("SELECT * FROM schedules WHERE user_id=? ORDER BY id", (user["id"],)):
        import datetime as dt
        nxt = scheduler.next_run(s, dt.datetime.fromtimestamp(max(s["last_run"], s["created"], time.time())))
        out.append({**s, "options": db.jload(s["options"], {}), "next": nxt.isoformat() if nxt and s["enabled"] else None})
    return out


@router.post("/schedules")
def schedule_add(body: SchedIn, user=Depends(current_user)):
    n = db.scalar("SELECT COUNT(*) FROM schedules WHERE user_id=?", (user["id"],)) or 0
    if n >= int(settings.get("schedules.max_per_user")):
        raise HTTPException(400, f"Höchstens {settings.get('schedules.max_per_user')} geplante Prompts pro Person.")
    if body.freq not in ("once", "daily", "weekly", "monthly") or not body.prompt.strip():
        raise HTTPException(400, "Bitte Prompt und Häufigkeit angeben.")
    sid = db.run("INSERT INTO schedules(user_id,name,prompt,options,freq,day,time,deliver,created) VALUES(?,?,?,?,?,?,?,?,?)",
                 (user["id"], body.name.strip()[:80] or "Geplanter Prompt", body.prompt, db.jdump(body.options),
                  body.freq, body.day, body.time, body.deliver, time.time()))
    return {"id": sid}


@router.patch("/schedules/{sid}")
def schedule_update(sid: int, body: dict, user=Depends(current_user)):
    if "enabled" in body:
        db.run("UPDATE schedules SET enabled=? WHERE id=? AND user_id=?", (1 if body["enabled"] else 0, sid, user["id"]))
    return {"ok": True}


@router.post("/schedules/{sid}/run")
async def schedule_run(sid: int, user=Depends(current_user)):
    s = db.row("SELECT * FROM schedules WHERE id=? AND user_id=?", (sid, user["id"]))
    if not s:
        raise HTTPException(404)
    asyncio.create_task(chat.run_schedule(s))
    return {"ok": True}


@router.delete("/schedules/{sid}")
def schedule_delete(sid: int, user=Depends(current_user)):
    db.run("DELETE FROM schedules WHERE id=? AND user_id=?", (sid, user["id"]))
    return {"ok": True}


# ------------------------------------------------------------ Projekte und Vorlagen
@router.get("/projects")
def projects(user=Depends(current_user)):
    return [{**p, "docs": db.jload(p["docs"], [])} for p in db.rows("SELECT * FROM projects WHERE user_id=? ORDER BY title", (user["id"],))]


@router.post("/projects")
def project_add(body: dict, user=Depends(current_user)):
    return {"id": db.run("INSERT INTO projects(user_id,title,description,created) VALUES(?,?,?,?)",
                         (user["id"], (body.get("title") or "Neues Projekt")[:80], body.get("description", ""), db.now()))}


@router.put("/projects/{pid}")
def project_update(pid: int, body: dict, user=Depends(current_user)):
    fields = {k: body[k] for k in ("title", "description", "notes", "system") if k in body}
    if "docs" in body:
        fields["docs"] = db.jdump(body["docs"])
    for k, v in fields.items():
        db.run(f"UPDATE projects SET {k}=? WHERE id=? AND user_id=?", (v, pid, user["id"]))
    return {"ok": True}


@router.delete("/projects/{pid}")
def project_delete(pid: int, user=Depends(current_user)):
    db.run("DELETE FROM projects WHERE id=? AND user_id=?", (pid, user["id"]))
    return {"ok": True}


@router.get("/templates")
def templates(user=Depends(current_user)):
    return db.rows("SELECT * FROM templates WHERE owner_id=? OR owner_id IS NULL ORDER BY owner_id IS NULL, title", (user["id"],))


@router.post("/templates")
def template_add(body: dict, user=Depends(current_user)):
    family = bool(body.get("family")) and users.is_admin(user)
    tid = db.run("INSERT INTO templates(owner_id,title,prompt,system,model,json_mode,created) VALUES(?,?,?,?,?,?,?)",
                 (None if family else user["id"], (body.get("title") or "Vorlage")[:80], body.get("prompt", ""),
                  body.get("system", ""), body.get("model", ""), 1 if body.get("json_mode") else 0, db.now()))
    return {"id": tid}


@router.put("/templates/{tid}")
def template_update(tid: int, body: dict, user=Depends(current_user)):
    t = db.row("SELECT * FROM templates WHERE id=?", (tid,))
    if not t or (t["owner_id"] != user["id"] and not (t["owner_id"] is None and users.is_admin(user))):
        raise HTTPException(403)
    for k in ("title", "prompt", "system", "model"):
        if k in body:
            db.run(f"UPDATE templates SET {k}=? WHERE id=?", (body[k], tid))
    return {"ok": True}


@router.delete("/templates/{tid}")
def template_delete(tid: int, user=Depends(current_user)):
    t = db.row("SELECT * FROM templates WHERE id=?", (tid,))
    if t and (t["owner_id"] == user["id"] or (t["owner_id"] is None and users.is_admin(user))):
        db.run("DELETE FROM templates WHERE id=?", (tid,))
    return {"ok": True}


# ------------------------------------------------------------ Startseite
@router.get("/start")
def start(user=Depends(current_user)):
    ins = db.rows("SELECT * FROM insights WHERE user_id=? AND done=0 ORDER BY created DESC", (user["id"],))
    out = {"suggestions": [], "deadlines": [], "calendar": []}
    seen = set()
    for i in ins:
        d = db.jload(i["data"], {}) | {"id": i["id"]}
        if i["kind"] == "suggestion":
            out["suggestions"].append(d)
        elif i["kind"] == "deadline" and i["ref"] not in seen:
            seen.add(i["ref"])
            out["deadlines"].append(d)
        elif i["kind"] == "calendar":
            out["calendar"].append(d)
    out["deadlines"].sort(key=lambda d: d.get("due", ""))
    out["calendar"].sort(key=lambda d: d.get("when", ""))
    return out


@router.post("/insights/{iid}/done")
def insight_done(iid: int, user=Depends(current_user)):
    i = db.row("SELECT * FROM insights WHERE id=? AND user_id=?", (iid, user["id"]))
    if i and i["kind"] == "deadline":
        db.run("UPDATE insights SET done=1 WHERE ref=? AND user_id=? AND kind='deadline'", (i["ref"], user["id"]))
    else:
        db.run("UPDATE insights SET done=1 WHERE id=? AND user_id=?", (iid, user["id"]))
    return {"ok": True}


# ------------------------------------------------------------ Status für die Kopfzeile
@router.get("/status")
async def status(user=Depends(current_user)):
    out = {"ollama": {"ok": scheduler.health["ok"], "since": scheduler.health["since"], "version": scheduler.health["version"]},
           "queue": queue.status(), "vm": None, "loaded": []}
    try:
        ps = await ollama.get("/api/ps", timeout=3)
        out["loaded"] = [{"name": m["name"], "size": m.get("size", 0), "until": m.get("expires_at", "")} for m in ps.get("models", [])]
    except Exception:  # noqa: BLE001
        pass
    if settings.get("proxmox.url"):
        try:
            out["vm"] = await system.vm_status()
        except Exception as e:  # noqa: BLE001
            out["vm"] = {"error": str(e)[:120]}
    names = {u["id"]: u["name"] for u in db.rows("SELECT id, name FROM users")}
    for r in out["queue"]["running"]:
        r["user"] = names.get(r.pop("user_id"), "System")
    out["unread"] = db.scalar("SELECT COUNT(*) FROM notifications WHERE user_id=? AND read=0", (user["id"],))
    return out


@router.get("/notifications")
def notifications(user=Depends(current_user)):
    rows = db.rows("SELECT * FROM notifications WHERE user_id=? ORDER BY id DESC LIMIT 30", (user["id"],))
    db.run("UPDATE notifications SET read=1 WHERE user_id=?", (user["id"],))
    return rows


@router.get("/events")
async def events(request: Request, user=Depends(current_user)):
    q = hub.subscribe(user["id"])

    async def gen():
        try:
            yield "retry: 5000\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    ev = await asyncio.wait_for(q.get(), timeout=25)
                    yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
                except asyncio.TimeoutError:
                    yield ": ping\n\n"
        finally:
            hub.unsubscribe(user["id"], q)
    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ------------------------------------------------------------ Haus (KNX-Schnellsteuerung)
@router.get("/knx")
async def knx_overview(user=Depends(current_user)):
    if not settings.get("knx.enabled"):
        return {"enabled": False}
    gas = knx.allowed_gas(user)
    rooms: dict[str, list] = {}
    values = await asyncio.gather(*(knx.read(g["address"], max_age=120) for g in gas[:60]), return_exceptions=True)
    for g, v in zip(gas[:60], values):
        val = None if isinstance(v, Exception) else v
        rooms.setdefault(g["room"] or "Ohne Raum", []).append({
            "address": g["address"], "name": g["name"], "dpt": g["dpt"], "value": val, "text": knx.human(val, g["dpt"]),
            "writable": g["permission"] == "write" and not g["locked"], "locked": bool(g["locked"])})
    error = next((str(v) for v in values if isinstance(v, Exception)), "")
    scenes = [s["name"] for s in settings.get("knx.scenes") or []] if users.is_admin(user) else []
    return {"enabled": True, "rooms": [{"name": k, "items": v} for k, v in rooms.items()], "scenes": scenes, "error": error[:200]}


@router.post("/knx/write")
async def knx_write(body: dict, user=Depends(current_user)):
    if not any(g["address"] == body.get("address") for g in knx.allowed_gas(user, "write")):
        raise HTTPException(403, "Diese Adresse darfst du nicht schalten.")
    try:
        await knx.write(body["address"], body.get("value"))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"Nicht geschaltet: {e}. Es wurde nichts geändert.")
    ga = db.row("SELECT name FROM knx_ga WHERE address=?", (body["address"],))
    audit(user["name"], "Aktion", f"Schnellsteuerung: {ga['name'] if ga else body['address']} = {body.get('value')}")
    return {"ok": True}


@router.post("/knx/scene")
async def knx_scene(body: dict, user=Depends(auth.require_admin)):
    try:
        text = await knx.run_scene(body.get("name", ""))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, str(e))
    audit(user["name"], "Aktion", text)
    return {"result": text}


@router.get("/knx/trip")
async def knx_trip(user=Depends(current_user)):
    return await knx.trip_check()


# ------------------------------------------------------------ Push-Benachrichtigungen
@router.get("/push/key")
def push_key(user=Depends(current_user)):
    from .. import push
    return {"key": push.keys()[1], "devices": db.scalar("SELECT COUNT(*) FROM push_subs WHERE user_id=?", (user["id"],))}


@router.post("/push/subscribe")
def push_subscribe(body: dict, request: Request, user=Depends(current_user)):
    from .. import push
    try:
        push.subscribe(user["id"], body, request.headers.get("user-agent", ""))
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"ok": True}


@router.post("/push/unsubscribe")
def push_unsubscribe(body: dict, user=Depends(current_user)):
    from .. import push
    push.unsubscribe(user["id"], body.get("endpoint", ""))
    return {"ok": True}


@router.post("/push/test")
async def push_test(user=Depends(current_user)):
    from .. import push
    n = await push.send(user["id"], "Haus-KI", "So sehen Benachrichtigungen von Haus-KI aus.", "/")
    if not n:
        raise HTTPException(400, "Auf keinem Gerät sind Benachrichtigungen eingeschaltet.")
    return {"sent": n}


# ------------------------------------------------------------ Gemeinsames Familienwissen
@router.get("/family")
def family_list(user=Depends(current_user)):
    rows = db.rows("SELECT f.*, u.name AS author FROM family_facts f LEFT JOIN users u ON u.id=f.created_by ORDER BY f.id DESC")
    for r in rows:
        r["mine"] = r["created_by"] == user["id"]
        r["can_edit"] = r["mine"] or users.is_admin(user)
    return rows


@router.post("/family")
def family_add(body: dict, user=Depends(current_user)):
    text = (body.get("text") or "").strip()[:300]
    if not text:
        raise HTTPException(400, "Bitte einen Text eingeben.")
    fid = db.run("INSERT INTO family_facts(text,created_by,created) VALUES(?,?,?)", (text, user["id"], db.now()))
    audit(user["name"], "Einstellung", f"Familienwissen ergänzt: {text}")
    return {"id": fid}


def _own_fact(fid: int, user: dict) -> dict:
    f = db.row("SELECT * FROM family_facts WHERE id=?", (fid,))
    if not f:
        raise HTTPException(404)
    if f["created_by"] != user["id"] and not users.is_admin(user):
        raise HTTPException(403, "Nur wer den Eintrag angelegt hat oder ein Administrator kann ihn ändern.")
    return f


@router.patch("/family/{fid}")
def family_update(fid: int, body: dict, user=Depends(current_user)):
    _own_fact(fid, user)
    if "enabled" in body:
        db.run("UPDATE family_facts SET enabled=? WHERE id=?", (1 if body["enabled"] else 0, fid))
    if body.get("text"):
        db.run("UPDATE family_facts SET text=? WHERE id=?", (str(body["text"])[:300], fid))
    return {"ok": True}


@router.delete("/family/{fid}")
def family_delete(fid: int, user=Depends(current_user)):
    f = _own_fact(fid, user)
    db.run("DELETE FROM family_facts WHERE id=?", (fid,))
    audit(user["name"], "Einstellung", f"Familienwissen gelöscht: {f['text']}")
    return {"ok": True}
