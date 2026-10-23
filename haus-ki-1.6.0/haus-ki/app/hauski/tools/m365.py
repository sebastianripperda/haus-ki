"""Microsoft 365 über Microsoft Graph mit dem Konto der angemeldeten Person.

Gelesen werden Mail, Kalender, OneDrive und SharePoint. Geschrieben werden nur
Entwürfe und To-Do-Aufgaben, beides nach Bestätigung. Senden ist nicht möglich.
"""
import datetime as dt
import html
import re

import httpx

from .. import auth, db, settings
from . import Cite, Ctx, Result, S, action, tool

GRAPH = "https://graph.microsoft.com/v1.0"
TZ = 'outlook.timezone="Europe/Berlin"'


async def client(user_id: int, audience: str = "graph") -> httpx.AsyncClient:
    tok = await auth.access_token(user_id, audience)
    return httpx.AsyncClient(base_url=GRAPH, timeout=20, headers={"Authorization": f"Bearer {tok}", "Prefer": TZ})


def strip_html(s: str) -> str:
    s = re.sub(r"(?is)<(script|style).*?</\1>", " ", s or "")
    s = re.sub(r"(?i)<br\s*/?>|</p>|</div>", "\n", s)
    s = html.unescape(re.sub(r"<[^>]+>", " ", s))
    return re.sub(r"[ \t]+", " ", re.sub(r"\n\s*\n+", "\n\n", s)).strip()


def _de(iso: str) -> str:
    try:
        d = dt.datetime.fromisoformat(iso[:19])
        return d.strftime("%d.%m.%Y %H:%M")
    except ValueError:
        return iso


async def search_mail(c: httpx.AsyncClient, query: str, label: str, source: str) -> Result:
    junk = (await c.get("/me/mailFolders/junkemail", params={"$select": "id"})).json().get("id")
    r = await c.get("/me/messages", params={"$search": f'"{query}"', "$top": 10,
                                           "$select": "id,subject,from,receivedDateTime,bodyPreview,webLink,parentFolderId"})
    r.raise_for_status()
    msgs = [m for m in r.json().get("value", []) if m.get("parentFolderId") != junk][:6]
    out = [{"id": m["id"], "subject": m.get("subject"), "from": (m.get("from") or {}).get("emailAddress", {}).get("name"),
            "date": _de(m.get("receivedDateTime", "")), "preview": m.get("bodyPreview", "")[:400]} for m in msgs]
    cites = [Cite(source, o["subject"] or "(ohne Betreff)", f"{o['from']}, {o['date']}", m.get("webLink", ""),
                  "In Outlook öffnen") for o, m in zip(out, msgs)]
    return Result(out or "Keine passenden Mails gefunden.", cites, f"{label} durchsucht: „{query}“, {len(out)} Mails")


@tool("m365_mail_search", "m365", "Durchsucht das eigene Outlook-Postfach (Microsoft 365). Spam wird nie gelesen.",
      {"query": S("Suchbegriffe, Absender oder Betreff")})
async def mail_search(ctx: Ctx, args: dict) -> Result:
    if not settings.get("ms.mail"):
        return Result("Mail ist für Microsoft 365 nicht freigegeben.")
    async with await client(ctx.user["id"]) as c:
        return await search_mail(c, args.get("query", ""), "Outlook", "Microsoft 365")


@tool("m365_mail_read", "m365", "Liest eine Mail aus Outlook vollständig, anhand der ID aus m365_mail_search.",
      {"id": S("Nachrichten-ID")})
async def mail_read(ctx: Ctx, args: dict) -> Result:
    async with await client(ctx.user["id"]) as c:
        r = await c.get(f"/me/messages/{args['id']}", params={"$select": "subject,from,receivedDateTime,body,webLink"})
        r.raise_for_status()
        m = r.json()
    return Result({"subject": m.get("subject"), "date": _de(m.get("receivedDateTime", "")),
                   "body": strip_html(m.get("body", {}).get("content", ""))[:5000]},
                  [Cite("Microsoft 365", m.get("subject", ""), _de(m.get("receivedDateTime", "")), m.get("webLink", ""),
                        "In Outlook öffnen")], f"Mail gelesen: {m.get('subject', '')}")


@tool("m365_calendar", "m365", "Liest Termine aus dem eigenen Outlook-Kalender in einem Zeitraum.",
      {"start": S("Startdatum JJJJ-MM-TT"), "end": S("Enddatum JJJJ-MM-TT (einschließlich)")})
async def calendar(ctx: Ctx, args: dict) -> Result:
    if not settings.get("ms.calendar"):
        return Result("Der Kalender ist nicht freigegeben.")
    start = args.get("start") or dt.date.today().isoformat()
    end_d = dt.date.fromisoformat(args.get("end") or start) + dt.timedelta(days=1)
    async with await client(ctx.user["id"]) as c:
        events = await calendar_view(c, "/me/calendarView", start, end_d.isoformat())
    out = [{"subject": e["subject"], "start": _de(e["start"]["dateTime"]), "end": _de(e["end"]["dateTime"]),
            "location": (e.get("location") or {}).get("displayName", "")} for e in events]
    return Result(out or "Keine Termine im Zeitraum.",
                  [Cite("Microsoft 365", "Kalender", f"{len(out)} Termine, {start} bis {args.get('end') or start}")],
                  f"Kalender gelesen: {len(out)} Termine")


async def calendar_view(c: httpx.AsyncClient, path: str, start: str, end: str) -> list[dict]:
    r = await c.get(path, params={"startDateTime": start + "T00:00:00", "endDateTime": end + "T00:00:00",
                                  "$select": "subject,start,end,location,showAs,isAllDay", "$orderby": "start/dateTime",
                                  "$top": 100})
    r.raise_for_status()
    return r.json().get("value", [])


@tool("m365_files_search", "m365", "Durchsucht OneDrive und SharePoint nach Dateien.",
      {"query": S("Dateiname oder Stichwörter")})
async def files_search(ctx: Ctx, args: dict) -> Result:
    if not settings.get("ms.files"):
        return Result("OneDrive und SharePoint sind nicht freigegeben.")
    body = {"requests": [{"entityTypes": ["driveItem"], "query": {"queryString": args.get("query", "")}, "size": 8}]}
    async with await client(ctx.user["id"]) as c:
        r = await c.post("/search/query", json=body)
        r.raise_for_status()
    hits = [h for v in r.json().get("value", []) for hc in v.get("hitsContainers", []) for h in hc.get("hits", [])]
    out, cites = [], []
    for h in hits:
        res = h.get("resource", {})
        out.append({"name": res.get("name"), "summary": strip_html(h.get("summary", "")),
                    "modified": _de(res.get("lastModifiedDateTime", ""))})
        cites.append(Cite("Microsoft 365", res.get("name", ""), _de(res.get("lastModifiedDateTime", "")),
                          res.get("webUrl", ""), "Öffnen"))
    return Result(out or "Keine Dateien gefunden.", cites, f"OneDrive und SharePoint durchsucht, {len(out)} Treffer")


@tool("m365_todo_add", "m365",
      "Schlägt vor, Aufgaben in Microsoft To Do anzulegen, z. B. eine Einkaufsliste. Erst nach Bestätigung.",
      {"items": S("Aufgaben", "array", items={"type": "string"}),
       "list": S("Name der To-Do-Liste", optional=True)}, kind="action")
async def todo_add(ctx: Ctx, args: dict) -> Result:
    if not settings.get("ms.todo"):
        return Result("To Do ist nicht freigegeben.")
    items = [str(i) for i in args.get("items", [])][:60]
    lst = args.get("list") or settings.get("ms.todo_list")
    return Result("Vorschlag erstellt.", action={
        "kind": "todo_add", "summary": f"{len(items)} Einträge in der To-Do-Liste „{lst}“ anlegen?",
        "payload": {"items": items, "list": lst}})


@action("todo_add")
async def do_todo_add(user: dict, p: dict) -> str:
    async with await client(user["id"]) as c:
        lists = (await c.get("/me/todo/lists")).json().get("value", [])
        lst = next((x for x in lists if x["displayName"].lower() == p["list"].lower()), None)
        if not lst:
            lst = (await c.post("/me/todo/lists", json={"displayName": p["list"]})).json()
        for item in p["items"]:
            (await c.post(f"/me/todo/lists/{lst['id']}/tasks", json={"title": item})).raise_for_status()
    return f"{len(p['items'])} Einträge in „{p['list']}“ angelegt."


@tool("m365_mail_draft", "m365",
      "Schlägt vor, einen Mail-Entwurf in Outlook anzulegen. Gesendet wird nie, nur gespeichert.",
      {"to": S("Empfänger-Adresse"), "subject": S("Betreff"), "body": S("Text der Mail")}, kind="action")
async def mail_draft(ctx: Ctx, args: dict) -> Result:
    if not settings.get("ms.mail_drafts"):
        return Result("Entwürfe sind nicht freigegeben.")
    return Result("Vorschlag erstellt.", action={
        "kind": "m365_draft", "summary": f"Entwurf an {args.get('to')} mit Betreff „{args.get('subject')}“ in Outlook speichern?",
        "payload": {k: args.get(k, "") for k in ("to", "subject", "body")}})


@action("m365_draft")
async def do_draft(user: dict, p: dict) -> str:
    async with await client(user["id"]) as c:
        r = await c.post("/me/messages", json={"subject": p["subject"], "body": {"contentType": "Text", "content": p["body"]},
                                              "toRecipients": [{"emailAddress": {"address": p["to"]}}]})
        r.raise_for_status()
    return "Entwurf in Outlook gespeichert. Gesendet wurde nichts."


# ------------------------------------------------------------ Familienkalender-Abgleich (nachts)
async def calendar_conflicts(days: int = 7) -> list[dict]:
    """Überschneidungen zwischen Terminen im gemeinsamen Kalender und persönlichen Terminen.

    Aus persönlichen Kalendern wird nur „belegt“ verwendet, Titel nur aus dem Familienkalender.
    """
    start = dt.date.today()
    end = start + dt.timedelta(days=days)
    owner = settings.get("ms.family_calendar_owner")
    owner_user = db.row("SELECT id FROM users WHERE lower(email)=lower(?)", (owner,)) if owner else None
    if not owner_user:
        return []
    async with await client(owner_user["id"]) as c:
        cals = (await c.get("/me/calendars", params={"$select": "id,name"})).json().get("value", [])
        fam = next((x for x in cals if x["name"].lower() == settings.get("ms.family_calendar_name").lower()), None)
        if not fam:
            return []
        family = await calendar_view(c, f"/me/calendars/{fam['id']}/calendarView", start.isoformat(), end.isoformat())
    family = [e for e in family if not e.get("isAllDay")]
    personal: dict[int, list] = {}
    for u in db.rows("SELECT u.id, u.name FROM users u JOIN ms_tokens t ON t.user_id=u.id AND t.audience='graph' "
                     "WHERE u.disabled=0"):
        try:
            async with await client(u["id"]) as c:
                personal[u["id"]] = [e for e in await calendar_view(c, "/me/calendar/calendarView", start.isoformat(), end.isoformat())
                                     if e.get("showAs") in ("busy", "oof", "tentative") and not e.get("isAllDay")]
        except Exception:  # noqa: BLE001 – ein fehlendes Konto soll den Abgleich nicht stoppen
            continue
    names = {u["id"]: u["name"] for u in db.rows("SELECT id, name FROM users")}
    conflicts = []
    for fe in family:
        fs, fend = fe["start"]["dateTime"][:16], fe["end"]["dateTime"][:16]
        for uid, events in personal.items():
            for pe in events:
                if pe["start"]["dateTime"][:16] < fend and pe["end"]["dateTime"][:16] > fs and pe["subject"] != fe["subject"]:
                    conflicts.append({"when": fs, "family": fe["subject"], "user_id": uid, "user": names.get(uid, ""),
                                      "busy": f"{pe['start']['dateTime'][11:16]} bis {pe['end']['dateTime'][11:16]}"})
    return conflicts
