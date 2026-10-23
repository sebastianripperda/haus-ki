"""Tests für Haus-KI. Ollama wird durch eine Attrappe ersetzt.

Start:  cd app && HAUSKI_DEV=1 python3 -m pytest -q tests
"""
import datetime as dt
import re
import json
import os
import tempfile

os.environ["HAUSKI_DEV"] = "1"
os.environ["HAUSKI_DATA"] = tempfile.mkdtemp()
os.environ["HAUSKI_SETUP_CODE"] = "TEST-123"
os.environ["HAUSKI_BOOTSTRAP"] = "/nonexistent"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from hauski import db, ollama, scheduler, security, settings  # noqa: E402
from hauski.main import app  # noqa: E402

SCRIPT: list = []  # Antworten der Attrappe, je Aufruf ein Eintrag


async def fake_chat_stream(model, messages, tools=None, opts=None, think=None, fmt=None):
    if fmt == "json":
        yield {"message": {"content": json.dumps({"fragen": ["Und 2024?", "Noch etwas?"]})}, "done": True}
        return
    step = SCRIPT.pop(0) if SCRIPT else {"text": "Hallo [1]!"}
    if "tools" in step:
        yield {"message": {"role": "assistant", "content": "", "tool_calls": [
            {"function": {"name": n, "arguments": a}} for n, a in step["tools"]]}, "done": True}
        return
    for w in step["text"].split(" "):
        yield {"message": {"content": w + " "}, "done": False}
    yield {"message": {"content": ""}, "done": True, "eval_count": 5, "eval_duration": 1e9, "prompt_eval_count": 100}


@pytest.fixture(scope="module")
def client():
    ollama.chat_stream = fake_chat_stream
    with TestClient(app) as c:
        c.headers["x-haus-ki"] = "1"
        r = c.post("/api/setup", json={"code": "TEST-123", "name": "Anna", "password": "sehr-geheim-123"})
        assert r.status_code == 200, r.text
        yield c


def ask(c, text, **kw):
    r = c.post("/api/chats", json={"text": text, **kw})
    assert r.status_code == 200, r.text
    d = r.json()
    events = []
    with c.stream("GET", f"/api/jobs/{d['job_id']}/events") as s:
        for line in s.iter_lines():
            if line.startswith("data: "):
                ev = json.loads(line[6:])
                events.append(ev)
                if ev["type"] == "end":
                    break
    return d, events


def test_setup_only_once(client):
    r = client.post("/api/setup", json={"code": "TEST-123", "name": "X", "password": "x" * 12})
    assert r.status_code == 409


def test_csrf_header_required(client):
    r = client.post("/api/memory", json={"text": "x"}, headers={"x-haus-ki": ""})
    assert r.status_code == 403


def test_simple_answer_and_followups(client):
    d, ev = ask(client, "Hallo")
    text = "".join(e["text"] for e in ev if e["type"] == "delta")
    assert "Hallo" in text
    chat = client.get(f"/api/chats/{d['chat_id']}").json()
    assert [m["role"] for m in chat["messages"]] == ["user", "assistant"]
    assert chat["messages"][1]["meta"]["followups"] == ["Und 2024?", "Noch etwas?"]


def test_memory_tool(client):
    SCRIPT[:] = [{"tools": [("memory_save", {"text": "Isst vegetarisch"})]}, {"text": "Gemerkt."}]
    ask(client, "Merke dir, dass ich vegetarisch esse")
    assert any(m["text"] == "Isst vegetarisch" for m in client.get("/api/memory").json())


def _enable_knx():
    settings.set_many({"knx.enabled": True, "knx.gateway_ip": "192.0.2.1", "web.enabled": True})
    db.run("INSERT OR REPLACE INTO knx_ga(address,name,dpt,room,permission,locked) VALUES('1/1/1','Licht Bad','1.001','Bad','write',0)")
    db.run("INSERT OR REPLACE INTO knx_ga(address,name,dpt,room,permission,locked) VALUES('9/9/9','Garagentor','1.001','Garage','read',1)")


def test_web_content_cannot_trigger_actions(client):
    _enable_knx()
    SCRIPT[:] = [{"tools": [("web_search", {"query": "x"}), ("knx_set", {"address": "1/1/1", "value": "an"})]}, {"text": "Ok."}]
    d, ev = ask(client, "Lies die Seite und mach das Licht an", sources=["web", "knx"])
    assert not [e for e in ev if e["type"] == "action"], "Aktion trotz Webinhalt vorgeschlagen"
    assert any("blockiert" in e.get("text", "") for e in ev if e["type"] == "step")
    assert db.scalar("SELECT COUNT(*) FROM audit WHERE text LIKE '%blockiert%'") >= 1


def test_action_needs_confirmation(client):
    _enable_knx()
    SCRIPT[:] = [{"tools": [("knx_set", {"address": "1/1/1", "value": "an"})]}, {"text": "Soll ich?"}]
    d, ev = ask(client, "Mach das Licht im Bad an", sources=["knx"])
    acts = [e for e in ev if e["type"] == "action"]
    assert len(acts) == 1 and "Licht Bad" in acts[0]["summary"]
    assert db.row("SELECT status FROM actions WHERE id=?", (acts[0]["id"],))["status"] == "pending"
    r = client.post(f"/api/actions/{acts[0]['id']}", json={"approve": False}).json()
    assert r["status"] == "rejected"
    r = client.post(f"/api/actions/{acts[0]['id']}", json={"approve": True})
    assert r.status_code == 400  # nicht mehr offen


def test_locked_device_never_writable(client):
    _enable_knx()
    SCRIPT[:] = [{"tools": [("knx_set", {"address": "9/9/9", "value": "an"})]}, {"text": "Geht nicht."}]
    d, ev = ask(client, "Öffne das Garagentor", sources=["knx"])
    assert not [e for e in ev if e["type"] == "action"]
    r = client.post("/api/knx/write", json={"address": "9/9/9", "value": True})
    assert r.status_code == 403


def test_member_cannot_admin_and_admin_read_is_logged(client):
    from hauski import users
    uid = users.create("Leo", "member")
    sid = security.token()
    db.run("INSERT INTO sessions(id,user_id,created,last_seen) VALUES(?,?,?,?)", (sid, uid, db.now(), db.now()))
    m = TestClient(app, cookies={"hk_session": sid})
    m.headers["x-haus-ki"] = "1"
    assert m.get("/api/admin/settings").status_code == 403
    cid = db.run("INSERT INTO chats(user_id,title,created,updated) VALUES(?,?,?,?)", (uid, "Hausaufgaben", db.now(), db.now()))
    assert client.get(f"/api/chats/{cid}").json()["readonly"] is True
    assert db.scalar("SELECT COUNT(*) FROM audit WHERE category='Einsicht'") >= 1
    assert client.post(f"/api/chats/{cid}/messages", json={"text": "x"}).status_code == 403


def test_emergency_lockout(client):
    for _ in range(5):
        r = client.post("/auth/emergency", json={"user_id": 1, "password": "falsch-falsch-1"})
    r = client.post("/auth/emergency", json={"user_id": 1, "password": "sehr-geheim-123"})
    assert r.status_code == 429
    db.run("UPDATE users SET locked_until=0, failed_logins=0 WHERE id=1")


def test_secrets_are_encrypted_and_hidden(client):
    client.put("/api/admin/settings", json={"paperless.token": "geheim-123"})
    raw = db.row("SELECT value FROM settings WHERE key='paperless.token'")["value"]
    assert "geheim" not in raw
    assert client.get("/api/admin/settings").json()["values"]["paperless.token"] == {"set": True}
    assert settings.get("paperless.token") == "geheim-123"


def test_schedule_next_run():
    s = {"freq": "weekly", "day": "Mo", "time": "07:00"}
    n = scheduler.next_run(s, dt.datetime(2026, 10, 21, 12, 0))  # Mittwoch
    assert n == dt.datetime(2026, 10, 26, 7, 0)
    assert scheduler.next_run({"freq": "daily", "day": None, "time": "06:30"}, dt.datetime(2026, 10, 21, 7, 0)) == dt.datetime(2026, 10, 22, 6, 30)
    assert scheduler.next_run({"freq": "monthly", "day": None, "time": "08:00"}, dt.datetime(2026, 10, 21)) == dt.datetime(2026, 11, 1, 8, 0)


def test_backup_and_retention(client):
    name = scheduler.backup_now("test")
    assert any(b["name"] == name for b in scheduler.list_backups())
    old = db.now() - 200 * 86400
    db.run("INSERT INTO chats(user_id,title,created,updated) VALUES(1,'alt',?,?)", (old, old))
    db.run("INSERT INTO chats(user_id,title,pinned,created,updated) VALUES(1,'alt angeheftet',1,?,?)", (old, old))
    scheduler.retention()
    titles = {r["title"] for r in db.rows("SELECT title FROM chats")}
    assert "alt" not in titles and "alt angeheftet" in titles


def test_password_hash():
    h = security.hash_password("korrekt-pferd-1")
    assert security.verify_password("korrekt-pferd-1", h) and not security.verify_password("falsch", h)


# ------------------------------------------------------------ Paperless mit nachgebildeter API
def _fake_paperless(monkeypatch):
    import httpx
    from hauski.tools import paperless
    state = {"tags": {1: "Strom"}, "patched": None, "deleted": None}

    def handler(req: httpx.Request) -> httpx.Response:
        p = req.url.path
        if p == "/api/documents/" and req.method == "GET":
            return httpx.Response(200, json={"count": 1, "results": [{"id": 7, "title": "Jahresabrechnung Strom 2025", "correspondent": 3,
                                                                       "created": "2026-02-12", "content": "Stadtwerke Musterstadt Gesamtbetrag 1.184,20 EUR", "tags": [1]}]})
        if p == "/api/correspondents/":
            return httpx.Response(200, json={"results": [{"id": 3, "name": "Stadtwerke Musterstadt"}]}) if req.method == "GET" else httpx.Response(201, json={"id": 4})
        if p == "/api/document_types/":
            return httpx.Response(200, json={"results": []}) if req.method == "GET" else httpx.Response(201, json={"id": 5})
        if p == "/api/tags/":
            if req.method == "GET":
                return httpx.Response(200, json={"results": [{"id": k, "name": v} for k, v in state["tags"].items()]})
            state["tags"][9] = json.loads(req.content)["name"]
            return httpx.Response(201, json={"id": 9})
        if p == "/api/documents/post_document/":
            return httpx.Response(200, json="task-1")
        if p == "/api/tasks/":
            return httpx.Response(200, json=[{"status": "SUCCESS", "related_document": "42"}])
        if p == "/api/documents/42/" and req.method == "GET":
            return httpx.Response(200, json={"id": 42, "title": "scan", "content": "Rechnung Zahlbar bis 15.11.2026"})
        if p == "/api/documents/42/" and req.method == "PATCH":
            state["patched"] = json.loads(req.content)
            return httpx.Response(200, json={})
        if p == "/api/documents/42/" and req.method == "DELETE":
            state["deleted"] = 42
            return httpx.Response(204)
        return httpx.Response(404)

    monkeypatch.setattr(paperless, "client", lambda user=None: httpx.AsyncClient(base_url="http://pl", transport=httpx.MockTransport(handler)))
    monkeypatch.setattr("asyncio.sleep", _no_sleep)
    settings.set_many({"paperless.enabled": True, "paperless.url": "http://pl", "paperless.upload": True})
    return state


async def _no_sleep(*a, **k):
    return None


def test_paperless_search_cites(client, monkeypatch):
    _fake_paperless(monkeypatch)
    SCRIPT[:] = [{"tools": [("paperless_search", {"query": "Strom 2025"})]}, {"text": "1.184,20 € [1]."}]
    d, ev = ask(client, "Was habe ich 2025 für Strom bezahlt?", sources=["paperless"])
    cites = [e for e in ev if e["type"] == "cites"][-1]["items"]
    assert cites[0]["title"] == "Jahresabrechnung Strom 2025" and "Stadtwerke" in cites[0]["meta"]
    assert any("Paperless durchsucht" in e["text"] for e in ev if e["type"] == "step")


def test_paperless_upload_and_apply(client, monkeypatch):
    state = _fake_paperless(monkeypatch)

    async def fake_json(model, prompt, system="", num_predict=600):
        return {"title": "Rechnung Stadtwerke", "correspondent": "Stadtwerke Musterstadt", "document_type": "Rechnung",
                "date": "2026-10-28", "tags": ["Strom", "Rechnung"], "deadline": "2026-11-15", "summary": "Eine Stromrechnung."}
    monkeypatch.setattr(ollama, "complete_json", fake_json)
    r = client.post("/api/paperless/upload", files={"file": ("brief.jpg", b"\xff\xd8bild", "image/jpeg")})
    assert r.status_code == 200, r.text
    d = r.json()
    with client.stream("GET", f"/api/jobs/{d['job_id']}/events") as s:
        events = [json.loads(line[6:]) for line in s.iter_lines() if line.startswith("data: ")]
    prop = next(e for e in events if e["type"] == "paperless")
    r = client.post(f"/api/paperless/decide/{prop['message_id']}", json={"approve": True, "title": "Stromrechnung Oktober", "tags": ["Strom", "Rechnung"]})
    assert r.status_code == 200 and r.json()["state"] == "saved"
    assert state["patched"]["title"] == "Stromrechnung Oktober" and state["patched"]["correspondent"] == 3
    assert any(d["due"] == "2026-11-15" for d in client.get("/api/start").json()["deadlines"])


def test_proxmox_uses_container_api(monkeypatch):
    import asyncio
    import httpx
    from hauski import system
    seen = []

    def handler(req):
        seen.append(req.url.path)
        return httpx.Response(200, json={"data": {"status": "running", "cpu": 0.42, "cpus": 8, "mem": 6e9, "maxmem": 40e9, "name": "ollama"}})
    monkeypatch.setattr(system, "_pve", lambda: httpx.AsyncClient(base_url="https://pve/api2/json", transport=httpx.MockTransport(handler)))
    settings.set_many({"proxmox.node": "pve", "proxmox.vmid": 105, "proxmox.kind": "lxc"})
    st = asyncio.run(system.vm_status())
    assert seen[-1] == "/api2/json/nodes/pve/lxc/105/status/current" and st["cpu"] == 42 and st["kind"] == "lxc"
    asyncio.run(system.vm_control("reboot"))
    assert seen[-1] == "/api2/json/nodes/pve/lxc/105/status/reboot"


def test_proxmox_uses_lxc_paths(monkeypatch):
    import asyncio
    import httpx
    from hauski import system
    seen = []

    def handler(req):
        seen.append(req.url.path)
        return httpx.Response(200, json={"data": {"status": "running", "cpu": 0.42, "cpus": 8, "mem": 6e9, "maxmem": 40e9}})
    monkeypatch.setattr(system, "_pve", lambda: httpx.AsyncClient(base_url="https://pve/api2/json", transport=httpx.MockTransport(handler)))
    settings.set_many({"proxmox.node": "pve", "proxmox.vmid": 105, "proxmox.kind": "lxc"})
    st = asyncio.run(system.vm_status())
    asyncio.run(system.vm_control("reboot"))
    assert seen == ["/api2/json/nodes/pve/lxc/105/status/current", "/api2/json/nodes/pve/lxc/105/status/reboot"]
    assert st["cpu"] == 42 and st["cpus"] == 8 and st["kind"] == "lxc"


# ------------------------------------------------------------ Sprache
def test_voice_text_preparation_and_yes_no():
    from hauski.voice import interpret_yes_no, prepare_speech
    t = prepare_speech("Du hast **1.184,20 €** bezahlt [1].\n\n| A | B |\n|---|---|\n| 1 | 2 |\n\nAm 01.03.2026 waren es 21,5 °C.")
    assert "eintausendeinhundertvierundachtzig Euro zwanzig" in t and "[1]" not in t
    assert "Tabelle mit 1 Zeilen" in t and "01.03.2026" in t and "einundzwanzig Komma fünf Grad" in t
    assert interpret_yes_no("Ja, mach das.") == "yes"
    assert interpret_yes_no("Ja aber nicht das Bad") == "no"
    assert interpret_yes_no("vielleicht später") == "unclear"
    assert interpret_yes_no("Ja ich glaube das passt so eigentlich schon") == "unclear"


def test_voice_stt_and_tts(client, monkeypatch):
    from hauski import voice
    monkeypatch.setattr(voice, "transcribe_sync", lambda data, suffix: {"text": "Wie warm ist es im Bad?", "audio_seconds": 2.1, "seconds": 0.4})
    r = client.post("/api/voice/stt", files={"file": ("a.webm", b"\x1a\x45\xdf\xa3" + b"0" * 4000, "audio/webm")})
    assert r.status_code == 200 and r.json()["text"] == "Wie warm ist es im Bad?"

    def nothing(data, suffix):
        raise voice.NothingHeard()
    monkeypatch.setattr(voice, "transcribe_sync", nothing)
    r = client.post("/api/voice/stt", files={"file": ("a.webm", b"0" * 4000, "audio/webm")})
    assert r.status_code == 422 and "nichts verstanden" in r.json()["detail"]
    assert client.post("/api/voice/stt", files={"file": ("a.webm", b"0" * 100, "audio/webm")}).status_code == 422

    spoken = {}

    def fake_synth(text, v, speed):
        spoken.update(text=text, voice=v, speed=speed)
        import io, wave
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(22050); w.writeframes(b"\0\0" * 22050)
        return buf.getvalue()
    monkeypatch.setattr(voice, "synth_sync", fake_synth)
    monkeypatch.setattr(voice, "installed_voices", lambda: ["de_DE-kerstin-low", "de_DE-thorsten-high"])
    client.put("/api/me/prefs", json={"voice": "de_DE-thorsten-high", "voice_speed": "fast"})
    r = client.post("/api/voice/tts", json={"text": "Das kostet 99 € [2]."})
    assert r.status_code == 200 and r.headers["content-type"] == "audio/wav" and r.content[:4] == b"RIFF"
    assert spoken == {"text": "Das kostet neunundneunzig Euro.", "voice": "de_DE-thorsten-high", "speed": "fast"}
    assert client.get("/api/voice/info").json()["my_voice"] == "de_DE-thorsten-high"
    assert client.get("/api/admin/voice").json()["stats"]["stt_count"] >= 1


def test_voice_confirmation_of_actions(client, monkeypatch):
    from hauski import tools
    _enable_knx()
    settings.set_many({"voice.confirm": True})
    calls = []

    async def fake_write(user, p):
        calls.append(p)
        return f"{p['name']} gesetzt."
    monkeypatch.setitem(tools.ACTIONS, "knx_write", fake_write)

    def propose():
        SCRIPT[:] = [{"tools": [("knx_set", {"address": "1/1/1", "value": "an"})]}, {"text": "Soll ich?"}]
        d, ev = ask(client, "Mach das Licht im Bad an", sources=["knx"])
        return [e for e in ev if e["type"] == "action"][0]["id"]

    aid = propose()
    r = client.post(f"/api/actions/{aid}/voice", json={"text": "vielleicht später"}).json()
    assert r["status"] == "unclear" and db.row("SELECT status FROM actions WHERE id=?", (aid,))["status"] == "pending"
    r = client.post(f"/api/actions/{aid}/voice", json={"text": "Ja, mach das"}).json()
    assert r["status"] == "done" and calls and calls[0]["address"] == "1/1/1"
    assert db.scalar("SELECT COUNT(*) FROM audit WHERE text LIKE '%per Sprache%'") >= 1

    aid = propose()
    assert client.post(f"/api/actions/{aid}/voice", json={"text": "Nein, lieber nicht"}).json()["status"] == "rejected"

    settings.set_many({"voice.confirm": False})
    aid = propose()
    assert client.post(f"/api/actions/{aid}/voice", json={"text": "Ja"}).status_code == 403
    settings.set_many({"voice.confirm": True})


def test_voice_respects_permission(client):
    from hauski import users
    uid = users.create("Gast", "member")
    db.run("UPDATE users SET perms=? WHERE id=?", ('{"voice": false}', uid))
    sid = security.token()
    db.run("INSERT INTO sessions(id,user_id,created,last_seen) VALUES(?,?,?,?)", (sid, uid, db.now(), db.now()))
    m = TestClient(app, cookies={"hk_session": sid})
    m.headers["x-haus-ki"] = "1"
    assert m.get("/api/me").json()["features"]["voice"] is False
    assert m.post("/api/voice/tts", json={"text": "Hallo"}).status_code == 403


# ------------------------------------------------------------ Schneller und besser antworten
def test_system_prompt_is_stable_and_time_goes_into_question():
    from hauski import chat, users
    u = users.get(1)
    s1, _ = chat.system_prompt(u, None)
    assert not re.search(r"\d{1,2}:\d{2}", s1) and "Uhrzeit steht am Ende" in s1
    cid = db.run("INSERT INTO chats(user_id,title,created,updated) VALUES(1,'t',?,?)", (db.now(), db.now()))
    mid = db.run("INSERT INTO messages(chat_id,role,content,meta,created) VALUES(?,?,?,?,?)", (cid, "user", "Hallo", "{}", db.now()))
    h = chat.history(cid, mid, 10000)
    assert h[-1]["content"].startswith("Hallo") and "[Uhrzeit:" in h[-1]["content"]
    assert db.row("SELECT content FROM messages WHERE id=?", (mid,))["content"] == "Hallo"  # nicht gespeichert


def test_simple_questions_use_fast_model(client):
    from hauski import chat
    settings.set_many({"ollama.route_simple": True, "ollama.fast_model": "qwen3:4b"})
    assert chat.is_simple("Mach das Licht im Bad an", {}, 0)
    assert not chat.is_simple("Fasse mir bitte die Stromrechnungen der letzten drei Jahre zusammen und vergleiche sie", {}, 0)
    assert not chat.is_simple("Licht an", {"attachments": [{"name": "x"}]}, 0)
    d, ev = ask(client, "Wie warm ist es im Bad?")
    meta = client.get(f"/api/chats/{d['chat_id']}").json()["messages"][1]["meta"]
    assert meta["model"] == "qwen3:4b" and meta["routed"] == "einfache Frage"
    settings.set_many({"ollama.route_simple": False})
    d, ev = ask(client, "Wie warm ist es im Bad?")
    assert client.get(f"/api/chats/{d['chat_id']}").json()["messages"][1]["meta"]["model"] == "qwen3:8b"


def test_tool_calls_are_logged(client):
    SCRIPT[:] = [{"tools": [("gibt_es_nicht", {}), ("memory_save", {"text": "Mag Tee"})]}, {"text": "Ok."}]
    ask(client, "Merke dir, dass ich Tee mag")
    q = client.get("/api/admin/quality").json()
    tools = {t["tool"]: t for t in q["tools"]}
    assert tools["gibt_es_nicht"]["errors"] >= 1 and tools["memory_save"]["errors"] == 0


def test_feedback_comment_and_rerun(client):
    d, ev = ask(client, "Wie heißt die Hauptstadt von Frankreich?")
    mid = client.get(f"/api/chats/{d['chat_id']}").json()["messages"][1]["id"]
    client.post(f"/api/messages/{mid}/feedback", json={"value": -1, "comment": "Falsche Stadt genannt"})
    bad = client.get("/api/admin/quality").json()["bad"]
    assert bad[0]["comment"] == "Falsche Stadt genannt" and bad[0]["question"].startswith("Wie heißt")
    r = client.post(f"/api/admin/quality/rerun/{mid}").json()
    assert db.row("SELECT kind FROM chats WHERE id=?", (r["chat_id"],))["kind"] == "eval"


def _fake_embed(monkeypatch):
    import numpy as np
    from hauski import semantic

    async def embed(texts):
        out = []
        for t in texts:
            v = np.zeros(64, dtype=np.float32)
            for w in re.findall(r"\w{4,}", t.lower()):
                v[hash(w[:5]) % 64] += 1
            out.append(v / max(np.linalg.norm(v), 1e-9))
        return np.vstack(out)
    monkeypatch.setattr(semantic, "embed", embed)
    return semantic


def test_semantic_search_respects_paperless_rights(client, monkeypatch):
    import asyncio
    import numpy as np
    state = _fake_paperless(monkeypatch)
    semantic = _fake_embed(monkeypatch)
    settings.set_many({"paperless.semantic": True, "paperless.token": "zentral"})
    out = asyncio.run(semantic.nightly())
    assert "indiziert" in out
    vec = asyncio.run(semantic.embed(["Versicherungsschein Hausrat Prämie jährlich"]))[0]
    for doc in (42, 99):  # 42 darf die Person sehen, 99 nicht (Paperless antwortet 404)
        db.run("INSERT OR REPLACE INTO paperless_chunks(doc_id,chunk,title,text,vec,modified) VALUES(?,?,?,?,?,?)",
               (doc, 0, f"Hausrat {doc}", "Versicherungsschein Hausrat Prämie jährlich", vec.astype(np.float32).tobytes(), ""))
    semantic._bump()
    SCRIPT[:] = [{"tools": [("paperless_search", {"query": "Versicherungsschein Hausrat"})]}, {"text": "Gefunden [1]."}]
    d, ev = ask(client, "Was kostet unsere Hausratversicherung?", sources=["paperless"])
    titles = [c["title"] for c in [e for e in ev if e["type"] == "cites"][-1]["items"]]
    steps = [e["text"] for e in ev if e["type"] == "step"]
    assert any("Bedeutung" in s for s in steps)
    assert "scan" in titles or any("42" in t for t in titles)        # Dokument 42 (sichtbar) ist dabei
    assert not any("99" in t for t in titles)                        # Dokument 99 (nicht sichtbar) nie


# ------------------------------------------------------------ Bedienung: Push und Updates
def test_push_subscription(client):
    key = client.get("/api/push/key").json()["key"]
    assert len(key) > 80  # öffentlicher VAPID-Schlüssel (65 Byte, base64url)
    assert client.post("/api/push/subscribe", json={"endpoint": "http://unsicher", "keys": {}}).status_code == 400
    sub = {"endpoint": "https://push.example/abc", "keys": {"p256dh": "BOr" + "A" * 84, "auth": "xyzxyzxyzxyzxyzx"}}
    assert client.post("/api/push/subscribe", json=sub).status_code == 200
    assert client.get("/api/push/key").json()["devices"] == 1
    client.post("/api/push/unsubscribe", json={"endpoint": sub["endpoint"]})
    assert client.get("/api/push/key").json()["devices"] == 0


def test_update_check_and_checksum(client, monkeypatch):
    import asyncio, hashlib, httpx
    from hauski import update
    from hauski.config import config
    pkg = b"\x1f\x8b" + b"paket" * 100
    good = hashlib.sha256(pkg).hexdigest()
    state = {"sha": good}

    def handler(req):
        if req.url.path.endswith("/releases/latest"):
            return httpx.Response(200, json={"tag_name": "v9.9.9", "body": "Neu: alles besser", "assets": [
                {"name": "haus-ki-9.9.9.tar.gz", "browser_download_url": "https://dl/haus-ki-9.9.9.tar.gz"},
                {"name": "haus-ki-9.9.9.tar.gz.sha256", "browser_download_url": "https://dl/haus-ki-9.9.9.tar.gz.sha256"}]})
        if req.url.path.endswith(".sha256"):
            return httpx.Response(200, text=f"{state['sha']}  haus-ki-9.9.9.tar.gz\n")
        return httpx.Response(200, content=pkg)
    real = httpx.AsyncClient
    monkeypatch.setattr(update.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **{k: v for k, v in kw.items() if k != "transport"}))
    settings.set_many({"update.source": "github:familie/haus-ki"})
    info = client.post("/api/admin/update/check").json()
    assert info["available"] and info["version"] == "9.9.9" and info["sha256"] == good
    r = client.post("/api/admin/update/install-available")
    assert r.status_code == 200 and (config.update_dir / "incoming.tar.gz").read_bytes() == pkg
    assert json.loads((config.update_dir / "request").read_text())["version"] == "9.9.9"
    state["sha"] = "0" * 64  # manipuliertes Paket: Prüfsumme passt nicht
    client.post("/api/admin/update/check")
    r = client.post("/api/admin/update/install-available")
    assert r.status_code == 400 and "Prüfsumme" in r.json()["detail"]
    settings.set_many({"update.source": ""})


def test_pwa_files_are_served(client):
    m = client.get("/manifest.webmanifest")
    assert m.status_code == 200 and m.json()["share_target"]["action"] == "/share"
    sw = client.get("/sw.js")
    assert sw.status_code == 200 and sw.headers.get("service-worker-allowed") == "/" and "receiveShare" in sw.text
    for f in json.loads(m.text)["icons"]:
        assert client.get(f["src"]).status_code == 200


# ------------------------------------------------------------ Einfache Ansicht, Familienwissen, alte Chats
def _member_client(name, perms='{}'):
    from hauski import users
    uid = users.create(name, "member")
    db.run("UPDATE users SET perms=? WHERE id=?", (perms, uid))
    sid = security.token()
    db.run("INSERT INTO sessions(id,user_id,created,last_seen) VALUES(?,?,?,?)", (sid, uid, db.now(), db.now()))
    m = TestClient(app, cookies={"hk_session": sid})
    m.headers["x-haus-ki"] = "1"
    return m, uid


def test_simple_ui_defaults(client):
    assert client.get("/api/me").json()["prefs"]["simple_ui"] is False          # Administrator: volle Ansicht
    m, _ = _member_client("Mia2")
    assert m.get("/api/me").json()["prefs"]["simple_ui"] is True                # Mitglied: einfache Ansicht
    assert m.put("/api/me/prefs", json={"simple_ui": False}).json()["simple_ui"] is False


def test_family_knowledge(client):
    from hauski import chat, users
    fid = client.post("/api/family", json={"text": "Die Müllabfuhr kommt dienstags"}).json()["id"]
    m, uid = _member_client("Leo2")
    assert any(f["text"].startswith("Die Müllabfuhr") for f in m.get("/api/family").json())
    prompt, _ = chat.system_prompt(users.get(uid), None)
    assert "Gemeinsames Familienwissen" in prompt and "Müllabfuhr kommt dienstags" in prompt
    assert m.delete(f"/api/family/{fid}").status_code == 403                   # fremder Eintrag
    own = m.post("/api/family", json={"text": "Leo hat dienstags Schwimmen"}).json()["id"]
    assert m.delete(f"/api/family/{own}").status_code == 200
    SCRIPT[:] = [{"tools": [("family_fact_save", {"text": "Die Katze heißt Mimi"})]}, {"text": "Für alle gemerkt."}]
    ask(client, "Merke dir für alle: Die Katze heißt Mimi")
    assert db.scalar("SELECT COUNT(*) FROM family_facts WHERE text='Die Katze heißt Mimi'") == 1
    client.delete(f"/api/family/{fid}")


def test_search_old_chats_only_own(client, monkeypatch):
    import asyncio
    from hauski import history
    _fake_embed(monkeypatch)
    settings.set_many({"history.semantic": True})
    SCRIPT[:] = [{"text": "Für das Gartenhaus brauchst du ab 30 Kubikmeter eine Baugenehmigung."}]
    d_own, _ = ask(client, "Brauche ich für das Gartenhaus eine Baugenehmigung?")
    m, uid = _member_client("Gast2")
    cid = db.run("INSERT INTO chats(user_id,title,created,updated) VALUES(?,?,?,?)", (uid, "Gartenhaus Geheimnis", db.now(), db.now()))
    db.run("INSERT INTO messages(chat_id,role,content,meta,created) VALUES(?,?,?,?,?)", (cid, "user", "Gartenhaus Baugenehmigung Kubikmeter", "{}", db.now()))
    db.run("INSERT INTO messages(chat_id,role,content,meta,created) VALUES(?,?,?,?,?)", (cid, "assistant", "Gartenhaus Baugenehmigung Kubikmeter privat", "{}", db.now()))
    asyncio.run(history.index_new())
    SCRIPT[:] = [{"tools": [("chats_search", {"query": "Gartenhaus Baugenehmigung"})]}, {"text": "Das hatten wir besprochen [1]."}]
    d, ev = ask(client, "Was hatten wir zum Gartenhaus besprochen?")
    cites = [e for e in ev if e["type"] == "cites"][-1]["items"]
    assert any(c["url"] == f"/#chat/{d_own['chat_id']}" for c in cites)
    assert not any(c["url"] == f"/#chat/{cid}" for c in cites)               # fremder Chat nie
    hits = client.get("/api/search", params={"q": "Baugenehmigung Gartenhaus Kubikmeter"}).json()
    assert d_own["chat_id"] in [h["id"] for h in hits] and cid not in [h["id"] for h in hits]
    db.run("DELETE FROM chats WHERE id=?", (d_own["chat_id"],))
    assert db.scalar("SELECT COUNT(*) FROM chat_chunks WHERE chat_id=?", (d_own["chat_id"],)) == 0  # gelöscht = aus dem Index


# ------------------------------------------------------------ Weniger Rückfragen, Einführung, Modellvergleich
def test_harmless_actions_without_confirmation(client, monkeypatch):
    from hauski import tools
    from hauski.tools.knx import category
    _enable_knx()
    db.run("INSERT OR REPLACE INTO knx_ga(address,name,dpt,room,permission,locked) VALUES('2/2/2','Rollladen Bad','1.008','Bad','write',0)")
    assert category({"name": "Licht Bad", "dpt": "1.001"}) == "knx_light"
    assert category({"name": "Rollladen Bad", "dpt": "1.008"}) == "knx_blind"
    assert category({"name": "Steckdose Waschmaschine", "dpt": "1.001"}) == "knx_other"
    calls = []

    async def fake_write(user, p):
        calls.append(p["address"])
        return f"{p['name']} gesetzt."
    monkeypatch.setitem(tools.ACTIONS, "knx_write", fake_write)
    settings.set_many({"actions.auto_allowed": ["knx_light", "knx_blind"]})
    # Unerlaubtes wird beim Speichern herausgefiltert
    assert client.put("/api/me/prefs", json={"auto_actions": ["knx_light", "mail_draft"]}).json()["auto_actions"] == ["knx_light"]

    def run(address, extra=None):
        SCRIPT[:] = (extra or []) + [{"tools": [("knx_set", {"address": address, "value": "an"})]}, {"text": "Erledigt."}]
        d, ev = ask(client, "Mach das an", sources=["knx", "web"])
        acts = [e for e in ev if e["type"] == "action"]
        return (acts[0] if acts else {"status": "kein Vorschlag"}), [e["text"] for e in ev if e["type"] == "step"]

    act, steps = run("1/1/1")
    assert act["status"] == "done" and act.get("auto") and calls == ["1/1/1"] and any("Ohne Rückfrage" in s for s in steps)
    act, _ = run("2/2/2")                                              # Rollladen: Person hat ihn nicht gewählt
    assert act["status"] == "pending" and calls == ["1/1/1"]
    act, _ = run("1/1/1", [{"tools": [("web_search", {"query": "x"})]}])  # nach Webinhalten nie
    assert act["status"] == "kein Vorschlag" and calls == ["1/1/1"]
    settings.set_many({"actions.auto_allowed": ["knx_blind"]})        # Administrator nimmt Licht heraus
    act, _ = run("1/1/1")
    assert act["status"] == "pending" and calls == ["1/1/1"]
    assert db.scalar("SELECT COUNT(*) FROM audit WHERE text LIKE '%ohne Rückfrage%'") >= 1
    settings.set_many({"actions.auto_allowed": ["knx_light", "knx_blind", "jellyfin_play"]})
    client.put("/api/me/prefs", json={"auto_actions": []})


def test_onboarding_flag(client):
    m, _ = _member_client("Neu3")
    assert m.get("/api/me").json()["prefs"]["onboarded"] is False
    assert m.put("/api/me/prefs", json={"onboarded": True}).json()["onboarded"] is True


def test_model_comparison(client):
    import time as _t
    r = client.post("/api/admin/quality/compare", json={"model_a": "qwen3:8b", "model_b": "llama3.2:3b"}).json()
    assert r["questions"] == 6
    assert client.post("/api/admin/quality/compare", json={"model_a": "qwen3:8b", "model_b": "qwen3:8b"}).status_code == 400
    for _ in range(100):
        res = [x for x in client.get("/api/admin/quality/compare").json() if x["run"] == r["run"]][0]
        if res["done"] >= 6:
            break
        _t.sleep(0.1)
    assert res["done"] == 6 and [m["model"] for m in res["models"]] == ["qwen3:8b", "llama3.2:3b"]
    assert all(m["answers"] == 6 for m in res["models"])
    assert db.scalar("SELECT COUNT(*) FROM chats WHERE kind='eval' AND title LIKE 'Vergleich:%'") >= 6
