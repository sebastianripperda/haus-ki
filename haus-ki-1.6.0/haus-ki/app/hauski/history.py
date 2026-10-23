"""Suche in alten Chats: „Was hatten wir letztes Mal zum Gartenhaus besprochen?“

Jede beantwortete Frage wird als Paar aus Frage und Antwort in einen Vektor umgerechnet
(gleiches Embedding-Modell wie für Paperless). Gesucht wird immer nur in den eigenen Chats
der fragenden Person, nie in denen anderer, auch nicht für Administratoren.
Gelöschte Chats verschwinden automatisch aus dem Index.
"""
import time

import numpy as np

from . import db, settings


def enabled() -> bool:
    return bool(settings.get("history.semantic"))


def _pairs(since_id: int, limit: int = 300) -> list[dict]:
    return db.rows(
        "SELECT a.id AS msg_id, a.chat_id, c.user_id, c.title, a.content AS answer, a.created, "
        "(SELECT q.content FROM messages q WHERE q.chat_id=a.chat_id AND q.role='user' AND q.id<a.id ORDER BY q.id DESC LIMIT 1) AS question "
        "FROM messages a JOIN chats c ON c.id=a.chat_id "
        "WHERE a.role='assistant' AND a.id>? AND c.kind IN ('chat','scheduled','shared') "
        "AND a.meta NOT LIKE '%\"variant\": \"b\"%' ORDER BY a.id LIMIT ?", (since_id, limit))


async def index_new() -> str:
    """Neue Frage-Antwort-Paare seit dem letzten Lauf aufnehmen."""
    if not enabled():
        return "übersprungen"
    from .semantic import embed
    last, done = db.kv_get("history_last_id", 0), 0
    while True:
        rows = _pairs(last)
        if not rows:
            break
        texts = [f"{r['title']}\nFrage: {(r['question'] or '')[:600]}\nAntwort: {(r['answer'] or '')[:900]}" for r in rows]
        for i in range(0, len(rows), 16):
            vecs = await embed(texts[i:i + 16])
            with db.tx() as conn:
                conn.executemany("INSERT OR REPLACE INTO chat_chunks(msg_id,chat_id,user_id,text,vec,created) VALUES(?,?,?,?,?,?)",
                                 [(r["msg_id"], r["chat_id"], r["user_id"], t, v.astype(np.float32).tobytes(), r["created"])
                                  for r, t, v in zip(rows[i:i + 16], texts[i:i + 16], vecs)])
        last = rows[-1]["msg_id"]
        done += len(rows)
        db.kv_set("history_last_id", last)
    return f"{done} Antworten aufgenommen"


async def search(user_id: int, query: str, limit: int = 5, exclude_chat: int | None = None) -> list[dict]:
    rows = db.rows("SELECT k.chat_id, k.text, k.vec, k.created, c.title FROM chat_chunks k JOIN chats c ON c.id=k.chat_id "
                   "WHERE k.user_id=? AND k.chat_id IS NOT ?", (user_id, exclude_chat))
    if not rows:
        return []
    from .semantic import embed
    q = (await embed([query]))[0]
    mat = np.vstack([np.frombuffer(r["vec"], dtype=np.float32) for r in rows])
    scores = mat @ q
    best, seen = [], set()
    for i in np.argsort(-scores):
        r = rows[int(i)]
        if r["chat_id"] in seen or scores[i] < 0.35:
            continue
        seen.add(r["chat_id"])
        best.append({"chat_id": r["chat_id"], "title": r["title"], "text": r["text"], "score": round(float(scores[i]), 3),
                     "date": time.strftime("%d.%m.%Y", time.localtime(r["created"]))})
        if len(best) >= limit:
            break
    return best


def status() -> dict:
    return {"enabled": enabled(), "answers": db.scalar("SELECT COUNT(*) FROM chat_chunks") or 0}
