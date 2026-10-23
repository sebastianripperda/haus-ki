"""Administration: nur für Personen mit der Rolle „Haus-KI Admins“."""
import asyncio
import csv
import io
import json
import time

import httpx
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, StreamingResponse

from .. import __version__, db, ollama, scheduler, settings, system, users
from ..auth import require_admin
from ..config import config
from ..events import audit
from ..jobs import queue
from ..tools import jellyfin, knx, paperless

router = APIRouter(prefix="/api/admin")


# ------------------------------------------------------------ Einstellungen
@router.get("/settings")
def get_settings(user=Depends(require_admin)):
    return {"values": settings.all_public(), "secrets": sorted(settings.SECRETS), "version": __version__,
            "base_url": config.base_url}


@router.put("/settings")
async def put_settings(body: dict, user=Depends(require_admin)):
    changed = settings.set_many(body)
    for k in changed:
        audit(user["name"], "Einstellung", f"{k} geändert")
    if any(k.startswith("knx.") for k in changed):
        await knx.stop()
    return {"changed": changed}


@router.post("/test/{what}")
async def test(what: str, user=Depends(require_admin)):
    try:
        if what == "ollama":
            v = await ollama.get("/api/version")
            return {"ok": True, "text": f"Ollama {v.get('version')} erreichbar."}
        if what == "paperless":
            async with paperless.client(None) as c:
                r = await c.get("/api/documents/", params={"page_size": 1})
                r.raise_for_status()
            return {"ok": True, "text": f"Verbunden, {r.json().get('count', 0)} Dokumente."}
        if what == "jellyfin":
            us = await jellyfin.users_list()
            return {"ok": True, "text": f"Verbunden, {len(us)} Jellyfin-Benutzer.", "users": us}
        if what == "knx":
            await knx.stop()
            await knx.connection()
            return {"ok": True, "text": "Verbindung zur KNX-Schnittstelle steht."}
        if what == "ms":
            async with httpx.AsyncClient(timeout=15) as c:
                r = await c.post(f"https://login.microsoftonline.com/{settings.get('ms.tenant_id')}/oauth2/v2.0/token",
                                 data={"client_id": settings.get("ms.client_id"), "client_secret": settings.get("ms.client_secret"),
                                       "grant_type": "client_credentials", "scope": "https://graph.microsoft.com/.default"})
            if r.status_code != 200:
                return {"ok": False, "text": r.json().get("error_description", r.text)[:300]}
            return {"ok": True, "text": "Tenant, Client-ID und Secret sind gültig."}
        if what == "proxmox":
            g = await system.pve_guests()
            return {"ok": True, "text": f"Verbunden, {len(g)} Gäste sichtbar.", "guests": g}
        if what == "agent":
            h = await system.agent("GET", "/health")
            return {"ok": True, "text": f"Agent {h.get('version')} auf {h.get('hostname')} antwortet.", "health": h}
        if what == "web":
            from ..tools import Ctx, web
            r = await web.search(Ctx(user=user, perms={}, sources={"web"}), {"query": "Wetter Deutschland"})
            return {"ok": True, "text": f"Websuche funktioniert, {len(r.cites)} Treffer."}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "text": str(e)[:300] or e.__class__.__name__}
    raise HTTPException(404)


# ------------------------------------------------------------ Übersicht
@router.get("/overview")
async def overview(user=Depends(require_admin)):
    since = time.time() - 30 * 86400
    usage = db.rows("SELECT u.id, u.name, u.color, COUNT(m.id) AS questions FROM users u "
                    "LEFT JOIN chats c ON c.user_id=u.id LEFT JOIN messages m ON m.chat_id=c.id AND m.role='user' AND m.created>? "
                    "WHERE u.disabled=0 GROUP BY u.id ORDER BY questions DESC", (since,))
    fb = db.row("SELECT SUM(value>0) AS up, SUM(value<0) AS down FROM feedback WHERE created>?", (since,)) or {}
    worst = db.rows("SELECT c.title, COUNT(*) AS n FROM feedback f JOIN messages m ON m.id=f.message_id "
                    "JOIN chats c ON c.id=m.chat_id WHERE f.value<0 AND f.created>? GROUP BY c.id ORDER BY n DESC LIMIT 5", (since,))
    errors = db.rows("SELECT ts, text FROM audit WHERE category='System' AND ts>? AND (text LIKE '%nicht%' OR text LIKE '%fehl%') "
                     "ORDER BY ts DESC LIMIT 10", (since,))
    night = db.kv_get("night_last", "")
    runs = db.rows("SELECT task, started, finished, status, detail FROM night_runs WHERE night=? ORDER BY id", (night,))
    warnings = []
    if not settings.get("agent.url"):
        warnings.append("Der Agent im Ollama-Container ist nicht eingerichtet. Server-Einstellungen lassen sich nicht ändern.")
    if not settings.get("ms.enabled"):
        warnings.append("Die Anmeldung über Microsoft ist noch nicht eingerichtet. Nur der Notfall-Zugang funktioniert.")
    if any(r["status"] == "error" for r in runs):
        warnings.append("Mindestens eine Nachtaufgabe ist letzte Nacht fehlgeschlagen.")
    vm = None
    try:
        vm = await system.vm_status() if settings.get("proxmox.url") else None
    except Exception as e:  # noqa: BLE001
        vm = {"error": str(e)[:120]}
    return {"usage": usage, "feedback": {"up": fb.get("up") or 0, "down": fb.get("down") or 0, "worst": worst},
            "errors": errors, "night": {"date": night, "runs": runs}, "warnings": warnings, "vm": vm,
            "ollama": scheduler.health, "queue": queue.status(), "version": __version__}


# ------------------------------------------------------------ Benutzer
@router.get("/users")
def users_list(user=Depends(require_admin)):
    out = []
    for u in db.rows("SELECT * FROM users ORDER BY id"):
        p = users.public(u, full=True)
        p["jellyfin_user"] = p["perms"].get("jellyfin_user", "")
        p["last_seen"] = db.scalar("SELECT MAX(last_seen) FROM sessions WHERE user_id=?", (u["id"],))
        p["ms_connected"] = bool(db.row("SELECT 1 FROM ms_tokens WHERE user_id=? AND audience='graph'", (u["id"],)))
        out.append(p)
    return out


@router.post("/users")
def user_add(body: dict, user=Depends(require_admin)):
    name = (body.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "Bitte einen Namen angeben.")
    uid = users.create(name, "admin" if body.get("role") == "admin" else "member", email=body.get("email", ""))
    audit(user["name"], "Einstellung", f"Benutzer {name} angelegt")
    return {"id": uid}


@router.put("/users/{uid}")
def user_update(uid: int, body: dict, user=Depends(require_admin)):
    u = users.get(uid)
    if not u:
        raise HTTPException(404)
    from .. import security
    if "name" in body:
        db.run("UPDATE users SET name=? WHERE id=?", (str(body["name"])[:40], uid))
    if "email" in body:
        db.run("UPDATE users SET email=? WHERE id=?", (body["email"], uid))
    if "color" in body:
        db.run("UPDATE users SET color=? WHERE id=?", (body["color"], uid))
    if "role" in body and body["role"] in ("admin", "member"):
        if uid == user["id"] and body["role"] != "admin":
            raise HTTPException(400, "Du kannst dir die Administratorrolle nicht selbst entziehen.")
        db.run("UPDATE users SET role=? WHERE id=?", (body["role"], uid))
    if "disabled" in body:
        if uid == user["id"]:
            raise HTTPException(400, "Du kannst dich nicht selbst sperren.")
        db.run("UPDATE users SET disabled=? WHERE id=?", (1 if body["disabled"] else 0, uid))
        if body["disabled"]:
            db.run("DELETE FROM sessions WHERE user_id=?", (uid,))
    if "perms" in body:
        p = db.jload(u["perms"], {}) or {}
        p.update(body["perms"])
        db.run("UPDATE users SET perms=? WHERE id=?", (db.jdump(p), uid))
    if body.get("password"):
        if len(body["password"]) < 12:
            raise HTTPException(400, "Das Notfall-Passwort braucht mindestens 12 Zeichen.")
        db.run("UPDATE users SET pw_hash=? WHERE id=?", (security.hash_password(body["password"]), uid))
    if "paperless_token" in body:
        users.set_personal_secret(uid, "paperless_token", body["paperless_token"] or "")
    if body.get("unlock"):
        db.run("UPDATE users SET failed_logins=0, locked_until=0 WHERE id=?", (uid,))
    audit(user["name"], "Einstellung", f"Benutzer {u['name']} geändert: {', '.join(k for k in body if k != 'password')}"
          + (", Notfall-Passwort gesetzt" if body.get("password") else ""))
    return {"ok": True}


@router.delete("/users/{uid}")
def user_delete(uid: int, user=Depends(require_admin)):
    if uid == user["id"]:
        raise HTTPException(400, "Du kannst dich nicht selbst löschen.")
    u = users.get(uid)
    db.run("DELETE FROM users WHERE id=?", (uid,))
    audit(user["name"], "Einstellung", f"Benutzer {u['name'] if u else uid} gelöscht")
    return {"ok": True}


# ------------------------------------------------------------ Protokoll
@router.get("/audit")
def audit_list(category: str = "", q: str = "", days: int = 30, user=Depends(require_admin)):
    sql, args = "SELECT * FROM audit WHERE ts>?", [time.time() - days * 86400]
    if category:
        sql += " AND category=?"
        args.append(category)
    if q:
        sql += " AND (text LIKE ? OR user LIKE ?)"
        args += [f"%{q}%", f"%{q}%"]
    return db.rows(sql + " ORDER BY ts DESC LIMIT 500", args)


@router.get("/audit.csv")
def audit_csv(user=Depends(require_admin)):
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(["Zeit", "Wer", "Bereich", "Was"])
    for r in db.rows("SELECT * FROM audit ORDER BY ts DESC"):
        w.writerow([time.strftime("%d.%m.%Y %H:%M:%S", time.localtime(r["ts"])), r["user"], r["category"], r["text"]])
    return PlainTextResponse("\ufeff" + buf.getvalue(), media_type="text/csv",
                             headers={"Content-Disposition": 'attachment; filename="haus-ki-protokoll.csv"'})


# ------------------------------------------------------------ KNX
@router.get("/knx")
def knx_list(user=Depends(require_admin)):
    gas = db.rows("SELECT * FROM knx_ga ORDER BY address")
    return {"gas": gas, "rooms": sorted({g["room"] for g in gas if g["room"]}),
            "keyring": knx.keyring_path().exists()}


@router.put("/knx/ga")
def knx_permissions(body: dict, user=Depends(require_admin)):
    n = 0
    for addr, perm in (body.get("permissions") or {}).items():
        if perm not in ("none", "read", "write"):
            continue
        ga = db.row("SELECT * FROM knx_ga WHERE address=?", (addr,))
        if ga and ga["locked"] and perm == "write":
            continue
        db.run("UPDATE knx_ga SET permission=? WHERE address=?", (perm, addr))
        n += 1
    audit(user["name"], "Einstellung", f"KNX-Freigaben für {n} Gruppenadressen geändert")
    return {"changed": n}


@router.post("/knx/import")
async def knx_import(file: UploadFile = File(...), password: str = Form(""), user=Depends(require_admin)):
    path = config.data_dir / "import.knxproj"
    path.write_bytes(await file.read())
    try:
        result = await asyncio.to_thread(knx.import_project, str(path), password)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, f"Das ETS-Projekt ließ sich nicht lesen: {e}")
    finally:
        path.unlink(missing_ok=True)
    audit(user["name"], "Einstellung", f"ETS-Projekt importiert: {result['added']} neu, {result['updated']} aktualisiert")
    return result


@router.post("/knx/keyring")
async def knx_keyring(file: UploadFile = File(...), user=Depends(require_admin)):
    knx.keyring_path().write_bytes(await file.read())
    knx.keyring_path().chmod(0o600)
    await knx.stop()
    audit(user["name"], "Einstellung", "KNX-Keyring hochgeladen")
    return {"ok": True}


# ------------------------------------------------------------ Modelle
@router.get("/models")
async def models(user=Depends(require_admin)):
    tags = await ollama.get("/api/tags")
    try:
        loaded = {m["name"] for m in (await ollama.get("/api/ps", timeout=3)).get("models", [])}
    except Exception:  # noqa: BLE001
        loaded = set()
    maxmem = 0
    try:
        maxmem = (await system.vm_status()).get("maxmem", 0) if settings.get("proxmox.url") else 0
    except Exception:  # noqa: BLE001
        pass
    out = []
    for m in tags.get("models", []):
        d = m.get("details", {})
        need = m.get("size", 0) * 1.2 + 0.5e9
        out.append({"name": m["name"], "size": m.get("size", 0), "family": d.get("family"), "params": d.get("parameter_size"),
                    "quant": d.get("quantization_level"), "modified": m.get("modified_at"), "loaded": m["name"] in loaded,
                    "ram_need": need, "fits": (need < maxmem * 0.9) if maxmem else None})
    return {"models": out, "default": settings.get("ollama.default_model"), "helper": settings.get("ollama.helper_model"),
            "members": settings.get("ollama.member_models"), "maxmem": maxmem}


@router.post("/models/pull")
async def models_pull(body: dict, user=Depends(require_admin)):
    name = (body.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "Bitte einen Modellnamen angeben, z. B. qwen3:8b.")
    audit(user["name"], "System", f"Modell {name} wird heruntergeladen")

    async def gen():
        try:
            async for ev in ollama.pull_stream(name):
                yield f"data: {json.dumps(ev)}\n\n"
        except Exception as e:  # noqa: BLE001
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
    return StreamingResponse(gen(), media_type="text/event-stream")


@router.delete("/models/{name:path}")
async def models_delete(name: str, user=Depends(require_admin)):
    if name in (settings.get("ollama.default_model"), settings.get("ollama.helper_model")):
        raise HTTPException(400, "Standard- und Hilfsmodell können nicht gelöscht werden. Wähle vorher ein anderes.")
    await ollama.post("/api/delete", {"model": name})
    audit(user["name"], "System", f"Modell {name} gelöscht")
    return {"ok": True}


@router.post("/models/profile")
async def models_profile(body: dict, user=Depends(require_admin)):
    name = (body.get("name") or "").strip().lower().replace(" ", "-")
    if not name or not body.get("from"):
        raise HTTPException(400, "Name und Basismodell sind nötig.")
    params = {k: v for k, v in (body.get("parameters") or {}).items() if v not in (None, "")}
    try:
        await ollama.create_model(name, body["from"], body.get("system", ""), params)
    except httpx.HTTPStatusError as e:
        raise HTTPException(400, f"Ollama hat das Profil abgelehnt: {e.response.text[:200]}")
    audit(user["name"], "System", f"Modell-Profil {name} auf Basis von {body['from']} erstellt")
    return {"ok": True}


# ------------------------------------------------------------ Ollama-Server (über den Agenten)
@router.get("/agent/env")
async def agent_env(user=Depends(require_admin)):
    return await system.agent("GET", "/ollama/env")


@router.put("/agent/env")
async def agent_env_put(body: dict, user=Depends(require_admin)):
    res = await system.agent("PUT", "/ollama/env", {"vars": body.get("vars", {})})
    audit(user["name"], "Einstellung", "Ollama-Umgebungsvariablen geschrieben: " + ", ".join(sorted(body.get("vars", {}))))
    if body.get("restart"):
        await system.agent("POST", "/ollama/restart", timeout=90)
        audit(user["name"], "System", "Ollama neu gestartet")
    return res


@router.post("/agent/{cmd}")
async def agent_cmd(cmd: str, user=Depends(require_admin)):
    if cmd == "restart":
        res = await system.agent("POST", "/ollama/restart", timeout=90)
        audit(user["name"], "System", "Ollama neu gestartet")
    elif cmd == "update":
        res = await system.agent("POST", "/ollama/update", timeout=30)
        audit(user["name"], "System", "Ollama-Aktualisierung gestartet")
    elif cmd == "update-status":
        res = await system.agent("GET", "/ollama/update")
    elif cmd == "logs":
        res = await system.agent("GET", "/ollama/logs?lines=200")
    elif cmd == "reset-fingerprint":
        settings.set_many({"agent.fingerprint": ""})
        audit(user["name"], "Einstellung", "Zertifikat des Agenten zurückgesetzt")
        res = {"ok": True}
    else:
        raise HTTPException(404)
    return res


# ------------------------------------------------------------ Proxmox
@router.get("/proxmox/guests")
async def pve_guests(user=Depends(require_admin)):
    return await system.pve_guests()


@router.post("/proxmox/{cmd}")
async def pve_cmd(cmd: str, user=Depends(require_admin)):
    await system.vm_control(cmd)
    audit(user["name"], "System", f"Ollama-Container: {cmd}")
    return {"ok": True}


# ------------------------------------------------------------ Sicherung und Updates
@router.get("/backups")
def backups(user=Depends(require_admin)):
    return {"backups": scheduler.list_backups(), "keep": settings.get("backup.keep"), "enabled": settings.get("backup.enabled")}


@router.post("/backups")
async def backup_create(user=Depends(require_admin)):
    name = await asyncio.to_thread(scheduler.backup_now, f"von {user['name']}")
    return {"name": name}


@router.post("/backups/restore")
async def backup_restore(body: dict, user=Depends(require_admin)):
    try:
        await asyncio.to_thread(scheduler.restore, body.get("name", ""))
    except FileNotFoundError:
        raise HTTPException(404, "Diese Sicherung gibt es nicht.")
    audit(user["name"], "Sicherung", f"Sicherung {body.get('name')} wiederhergestellt")
    return {"ok": True}


@router.get("/backups/{name}")
def backup_download(name: str, user=Depends(require_admin)):
    path = config.backup_dir / name
    if "/" in name or not path.exists():
        raise HTTPException(404)
    return FileResponse(path, filename=name)


@router.get("/update")
def update_status(user=Depends(require_admin)):
    status = {}
    f = config.update_dir / "status.json"
    if f.exists():
        try:
            status = json.loads(f.read_text())
        except ValueError:
            pass
    from .. import update
    return {"version": __version__, "status": status, "source": settings.get("update.source"), "available": update.last_info()}


@router.post("/update/check")
async def update_check(user=Depends(require_admin)):
    from .. import update
    try:
        return await update.check()
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"Die Update-Quelle ist nicht erreichbar: {e}"[:300])


@router.post("/update/install-available")
async def update_install_available(user=Depends(require_admin)):
    from .. import update
    try:
        r = await update.install_available(user["name"])
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, str(e)[:300])
    audit(user["name"], "System", f"Update auf {r['version']} heruntergeladen und geprüft, Installation angestoßen")
    return r


@router.post("/update")
async def update_upload(file: UploadFile = File(...), user=Depends(require_admin)):
    config.update_dir.mkdir(parents=True, exist_ok=True)
    data = await file.read()
    if not data[:2] == b"\x1f\x8b":
        raise HTTPException(400, "Bitte ein Haus-KI-Paket (.tar.gz) hochladen.")
    (config.update_dir / "incoming.tar.gz").write_bytes(data)
    (config.update_dir / "request").write_text(json.dumps({"action": "install", "by": user["name"], "ts": time.time()}))
    audit(user["name"], "System", f"App-Update hochgeladen ({len(data) / 1e6:.1f} MB), Installation angestoßen")
    return {"ok": True}


@router.post("/update/rollback")
def update_rollback(user=Depends(require_admin)):
    config.update_dir.mkdir(parents=True, exist_ok=True)
    (config.update_dir / "request").write_text(json.dumps({"action": "rollback", "by": user["name"], "ts": time.time()}))
    audit(user["name"], "System", "Rückkehr zur vorherigen App-Version angestoßen")
    return {"ok": True}


@router.post("/night/run")
async def night_run(user=Depends(require_admin)):
    asyncio.create_task(scheduler.night_plan())
    audit(user["name"], "System", "Nachtplan von Hand gestartet")
    return {"ok": True}


# ------------------------------------------------------------ Antwortqualität
@router.get("/quality")
def quality(days: int = 30, user=Depends(require_admin)):
    since = time.time() - days * 86400
    tools = db.rows("SELECT tool, COUNT(*) AS calls, SUM(ok=0) AS errors, CAST(AVG(ms) AS INT) AS avg_ms, "
                    "(SELECT error FROM tool_log t2 WHERE t2.tool=t.tool AND t2.ok=0 AND t2.ts>? ORDER BY ts DESC LIMIT 1) AS last_error, "
                    "(SELECT model FROM tool_log t3 WHERE t3.tool=t.tool AND t3.ok=0 AND t3.ts>? ORDER BY ts DESC LIMIT 1) AS last_model "
                    "FROM tool_log t WHERE ts>? GROUP BY tool ORDER BY errors DESC, calls DESC", (since, since, since))
    bad = db.rows("SELECT f.message_id, f.comment, f.created, u.name AS user, m.content AS answer, m.meta, c.title, c.id AS chat_id, "
                  "(SELECT content FROM messages q WHERE q.chat_id=m.chat_id AND q.role='user' AND q.id<m.id ORDER BY q.id DESC LIMIT 1) AS question "
                  "FROM feedback f JOIN messages m ON m.id=f.message_id JOIN chats c ON c.id=m.chat_id JOIN users u ON u.id=f.user_id "
                  "WHERE f.value<0 AND f.created>? ORDER BY f.created DESC LIMIT 200", (since,))
    for b in bad:
        meta = db.jload(b.pop("meta"), {})
        b.update(model=meta.get("model", ""), sources=meta.get("sources", []), routed=meta.get("routed", ""))
        b["answer"] = (b["answer"] or "")[:600]
    routed = db.scalar("SELECT COUNT(*) FROM messages WHERE role='assistant' AND created>? AND meta LIKE ?", (since, '%"routed": "einfache%')) or 0
    from .. import history, semantic
    return {"tools": tools, "bad": bad, "routed": routed, "semantic": semantic.status(), "history": history.status()}


@router.get("/quality/export")
def quality_export(user=Depends(require_admin)):
    data = quality(3650, user)["bad"]
    return JSONResponse([{k: b[k] for k in ("question", "answer", "comment", "model", "sources", "created")} for b in data],
                        headers={"Content-Disposition": 'attachment; filename="haus-ki-schlechte-antworten.json"'})


@router.post("/quality/rerun/{mid}")
def quality_rerun(mid: int, user=Depends(require_admin)):
    """Eine schlecht bewertete Frage mit den heutigen Einstellungen erneut stellen (eigener Testchat)."""
    from .. import chat
    m = db.row("SELECT * FROM messages WHERE id=?", (mid,))
    q = db.row("SELECT * FROM messages WHERE chat_id=? AND role='user' AND id<? ORDER BY id DESC LIMIT 1", (m["chat_id"], mid)) if m else None
    if not q:
        raise HTTPException(404)
    meta = db.jload(m["meta"], {})
    cid = db.run("INSERT INTO chats(user_id,title,kind,created,updated) VALUES(?,?,?,?,?)",
                 (user["id"], "Test: " + q["content"][:50], "eval", db.now(), db.now()))
    qid = db.run("INSERT INTO messages(chat_id,role,content,meta,created) VALUES(?,?,?,?,?)",
                 (cid, "user", q["content"], db.jdump({"eval_of": mid}), db.now()))
    job = chat.submit(user, cid, qid, {"model": settings.get("ollama.default_model"), "sources": meta.get("sources", [])})
    audit(user["name"], "System", f"Schlecht bewertete Antwort erneut getestet (Nachricht {mid})")
    return {"chat_id": cid, "job_id": job.id}


@router.post("/semantic/rebuild")
async def semantic_rebuild(user=Depends(require_admin)):
    from .. import scheduler
    db.kv_set("semantic_since", "")
    asyncio.create_task(scheduler.task_semantic())
    audit(user["name"], "System", "Paperless-Index wird neu aufgebaut")
    return {"ok": True}


@router.get("/agent/guard")
async def agent_guard(user=Depends(require_admin)):
    return await system.agent("GET", "/ollama/guard")


@router.put("/agent/guard")
async def agent_guard_put(body: dict, user=Depends(require_admin)):
    res = await system.agent("PUT", "/ollama/guard", {"enabled": bool(body.get("enabled", True)), "allow": body.get("allow", [])})
    audit(user["name"], "Einstellung", "Ollama-Schutz " + ("eingeschaltet, erlaubt: " + ", ".join(res.get("allow", [])) if res.get("enabled") else "ausgeschaltet"))
    return res


# ------------------------------------------------------------ Modelle vergleichen
STANDARD_QUESTIONS = [
    ("Erkläre in drei Sätzen, wann ein Heizstab in einer Wärmepumpe anspringt.", []),
    ("Rechne: Wir zahlen 99 € Abschlag im Monat, die Jahresrechnung war 1.184,20 €. Zahlen wir nach oder bekommen wir Geld zurück, und wie viel?", []),
    ("Welche Dokumente von den Stadtwerken haben wir 2025 bekommen, und was war der höchste Betrag?", ["paperless"]),
    ("Wie warm ist es gerade im Wohnzimmer, und ist irgendwo ein Fenster offen?", ["knx"]),
    ("Was steht diese Woche im Familienkalender?", ["m365"]),
    ("Schlag uns einen Familienfilm unter zwei Stunden vor, den noch niemand gesehen hat.", ["jellyfin"]),
]


@router.post("/quality/compare")
def compare_start(body: dict, user=Depends(require_admin)):
    """Gleiche Fragen an zwei Modelle, nebeneinander. Läuft hinter allen Fragen der Familie."""
    from .. import chat
    from ..jobs import SCHEDULED
    a, b = body.get("model_a") or settings.get("ollama.default_model"), body.get("model_b")
    if not b or a == b:
        raise HTTPException(400, "Bitte zwei verschiedene Modelle wählen.")
    if body.get("set") == "bad":
        rows = quality(3650, user)["bad"][:10]
        questions = [(r["question"], r["sources"]) for r in rows if r["question"]]
    else:
        questions = STANDARD_QUESTIONS
    if not questions:
        raise HTTPException(400, "Es gibt noch keine schlecht bewerteten Antworten.")
    run = f"{int(time.time())}"
    for text, sources in questions:
        cid = db.run("INSERT INTO chats(user_id,title,kind,created,updated) VALUES(?,?,?,?,?)",
                     (user["id"], f"Vergleich: {text[:50]}", "eval", db.now(), db.now()))
        qid = db.run("INSERT INTO messages(chat_id,role,content,meta,created) VALUES(?,?,?,?,?)",
                     (cid, "user", text, db.jdump({"eval_run": run, "eval_models": [a, b]}), db.now()))
        chat.submit(user, cid, qid, {"model": a, "compare_model": b, "sources": sources},
                    priority=SCHEDULED, label="Modellvergleich")
    db.kv_set(f"compare:{run}", {"a": a, "b": b, "n": len(questions), "by": user["name"], "started": time.time()})
    audit(user["name"], "System", f"Modellvergleich {a} gegen {b} mit {len(questions)} Fragen gestartet")
    return {"run": run, "questions": len(questions)}


@router.get("/quality/compare")
def compare_results(user=Depends(require_admin)):
    runs = []
    for row in db.rows("SELECT key, value FROM kv WHERE key LIKE 'compare:%' ORDER BY key DESC LIMIT 5"):
        info, run = db.jload(row["value"], {}), row["key"].split(":", 1)[1]
        chats = [r["chat_id"] for r in db.rows("SELECT chat_id FROM messages WHERE role='user' AND meta LIKE ?", (f'%"eval_run": "{run}"%',))]
        per = {}
        for cid in chats:
            for m in db.rows("SELECT id, meta FROM messages WHERE chat_id=? AND role='assistant'", (cid,)):
                meta = db.jload(m["meta"], {})
                st = meta.get("stats", {})
                p = per.setdefault(meta.get("model", "?"), {"answers": 0, "seconds": 0.0, "tps": 0.0, "up": 0, "down": 0, "errors": 0})
                p["answers"] += 1
                p["seconds"] += st.get("seconds", 0)
                p["tps"] += st.get("tps", 0)
                p["errors"] += 1 if meta.get("error") else 0
                fb = db.scalar("SELECT value FROM feedback WHERE message_id=?", (m["id"],))
                if fb == 1:
                    p["up"] += 1
                elif fb == -1:
                    p["down"] += 1
        models = []
        for name in (info.get("a"), info.get("b")):
            p = per.get(name, {"answers": 0})
            n = max(p.get("answers", 0), 1)
            models.append({"model": name, "answers": p.get("answers", 0), "avg_seconds": round(p.get("seconds", 0) / n, 1),
                           "avg_tps": round(p.get("tps", 0) / n, 1), "up": p.get("up", 0), "down": p.get("down", 0)})
        runs.append({"run": run, **info, "chats": chats, "done": sum(m["answers"] for m in models) // 2, "models": models})
    return runs
