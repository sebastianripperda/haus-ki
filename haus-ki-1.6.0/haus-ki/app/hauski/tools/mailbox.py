"""Weitere Postfächer: GMX und Gmail über IMAP mit App-Passwort, Outlook.com über Microsoft-Login.

Gelesen wird nur der Posteingang (bei Gmail „Alle Nachrichten“, das Spam ausschließt).
Spam-Ordner werden nie geöffnet, Senden ist nicht möglich.
"""
import asyncio
import datetime as dt
import email
import imaplib
import re
from email.header import decode_header, make_header
from email.message import EmailMessage

from .. import db, security, settings
from . import Cite, Ctx, Result, S, action, tool
from .m365 import GRAPH, search_mail, strip_html

HOSTS = {"gmx": "imap.gmx.net", "gmail": "imap.gmail.com"}
LABEL = {"gmx": "GMX", "gmail": "Gmail", "outlookcom": "Outlook.com"}


def accounts(user_id: int) -> list[dict]:
    return db.rows("SELECT * FROM accounts WHERE user_id=? AND kind IN ('gmx','gmail','outlookcom') ORDER BY id", (user_id,))


def allowed(kind: str) -> bool:
    return bool(settings.get(f"mail.allow_{kind}"))


def _hdr(v) -> str:
    try:
        return str(make_header(decode_header(v or "")))
    except Exception:  # noqa: BLE001
        return v or ""


def _text(msg) -> str:
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain" and "attachment" not in str(part.get("Content-Disposition")):
                return part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8", "replace")
        for part in msg.walk():
            if part.get_content_type() == "text/html":
                return strip_html(part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8", "replace"))
        return ""
    payload = msg.get_payload(decode=True) or b""
    text = payload.decode(msg.get_content_charset() or "utf-8", "replace")
    return strip_html(text) if msg.get_content_type() == "text/html" else text


def _imap(acc: dict) -> imaplib.IMAP4_SSL:
    m = imaplib.IMAP4_SSL(HOSTS[acc["kind"]], 993, timeout=20)
    m.login(acc["address"], security.decrypt(acc["secret"]))
    return m


def _imap_search(acc: dict, query: str) -> list[dict]:
    m = _imap(acc)
    try:
        if acc["kind"] == "gmail":
            m.select('"[Gmail]/All Mail"', readonly=True)
            typ, data = m.search(None, "X-GM-RAW", '"' + query.replace('"', "") + '"')
        else:
            m.select("INBOX", readonly=True)
            since = (dt.date.today() - dt.timedelta(days=730)).strftime("%d-%b-%Y")
            m.literal = query.encode()
            typ, data = m.search("UTF-8", "SINCE", since, "TEXT")
        ids = (data[0] or b"").split()[-6:][::-1]
        out = []
        for i in ids:
            typ, raw = m.fetch(i, "(BODY.PEEK[])")
            msg = email.message_from_bytes(raw[0][1])
            out.append({"subject": _hdr(msg["Subject"]), "from": _hdr(msg["From"]), "date": msg["Date"],
                        "text": re.sub(r"\s+", " ", _text(msg))[:1500]})
        return out
    finally:
        try:
            m.logout()
        except Exception:  # noqa: BLE001
            pass


def _imap_draft(acc: dict, to: str, subject: str, body: str) -> None:
    m = _imap(acc)
    try:
        typ, folders = m.list()
        drafts = None
        for f in folders or []:
            line = f.decode()
            if "\\Drafts" in line:
                drafts = line.split(' "/" ')[-1].strip()
        drafts = drafts or ('"[Gmail]/Drafts"' if acc["kind"] == "gmail" else "Entw&APw-rfe")
        msg = EmailMessage()
        msg["From"], msg["To"], msg["Subject"] = acc["address"], to, subject
        msg.set_content(body)
        m.append(drafts, "\\Draft", imaplib.Time2Internaldate(dt.datetime.now().timestamp()), msg.as_bytes())
    finally:
        m.logout()


async def test_login(acc: dict) -> None:
    def t():
        _imap(acc).logout()
    await asyncio.to_thread(t)


@tool("mail_other_search", "mail",
      "Durchsucht die weiteren Postfächer der Person (GMX, Gmail, Outlook.com). Spam wird nie gelesen.",
      {"query": S("Suchbegriffe"), "account": S("gmx, gmail oder outlookcom; leer = alle", optional=True)})
async def search(ctx: Ctx, args: dict) -> Result:
    query = args.get("query", "")
    accs = [a for a in accounts(ctx.user["id"]) if allowed(a["kind"]) and (not args.get("account") or a["kind"] == args["account"])]
    if not accs:
        return Result("Es sind keine weiteren Postfächer verbunden.")
    out, cites, steps = [], [], []
    for a in accs:
        try:
            if a["kind"] == "outlookcom":
                from . import m365
                async with await m365.client(a["user_id"], f"outlookcom:{a['id']}") as c:
                    r = await search_mail(c, query, "Outlook.com", "Outlook.com")
                out += [dict(x, account=a["address"]) for x in (r.text if isinstance(r.text, list) else [])]
                cites += r.cites
            else:
                found = await asyncio.to_thread(_imap_search, a, query)
                out += [dict(x, account=a["address"]) for x in found]
                cites += [Cite(LABEL[a["kind"]], f["subject"] or "(ohne Betreff)", f"{f['from']}, {f['date']}") for f in found]
            steps.append(LABEL[a["kind"]])
        except Exception as e:  # noqa: BLE001
            out.append({"account": a["address"], "error": f"Postfach nicht erreichbar: {e}"[:200]})
    return Result(out or "Keine passenden Mails gefunden.", cites,
                  f"{', '.join(steps) or 'Postfächer'} durchsucht: „{query}“, {len(cites)} Mails")


@tool("mail_other_draft", "mail",
      "Schlägt einen Entwurf in einem weiteren Postfach vor (GMX, Gmail, Outlook.com). Gesendet wird nie.",
      {"account": S("gmx, gmail oder outlookcom"), "to": S("Empfänger"), "subject": S("Betreff"), "body": S("Text")},
      kind="action")
async def draft(ctx: Ctx, args: dict) -> Result:
    acc = next((a for a in accounts(ctx.user["id"]) if a["kind"] == args.get("account")), None)
    if not acc or not acc["drafts"] or not settings.get("mail.drafts"):
        return Result("Entwürfe sind für dieses Postfach nicht erlaubt.")
    return Result("Vorschlag erstellt.", action={
        "kind": "mail_draft", "summary": f"Entwurf an {args.get('to')} in {LABEL[acc['kind']]} ({acc['address']}) speichern?",
        "payload": {"account_id": acc["id"], **{k: args.get(k, "") for k in ("to", "subject", "body")}}})


@action("mail_draft")
async def do_draft(user: dict, p: dict) -> str:
    acc = db.row("SELECT * FROM accounts WHERE id=? AND user_id=?", (p["account_id"], user["id"]))
    if not acc:
        raise PermissionError("Postfach nicht gefunden.")
    if acc["kind"] == "outlookcom":
        from . import m365
        async with await m365.client(user["id"], f"outlookcom:{acc['id']}") as c:
            (await c.post("/me/messages", json={"subject": p["subject"], "body": {"contentType": "Text", "content": p["body"]},
                                               "toRecipients": [{"emailAddress": {"address": p["to"]}}]})).raise_for_status()
    else:
        await asyncio.to_thread(_imap_draft, acc, p["to"], p["subject"], p["body"])
    return f"Entwurf in {LABEL[acc['kind']]} gespeichert. Gesendet wurde nichts."


__all__ = ["GRAPH"]
