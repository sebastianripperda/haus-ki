"""Suche nach Bedeutung in Paperless.

Nachts zerlegt Haus-KI neue und geänderte Dokumente in Abschnitte und berechnet für jeden
Abschnitt einen Vektor mit einem Embedding-Modell in Ollama (Standard: bge-m3, versteht Deutsch).
Bei einer Frage wird die Frage genauso umgerechnet und mit allen Abschnitten verglichen.

Der Index wird mit dem zentralen Paperless-Zugang aufgebaut. Treffer werden deshalb vor der
Anzeige mit dem Zugang der fragenden Person geprüft: Was sie in Paperless nicht sehen darf,
taucht auch hier nicht auf.
"""
import logging
import re
import time

import httpx
import numpy as np

from . import db, ollama, settings

log = logging.getLogger("hauski.semantic")
CHUNK, OVERLAP, MAX_CHUNKS = 900, 150, 40
_cache: dict = {"ver": -1, "ids": None, "mat": None, "titles": None, "texts": None}


def enabled() -> bool:
    return bool(settings.get("paperless.enabled") and settings.get("paperless.semantic"))


def chunks(text: str) -> list[str]:
    text = re.sub(r"\s+", " ", text or "").strip()
    if not text:
        return []
    out, i = [], 0
    while i < len(text) and len(out) < MAX_CHUNKS:
        end = min(len(text), i + CHUNK)
        if end < len(text):  # an einer Satz- oder Wortgrenze schneiden
            cut = max(text.rfind(". ", i + CHUNK // 2, end), text.rfind(" ", i + CHUNK // 2, end))
            end = cut + 1 if cut > i else end
        out.append(text[i:end].strip())
        if end >= len(text):
            break
        i = max(end - OVERLAP, i + 1)
    return out


async def embed(texts: list[str]) -> np.ndarray:
    async with httpx.AsyncClient(timeout=httpx.Timeout(10, read=600)) as c:
        r = await c.post(ollama.base() + "/api/embed", json={"model": settings.get("paperless.embed_model"), "input": texts,
                                                           "keep_alive": "10m"})
        if r.status_code == 404 or "not found" in r.text:
            raise RuntimeError(f"Das Embedding-Modell {settings.get('paperless.embed_model')} ist in Ollama nicht installiert.")
        r.raise_for_status()
    m = np.asarray(r.json()["embeddings"], dtype=np.float32)
    n = np.linalg.norm(m, axis=1, keepdims=True)
    return m / np.maximum(n, 1e-9)


def _version() -> int:
    return int(db.kv_get("semantic_ver", 0))


def _bump() -> None:
    db.kv_set("semantic_ver", _version() + 1)


def _matrix():
    v = _version()
    if _cache["ver"] != v:
        rows = db.rows("SELECT doc_id, title, text, vec FROM paperless_chunks ORDER BY doc_id, chunk")
        if rows:
            _cache.update(ids=np.array([r["doc_id"] for r in rows]), titles=[r["title"] for r in rows],
                          texts=[r["text"] for r in rows], mat=np.vstack([np.frombuffer(r["vec"], dtype=np.float32) for r in rows]))
        else:
            _cache.update(ids=None, mat=None, titles=None, texts=None)
        _cache["ver"] = v
    return _cache


async def search(query: str, limit: int = 6) -> list[dict]:
    """Beste Dokumente zur Frage, je Dokument der passendste Abschnitt."""
    c = _matrix()
    if c["mat"] is None:
        return []
    q = (await embed([query]))[0]
    scores = c["mat"] @ q
    best: dict[int, tuple[float, int]] = {}
    for idx in np.argsort(-scores)[: limit * 6]:
        doc = int(c["ids"][idx])
        if doc not in best:
            best[doc] = (float(scores[idx]), int(idx))
        if len(best) >= limit:
            break
    return [{"id": d, "score": round(s, 3), "title": c["titles"][i], "text": c["texts"][i]}
            for d, (s, i) in sorted(best.items(), key=lambda x: -x[1][0]) if s > 0.35]


async def index_documents(docs: list[dict]) -> int:
    """Dokumente (mit id, title, content, modified) in den Index aufnehmen oder erneuern."""
    n = 0
    for d in docs:
        parts = chunks(d.get("content") or "")
        if not parts:
            continue
        vecs = []
        for i in range(0, len(parts), 16):
            vecs.append(await embed([f"{d.get('title', '')}: {p}" for p in parts[i:i + 16]]))
        mat = np.vstack(vecs)
        with db.tx() as conn:
            conn.execute("DELETE FROM paperless_chunks WHERE doc_id=?", (d["id"],))
            conn.executemany("INSERT INTO paperless_chunks(doc_id,chunk,title,text,vec,modified) VALUES(?,?,?,?,?,?)",
                             [(d["id"], i, d.get("title", ""), parts[i], mat[i].astype(np.float32).tobytes(), d.get("modified", ""))
                              for i in range(len(parts))])
        _bump()
        n += 1
    return n


async def nightly() -> str:
    """Neue und geänderte Dokumente seit dem letzten Lauf indizieren, gelöschte entfernen."""
    if not enabled() or not settings.get("paperless.token"):
        return "übersprungen"
    from .tools import paperless
    since = db.kv_get("semantic_since", "")
    started = time.strftime("%Y-%m-%dT%H:%M:%S")
    done, page, all_ids = 0, 1, set()
    async with paperless.client(None) as c:
        while True:
            params = {"page": page, "page_size": 50, "ordering": "modified", "fields": "id,title,content,modified"}
            if since:
                params["modified__gt"] = since
            r = await c.get("/api/documents/", params=params)
            r.raise_for_status()
            data = r.json()
            done += await index_documents(data.get("results", []))
            if not data.get("next"):
                break
            page += 1
        # Gelöschte Dokumente aus dem Index nehmen (nur IDs abfragen)
        page = 1
        while True:
            r = await c.get("/api/documents/", params={"page": page, "page_size": 500, "fields": "id"})
            r.raise_for_status()
            data = r.json()
            all_ids |= {x["id"] for x in data.get("results", [])}
            if not data.get("next"):
                break
            page += 1
    removed = 0
    if all_ids:
        known = {r["doc_id"] for r in db.rows("SELECT DISTINCT doc_id FROM paperless_chunks")}
        for gone in known - all_ids:
            db.run("DELETE FROM paperless_chunks WHERE doc_id=?", (gone,))
            removed += 1
        if removed:
            _bump()
    db.kv_set("semantic_since", started)
    return f"{done} Dokumente indiziert" + (f", {removed} entfernt" if removed else "")


def status() -> dict:
    return {"docs": db.scalar("SELECT COUNT(DISTINCT doc_id) FROM paperless_chunks") or 0,
            "chunks": db.scalar("SELECT COUNT(*) FROM paperless_chunks") or 0,
            "since": db.kv_get("semantic_since", ""), "model": settings.get("paperless.embed_model"), "enabled": enabled()}
