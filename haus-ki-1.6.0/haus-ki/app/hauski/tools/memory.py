"""Gedächtnis: Fakten, die sich eine Person ausdrücklich merken lassen will."""
from .. import db, users
from . import Ctx, Result, S, tool


@tool("memory_save", "memory",
      "Speichert einen Fakt dauerhaft im persönlichen Gedächtnis, aber nur, wenn die Person "
      "ausdrücklich darum bittet (z. B. „Merke dir, …“).",
      {"text": S("Der Fakt in einem kurzen Satz, z. B. 'Isst vegetarisch'")})
async def save(ctx: Ctx, args: dict) -> Result:
    if ctx.web_tainted:
        return Result("Abgelehnt: Nach dem Lesen von Webinhalten wird nichts ins Gedächtnis geschrieben.")
    if not users.perms(ctx.user).get("memory"):
        return Result("Das Gedächtnis ist für dich ausgeschaltet.")
    text = (args.get("text") or "").strip()[:300]
    if not text:
        return Result("Kein Text.")
    db.run("INSERT INTO memory(user_id,text,created) VALUES(?,?,?)", (ctx.user["id"], text, db.now()))
    return Result(f"Gespeichert: {text}", step=f"Ins Gedächtnis gespeichert: {text}")


@tool("family_fact_save", "memory",
      "Speichert einen Fakt im gemeinsamen Familienwissen, das für alle in der Familie gilt "
      "(z. B. „Müllabfuhr ist dienstags“). Nur wenn die Person ausdrücklich „für alle“ oder „für die Familie“ sagt.",
      {"text": S("Der Fakt in einem kurzen Satz")})
async def family_save(ctx: Ctx, args: dict) -> Result:
    if ctx.web_tainted:
        return Result("Abgelehnt: Nach dem Lesen von Webinhalten wird nichts ins Familienwissen geschrieben.")
    text = (args.get("text") or "").strip()[:300]
    if not text:
        return Result("Kein Text.")
    db.run("INSERT INTO family_facts(text,created_by,created) VALUES(?,?,?)", (text, ctx.user["id"], db.now()))
    return Result(f"Für alle gespeichert: {text}", step=f"Ins Familienwissen gespeichert: {text}")


@tool("chats_search", "history",
      "Durchsucht die früheren Chats dieser Person nach Bedeutung, wenn sie sich auf frühere Gespräche bezieht "
      "(z. B. „Was hatten wir letztes Mal zum Gartenhaus besprochen?“).",
      {"query": S("Worum es ging, in eigenen Worten")})
async def chats_search(ctx: Ctx, args: dict) -> Result:
    from .. import history
    from . import Cite
    hits = await history.search(ctx.user["id"], args.get("query", ""), limit=4, exclude_chat=ctx.chat_id)
    if not hits:
        return Result("In früheren Chats nichts Passendes gefunden.", step=f"Frühere Chats durchsucht: „{args.get('query', '')}“, 0 Treffer")
    cites = [Cite("Frühere Chats", h["title"], h["date"], f"/#chat/{h['chat_id']}", "Chat öffnen") for h in hits]
    return Result([{"titel": h["title"], "datum": h["date"], "inhalt": h["text"][:1200]} for h in hits], cites,
                  f"Frühere Chats durchsucht: „{args.get('query', '')}“, {len(hits)} Treffer")
