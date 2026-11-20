"""Weitere Postfächer: Anmeldung mit Benutzername und Passwort über IMAP, Outlook.com über Microsoft-Login.

Gelesen wird nur der Posteingang (bei Gmail „Alle Nachrichten“, das Spam und Papierkorb ausschließt).
Spam-Ordner werden nie geöffnet, Senden ist nicht möglich.
"""
import asyncio
import base64
import datetime as dt
import email
import imaplib
import re
import socket
import ssl
import time
from email.header import decode_header, make_header
from email.message import EmailMessage

from .. import db, security, settings
from . import Cite, Ctx, Result, S, action, tool
from .m365 import GRAPH, search_mail, strip_html

# Anbieter mit bekannten Servern. Alles Weitere geht über „imap“ mit eigenem Server.
# Outlook.com/Hotmail erlaubt seit 2024 keine Passwort-Anmeldung für fremde Programme mehr, daher Microsoft-Login.
PROVIDERS: dict[str, dict] = {
    "gmx": {"label": "GMX", "host": "imap.gmx.net", "setting": "mail.allow_gmx",
            "help": "Bei GMX im Postfach unter Einstellungen › POP3/IMAP Abruf „Zugriff über POP3 und IMAP erlauben“ einschalten. "
                    "Benutzername ist die E-Mail-Adresse, Passwort dein GMX-Passwort."},
    "webde": {"label": "WEB.DE", "host": "imap.web.de",
              "help": "Bei WEB.DE im Postfach unter Einstellungen › POP3/IMAP Abruf „Zugriff über POP3 und IMAP erlauben“ einschalten. "
                      "Benutzername ist die E-Mail-Adresse, Passwort dein WEB.DE-Passwort."},
    "gmail": {"label": "Gmail", "host": "imap.gmail.com", "setting": "mail.allow_gmail", "strip_spaces": True,
              "help": "Google lässt das normale Passwort nicht zu. Unter myaccount.google.com › Sicherheit die Bestätigung in zwei Schritten "
                      "einschalten und dann unter „App-Passwörter“ ein Passwort für Haus-KI erzeugen. Dieses 16-stellige Passwort hier eintragen."},
    "tonline": {"label": "T-Online", "host": "secureimap.t-online.de",
                "help": "Im Telekom-Kundencenter unter E-Mail › E-Mail-Passwort ein eigenes Passwort für E-Mail-Programme festlegen "
                        "und hier eintragen. Das Passwort für das Kundencenter funktioniert nicht."},
    "icloud": {"label": "iCloud", "host": "imap.mail.me.com",
               "help": "Unter account.apple.com › Anmeldung und Sicherheit › App-spezifische Passwörter ein Passwort für Haus-KI erzeugen."},
    "yahoo": {"label": "Yahoo", "host": "imap.mail.yahoo.com",
              "help": "In den Yahoo-Kontoeinstellungen unter Sicherheit ein App-Passwort für Haus-KI erzeugen."},
    "imap": {"label": "Anderer Anbieter (IMAP)", "host": "", "custom": True,
             "help": "Server, Port und Verschlüsselung findest du in der Hilfe deines Anbieters unter „IMAP“ oder „E-Mail-Programm einrichten“. "
                     "Üblich ist Port 993 mit SSL/TLS."},
    "outlookcom": {"label": "Outlook.com / Hotmail", "oauth": True, "setting": "mail.allow_outlookcom",
                   "help": "Microsoft erlaubt für Outlook.com, Hotmail und Live keine Anmeldung mit Passwort in anderen Programmen. "
                           "Du wirst zu Microsoft weitergeleitet und meldest dich dort an."},
}
KINDS = tuple(PROVIDERS)
LABEL = {k: v["label"] for k, v in PROVIDERS.items()}
SECURITY = ("ssl", "starttls")  # unverschlüsselt ist nicht vorgesehen: Passwörter gehen nie im Klartext übers Netz
TIMEOUT = 20


class MailError(Exception):
    """Verständliche Fehlermeldung für die Person, die das Postfach eingerichtet hat."""


def accounts(user_id: int) -> list[dict]:
    q = ",".join("?" * len(KINDS))
    return db.rows(f"SELECT * FROM accounts WHERE user_id=? AND kind IN ({q}) ORDER BY id", (user_id, *KINDS))


def allowed(kind: str) -> bool:
    p = PROVIDERS.get(kind)
    return bool(p and settings.get(p.get("setting", "mail.allow_imap")))


def conf(acc: dict) -> dict:
    """Verbindungsdaten: Vorgaben des Anbieters, überschrieben durch die gespeicherten Angaben."""
    p = PROVIDERS.get(acc["kind"], PROVIDERS["imap"])
    c = {"host": p.get("host", ""), "port": p.get("port", 993), "security": p.get("security", "ssl"), "username": ""}
    saved = db.jload(acc.get("config"), {}) or {}
    c.update({k: v for k, v in saved.items() if k in ("host", "port", "security", "username") and v not in (None, "")}
             if p.get("custom") else {k: v for k, v in saved.items() if k == "username" and v})
    c["port"] = int(c["port"] or 993)
    return c


def clean_password(kind: str, pw: str) -> str:
    # Google zeigt App-Passwörter in Vierergruppen mit Leerzeichen an; echte Passwörter bleiben, wie sie sind.
    return pw.replace(" ", "") if PROVIDERS.get(kind, {}).get("strip_spaces") else pw


def mark(acc_id: int | None, error: str | None) -> None:
    """Letzten Verbindungsstatus merken, damit „Meine Konten“ Probleme zeigt."""
    if not acc_id:
        return
    r = db.row("SELECT config FROM accounts WHERE id=?", (acc_id,))
    if not r:
        return
    c = db.jload(r["config"], {}) or {}
    c.update({"checked": db.now(), "error": error or ""})
    db.run("UPDATE accounts SET config=? WHERE id=?", (db.jdump(c), acc_id))


def _hdr(v) -> str:
    try:
        return str(make_header(decode_header(v or "")))
    except Exception:  # noqa: BLE001
        return v or ""


def _text(msg) -> str:
    def dec(part) -> str:
        payload = part.get_payload(decode=True) or b""
        try:
            return payload.decode(part.get_content_charset() or "utf-8", "replace")
        except LookupError:  # unbekannter Zeichensatz
            return payload.decode("utf-8", "replace")
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain" and "attachment" not in str(part.get("Content-Disposition")):
                return dec(part)
        for part in msg.walk():
            if part.get_content_type() == "text/html":
                return strip_html(dec(part))
        return ""
    text = dec(msg)
    return strip_html(text) if msg.get_content_type() == "text/html" else text


def _friendly(e: Exception, acc: dict, c: dict) -> str:
    host, port = c["host"], c["port"]
    p = PROVIDERS.get(acc["kind"], {})
    hint = "" if p.get("custom") else p.get("help", "")  # bei eigenen Servern hilft der Hinweis auf Port und Server hier nicht
    if isinstance(e, MailError):
        return str(e)
    if isinstance(e, socket.gaierror):
        return f"Den Server {host} gibt es nicht oder er ist nicht erreichbar. Prüfe den Servernamen und die Internetverbindung."
    if isinstance(e, ssl.SSLCertVerificationError):
        return f"Das Zertifikat von {host} ist nicht vertrauenswürdig ({getattr(e, 'verify_message', '') or 'unbekannt'})."
    if isinstance(e, ssl.SSLError):
        return f"Die Verschlüsselung mit {host}:{port} klappt nicht. Üblich ist Port 993 mit SSL/TLS oder Port 143 mit STARTTLS."
    if isinstance(e, (TimeoutError, socket.timeout)):
        return f"{host} antwortet nicht auf Port {port}. Prüfe Server und Port."
    if isinstance(e, ConnectionRefusedError):
        return f"{host} lehnt Verbindungen auf Port {port} ab. Prüfe den Port."
    if isinstance(e, imaplib.IMAP4.error):
        t = str(e).lower()
        if any(x in t for x in ("authenticat", "invalid credentials", "login", "password", "passwort", "username", "benutzer")):
            msg = "Benutzername oder Passwort stimmt nicht."
            if "application-specific" in t or acc["kind"] == "gmail":
                msg += " Gmail braucht ein App-Passwort."
            return f"{msg} {hint}".strip()
        return f"Der Server hat abgelehnt: {str(e)[:160]}"
    if isinstance(e, OSError):
        return f"Keine Verbindung zu {host}:{port} ({e.strerror or e.__class__.__name__})."
    return f"Unerwarteter Fehler: {str(e)[:160] or e.__class__.__name__}"


def _login(m: imaplib.IMAP4, user: str, pw: str) -> None:
    caps = {c.upper() for c in m.capabilities}
    if "AUTH=PLAIN" in caps:
        # SASL PLAIN überträgt Benutzername und Passwort als UTF-8, auch mit Umlauten, ß oder €
        blob = b"\0" + user.encode() + b"\0" + pw.encode()
        m.authenticate("PLAIN", lambda _challenge: blob)
    elif user.isascii() and pw.isascii():
        m.login(user, pw)
    else:
        raise MailError("Dieser Server unterstützt keine Anmeldung mit Umlauten oder Sonderzeichen. "
                        "Ändere das Passwort beim Anbieter oder lege ein App-Passwort an.")


def _connect(acc: dict, password: str | None = None) -> imaplib.IMAP4:
    """Verbindung aufbauen und anmelden. Wirft MailError mit verständlichem Text."""
    c = conf(acc)
    if not c["host"]:
        raise MailError("Bitte den IMAP-Server angeben.")
    ctx = ssl.create_default_context()
    m = None
    try:
        if c["security"] == "starttls":
            m = imaplib.IMAP4(c["host"], c["port"], timeout=TIMEOUT)
            m.starttls(ssl_context=ctx)
        else:
            m = imaplib.IMAP4_SSL(c["host"], c["port"], ssl_context=ctx, timeout=TIMEOUT)
        _login(m, c["username"] or acc["address"], password if password is not None else security.decrypt(acc["secret"]))
        return m
    except Exception as e:  # noqa: BLE001
        if m is not None:
            try:
                m.shutdown()
            except Exception:  # noqa: BLE001
                pass
        raise MailError(_friendly(e, acc, c)) from e


def _logout(m: imaplib.IMAP4) -> None:
    try:
        m.logout()
    except Exception:  # noqa: BLE001
        pass


_LIST = re.compile(r'^\((?P<flags>[^)]*)\)\s+(?P<delim>"(?:[^"\\]|\\.)*"|NIL)\s+(?P<name>.*)$')


def _unquote(name: str) -> str:
    name = name.strip()
    if len(name) >= 2 and name[0] == name[-1] == '"':
        name = re.sub(r'\\(.)', r"\1", name[1:-1])
    return name


def _q(name: str) -> str:
    """Ordnernamen und Suchbegriffe für IMAP in Anführungszeichen setzen."""
    return '"' + name.replace("\\", "\\\\").replace('"', '\\"') + '"'


def folders(m: imaplib.IMAP4) -> list[tuple[set[str], str]]:
    """Alle Ordner mit ihren Kennzeichen (\\Drafts, \\All, \\Junk …), unabhängig von Sprache und Trennzeichen."""
    typ, data = m.list()
    out = []
    for item in data or []:
        if isinstance(item, tuple):  # Ordnername als Literal, z. B. bei Umlauten oder Sonderzeichen
            hit = _LIST.match(item[0].decode("utf-8", "replace").rsplit("{", 1)[0].strip() + " x")
            name = item[1].decode("utf-8", "replace")
        elif isinstance(item, bytes) and item:
            hit = _LIST.match(item.decode("utf-8", "replace"))
            name = _unquote(hit["name"]) if hit else ""
        else:
            continue
        if hit and name:
            out.append(({f.lower() for f in hit["flags"].split()}, name))
    return out


def special(fs: list[tuple[set[str], str]], flag: str, fallbacks: tuple[str, ...] = ()) -> str | None:
    for flags, name in fs:
        if flag.lower() in flags:
            return name
    for flags, name in fs:
        last = re.split(r"[./]", name)[-1].lower()
        if last in fallbacks:
            return name
    return None


def _search_criteria(m: imaplib.IMAP4, query: str, gmail: bool) -> tuple[str | None, list[str]]:
    """Suchbedingungen: jedes Wort einzeln (UND), nicht nur die exakte Wortfolge."""
    words = [w for w in re.findall(r"[^\s\"()]+", query) if len(w) > 1][:6]
    utf8 = bool(getattr(m, "utf8_enabled", False))
    if not utf8 and any(not w.isascii() for w in words) and "UTF8=ACCEPT" in {c.upper() for c in m.capabilities} \
            and "ENABLE" in m.capabilities:
        try:
            m.enable("UTF8=ACCEPT")  # danach versteht der Server Umlaute direkt
            utf8 = True
        except imaplib.IMAP4.error:
            pass
    literal = None
    if not utf8 and any(not w.isascii() for w in words):
        # Ohne UTF-8-Modus geht genau ein Begriff mit Umlauten als Literal, der längste ist am aussagekräftigsten
        literal = max((w for w in words if not w.isascii()), key=len)
        words = [w for w in words if w.isascii()]
    if gmail:
        raw = " ".join(words)
        if literal:
            m.literal = (raw + " " + literal).strip().encode()
            return "UTF-8", ["X-GM-RAW"]
        return None, ["X-GM-RAW", _q(raw or "in:inbox")]
    since = (dt.date.today() - dt.timedelta(days=730)).strftime("%d-%b-%Y")
    crit = ["SINCE", since]
    for w in words:
        crit += ["TEXT", _q(w)]
    if literal:
        m.literal = literal.encode()
        return "UTF-8", crit + ["TEXT"]
    return None, crit


# Zusätzlich zum Posteingang durchsuchte Ordner. Spam und Papierkorb werden nie geöffnet.
EXTRA_BOXES = (("\\Sent", "Gesendet", ("sent", "gesendet", "gesendete objekte", "gesendete elemente", "sent items",
                                        "sent messages", "sent mail")),
               ("\\Archive", "Archiv", ("archive", "archiv", "archives")))
PREVIEW = 65536            # so viel Text pro Treffer laden, Anhänge bleiben auf dem Server
READ_FULL = 10 * 1024**2   # ganze Mail laden bis zu dieser Größe, darüber nur den Textanfang


def search_boxes(m: imaplib.IMAP4, gmail: bool) -> list[tuple[str, str]]:
    """(Ordnername, Anzeigename) der zu durchsuchenden Ordner."""
    fs = folders(m)
    if gmail:
        allbox = special(fs, "\\All")  # „Alle Nachrichten“ enthält Gesendetes und Archiviertes, aber kein Spam
        if allbox:
            return [(allbox, "Alle Nachrichten")]
    out = [("INBOX", "Posteingang")]
    for flag, label, names in EXTRA_BOXES:
        name = special(fs, flag, names)
        if name and name.upper() != "INBOX" and all(name != x for x, _ in out):
            out.append((name, label))
    return out


def _select(m: imaplib.IMAP4, box: str) -> bool:
    typ, _ = m.select(box if box.upper() == "INBOX" else _q(box), readonly=True)
    return typ == "OK"


_META = re.compile(rb'RFC822\.SIZE (\d+)|INTERNALDATE "([^"]+)"')


def _fetch(m: imaplib.IMAP4, uid: str, items: str) -> dict:
    """Eine Mail per UID abrufen und die Teile der Antwort zuordnen."""
    typ, data = m.uid("FETCH", uid, items)
    out = {"header": b"", "text": b"", "body": b"", "size": 0, "ts": 0.0}
    for x in data or []:
        meta = x[0] if isinstance(x, tuple) else x
        if not isinstance(meta, bytes):
            continue
        for size, date in _META.findall(meta):
            if size:
                out["size"] = int(size)
            if date:
                t = imaplib.Internaldate2tuple(b'INTERNALDATE "' + date + b'"')
                out["ts"] = time.mktime(t) if t else 0.0
        if isinstance(x, tuple):
            if b"BODY[HEADER]" in meta:
                out["header"] = x[1]
            elif b"BODY[TEXT]" in meta:
                out["text"] = x[1]
            elif b"BODY[]" in meta:
                out["body"] = x[1]
    return out


def mail_id(acc_id: int, box: str, uid: str) -> str:
    """Stabile Kennung einer Mail: Postfach, Ordner, UID. Für mail_other_read."""
    return f"{acc_id}:{base64.urlsafe_b64encode(box.encode()).decode().rstrip('=')}:{uid}"


def parse_mail_id(mid: str) -> tuple[int, str, str]:
    acc, box, uid = str(mid).split(":", 2)
    if box == "graph":
        return int(acc), box, uid
    return int(acc), base64.urlsafe_b64decode(box + "=" * (-len(box) % 4)).decode(), uid


def _summary(header: bytes, text: bytes, n: int = 1500) -> dict:
    msg = email.message_from_bytes(header + text)
    return {"subject": _hdr(msg["Subject"]), "from": _hdr(msg["From"]), "date": msg["Date"],
            "message_id": (msg["Message-ID"] or "").strip(), "text": re.sub(r"\s+", " ", _text(msg))[:n]}


def _imap_search(acc: dict, query: str, limit: int = 6) -> list[dict]:
    m = _connect(acc)
    try:
        gmail = acc["kind"] == "gmail"
        found = []
        # Schritt 1: in allen Ordnern suchen, nur Kopfzeilen der Treffer laden
        for box, label in search_boxes(m, gmail):
            if not _select(m, box):
                continue
            charset, crit = _search_criteria(m, query, gmail)
            typ, data = m.uid("SEARCH", *((["CHARSET", charset] if charset else []) + crit))
            if typ != "OK":
                continue
            for uid in (data[0] or b"").split()[-limit:]:
                p = _fetch(m, uid.decode(), "(UID RFC822.SIZE INTERNALDATE BODY.PEEK[HEADER])")
                if p["header"]:
                    found.append({"box": box, "label": label, "uid": uid.decode(), **p})
        # Schritt 2: nur für die neuesten Treffer den Textanfang laden, nie die Anhänge
        found = sorted(found, key=lambda f: f["ts"], reverse=True)[:limit]
        out = []
        for box in dict.fromkeys(f["box"] for f in found):
            _select(m, box)
            for f in (x for x in found if x["box"] == box):
                p = _fetch(m, f["uid"], f"(BODY.PEEK[TEXT]<0.{PREVIEW}>)")
                out.append({"id": mail_id(acc["id"], box, f["uid"]), "folder": f["label"], "ts": f["ts"],
                            **_summary(f["header"], p["text"])})
        return sorted(out, key=lambda x: x["ts"], reverse=True)
    except imaplib.IMAP4.error as e:
        raise MailError(_friendly(e, acc, conf(acc))) from e
    finally:
        _logout(m)


def _imap_read(acc: dict, box: str, uid: str) -> dict:
    m = _connect(acc)
    try:
        if not _select(m, box):
            raise MailError("Der Ordner dieser Mail lässt sich nicht mehr öffnen.")
        head = _fetch(m, uid, "(UID RFC822.SIZE INTERNALDATE BODY.PEEK[HEADER])")
        if not head["header"]:
            raise MailError("Diese Mail gibt es im Postfach nicht mehr.")
        if head["size"] <= READ_FULL:
            msg = email.message_from_bytes(_fetch(m, uid, "(BODY.PEEK[])")["body"] or head["header"])
            files = [_hdr(p.get_filename()) for p in msg.walk() if p.get_filename()]
            note = ""
        else:  # sehr große Mail: nur Text, Anhänge bleiben auf dem Server
            msg = email.message_from_bytes(head["header"] + _fetch(m, uid, "(BODY.PEEK[TEXT]<0.262144>)")["text"])
            files, note = [], f"Die Mail ist {head['size'] // 1024**2} MB groß, Anhänge wurden nicht geladen."
        return {"subject": _hdr(msg["Subject"]), "from": _hdr(msg["From"]), "to": _hdr(msg["To"]), "date": msg["Date"],
                "body": _text(msg).strip()[:8000], "attachments": files, "note": note}
    except imaplib.IMAP4.error as e:
        raise MailError(_friendly(e, acc, conf(acc))) from e
    finally:
        _logout(m)


def _imap_recent(acc: dict, since: dt.date, limit: int = 40) -> list[dict]:
    """Neue Mails im Posteingang seit einem Tag (für den Nachtplan), nur Kopf und Textanfang."""
    m = _connect(acc)
    try:
        if not _select(m, "INBOX"):
            return []
        typ, data = m.uid("SEARCH", "SINCE", since.strftime("%d-%b-%Y"))
        out = []
        for uid in (data[0] or b"").split()[-limit:] if typ == "OK" else []:
            u = uid.decode()
            p = _fetch(m, u, "(UID RFC822.SIZE INTERNALDATE BODY.PEEK[HEADER] BODY.PEEK[TEXT]<0.16384>)")
            if p["header"]:
                s = _summary(p["header"], p["text"], 4000)
                out.append({"id": mail_id(acc["id"], "INBOX", u), "ref": s["message_id"] or f"uid{u}", "ts": p["ts"], **s})
        return out
    except imaplib.IMAP4.error as e:
        raise MailError(_friendly(e, acc, conf(acc))) from e
    finally:
        _logout(m)


async def recent(acc: dict, since: dt.date) -> list[dict]:
    """Neue Mails eines Postfachs seit `since`, gleich aufgebaut für IMAP und Outlook.com."""
    if acc["kind"] != "outlookcom":
        return await asyncio.to_thread(_imap_recent, acc, since)
    from . import m365
    async with await m365.client(acc["user_id"], f"outlookcom:{acc['id']}") as c:
        r = await c.get("/me/mailFolders/inbox/messages", params={
            "$filter": f"receivedDateTime ge {since.isoformat()}T00:00:00Z", "$top": 40, "$orderby": "receivedDateTime desc",
            "$select": "id,subject,from,receivedDateTime,bodyPreview,internetMessageId"})
        r.raise_for_status()
    return [{"id": f"{acc['id']}:graph:{x['id']}", "ref": x.get("internetMessageId") or x["id"], "subject": x.get("subject") or "",
             "from": (x.get("from") or {}).get("emailAddress", {}).get("name", ""), "date": x.get("receivedDateTime", ""),
             "text": x.get("bodyPreview", "")} for x in r.json().get("value", [])]


# ---------------------------------------------------------------- Rechnungen und Fristen erkennen (Nachtplan)
_KINDS = (("Mahnung", re.compile(r"\b(mahnung|zahlungserinnerung|letzte erinnerung|inkasso)\b", re.I)),
          ("Rechnung", re.compile(r"\b(rechnung|invoice|beitragsrechnung|jahresabrechnung|zahlungsaufforderung|lastschrift|abbuchung)", re.I)),
          ("Frist", re.compile(r"\b(frist|fällig|kündigung|vertragsende|läuft ab|bis spätestens)", re.I)))
_DUE = re.compile(r"(?:fällig(?:\s+am)?|zahlbar\s+bis(?:\s+zum)?|bis\s+(?:zum|spätestens(?:\s+am|\s+zum)?)|spätestens\s+(?:am|bis(?:\s+zum)?)"
                  r"|frist\D{0,15}|abbuchung\s+am|kündbar\s+bis(?:\s+zum)?|endet\s+am|abgebucht\s+am)\s*:?\s*"
                  r"(\d{1,2})\.\s?(\d{1,2})\.\s?(\d{4}|\d{2})\b", re.I)
_AMOUNT = re.compile(r"(\d{1,3}(?:\.\d{3})*,\d{2})\s?(?:€|EUR)|(?:€|EUR)\s?(\d{1,3}(?:\.\d{3})*,\d{2})", re.I)
_ADS = re.compile(r"newsletter|angebot|rabatt|gutschein|sale\b|\d+\s?%", re.I)


def classify(item: dict, today: dt.date | None = None) -> dict | None:
    """Rechnung, Mahnung oder Frist erkennen. Ohne Sprachmodell: schnell, nachvollziehbar, nachts ohne Last."""
    today = today or dt.date.today()
    subject, text = item.get("subject") or "", item.get("text") or ""
    if _ADS.search(subject):
        return None
    due = None
    for d, mo, y in _DUE.findall(text + " " + subject):
        try:
            cand = dt.date(int(y) + (2000 if len(y) == 2 else 0), int(mo), int(d))
        except ValueError:
            continue
        if today <= cand <= today + dt.timedelta(days=366):
            due = cand
            break
    amount = next((a or b for a, b in _AMOUNT.findall(text + " " + subject)), "")
    for kind, rx in _KINDS:
        # Im Betreff reicht das Stichwort; im Text muss zusätzlich ein Datum oder Betrag stehen
        if rx.search(subject) or (rx.search(text) and (due or amount)):
            return {"kind": kind, "due": due.isoformat() if due else None, "amount": f"{amount} €" if amount else ""}
    return None


def set_conf(acc_id: int, **values) -> None:
    r = db.row("SELECT config FROM accounts WHERE id=?", (acc_id,))
    if r:
        c = db.jload(r["config"], {}) or {}
        c.update(values)
        db.run("UPDATE accounts SET config=? WHERE id=?", (db.jdump(c), acc_id))


def _imap_draft(acc: dict, to: str, subject: str, body: str) -> None:
    m = _connect(acc)
    try:
        box = special(folders(m), "\\Drafts", ("drafts", "entw&apw-rfe", "entwürfe", "draft")) or "Drafts"
        msg = EmailMessage()
        msg["From"], msg["To"], msg["Subject"] = acc["address"], to, subject
        msg.set_content(body)
        typ, data = m.append(_q(box), "(\\Draft)", imaplib.Time2Internaldate(dt.datetime.now().timestamp()), msg.as_bytes())
        if typ != "OK":
            raise MailError(f"Der Entwurf ließ sich nicht im Ordner {box} speichern.")
    finally:
        _logout(m)


def _check(acc: dict, password: str | None = None) -> str:
    m = _connect(acc, password)
    try:
        typ, data = m.select("INBOX", readonly=True)
        n = int(data[0]) if typ == "OK" and data and data[0] and data[0].isdigit() else None
        return "Verbindung steht" + (f", {n} Mails im Posteingang." if n is not None else ".")
    finally:
        _logout(m)


async def test_login(acc: dict, password: str | None = None) -> str:
    """Anmeldung prüfen. Gibt eine kurze Erfolgsmeldung zurück oder wirft MailError."""
    return await asyncio.to_thread(_check, acc, password)


def _pick(ctx: Ctx, which: str | None) -> list[dict]:
    """Postfächer nach Anbieter oder Adresse auswählen; leer = alle freigegebenen."""
    w = (which or "").strip().lower()
    accs = [a for a in accounts(ctx.user["id"]) if allowed(a["kind"]) and a["secret"]]
    if not w:
        return accs
    return [a for a in accs if w in (a["kind"], a["address"].lower(), LABEL[a["kind"]].lower())] or \
        [a for a in accs if w in a["address"].lower() or w in LABEL[a["kind"]].lower()]


async def _search_one(a: dict, query: str) -> tuple[list, list, str]:
    if a["kind"] == "outlookcom":
        from . import m365
        async with await m365.client(a["user_id"], f"outlookcom:{a['id']}") as c:
            r = await search_mail(c, query, "Outlook.com", "Outlook.com")
        items = [dict(x, id=f"{a['id']}:graph:{x['id']}", account=a["address"]) for x in (r.text if isinstance(r.text, list) else [])]
        return items, r.cites, f"Outlook.com ({a['address']})"
    found = await asyncio.to_thread(_imap_search, a, query)
    items = [dict({k: v for k, v in f.items() if k not in ("ts", "message_id")}, account=a["address"]) for f in found]
    cites = [Cite(LABEL[a["kind"]], f["subject"] or "(ohne Betreff)", f"{a['address']} · {f['folder']} · {f['from']}, {f['date']}")
             for f in found]
    return items, cites, f"{LABEL[a['kind']]} ({a['address']})"


@tool("mail_other_search", "mail",
      "Durchsucht die weiteren privaten Postfächer der Person (z. B. GMX, WEB.DE, Gmail, T-Online, iCloud, Outlook.com): "
      "Posteingang, Gesendet und Archiv. Spam wird nie gelesen. Liefert pro Mail eine ID für mail_other_read.",
      {"query": S("Suchbegriffe, Absender oder Betreff"),
       "account": S("Anbieter oder E-Mail-Adresse des Postfachs; leer = alle", optional=True)})
async def search(ctx: Ctx, args: dict) -> Result:
    query = args.get("query", "")
    accs = _pick(ctx, args.get("account"))
    if not accs:
        return Result("Es sind keine passenden weiteren Postfächer verbunden.")
    # Alle Postfächer gleichzeitig durchsuchen, jedes in seiner eigenen Verbindung
    results = await asyncio.gather(*(_search_one(a, query) for a in accs), return_exceptions=True)
    out, cites, steps = [], [], []
    for a, res in zip(accs, results):
        if isinstance(res, Exception):
            text = str(res) if isinstance(res, (MailError, PermissionError)) else f"Postfach nicht erreichbar: {res}"
            mark(a["id"], text[:300])
            out.append({"account": a["address"], "error": text[:300]})
            continue
        items, c, step = res
        out += items
        cites += c
        steps.append(step)
        mark(a["id"], None)
    return Result(out or "Keine passenden Mails gefunden.", cites,
                  f"{', '.join(steps) or 'Postfächer'} durchsucht: „{query}“, {len(cites)} Mails")


@tool("mail_other_read", "mail",
      "Liest eine Mail aus einem weiteren privaten Postfach vollständig, anhand der ID aus mail_other_search.",
      {"id": S("ID der Mail aus mail_other_search")})
async def read(ctx: Ctx, args: dict) -> Result:
    try:
        acc_id, box, uid = parse_mail_id(args.get("id", ""))
    except (ValueError, TypeError):
        return Result("Diese Mail-ID ist ungültig. Bitte zuerst mit mail_other_search suchen.")
    a = next((x for x in _pick(ctx, None) if x["id"] == acc_id), None)
    if not a:
        return Result("Dieses Postfach gibt es nicht oder es ist nicht freigegeben.")
    if box == "graph":
        from . import m365
        async with await m365.client(a["user_id"], f"outlookcom:{a['id']}") as c:
            r = await c.get(f"/me/messages/{uid}", params={"$select": "subject,from,toRecipients,receivedDateTime,body,webLink,hasAttachments"})
            r.raise_for_status()
            x = r.json()
            files = []
            if x.get("hasAttachments"):
                at = await c.get(f"/me/messages/{uid}/attachments", params={"$select": "name"})
                files = [f.get("name", "") for f in at.json().get("value", [])] if at.status_code == 200 else []
        mail = {"subject": x.get("subject"), "from": (x.get("from") or {}).get("emailAddress", {}).get("name"),
                "date": x.get("receivedDateTime"), "body": strip_html(x.get("body", {}).get("content", ""))[:8000], "attachments": files}
        link = x.get("webLink", "")
    else:
        mail = await asyncio.to_thread(_imap_read, a, box, uid)
        link = ""
    return Result(mail, [Cite(LABEL[a["kind"]], mail.get("subject") or "(ohne Betreff)", f"{a['address']} · {mail.get('from')}", link)],
                  f"Mail gelesen: „{mail.get('subject') or '(ohne Betreff)'}“")


@tool("mail_other_draft", "mail",
      "Schlägt einen Entwurf in einem weiteren privaten Postfach vor. Gesendet wird nie.",
      {"account": S("Anbieter oder E-Mail-Adresse des Postfachs"), "to": S("Empfänger"), "subject": S("Betreff"), "body": S("Text")},
      kind="action")
async def draft(ctx: Ctx, args: dict) -> Result:
    accs = _pick(ctx, args.get("account"))
    # Ohne Angabe nur, wenn es genau ein Postfach gibt; sonst wäre unklar, wohin der Entwurf gehört
    acc = accs[0] if accs and (args.get("account") or len(accs) == 1) else None
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
