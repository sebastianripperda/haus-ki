"""Hintergrundaufgaben: Nachtplan, geplante Prompts, Aufbewahrung, Sicherung, Ollama-Überwachung."""
import asyncio
import datetime as dt
import gzip
import logging
import shutil
import sqlite3
import time

from . import chat, db, ollama, settings, users
from .config import config
from .events import audit, notify, notify_admins
from .jobs import NIGHT, Job, queue

log = logging.getLogger("hauski.scheduler")
DAYS = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]
health = {"ok": None, "fails": 0, "version": "", "since": time.time(), "alerted": False}


# ------------------------------------------------------------ geplante Prompts
def next_run(s: dict, after: dt.datetime) -> dt.datetime | None:
    try:
        h, m = (int(x) for x in s["time"].split(":"))
    except ValueError:
        return None
    cand = after.replace(hour=h, minute=m, second=0, microsecond=0)
    if cand <= after:
        cand += dt.timedelta(days=1)
    for _ in range(400):
        if s["freq"] in ("daily", "once"):
            return cand
        if s["freq"] == "weekly" and DAYS[cand.weekday()] == (s["day"] or "Mo"):
            return cand
        if s["freq"] == "monthly" and cand.day == 1:
            return cand
        cand += dt.timedelta(days=1)
    return None


async def run_due_schedules() -> None:
    now = dt.datetime.now()
    for s in db.rows("SELECT * FROM schedules WHERE enabled=1"):
        base = dt.datetime.fromtimestamp(max(s["last_run"], s["created"]))
        due = next_run(s, base)
        if due and due <= now and (now - due) < dt.timedelta(hours=6):
            db.run("UPDATE schedules SET last_run=? WHERE id=?", (time.time(), s["id"]))
            if s["freq"] == "once":
                db.run("UPDATE schedules SET enabled=0 WHERE id=?", (s["id"],))
            asyncio.create_task(chat.run_schedule(s))


# ------------------------------------------------------------ Sicherung
def backup_now(label: str = "nachts") -> str:
    config.backup_dir.mkdir(parents=True, exist_ok=True)
    name = f"haus-ki-{dt.datetime.now():%Y%m%d-%H%M}.db"
    tmp = config.backup_dir / name
    dst = sqlite3.connect(tmp)
    with dst:
        db.connect().backup(dst)
    dst.close()
    with open(tmp, "rb") as f_in, gzip.open(str(tmp) + ".gz", "wb") as f_out:
        shutil.copyfileobj(f_in, f_out)
    tmp.unlink()
    keep = int(settings.get("backup.keep") or 14)
    for old in sorted(config.backup_dir.glob("haus-ki-*.db.gz"))[:-keep]:
        old.unlink()
    size = (config.backup_dir / (name + ".gz")).stat().st_size
    audit("System", "Sicherung", f"Sicherung erstellt ({label}), {size / 1e6:.1f} MB")
    return name + ".gz"


def list_backups() -> list[dict]:
    if not config.backup_dir.exists():
        return []
    return [{"name": p.name, "size": p.stat().st_size, "created": p.stat().st_mtime}
            for p in sorted(config.backup_dir.glob("haus-ki-*.db.gz"), reverse=True)]


def restore(name: str) -> None:
    path = config.backup_dir / name
    if not path.exists() or "/" in name:
        raise FileNotFoundError(name)
    backup_now("vor Wiederherstellung")
    raw = config.data_dir / "restore.tmp.db"
    with gzip.open(path, "rb") as f_in, open(raw, "wb") as f_out:
        shutil.copyfileobj(f_in, f_out)
    src = sqlite3.connect(raw)
    with src:
        src.backup(db.connect())
    src.close()
    raw.unlink()
    settings._cache = None


# ------------------------------------------------------------ Aufbewahrung
def retention() -> dict:
    days = int(settings.get("chat.retention_days") or 90)
    cutoff = time.time() - days * 86400
    pinned = "AND pinned=0" if settings.get("chat.keep_pinned") else ""
    n = db.scalar(f"SELECT COUNT(*) FROM chats WHERE updated<? {pinned}", (cutoff,)) or 0
    db.run(f"DELETE FROM chats WHERE updated<? {pinned}", (cutoff,))
    db.run("DELETE FROM audit WHERE ts<?", (time.time() - 365 * 86400,))
    db.run("DELETE FROM notifications WHERE created<?", (time.time() - 30 * 86400,))
    db.run("DELETE FROM actions WHERE created<?", (time.time() - 90 * 86400,))
    db.run("DELETE FROM night_runs WHERE started<?", (time.time() - 30 * 86400,))
    db.run("DELETE FROM tool_log WHERE ts<?", (time.time() - 90 * 86400,))
    db.run("DELETE FROM insights WHERE done=1 AND created<?", (time.time() - 30 * 86400,))
    db.run("DELETE FROM kv WHERE key LIKE 'oidc:%'")
    return {"chats": n}


# ------------------------------------------------------------ Nachtaufgaben
async def _llm_job(label: str, coro_fn) -> object:
    """Nachtaufgaben mit Modellnutzung laufen über die Warteschlange (niedrigste Priorität)."""
    box = {}

    async def run(job: Job) -> None:
        box["result"] = await coro_fn()
    job = queue.submit(Job(0, NIGHT, label, run))
    await job.done.wait()
    if job.status == "error":
        raise RuntimeError(job.events[-2].get("text", "Fehler") if len(job.events) > 1 else "Fehler")
    return box.get("result")


async def task_deadlines() -> str:
    if not (settings.get("paperless.enabled") and settings.get("paperless.deadlines") and settings.get("paperless.token")):
        return "übersprungen"
    from .tools import paperless
    last = db.kv_get("paperless_last_id", 0)
    docs = await paperless.recent_documents(last)
    if not last and docs:  # erster Lauf: nur die letzten 20 Dokumente prüfen
        docs = docs[:20]
    found = 0
    targets = [u for u in db.rows("SELECT * FROM users WHERE disabled=0") if users.perms(u).get("paperless")]
    for d in sorted(docs, key=lambda x: x["id"]):
        prompt = ("Lies den Anfang dieses Dokuments. Gibt es eine Frist, ein Zahlungsziel oder ein Kündigungsdatum, "
                  "das die Familie einhalten muss? Antworte nur als JSON: "
                  '{"frist": "JJJJ-MM-TT" oder null, "was": "kurze Beschreibung"}.\n\n'
                  f"Titel: {d.get('title')}\n\n{(d.get('content') or '')[:3000]}")
        data = await _llm_job("Fristen-Wächter", lambda p=prompt: ollama.complete_json(settings.get("ollama.helper_model"), p, num_predict=80))
        if isinstance(data, dict) and data.get("frist"):
            try:
                due = dt.date.fromisoformat(str(data["frist"])[:10])
            except ValueError:
                due = None
            if due and due >= dt.date.today():
                for u in targets:
                    db.run("INSERT INTO insights(user_id,kind,ref,data,created) VALUES(?,?,?,?,?)",
                           (u["id"], "deadline", str(d["id"]), db.jdump({
                               "title": str(data.get("was") or d.get("title"))[:120], "doc": d.get("title"),
                               "due": due.isoformat(), "url": paperless.doc_url(d["id"])}), time.time()))
                found += 1
        db.kv_set("paperless_last_id", max(db.kv_get("paperless_last_id", 0), d["id"]))
    return f"{len(docs)} Dokumente geprüft, {found} Fristen"


async def task_semantic() -> str:
    from . import semantic
    return await _llm_job("Paperless-Index", semantic.nightly)


async def task_history() -> str:
    from . import history
    return await _llm_job("Chat-Index", history.index_new)


async def task_calendar() -> str:
    if not (settings.get("ms.enabled") and settings.get("ms.cal_check")):
        return "übersprungen"
    from .tools import m365
    conflicts = await m365.calendar_conflicts()
    db.run("DELETE FROM insights WHERE kind='calendar'")
    admins = [u["id"] for u in db.rows("SELECT id FROM users WHERE role='admin' AND disabled=0")]
    members = db.rows("SELECT id, name FROM users WHERE role='member' AND disabled=0")
    for c in conflicts:
        involved = set(admins) | {c["user_id"]} | {m["id"] for m in members if m["name"].lower() in c["family"].lower()}
        for uid in involved:
            db.run("INSERT INTO insights(user_id,kind,data,created) VALUES(?,?,?,?)",
                   (uid, "calendar", db.jdump(c), time.time()))
    return f"{len(conflicts)} Überschneidungen"


async def task_suggestions(only_user: int | None = None) -> str:
    if settings.get("suggestions.mode") == "off":
        return "ausgeschaltet"
    count = 0
    for u in db.rows("SELECT * FROM users WHERE disabled=0"):
        if only_user and u["id"] != only_user or not users.prefs(u).get("suggestions"):
            continue
        recent = db.rows("SELECT c.title, (SELECT content FROM messages m WHERE m.chat_id=c.id AND m.role='user' "
                         "ORDER BY id LIMIT 1) AS q FROM chats c WHERE c.user_id=? AND c.updated>? AND c.kind='chat' "
                         "ORDER BY c.updated DESC LIMIT 12", (u["id"], time.time() - 14 * 86400))
        if len(recent) < 2:
            continue
        srcs = sorted(chat.allowed_sources(u, ["paperless", "jellyfin", "knx", "m365", "mail", "web"]) - {"memory"})
        prompt = ("Hier sind die letzten Fragen einer Person an ihren Haus-Assistenten:\n" +
                  "\n".join(f"- {r['q'][:160] if r['q'] else r['title']}" for r in recent) +
                  f"\n\nVerfügbare Quellen: {', '.join(srcs) or 'keine'}.\n"
                  "Schlage vier neue, konkrete Fragen vor, die sie als Nächstes interessieren könnten. "
                  'Antworte nur als JSON: {"vorschlaege": [{"frage": "…", "grund": "kurzer Grund", "quellen": ["paperless"]}]}')
        data = await _llm_job("Vorschläge", lambda p=prompt: ollama.complete_json(settings.get("ollama.helper_model"), p, num_predict=500))
        items = data.get("vorschlaege", []) if isinstance(data, dict) else []
        items = [{"text": str(i.get("frage", ""))[:140], "why": str(i.get("grund", ""))[:100],
                  "sources": [s for s in i.get("quellen", []) if s in srcs]} for i in items if isinstance(i, dict) and i.get("frage")][:4]
        if items:
            db.run("DELETE FROM insights WHERE user_id=? AND kind='suggestion'", (u["id"],))
            for i in items:
                db.run("INSERT INTO insights(user_id,kind,data,created) VALUES(?,?,?,?)", (u["id"], "suggestion", db.jdump(i), time.time()))
            count += 1
    db.kv_set("suggestions_last", time.time())
    return f"für {count} Personen"


async def night_plan() -> None:
    night = dt.date.today().isoformat()
    tasks = [("Sicherung", lambda: asyncio.to_thread(backup_now)),
             ("Aufräumen nach Aufbewahrungsfrist", lambda: asyncio.to_thread(retention)),
             ("Fristen-Wächter", task_deadlines),
             ("Paperless-Index", task_semantic),
             ("Chat-Index", task_history),
             ("Familienkalender-Abgleich", task_calendar),
             ("Vorschläge", task_suggestions)]
    for name, fn in tasks:
        if name == "Sicherung" and not settings.get("backup.enabled"):
            continue
        rid = db.run("INSERT INTO night_runs(night,task,started) VALUES(?,?,?)", (night, name, time.time()))
        try:
            detail = await fn()
            db.run("UPDATE night_runs SET finished=?, status='ok', detail=? WHERE id=?", (time.time(), str(detail)[:200], rid))
        except Exception as e:  # noqa: BLE001
            log.exception("Nachtaufgabe %s fehlgeschlagen", name)
            db.run("UPDATE night_runs SET finished=?, status='error', detail=? WHERE id=?", (time.time(), str(e)[:200], rid))
            if name == "Sicherung":
                notify_admins(f"Die nächtliche Sicherung ist fehlgeschlagen: {e}", "#admin/backup", "error")
    _notify_morning()


def _notify_morning() -> None:
    for u in db.rows("SELECT * FROM users WHERE disabled=0"):
        p = users.prefs(u)
        n_dead = db.scalar("SELECT COUNT(*) FROM insights WHERE user_id=? AND kind='deadline' AND done=0 AND created>?",
                           (u["id"], time.time() - 6 * 3600)) or 0
        n_cal = db.scalar("SELECT COUNT(*) FROM insights WHERE user_id=? AND kind='calendar'", (u["id"],)) or 0
        if n_dead and p.get("notify_deadlines"):
            notify(u["id"], f"{n_dead} neue Frist(en) aus Paperless erkannt.", "#start")
        if n_cal and p.get("notify_calendar"):
            notify(u["id"], f"{n_cal} Überschneidung(en) im Familienkalender in den nächsten 7 Tagen.", "#start")


# ------------------------------------------------------------ Ollama-Überwachung
async def health_check() -> None:
    try:
        v = await ollama.get("/api/version", timeout=5)
        if health["ok"] is False and health["alerted"]:
            notify_admins("Ollama antwortet wieder.", "#admin/overview", "info")
            audit("System", "System", "Ollama wieder erreichbar")
        health.update(ok=True, fails=0, version=v.get("version", ""), alerted=False)
    except Exception:  # noqa: BLE001
        health["fails"] += 1
        if health["ok"] is not False:
            health["since"] = time.time()
        health["ok"] = False
        if health["fails"] >= 3 and not health["alerted"]:
            health["alerted"] = True
            notify_admins("Ollama im Container reagiert nicht. Haus-KI kann gerade keine Fragen beantworten.",
                          "#admin/overview", "error")
            audit("System", "System", "Ollama nicht erreichbar")


async def _check_updates() -> None:
    from . import update
    try:
        info = await update.check()
        if info.get("available") and db.kv_get("update_notified") != info.get("version"):
            db.kv_set("update_notified", info.get("version"))
            notify_admins(f"Haus-KI {info.get('version')} ist verfügbar.", "#admin/backup", "info")
    except Exception as e:  # noqa: BLE001
        log.info("Update-Prüfung fehlgeschlagen: %s", e)


async def loop() -> None:
    last_minute, last_night = 0.0, db.kv_get("night_last", "")
    while True:
        try:
            await health_check()
            if time.time() - last_minute >= 60:
                last_minute = time.time()
                await run_due_schedules()
                now = dt.datetime.now()
                if now.strftime("%H:%M") >= settings.get("night.start") and now.hour < 6 and last_night != now.date().isoformat():
                    last_night = now.date().isoformat()
                    db.kv_set("night_last", last_night)
                    asyncio.create_task(night_plan())
                if settings.get("update.auto_check") and settings.get("update.source") and time.time() - db.kv_get("update_checked", 0) > 86400:
                    db.kv_set("update_checked", time.time())
                    asyncio.create_task(_check_updates())
                if settings.get("suggestions.mode") == "idle" and not queue.running and not queue.waiting \
                        and time.time() - db.kv_get("suggestions_last", 0) > 86400:
                    asyncio.create_task(task_suggestions())
        except Exception:  # noqa: BLE001
            log.exception("Fehler im Hintergrund")
        await asyncio.sleep(15)
