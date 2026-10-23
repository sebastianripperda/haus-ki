"""Chats, Nachrichten, laufende Antworten und Bestätigungen."""
import asyncio
import json
import re
import time

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import PlainTextResponse, StreamingResponse
from pydantic import BaseModel

from .. import chat, db, ollama, settings, users
from ..auth import current_user
from ..events import audit, notify
from ..jobs import INTERACTIVE, Job, queue

router = APIRouter(prefix="/api")


class AskIn(BaseModel):
    text: str
    model: str = ""
    sources: list[str] = []
    style: str = "ausgewogen"
    think: bool = False
    compare_model: str = ""
    advanced: dict = {}
    attachments: list[dict] = []
    project_id: int | None = None
    template_id: int | None = None


def _own_chat(cid: int, user: dict, write: bool = True) -> dict:
    c = db.row("SELECT * FROM chats WHERE id=?", (cid,))
    if not c:
        raise HTTPException(404, "Diesen Chat gibt es nicht mehr.")
    if c["user_id"] == user["id"]:
        return c
    if not write and users.is_admin(user) and settings.get("chat.admin_read"):
        owner = users.get(c["user_id"])
        key = f"einsicht:{user['id']}:{c['id']}:{time.strftime('%Y-%m-%d')}"
        if not db.kv_get(key):
            db.kv_set(key, True)
            audit(user["name"], "Einsicht", f"Chat „{c['title']}“ von {owner['name'] if owner else '?'} gelesen")
        return c
    raise HTTPException(403, "Dieser Chat gehört jemand anderem.")


def _request(user: dict, body: AskIn) -> dict:
    allowed = chat.allowed_models(user)
    model = body.model or settings.get("ollama.default_model")
    if allowed is not None and model not in allowed:
        model = settings.get("ollama.default_model")
    req = {"model": model, "sources": body.sources, "style": body.style, "think": body.think,
           "advanced": body.advanced if users.is_admin(user) else {}}
    if body.compare_model and users.is_admin(user):
        req["compare_model"] = body.compare_model
    if body.template_id:
        t = db.row("SELECT * FROM templates WHERE id=? AND (owner_id=? OR owner_id IS NULL)", (body.template_id, user["id"]))
        if t:
            req["template_system"] = t["system"]
            req["json"] = bool(t["json_mode"])
            if t["model"] and (allowed is None or t["model"] in allowed):
                req["model"] = t["model"]
    return req


def _attachments(items: list[dict]) -> list[dict]:
    out, total = [], 0
    for a in items[:6]:
        if a.get("image"):
            data = str(a.get("data", ""))
            total += len(data)
            out.append({"name": a.get("name", "Bild")[:100], "image": True, "data": data, "size": len(data) * 3 // 4})
        else:
            text = str(a.get("text", ""))[:60000]
            total += len(text)
            out.append({"name": a.get("name", "Datei")[:100], "text": text, "size": len(text)})
    if total > 15_000_000:
        raise HTTPException(413, "Die Anhänge sind zu groß (höchstens etwa 10 MB).")
    return out


def _start(user: dict, cid: int, body: AskIn) -> dict:
    meta = {"attachments": _attachments(body.attachments)} if body.attachments else {}
    mid = db.run("INSERT INTO messages(chat_id,role,content,meta,created) VALUES(?,?,?,?,?)",
                 (cid, "user", body.text, db.jdump(meta), db.now()))
    db.run("UPDATE chats SET updated=? WHERE id=?", (db.now(), cid))
    job = chat.submit(user, cid, mid, _request(user, body))
    return {"chat_id": cid, "message_id": mid, "job_id": job.id, "position": queue.position(job)}


# ------------------------------------------------------------ Liste und Suche
@router.get("/chats")
def chats(of: int | None = None, user=Depends(current_user)):
    owner = user["id"]
    if of and of != user["id"]:
        if not users.is_admin(user) or not settings.get("chat.admin_read"):
            raise HTTPException(403)
        owner = of
    rows = db.rows("SELECT c.id, c.title, c.pinned, c.project_id, c.kind, c.updated, c.created, s.name AS shared_by_name "
                   "FROM chats c LEFT JOIN users s ON s.id=c.shared_by WHERE c.user_id=? ORDER BY c.updated DESC LIMIT 500", (owner,))
    return {"chats": rows, "retention_days": settings.get("chat.retention_days")}


@router.get("/search")
async def search(q: str, user=Depends(current_user)):
    like = f"%{q.strip()}%"
    hits = db.rows("SELECT DISTINCT c.id, c.title, c.updated FROM chats c LEFT JOIN messages m ON m.chat_id=c.id "
                   "WHERE c.user_id=? AND (c.title LIKE ? OR m.content LIKE ?) ORDER BY c.updated DESC LIMIT 40",
                   (user["id"], like, like))
    from .. import history
    if history.enabled() and len(q.strip()) > 3:
        try:
            known = {h["id"] for h in hits}
            for h in await history.search(user["id"], q, limit=8):
                if h["chat_id"] not in known:
                    hits.append({"id": h["chat_id"], "title": h["title"], "updated": 0, "by_meaning": True})
        except Exception:  # noqa: BLE001 – ohne Embedding-Modell nur die Stichwortsuche
            pass
    return hits


@router.get("/chats/{cid}")
def chat_get(cid: int, user=Depends(current_user)):
    c = _own_chat(cid, user, write=False)
    msgs = db.rows("SELECT id, role, content, meta, created FROM messages WHERE chat_id=? ORDER BY id", (cid,))
    action_ids = [a for m in msgs for a in db.jload(m["meta"], {}).get("actions", [])]
    acts = {a["id"]: a for a in db.rows(
        f"SELECT id, kind, summary, status, result, via FROM actions WHERE id IN ({','.join('?' * len(action_ids)) or 'NULL'})",
        action_ids)} if action_ids else {}
    fb = {f["message_id"]: f["value"] for f in db.rows(
        "SELECT message_id, value FROM feedback WHERE user_id=? AND message_id IN (SELECT id FROM messages WHERE chat_id=?)",
        (user["id"], cid))}
    for m in msgs:
        meta = db.jload(m.pop("meta"), {})
        for a in meta.get("attachments", []):
            a.pop("data", None)
            a.pop("text", None)
        meta["actions"] = [acts[a] for a in meta.get("actions", []) if a in acts]
        meta["feedback"] = fb.get(m["id"], 0)
        m["meta"] = meta
    jobs = [{"id": j.id, "status": j.status} for j in queue.jobs.values() if j.chat_id == cid and not j.done.is_set()]
    return {"chat": c, "messages": msgs, "jobs": jobs, "readonly": c["user_id"] != user["id"]}


# ------------------------------------------------------------ Fragen stellen
@router.post("/chats")
def chat_new(body: AskIn, user=Depends(current_user)):
    if not body.text.strip() and not body.attachments:
        raise HTTPException(400, "Die Nachricht ist leer.")
    title = re.sub(r"\s+", " ", body.text).strip()[:60] or (body.attachments[0].get("name") if body.attachments else "Neuer Chat")
    pid = body.project_id if body.project_id and db.row("SELECT id FROM projects WHERE id=? AND user_id=?",
                                                        (body.project_id, user["id"])) else None
    cid = db.run("INSERT INTO chats(user_id,project_id,title,created,updated) VALUES(?,?,?,?,?)",
                 (user["id"], pid, title, db.now(), db.now()))
    return _start(user, cid, body)


@router.post("/chats/{cid}/messages")
def chat_send(cid: int, body: AskIn, user=Depends(current_user)):
    _own_chat(cid, user)
    if any(j.chat_id == cid and not j.done.is_set() for j in queue.jobs.values()):
        raise HTTPException(409, "In diesem Chat läuft noch eine Antwort.")
    return _start(user, cid, body)


@router.post("/chats/{cid}/regenerate")
def regenerate(cid: int, body: AskIn, user=Depends(current_user)):
    _own_chat(cid, user)
    last = db.row("SELECT id FROM messages WHERE chat_id=? AND role='user' ORDER BY id DESC LIMIT 1", (cid,))
    if not last:
        raise HTTPException(400)
    db.run("DELETE FROM messages WHERE chat_id=? AND id>?", (cid, last["id"]))
    job = chat.submit(user, cid, last["id"], _request(user, body))
    return {"chat_id": cid, "job_id": job.id, "message_id": last["id"]}


@router.post("/messages/{mid}/edit")
def edit(mid: int, body: AskIn, user=Depends(current_user)):
    m = db.row("SELECT * FROM messages WHERE id=? AND role='user'", (mid,))
    if not m:
        raise HTTPException(404)
    _own_chat(m["chat_id"], user)
    db.run("UPDATE messages SET content=? WHERE id=?", (body.text, mid))
    db.run("DELETE FROM messages WHERE chat_id=? AND id>?", (m["chat_id"], mid))
    job = chat.submit(user, m["chat_id"], mid, _request(user, body))
    return {"chat_id": m["chat_id"], "job_id": job.id, "message_id": mid}


@router.get("/jobs/{jid}/events")
async def job_events(jid: int, request: Request, user=Depends(current_user)):
    job = queue.jobs.get(jid)
    if not job or job.user_id != user["id"]:
        raise HTTPException(404, "Diese Antwort läuft nicht mehr.")
    q: asyncio.Queue = asyncio.Queue()
    replay = list(job.events)
    job.listeners.add(q)

    async def gen():
        try:
            for ev in replay:
                yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
            if job.done.is_set() and (not replay or replay[-1].get("type") == "end"):
                return
            while True:
                if await request.is_disconnected():
                    return
                try:
                    ev = await asyncio.wait_for(q.get(), timeout=20)
                except asyncio.TimeoutError:
                    yield ": ping\n\n"
                    continue
                yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
                if ev.get("type") == "end":
                    return
        finally:
            job.listeners.discard(q)
    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.post("/jobs/{jid}/cancel")
def job_cancel(jid: int, user=Depends(current_user)):
    job = queue.jobs.get(jid)
    if job and job.user_id == user["id"]:
        queue.cancel(job)
    return {"ok": True}


# ------------------------------------------------------------ Chat verwalten
@router.patch("/chats/{cid}")
def chat_update(cid: int, body: dict, user=Depends(current_user)):
    _own_chat(cid, user)
    if "title" in body:
        db.run("UPDATE chats SET title=? WHERE id=?", (str(body["title"])[:80], cid))
    if "pinned" in body:
        db.run("UPDATE chats SET pinned=? WHERE id=?", (1 if body["pinned"] else 0, cid))
    if "project_id" in body:
        pid = body["project_id"]
        if pid and not db.row("SELECT id FROM projects WHERE id=? AND user_id=?", (pid, user["id"])):
            raise HTTPException(400)
        db.run("UPDATE chats SET project_id=? WHERE id=?", (pid or None, cid))
    return {"ok": True}


@router.delete("/chats/{cid}")
def chat_delete(cid: int, user=Depends(current_user)):
    _own_chat(cid, user)
    db.run("DELETE FROM chats WHERE id=?", (cid,))
    return {"ok": True}


@router.get("/chats/{cid}/export")
def chat_export(cid: int, user=Depends(current_user)):
    c = _own_chat(cid, user, write=False)
    lines = [f"# {c['title']}", ""]
    for m in db.rows("SELECT * FROM messages WHERE chat_id=? ORDER BY id", (cid,)):
        meta = db.jload(m["meta"], {})
        who = user["name"] if m["role"] == "user" else f"Haus-KI ({meta.get('model', '')})"
        lines += [f"**{who}** – {time.strftime('%d.%m.%Y %H:%M', time.localtime(m['created']))}", "", m["content"], ""]
        for ci in meta.get("cites", []):
            lines.append(f"[{ci['nr']}] {ci['source']}: {ci['title']} {ci.get('url', '')}")
        lines.append("")
    name = re.sub(r"[^\w\- ]", "", c["title"])[:40] or "chat"
    return PlainTextResponse("\n".join(lines), media_type="text/markdown",
                             headers={"Content-Disposition": f'attachment; filename="{name}.md"'})


@router.post("/messages/{mid}/share")
def share(mid: int, body: dict, user=Depends(current_user)):
    m = db.row("SELECT * FROM messages WHERE id=? AND role='assistant'", (mid,))
    if not m:
        raise HTTPException(404)
    c = _own_chat(m["chat_id"], user)
    to = users.get(int(body.get("to", 0)))
    if not to or to["disabled"] or to["id"] == user["id"]:
        raise HTTPException(400, "Empfänger nicht gefunden.")
    q = db.row("SELECT * FROM messages WHERE chat_id=? AND role='user' AND id<? ORDER BY id DESC LIMIT 1", (m["chat_id"], mid))
    cid = db.run("INSERT INTO chats(user_id,title,kind,shared_by,created,updated) VALUES(?,?,?,?,?,?)",
                 (to["id"], c["title"], "shared", user["id"], db.now(), db.now()))
    for msg in [x for x in (q, m) if x]:
        meta = db.jload(msg["meta"], {})
        meta.pop("actions", None)
        db.run("INSERT INTO messages(chat_id,role,content,meta,created) VALUES(?,?,?,?,?)",
               (cid, msg["role"], msg["content"], db.jdump(meta), db.now()))
    notify(to["id"], f"{user['name']} hat dir eine Antwort geteilt: „{c['title']}“", f"#chat/{cid}")
    return {"ok": True}


@router.post("/messages/{mid}/feedback")
def feedback(mid: int, body: dict, user=Depends(current_user)):
    m = db.row("SELECT chat_id FROM messages WHERE id=?", (mid,))
    if not m:
        raise HTTPException(404)
    _own_chat(m["chat_id"], user)
    v = int(body.get("value", 0))
    comment = (body.get("comment") or "").strip()[:500] or None
    if v == 0:
        db.run("DELETE FROM feedback WHERE message_id=? AND user_id=?", (mid, user["id"]))
    else:
        db.run("INSERT INTO feedback(message_id,user_id,value,created,comment) VALUES(?,?,?,?,?) "
               "ON CONFLICT(message_id,user_id) DO UPDATE SET value=excluded.value, comment=COALESCE(excluded.comment, comment)",
               (mid, user["id"], 1 if v > 0 else -1, db.now(), comment))
    return {"ok": True}


@router.post("/actions/{aid}")
async def decide(aid: int, body: dict, user=Depends(current_user)):
    try:
        return await chat.decide(user, aid, bool(body.get("approve")))
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/chats/{cid}/summarize")
def summarize(cid: int, user=Depends(current_user)):
    c = _own_chat(cid, user)
    msgs = db.rows("SELECT role, content FROM messages WHERE chat_id=? ORDER BY id", (cid,))
    text = "\n\n".join(f"{'Frage' if m['role'] == 'user' else 'Antwort'}: {m['content'][:2000]}" for m in msgs)[-24000:]
    new = db.run("INSERT INTO chats(user_id,project_id,title,created,updated) VALUES(?,?,?,?,?)",
                 (user["id"], c["project_id"], c["title"] + " (Fortsetzung)", db.now(), db.now()))
    mid = db.run("INSERT INTO messages(chat_id,role,content,meta,created) VALUES(?,?,?,?,?)",
                 (new, "user", "Fasse diese Unterhaltung kurz zusammen, damit wir sie fortsetzen können. Halte Fakten, "
                               "Zahlen und offene Punkte fest.\n\n" + text, db.jdump({"summary_of": cid}), db.now()))
    job = chat.submit(user, new, mid, {"model": settings.get("ollama.default_model"), "sources": [], "style": "genau"})
    return {"chat_id": new, "job_id": job.id}


# ------------------------------------------------------------ Dokument in Paperless ablegen
@router.post("/paperless/upload")
async def paperless_upload(file: UploadFile = File(...), chat_id: int | None = Form(None), user=Depends(current_user)):
    from ..tools import paperless
    if not (settings.get("paperless.enabled") and settings.get("paperless.upload") and users.perms(user).get("paperless")):
        raise HTTPException(403, "Ablegen in Paperless ist für dich nicht freigegeben.")
    data = await file.read()
    if len(data) > 50_000_000:
        raise HTTPException(413, "Die Datei ist größer als 50 MB.")
    if chat_id:
        _own_chat(chat_id, user)
    else:
        chat_id = db.run("INSERT INTO chats(user_id,title,created,updated) VALUES(?,?,?,?)",
                         (user["id"], f"In Paperless ablegen: {file.filename}"[:60], db.now(), db.now()))
    size = f"{len(data) / 1e6:.1f} MB".replace(".", ",")
    mid = db.run("INSERT INTO messages(chat_id,role,content,meta,created) VALUES(?,?,?,?,?)",
                 (chat_id, "user", "In Paperless ablegen", db.jdump({"attachments": [{"name": file.filename, "size": len(data),
                                                                                      "label": f"{file.filename}, {size}"}]}), db.now()))

    async def run(job: Job) -> None:
        job.emit({"type": "step", "key": "a", "text": "An Paperless übergeben, Texterkennung durch Paperless", "state": "ok"})
        doc = await paperless.upload(user, file.filename or "dokument", data, file.content_type or "application/octet-stream")
        job.emit({"type": "step", "key": "a", "text": "Text erkannt, Vorschlag wird erstellt", "state": "ok"})
        prompt = ("Hier ist der erkannte Text eines Dokuments. Schlage Metadaten für die Ablage vor. Antworte nur als JSON: "
                  '{"title": "…", "correspondent": "Absender", "document_type": "z. B. Rechnung, Vertrag, Bescheid, Brief", '
                  '"date": "JJJJ-MM-TT", "amount": "Betrag oder leer", "tags": ["…"], "deadline": "JJJJ-MM-TT oder leer", '
                  '"summary": "ein Satz"}\n\n' + doc["content"][:4000])
        meta = await ollama.complete_json(settings.get("ollama.default_model"), prompt, num_predict=300) or {}
        if not isinstance(meta, dict):
            meta = {}
        meta.setdefault("title", doc["title"])
        text = f"Paperless hat das Dokument angenommen und den Text erkannt. {meta.get('summary', '')} Prüf meinen Vorschlag und leg es dann ab."
        job.emit({"type": "delta", "key": "a", "text": text})
        amid = db.run("INSERT INTO messages(chat_id,role,content,meta,created) VALUES(?,?,?,?,?)",
                      (chat_id, "assistant", text, db.jdump({"model": settings.get("ollama.default_model"), "steps": [
                          {"text": "An Paperless übergeben, Texterkennung durch Paperless", "state": "ok"},
                          {"text": "Text erkannt, Vorschlag erstellt", "state": "ok"}],
                          "paperless": {"doc_id": doc["id"], "url": doc["url"], "proposal": meta, "state": "pending"}}), db.now()))
        job.emit({"type": "paperless", "key": "a", "message_id": amid, "doc_id": doc["id"], "proposal": meta})
        job.emit({"type": "done", "key": "a", "message_id": amid, "stats": {}})
    job = queue.submit(Job(user["id"], INTERACTIVE, "Paperless", run, chat_id))
    return {"chat_id": chat_id, "message_id": mid, "job_id": job.id}


@router.post("/paperless/decide/{mid}")
async def paperless_decide(mid: int, body: dict, user=Depends(current_user)):
    from ..tools import paperless
    m = db.row("SELECT * FROM messages WHERE id=?", (mid,))
    if not m:
        raise HTTPException(404)
    _own_chat(m["chat_id"], user)
    meta = db.jload(m["meta"], {})
    pl = meta.get("paperless")
    if not pl or pl.get("state") != "pending":
        raise HTTPException(400, "Dieser Vorschlag ist schon erledigt.")
    if body.get("approve"):
        proposal = {**pl["proposal"], **{k: body[k] for k in ("title", "tags") if k in body}}
        try:
            await paperless.apply_metadata(user, pl["doc_id"], proposal)
        except Exception as e:  # noqa: BLE001
            raise HTTPException(502, f"Paperless hat die Angaben nicht übernommen: {e}")
        pl.update(state="saved", proposal=proposal)
        if proposal.get("deadline"):
            db.run("INSERT INTO insights(user_id,kind,ref,data,created) VALUES(?,?,?,?,?)",
                   (user["id"], "deadline", str(pl["doc_id"]), db.jdump({"title": proposal.get("title"), "doc": proposal.get("title"),
                                                                         "due": proposal["deadline"], "url": pl["url"]}), db.now()))
        audit(user["name"], "Aktion", f"Paperless: Dokument {pl['doc_id']} „{proposal.get('title')}“ abgelegt")
    else:
        try:
            await paperless.delete(user, pl["doc_id"])
        except Exception:  # noqa: BLE001
            pass
        pl["state"] = "discarded"
        audit(user["name"], "Aktion", f"Paperless: Dokument {pl['doc_id']} verworfen")
    meta["paperless"] = pl
    db.run("UPDATE messages SET meta=? WHERE id=?", (db.jdump(meta), mid))
    return pl
