"""Postfächer gegen einen echten IMAP-Server (Dovecot), der für den Test gestartet wird.

Läuft, wenn Dovecot installiert ist und die Tests als root laufen (z. B. im Haus-KI-Container:
apt install dovecot-imapd). Sonst wird er übersprungen. Der Server ist absichtlich „schwierig“
eingerichtet: Umlaut-Passwort, eigener Benutzername, "." als Ordner-Trennzeichen, deutsche Ordnernamen,
SSL/TLS und STARTTLS.

Start:  cd app && HAUSKI_DEV=1 python3 -m pytest -q tests/test_imap_dovecot.py
"""
import asyncio
import datetime as dt
import imaplib
import os
import shutil
import socket
import ssl
import subprocess
import tempfile
import time
from email.message import EmailMessage

os.environ.setdefault("HAUSKI_DEV", "1")
os.environ.setdefault("HAUSKI_DATA", tempfile.mkdtemp())
os.environ.setdefault("HAUSKI_SETUP_CODE", "TEST-123")
os.environ.setdefault("HAUSKI_BOOTSTRAP", "/nonexistent")

import pytest  # noqa: E402

pytestmark = pytest.mark.skipif(not shutil.which("dovecot") or os.geteuid() != 0,
                                reason="Dovecot nicht installiert oder Tests nicht als root")

PW = "Grüße-Straße€1"          # Umlaute, ß und € im Passwort
TOM_PW = "has space 123"      # Leerzeichen müssen erhalten bleiben
DUE = dt.date.today() + dt.timedelta(days=30)


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _cert(d: str) -> str:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID
    import ipaddress
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    now = dt.datetime.now(dt.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - dt.timedelta(days=1))
            .not_valid_after(now + dt.timedelta(days=7))
            .add_extension(x509.SubjectAlternativeName([x509.DNSName("localhost"), x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]), False)
            .add_extension(x509.BasicConstraints(ca=True, path_length=None), True)
            .sign(key, hashes.SHA256()))
    with open(f"{d}/cert.pem", "wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))
    with open(f"{d}/key.pem", "wb") as f:
        f.write(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    return f"{d}/cert.pem"


@pytest.fixture(scope="module")
def dovecot():
    d = tempfile.mkdtemp(prefix="hkdv-")
    os.chmod(d, 0o755)
    run = tempfile.mkdtemp(prefix="hkr-", dir="/tmp")  # kurzer Pfad, Unix-Sockets vertragen keine langen
    cert = _cert(d)
    os.makedirs(f"{d}/mail")
    shutil.chown(f"{d}/mail", "nobody", "nogroup")
    with open(f"{d}/users", "w", encoding="utf-8") as f:
        f.write(f"anna@gmx.test:{{PLAIN}}{PW}::::::\ntom:{{PLAIN}}{TOM_PW}::::::\n")
    os.chmod(f"{d}/users", 0o644)
    ssl_port, tls_port = _free_port(), _free_port()
    conf = f"""protocols = imap
listen = 127.0.0.1
base_dir = {run}
state_dir = {d}/state
log_path = {d}/dovecot.log
ssl = yes
ssl_cert = <{d}/cert.pem
ssl_key = <{d}/key.pem
disable_plaintext_auth = yes
auth_mechanisms = plain login
default_internal_user = dovecot
default_login_user = dovenull
service imap-login {{
  inet_listener imap {{
    port = {tls_port}
  }}
  inet_listener imaps {{
    port = {ssl_port}
    ssl = yes
  }}
}}
passdb {{
  driver = passwd-file
  args = scheme=PLAIN username_format=%u {d}/users
}}
userdb {{
  driver = static
  args = uid=nobody gid=nogroup home={d}/mail/%u
}}
mail_location = maildir:~/Maildir
namespace inbox {{
  inbox = yes
  separator = .
  mailbox Entwürfe {{
    special_use = \\Drafts
    auto = subscribe
  }}
  mailbox "Gesendete Objekte" {{
    special_use = \\Sent
    auto = subscribe
  }}
  mailbox Archiv {{
    auto = subscribe
  }}
  mailbox Spam {{
    special_use = \\Junk
    auto = subscribe
  }}
}}
"""
    with open(f"{d}/dovecot.conf", "w", encoding="utf-8") as f:
        f.write(conf)
    subprocess.run(["dovecot", "-c", f"{d}/dovecot.conf"], check=True)
    for _ in range(50):
        try:
            socket.create_connection(("127.0.0.1", ssl_port), 0.2).close()
            break
        except OSError:
            time.sleep(0.1)
    yield {"ssl": ssl_port, "tls": tls_port, "cert": cert, "dir": d}
    subprocess.run(["doveadm", "-c", f"{d}/dovecot.conf", "stop"], check=False)
    shutil.rmtree(d, ignore_errors=True)
    shutil.rmtree(run, ignore_errors=True)


def _seed(port: int, cert: str) -> None:
    m = imaplib.IMAP4_SSL("127.0.0.1", port, ssl_context=ssl.create_default_context(cafile=cert))
    m.authenticate("PLAIN", lambda _: b"\0anna@gmx.test\0" + PW.encode())
    t = time.time()
    def put(box, subj, body, attach=None, age=0):
        e = EmailMessage()
        e["From"], e["To"], e["Subject"] = "Absender <a@b.de>", "anna@gmx.test", subj
        e["Message-ID"] = f"<{abs(hash(subj))}@test>"
        e.set_content(body)
        if attach:
            e.add_attachment(attach, maintype="application", subtype="pdf", filename="Rechnung.pdf")
        m.append(box, None, imaplib.Time2Internaldate(t - age), e.as_bytes())
    put("INBOX", "Ihre Rechnung Oktober", f"Hallo, anbei die Telekom Abrechnung über 39,95 EUR. Fällig am {DUE:%d.%m.%Y}.", age=50)
    put("INBOX", "Termin beim Arzt", "Herr Müller bestätigt Ihren Termin am Freitag.", age=40)
    put("INBOX", "Großer Anhang Telekom", "Siehe Anlage. " + "Langer Text. " * 400, attach=os.urandom(3 * 1024 * 1024), age=30)
    put('"Gesendete Objekte"', "Antwort an Telekom Kundenservice", "Ich habe die Telekom Rechnung bezahlt.", age=20)
    put("Archiv", "Alter Telekom Vertrag", "Archivierter Telekom Vertrag von 2020.", age=10)
    put("Spam", "Telekom Gewinnspiel", "Sie haben gewonnen! Telekom", age=5)
    m.logout()


@pytest.fixture(scope="module")
def mailenv(dovecot):
    from fastapi.testclient import TestClient
    from hauski import db, security, users
    from hauski.main import app
    _seed(dovecot["ssl"], dovecot["cert"])
    os.environ["SSL_CERT_FILE"] = dovecot["cert"]
    with TestClient(app) as c:
        c.headers["x-haus-ki"] = "1"
        uid = users.create("Postfach-Test", "member")
        sid = security.token()
        db.run("INSERT INTO sessions(id,user_id,created,last_seen) VALUES(?,?,?,?)", (sid, uid, db.now(), db.now()))
        c.cookies.set("hk_session", sid)
        yield c, db.row("SELECT * FROM users WHERE id=?", (uid,)), dovecot
    os.environ.pop("SSL_CERT_FILE", None)


def _ctx(user):
    from hauski.tools import Ctx
    return Ctx(user=user, perms={}, sources={"mail"})


def test_connection_errors_are_explained(mailenv):
    c, user, dv = mailenv
    base = {"kind": "imap", "address": "anna@gmx.test", "host": "127.0.0.1", "port": dv["ssl"], "security": "ssl"}
    def err(**kw):
        r = c.post("/api/accounts", json={**base, **kw})
        assert r.status_code == 400, r.text
        return r.json()["detail"]
    assert "Passwort stimmt nicht" in err(password="falsch")
    assert "lehnt Verbindungen" in err(password=PW, port=_free_port())
    assert "Verschlüsselung" in err(password=PW, port=dv["tls"])
    assert "gibt es nicht" in err(password=PW, host="imap.nicht-vorhanden.invalid")
    os.environ["SSL_CERT_FILE"] = "/nonexistent"
    try:
        assert "Zertifikat" in err(password=PW)
    finally:
        os.environ["SSL_CERT_FILE"] = dv["cert"]


def test_login_variants(mailenv):
    c, user, dv = mailenv
    r = c.post("/api/accounts", json={"kind": "imap", "address": "anna@gmx.test", "host": "127.0.0.1", "port": dv["ssl"],
                                      "security": "ssl", "password": PW})
    assert r.status_code == 200, r.text
    assert "Mails im Posteingang" in r.json()["text"]
    r = c.post("/api/accounts", json={"kind": "imap", "address": "tom@example.test", "username": "tom", "host": "127.0.0.1",
                                      "port": dv["tls"], "security": "starttls", "password": TOM_PW})
    assert r.status_code == 200, r.text
    from hauski import db
    assert PW not in str(db.rows("SELECT * FROM accounts"))


def test_search_folders_and_speed(mailenv):
    from hauski.tools import mailbox
    c, user, dv = mailenv
    res = asyncio.run(mailbox.search(_ctx(user), {"query": "Telekom", "account": "anna@gmx.test"}))
    got = {x["subject"]: x["folder"] for x in res.text}
    assert got.get("Antwort an Telekom Kundenservice") == "Gesendet"
    assert got.get("Alter Telekom Vertrag") == "Archiv"            # per Name gefunden, ohne Kennzeichen
    assert got.get("Ihre Rechnung Oktober") == "Posteingang"
    assert "Telekom Gewinnspiel" not in got                        # Spam nie
    assert list(got)[0] == "Alter Telekom Vertrag"                 # neueste zuerst, über Ordner hinweg
    big = next(x for x in res.text if x["subject"] == "Großer Anhang Telekom")
    assert len(big["text"]) <= 1500 and "JVBER" not in big["text"]  # Anhang wurde nicht geladen
    res = asyncio.run(mailbox.search(_ctx(user), {"query": "Rechnung Telekom"}))
    assert "Ihre Rechnung Oktober" in [x.get("subject") for x in res.text]
    res = asyncio.run(mailbox.search(_ctx(user), {"query": "Müller Termin", "account": "gmx.test"}))
    assert [x["subject"] for x in res.text] == ["Termin beim Arzt"]


def test_read_full_mail(mailenv):
    from hauski.tools import mailbox
    c, user, dv = mailenv
    res = asyncio.run(mailbox.search(_ctx(user), {"query": "Anhang", "account": "anna@gmx.test"}))
    mid = res.text[0]["id"]
    full = asyncio.run(mailbox.read(_ctx(user), {"id": mid}))
    assert full.text["subject"] == "Großer Anhang Telekom" and full.text["attachments"] == ["Rechnung.pdf"]
    assert len(full.text["body"]) > 1500
    sent = asyncio.run(mailbox.search(_ctx(user), {"query": "Kundenservice", "account": "anna@gmx.test"}))
    assert asyncio.run(mailbox.read(_ctx(user), {"id": sent.text[0]["id"]})).text["subject"] == "Antwort an Telekom Kundenservice"
    assert "ungültig" in asyncio.run(mailbox.read(_ctx(user), {"id": "quatsch"})).text
    assert "nicht freigegeben" in asyncio.run(mailbox.read(_ctx(user), {"id": "999:SU5CT1g:1"})).text


def test_drafts_and_password_change(mailenv):
    from hauski import db
    from hauski.tools import mailbox
    c, user, dv = mailenv
    accs = {a["address"]: a for a in c.get("/api/accounts").json()["accounts"]}
    anna, tom = accs["anna@gmx.test"]["id"], accs["tom@example.test"]["id"]
    c.patch(f"/api/accounts/{anna}", json={"drafts": True})
    asyncio.run(mailbox.do_draft(user, {"account_id": anna, "to": "x@y.de", "subject": "Entwurf Test", "body": "Hallo"}))
    m = mailbox._connect(db.row("SELECT * FROM accounts WHERE id=?", (anna,)))
    box = mailbox.special(mailbox.folders(m), "\\Drafts")
    m.select(mailbox._q(box), readonly=True)
    assert box == "Entw&APw-rfe" and len(m.search(None, "SUBJECT", '"Entwurf Test"')[1][0].split()) == 1
    m.logout()
    before = db.row("SELECT secret FROM accounts WHERE id=?", (tom,))["secret"]
    r = c.patch(f"/api/accounts/{tom}", json={"password": "anders"})
    assert r.status_code == 400 and db.row("SELECT secret FROM accounts WHERE id=?", (tom,))["secret"] == before
    assert c.post(f"/api/accounts/{tom}/test").json()["ok"]
    assert c.patch(f"/api/accounts/{tom}", json={"port": dv["ssl"], "security": "ssl"}).status_code == 200


def test_night_scan_finds_invoice(mailenv):
    from hauski import db, scheduler
    c, user, dv = mailenv
    detail = asyncio.run(scheduler.task_mail())
    assert "Rechnung oder Frist" in detail
    found = [db.jload(i["data"]) for i in db.rows("SELECT * FROM insights WHERE user_id=? AND kind='mail'", (user["id"],))]
    inv = next(f for f in found if f["title"] == "Ihre Rechnung Oktober")
    assert inv["due"] == DUE.isoformat() and inv["amount"] == "39,95 €" and inv["kind"] == "Rechnung"
    assert "Termin beim Arzt" not in [f["title"] for f in found]
    n = len(found)
    asyncio.run(scheduler.task_mail())  # zweiter Lauf legt nichts doppelt an
    assert db.scalar("SELECT COUNT(*) FROM insights WHERE user_id=? AND kind='mail'", (user["id"],)) == n
