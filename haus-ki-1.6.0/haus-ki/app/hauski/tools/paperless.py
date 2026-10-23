"""Paperless-ngx: Suche, Dokumente lesen, Ablegen aus dem Chat, Fristen-Wächter."""
import asyncio
import re

import httpx

from .. import settings, users
from . import Cite, Ctx, Result, S, action, tool


def _token(user: dict | None) -> str:
    if user and settings.get("paperless.personal_tokens"):
        t = users.personal_secret(user["id"], "paperless_token")
        if t:
            return t
    return settings.get("paperless.token")


def client(user: dict | None = None) -> httpx.AsyncClient:
    url = settings.get("paperless.url").rstrip("/")
    if not url:
        raise RuntimeError("Paperless ist nicht eingerichtet.")
    return httpx.AsyncClient(base_url=url, timeout=20, headers={"Authorization": f"Token {_token(user)}",
                                                                 "Accept": "application/json; version=5"})


def doc_url(doc_id) -> str:
    return f"{settings.get('paperless.url').rstrip('/')}/documents/{doc_id}/details"


async def _names(c: httpx.AsyncClient, kind: str) -> dict[int, str]:
    r = await c.get(f"/api/{kind}/", params={"page_size": 1000})
    r.raise_for_status()
    return {x["id"]: x["name"] for x in r.json().get("results", [])}


def _snippet(text: str, query: str, n: int = 1200) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    words = [w for w in re.findall(r"\w{3,}", query.lower())]
    pos = min([p for p in (text.lower().find(w) for w in words) if p >= 0], default=0)
    start = max(0, pos - n // 3)
    return ("…" if start else "") + text[start:start + n] + ("…" if start + n < len(text) else "")


@tool("paperless_search", "paperless",
      "Durchsucht die Dokumente in Paperless-ngx (Rechnungen, Verträge, Briefe, Bescheide). "
      "Liefert die passendsten Dokumente mit Textauszug.",
      {"query": S("Suchbegriffe, z. B. 'Stromrechnung 2025' oder 'Versicherungsschein Hausrat'"),
       "limit": S("Anzahl Dokumente, Standard 4", "integer", optional=True)})
async def search(ctx: Ctx, args: dict) -> Result:
    query = args.get("query", "")
    limit = min(int(args.get("limit") or 4), 8)
    from .. import semantic
    sem, sem_note = [], ""
    if semantic.enabled():
        try:
            sem = await semantic.search(query, limit=limit + 2)
        except Exception as e:  # noqa: BLE001 – Stichwortsuche funktioniert trotzdem
            sem_note = f" (Suche nach Bedeutung nicht verfügbar: {e})"[:120]
    async with client(ctx.user) as c:
        r = await c.get("/api/documents/", params={"query": query, "page_size": limit})
        r.raise_for_status()
        docs = r.json().get("results", [])
        # Treffer beider Suchen zusammenführen (Reciprocal Rank Fusion)
        score: dict[int, float] = {}
        for rank, d in enumerate(docs):
            score[d["id"]] = score.get(d["id"], 0) + 1 / (60 + rank)
        for rank, h in enumerate(sem):
            score[h["id"]] = score.get(h["id"], 0) + 1 / (60 + rank)
        by_id = {d["id"]: d for d in docs}
        snippets = {h["id"]: h["text"] for h in sem}
        order = sorted(score, key=lambda i: -score[i])[:limit]
        for doc_id in order:
            if doc_id not in by_id:
                # Nur aus dem Index gefunden: mit dem Zugang der Person prüfen, ob sie es sehen darf
                rr = await c.get(f"/api/documents/{doc_id}/")
                if rr.status_code == 200:
                    by_id[doc_id] = rr.json()
        docs = [by_id[i] for i in order if i in by_id]
        corr = await _names(c, "correspondents") if docs else {}
    if not docs:
        return Result(f"Keine Dokumente in Paperless zu „{query}“ gefunden.",
                      step=f"Paperless durchsucht: „{query}“, 0 Treffer{sem_note}")
    parts, cites = [], []
    for d in docs:
        name = corr.get(d.get("correspondent"), "")
        date = (d.get("created") or "")[:10]
        cites.append(Cite("Paperless", d.get("title", ""), ", ".join(x for x in [name, _de_date(date)] if x),
                          doc_url(d["id"]), "In Paperless öffnen"))
        text = snippets.get(d["id"]) or _snippet(d.get("content", ""), query)
        parts.append({"title": d.get("title"), "id": d["id"], "correspondent": name, "date": date, "text": text})
    how = "Stichwort und Bedeutung" if sem else "Stichwort"
    return Result(parts, cites, f"Paperless durchsucht ({how}): „{query}“, {len(docs)} Dokumente{sem_note}")


@tool("paperless_document", "paperless",
      "Liest den vollständigen Text eines Paperless-Dokuments anhand seiner ID.",
      {"id": S("Dokument-ID aus paperless_search", "integer")})
async def document(ctx: Ctx, args: dict) -> Result:
    async with client(ctx.user) as c:
        r = await c.get(f"/api/documents/{int(args['id'])}/")
        if r.status_code == 404:
            return Result("Dieses Dokument gibt es nicht oder es ist für dich nicht sichtbar.")
        r.raise_for_status()
        d = r.json()
    text = re.sub(r"\s+", " ", d.get("content", ""))[:6000]
    return Result({"title": d["title"], "date": d.get("created", "")[:10], "text": text},
                  [Cite("Paperless", d["title"], _de_date(d.get("created", "")[:10]), doc_url(d["id"]), "In Paperless öffnen")],
                  f"Dokument gelesen: {d['title']}")


@tool("paperless_set_tags", "paperless",
      "Schlägt vor, Tags eines Paperless-Dokuments zu ergänzen. Wird erst nach Bestätigung ausgeführt.",
      {"id": S("Dokument-ID", "integer"), "tags": S("Tag-Namen", "array", items={"type": "string"})},
      kind="action")
async def set_tags(ctx: Ctx, args: dict) -> Result:
    if not settings.get("paperless.write_tags"):
        return Result("Tags setzen ist in Haus-KI nicht freigegeben.")
    tags = [str(t) for t in args.get("tags", [])][:8]
    return Result("Vorschlag erstellt.", action={
        "kind": "paperless_tags", "summary": f"Tags {', '.join(tags)} an Dokument {args['id']} setzen?",
        "payload": {"id": int(args["id"]), "tags": tags}})


@action("paperless_tags")
async def do_set_tags(user: dict, p: dict) -> str:
    async with client(user) as c:
        ids = await ensure_tags(c, p["tags"])
        d = (await c.get(f"/api/documents/{p['id']}/")).json()
        r = await c.patch(f"/api/documents/{p['id']}/", json={"tags": sorted(set(d.get("tags", []) + ids))})
        r.raise_for_status()
    return f"Tags an Dokument {p['id']} gesetzt."


async def ensure_tags(c: httpx.AsyncClient, names: list[str]) -> list[int]:
    existing = {v.lower(): k for k, v in (await _names(c, "tags")).items()}
    ids = []
    for n in names:
        if n.lower() in existing:
            ids.append(existing[n.lower()])
        else:
            r = await c.post("/api/tags/", json={"name": n})
            r.raise_for_status()
            ids.append(r.json()["id"])
    return ids


async def _ensure(c: httpx.AsyncClient, kind: str, name: str) -> int | None:
    if not name:
        return None
    for k, v in (await _names(c, kind)).items():
        if v.lower() == name.lower():
            return k
    r = await c.post(f"/api/{kind}/", json={"name": name})
    r.raise_for_status()
    return r.json()["id"]


# ------------------------------------------------------------ Ablegen aus dem Chat
async def upload(user: dict, filename: str, data: bytes, content_type: str) -> dict:
    """Übergibt die Datei an Paperless und wartet, bis Texterkennung und Ablage fertig sind."""
    async with client(user) as c:
        r = await c.post("/api/documents/post_document/", files={"document": (filename, data, content_type)})
        r.raise_for_status()
        task_id = r.json() if isinstance(r.json(), str) else r.text.strip('"')
        for _ in range(120):  # bis zu 4 Minuten
            await asyncio.sleep(2)
            t = (await c.get("/api/tasks/", params={"task_id": task_id})).json()
            t = t[0] if isinstance(t, list) and t else t
            status = (t or {}).get("status")
            if status == "SUCCESS":
                doc_id = int(t["related_document"])
                d = (await c.get(f"/api/documents/{doc_id}/")).json()
                return {"id": doc_id, "content": d.get("content", ""), "title": d.get("title", ""), "url": doc_url(doc_id)}
            if status == "FAILURE":
                raise RuntimeError("Paperless konnte das Dokument nicht verarbeiten: " + str(t.get("result", ""))[:200])
    raise RuntimeError("Paperless braucht ungewöhnlich lange. Das Dokument erscheint später in Paperless.")


async def apply_metadata(user: dict, doc_id: int, meta: dict) -> None:
    async with client(user) as c:
        body = {"title": meta.get("title") or None,
                "correspondent": await _ensure(c, "correspondents", meta.get("correspondent", "")),
                "document_type": await _ensure(c, "document_types", meta.get("document_type", "")),
                "tags": await ensure_tags(c, meta.get("tags", []))}
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", meta.get("date", "")):
            body["created"] = meta["date"]
        r = await c.patch(f"/api/documents/{doc_id}/", json={k: v for k, v in body.items() if v is not None})
        r.raise_for_status()


async def delete(user: dict, doc_id: int) -> None:
    async with client(user) as c:
        (await c.delete(f"/api/documents/{doc_id}/")).raise_for_status()


async def recent_documents(since_id: int) -> list[dict]:
    """Für den Fristen-Wächter: neue Dokumente seit der letzten Nacht (zentraler Zugang)."""
    async with client(None) as c:
        r = await c.get("/api/documents/", params={"ordering": "-id", "page_size": 50, "id__gt": since_id})
        r.raise_for_status()
        return r.json().get("results", [])


def _de_date(iso: str) -> str:
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", iso or "")
    return f"{m[3]}.{m[2]}.{m[1]}" if m else ""
