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


# ------------------------------------------------------------ Anmeldung: Microsoft 365, lokal oder beides
def _fresh():
    c = TestClient(app)
    c.headers["x-haus-ki"] = "1"
    return c


def _uid(name):
    return db.scalar("SELECT id FROM users WHERE name=?", (name,))


def test_admin_creates_local_user_and_login_modes(client):
    # Ohne Passwort keine lokale Anmeldung, zu kurze Passwörter werden abgelehnt
    assert client.post("/api/admin/users", json={"name": "Lina", "login": "local"}).status_code == 400
    assert client.post("/api/admin/users", json={"name": "Lina", "login": "local", "local_password": "kurz"}).status_code == 400
    assert client.post("/api/admin/users", json={"name": "Lina", "login": "quatsch", "local_password": "lang-genug-1"}).status_code == 400
    r = client.post("/api/admin/users", json={"name": "Lina", "login": "local", "local_password": "lina-pass-1"})
    assert r.status_code == 200, r.text
    lina = r.json()["id"]
    assert client.post("/api/admin/users", json={"name": "lina"}).status_code == 400  # Name doppelt
    tom = client.post("/api/admin/users", json={"name": "Tom", "email": "tom@example.org"}).json()["id"]  # Standard: Microsoft 365

    st = client.get("/api/setup/status").json()
    assert lina in [u["id"] for u in st["local"]] and tom not in [u["id"] for u in st["local"]]
    assert lina not in [u["id"] for u in st["recent"]]
    users_ = {u["id"]: u for u in client.get("/api/admin/users").json()}
    assert users_[lina]["login"] == "local" and users_[lina]["has_local_password"] and not users_[lina]["has_password"]
    assert "lina-pass-1" not in (db.row("SELECT local_pw FROM users WHERE id=?", (lina,))["local_pw"] or "")

    c = _fresh()
    assert c.post("/auth/local", json={"user_id": lina, "password": "falsch-falsch"}).status_code == 401
    assert c.post("/auth/local", json={"user_id": lina, "password": "lina-pass-1"}).status_code == 200
    me = c.get("/api/me").json()
    assert me["name"] == "Lina" and me["login"] == "local" and me["features"]["m365"] is False
    assert db.row("SELECT method FROM sessions WHERE user_id=? ORDER BY created DESC", (lina,))["method"] == "Lokal"
    # Nur-Microsoft-Personen können sich nicht lokal anmelden, auch nicht mit dem Notfall-Passwort eines Admins
    assert _fresh().post("/auth/local", json={"user_id": tom, "password": "irgendwas-1"}).status_code == 401
    assert _fresh().post("/auth/local", json={"user_id": 1, "password": "sehr-geheim-123"}).status_code == 401
    # Lokales Passwort ist kein Notfall-Passwort
    client.put(f"/api/admin/users/{lina}", json={"role": "admin"})
    assert _fresh().post("/auth/emergency", json={"user_id": lina, "password": "lina-pass-1"}).status_code == 401
    client.put(f"/api/admin/users/{lina}", json={"role": "member"})


def test_switching_login_mode_ends_sessions(client):
    lina = _uid("Lina")
    c = _fresh()
    assert c.post("/auth/local", json={"user_id": lina, "password": "lina-pass-1"}).status_code == 200
    assert c.get("/api/me").status_code == 200
    r = client.put(f"/api/admin/users/{lina}", json={"login": "m365"})
    assert r.status_code == 200, r.text
    assert c.get("/api/me").status_code == 401
    assert _fresh().post("/auth/local", json={"user_id": lina, "password": "lina-pass-1"}).status_code == 401
    # Zurück auf „beides“: das gespeicherte Passwort gilt wieder
    assert client.put(f"/api/admin/users/{lina}", json={"login": "both"}).status_code == 200
    assert _fresh().post("/auth/local", json={"user_id": lina, "password": "lina-pass-1"}).status_code == 200
    # Lokales Passwort entfernen geht nur bei „nur Microsoft 365“
    assert client.put(f"/api/admin/users/{lina}", json={"remove_local_password": True}).status_code == 400
    tom = _uid("Tom")
    assert client.put(f"/api/admin/users/{tom}", json={"login": "both"}).status_code == 400  # erst Passwort vergeben
    assert client.put(f"/api/admin/users/{tom}", json={"login": "both", "local_password": "tom-pass-12"}).status_code == 200
    assert client.put(f"/api/admin/users/{tom}", json={"login": "m365", "remove_local_password": True}).status_code == 200
    assert db.row("SELECT local_pw, login FROM users WHERE id=?", (tom,)) == {"local_pw": None, "login": "m365"}
    assert db.scalar("SELECT COUNT(*) FROM audit WHERE text LIKE '%Anmeldung: Lokal%' OR text LIKE '%Anmeldung: Microsoft 365%'") >= 2


def test_user_changes_own_password(client):
    lina = _uid("Lina")
    c = _fresh()
    assert c.post("/auth/local", json={"user_id": lina, "password": "lina-pass-1"}).status_code == 200
    other = _fresh()
    assert other.post("/auth/local", json={"user_id": lina, "password": "lina-pass-1"}).status_code == 200
    assert c.put("/api/me/password", json={"current": "falsch-123", "new": "neu-pass-22"}).status_code == 400
    assert c.put("/api/me/password", json={"current": "lina-pass-1", "new": "kurz"}).status_code == 400
    assert c.put("/api/me/password", json={"current": "lina-pass-1", "new": "neu-pass-22"}).status_code == 200
    assert c.get("/api/me").status_code == 200          # eigene Sitzung bleibt
    assert other.get("/api/me").status_code == 401      # andere lokale Sitzungen enden
    assert _fresh().post("/auth/local", json={"user_id": lina, "password": "lina-pass-1"}).status_code == 401
    assert _fresh().post("/auth/local", json={"user_id": lina, "password": "neu-pass-22"}).status_code == 200
    # Wer nur Microsoft verwendet, hat kein lokales Passwort zum Ändern
    assert client.put("/api/me/password", json={"current": "x", "new": "neu-pass-22"}).status_code == 400


def test_local_login_lockout(client):
    lina = _uid("Lina")
    for _ in range(5):
        _fresh().post("/auth/local", json={"user_id": lina, "password": "falsch-falsch"})
    assert _fresh().post("/auth/local", json={"user_id": lina, "password": "neu-pass-22"}).status_code == 429
    client.put(f"/api/admin/users/{lina}", json={"unlock": True})
    assert _fresh().post("/auth/local", json={"user_id": lina, "password": "neu-pass-22"}).status_code == 200


def test_microsoft_login_rejected_for_local_only(client, monkeypatch):
    from hauski import auth
    lina = _uid("Lina")
    client.put(f"/api/admin/users/{lina}", json={"login": "local", "email": "lina@example.org"})

    async def fake_exchange(code, verifier, tenant=None):
        return {"id_token": "x", "access_token": "a", "refresh_token": "r", "expires_in": 3600}
    claims = {"roles": ["HausKI.Member"], "oid": "oid-lina", "name": "Lina Muster", "email": "lina@example.org", "nonce": "n"}
    monkeypatch.setattr(auth, "exchange", fake_exchange)
    monkeypatch.setattr(auth, "validate_id_token", lambda tok, nonce: claims)

    def login_ms(state):
        db.kv_set(f"oidc:{state}", {"v": "v", "n": "n", "p": "login", "t": __import__("time").time(), "tenant": None})
        return _fresh().get(f"/auth/callback?code=c&state={state}", follow_redirects=False)

    r = login_ms("s1")
    assert r.status_code in (302, 307) and "fehler=nur-lokal" in r.headers["location"]
    assert db.row("SELECT oid FROM users WHERE id=?", (lina,))["oid"] is None  # nicht verknüpft
    assert not db.row("SELECT 1 FROM ms_tokens WHERE user_id=?", (lina,))
    # Mit „beides“ klappt Microsoft und verknüpft das Konto
    client.put(f"/api/admin/users/{lina}", json={"login": "both"})
    r = login_ms("s2")
    assert r.headers["location"].startswith("/?angemeldet=") and "hk_session" in r.headers.get("set-cookie", "")
    assert db.row("SELECT oid FROM users WHERE id=?", (lina,))["oid"] == "oid-lina"
    # Wieder auf „nur lokal“: Microsoft-Verbindung wird getrennt, Anmeldung abgewiesen
    client.put(f"/api/admin/users/{lina}", json={"login": "local"})
    assert not db.row("SELECT 1 FROM ms_tokens WHERE user_id=? AND audience='graph'", (lina,))
    assert "fehler=nur-lokal" in login_ms("s3").headers["location"]


def test_static_files_are_versioned_for_safari(client):
    """Safari (iPhone/iPad) benutzt sonst nach Updates tagelang alte Skripte aus dem Cache."""
    from hauski import __version__
    html = client.get("/").text
    assert f"/static/login.js?v={__version__}" in html and f"/static/app.css?v={__version__}" in html
    assert "__HK_VERSION__" not in html and 'src="/static/core.js"' not in html
    assert "immutable" in client.get(f"/static/login.js?v={__version__}").headers["cache-control"]
    assert client.get("/static/login.js").headers["cache-control"] == "no-cache"
    assert client.get("/static/login.js?v=0.0.1").headers["cache-control"] == "no-cache"  # alte Version: nicht festhalten
    sw = client.get("/sw.js")
    assert f'const V = "{__version__}"' in sw.text and sw.headers["cache-control"] == "no-cache"
    assert client.get("/api/setup/status").json()["version"] == __version__


# ------------------------------------------------------------ Weitere Postfächer (IMAP mit Benutzername und Passwort)
class FakeIMAP:
    """Nachbildung eines IMAP-Servers mit deutschen Ordnernamen und "." als Trennzeichen."""
    caps = ("IMAP4REV1", "AUTH=PLAIN")
    instances: list = []
    error = __import__("imaplib").IMAP4.error  # bleibt erhalten, wenn imaplib.IMAP4 ersetzt wird

    def __init__(self, host, port, ssl_context=None, timeout=None):
        self.host, self.port, self.capabilities, self.log, self.literal = host, port, self.caps, [], None
        FakeIMAP.instances.append(self)

    def starttls(self, ssl_context=None):
        self.log.append(("STARTTLS",))

    def authenticate(self, mech, cb):
        blob = cb(b"")
        self.log.append(("AUTH", mech, blob))
        if blob.split(b"\0")[2] != "Grüße-Straße€1".encode():
            raise FakeIMAP.error("[AUTHENTICATIONFAILED] Authentication failed.")

    def login(self, user, pw):
        self.log.append(("LOGIN", user, pw))

    def list(self):
        return "OK", [b'(\\HasNoChildren) "." INBOX', b'(\\HasNoChildren \\Drafts) "." Entw&APw-rfe',
                      b'(\\HasNoChildren \\Junk) "." Spam', b'(\\HasNoChildren \\All) "." "[Gmail].Alle Nachrichten"']

    def select(self, box, readonly=False):
        self.log.append(("SELECT", box))
        return "OK", [b"2"]

    def search(self, charset, *crit):
        self.log.append(("SEARCH", charset, crit, self.literal))
        return "OK", [b"1 2"]

    def fetch(self, i, what):
        return "OK", [(b"1 (BODY[] {10}", b"Subject: Rechnung " + i + b"\r\nFrom: a@b.de\r\n\r\nText")]

    def uid(self, cmd, *args):
        self.log.append(("UID", cmd) + args)
        if cmd == "SEARCH":
            return "OK", [b"1 2"]
        uid, items = args[0], args[1]
        head = b"Subject: Rechnung " + uid.encode() + b"\r\nFrom: a@b.de\r\nMessage-ID: <m" + uid.encode() + b"@x>\r\n\r\n"
        meta = b"1 (UID " + uid.encode() + b' RFC822.SIZE 120 INTERNALDATE "13-Nov-2026 10:0' + uid.encode() + b':00 +0100"'
        if "HEADER" in items:
            return "OK", [(meta + b" BODY[HEADER] {%d}" % len(head), head), b")"]
        if "TEXT" in items:
            return "OK", [(b"1 (BODY[TEXT]<0> {12}", b"Telekom Text"), b")"]
        return "OK", [(b"1 (BODY[] {%d}" % (len(head) + 4), head + b"Text"), b")"]

    def append(self, box, flags, date, msg):
        self.log.append(("APPEND", box, flags))
        return "OK", [b""]

    def enable(self, what):
        self.log.append(("ENABLE", what))

    def logout(self):
        pass

    def shutdown(self):
        pass


@pytest.fixture()
def fake_imap(monkeypatch):
    import imaplib
    FakeIMAP.instances.clear()
    FakeIMAP.caps = ("IMAP4REV1", "AUTH=PLAIN")
    monkeypatch.setattr(imaplib, "IMAP4_SSL", FakeIMAP)
    monkeypatch.setattr(imaplib, "IMAP4", FakeIMAP)
    return FakeIMAP


def test_mail_folders_and_search_criteria(fake_imap):
    from hauski.tools import mailbox
    m = FakeIMAP("h", 993)
    fs = mailbox.folders(m)
    assert mailbox.special(fs, "\\Drafts") == "Entw&APw-rfe" and mailbox.special(fs, "\\All") == "[Gmail].Alle Nachrichten"
    assert mailbox.special([({"\\hasnochildren"}, "INBOX.Entw&APw-rfe")], "\\Drafts", ("entw&apw-rfe",)) == "INBOX.Entw&APw-rfe"
    # Jedes Wort einzeln, nicht nur die exakte Wortfolge
    cs, crit = mailbox._search_criteria(m, "Rechnung Telekom", gmail=False)
    assert cs is None and crit[2:] == ["TEXT", '"Rechnung"', "TEXT", '"Telekom"']
    # Umlaute ohne UTF-8-Modus: Zeichensatz UTF-8 mit Literal
    cs, crit = mailbox._search_criteria(m, "Termin Müller", gmail=False)
    assert cs == "UTF-8" and crit[-1] == "TEXT" and m.literal == "Müller".encode()
    # Umlaute mit UTF8=ACCEPT: direkt
    m2 = FakeIMAP("h", 993); m2.capabilities = ("IMAP4REV1", "ENABLE", "UTF8=ACCEPT")
    cs, crit = mailbox._search_criteria(m2, "Müller", gmail=False)
    assert cs is None and ("ENABLE", "UTF8=ACCEPT") in m2.log and crit[-1] == '"Müller"'
    cs, crit = mailbox._search_criteria(m, "Strom 2025", gmail=True)
    assert crit == ["X-GM-RAW", '"Strom 2025"']
    assert mailbox._q('a"b\\c') == '"a\\"b\\\\c"'
    assert mailbox.clean_password("gmail", "abcd efgh ijkl mnop") == "abcdefghijklmnop"
    assert mailbox.clean_password("gmx", "mit Leer zeichen") == "mit Leer zeichen"


def test_mail_login_utf8_and_german_gmail(client, fake_imap):
    from hauski.tools import mailbox
    r = client.post("/api/accounts", json={"kind": "gmail", "address": "anna@gmail.com", "password": "falsch"})
    assert r.status_code == 400 and "App-Passwort" in r.json()["detail"]
    r = client.post("/api/accounts", json={"kind": "gmail", "address": "anna@gmail.com", "password": "Grüße-Straße€1"})
    assert r.status_code == 200, r.text
    m = FakeIMAP.instances[-1]
    assert m.host == "imap.gmail.com" and m.port == 993 and m.log[0][0] == "AUTH"
    assert m.log[0][2] == b"\0anna@gmail.com\0" + "Grüße-Straße€1".encode()
    # Gmail: Suche im Ordner mit \All, egal wie er in der Kontosprache heißt
    user = db.row("SELECT * FROM users WHERE id=1")
    from hauski.tools import Ctx
    import asyncio
    res = asyncio.run(mailbox.search(Ctx(user=user, perms={}, sources={"mail"}), {"query": "Rechnung", "account": "gmail"}))
    m = FakeIMAP.instances[-1]
    assert ("SELECT", '"[Gmail].Alle Nachrichten"') in m.log
    assert [x["subject"] for x in res.text] == ["Rechnung 2", "Rechnung 1"]
    # Server ohne AUTH=PLAIN: LOGIN nur mit ASCII, sonst verständliche Meldung
    FakeIMAP.caps = ("IMAP4REV1",)
    r = client.post("/api/accounts", json={"kind": "webde", "address": "a@web.de", "password": "Grüße-Straße€1"})
    assert r.status_code == 400 and "Sonderzeichen" in r.json()["detail"]
    r = client.post("/api/accounts", json={"kind": "webde", "address": "a@web.de", "password": "einfach 123", "username": "anna"})
    assert r.status_code == 200 and FakeIMAP.instances[-1].log[0] == ("LOGIN", "anna", "einfach 123")
    assert FakeIMAP.instances[-1].host == "imap.web.de"
    accs = client.get("/api/accounts").json()
    assert {a["label"] for a in accs["accounts"]} >= {"Gmail", "WEB.DE"}
    assert {p["id"] for p in accs["providers"]} >= {"gmx", "webde", "gmail", "tonline", "icloud", "yahoo", "imap"}


def test_mail_account_validation(client, fake_imap):
    assert client.post("/api/accounts", json={"kind": "imap", "address": "x@y.de", "password": "p", "host": ""}).status_code == 400
    assert client.post("/api/accounts", json={"kind": "imap", "address": "x@y.de", "password": "p", "host": "a b"}).status_code == 400
    assert client.post("/api/accounts", json={"kind": "imap", "address": "x@y.de", "password": "p", "host": "imap.y.de",
                                              "security": "none"}).status_code == 400  # unverschlüsselt nie
    assert client.post("/api/accounts", json={"kind": "gmx", "address": "keine-adresse", "password": "p"}).status_code == 400
    assert client.post("/api/accounts", json={"kind": "gmx", "address": "x@gmx.de", "password": ""}).status_code == 400
    settings.set_many({"ms.client_id": "", "ms.client_secret": ""})
    r = client.post("/api/accounts", json={"kind": "outlookcom", "address": "x@outlook.com"})
    assert r.status_code == 400 and "Microsoft 365" in r.json()["detail"]
    settings.set_many({"mail.allow_imap": False})
    assert client.post("/api/accounts", json={"kind": "tonline", "address": "x@t-online.de", "password": "Grüße-Straße€1"}).status_code == 400
    assert "tonline" not in {p["id"] for p in client.get("/api/accounts").json()["providers"]}
    settings.set_many({"mail.allow_imap": True})
    # STARTTLS wird vor der Anmeldung ausgeführt
    r = client.post("/api/accounts", json={"kind": "imap", "address": "x@y.de", "password": "Grüße-Straße€1", "host": "mail.y.de",
                                           "port": 143, "security": "starttls"})
    assert r.status_code == 200 and FakeIMAP.instances[-1].log[0] == ("STARTTLS",)


def test_mail_invoice_detection():
    import datetime as dt
    from hauski.tools.mailbox import classify
    today = dt.date(2026, 11, 13)
    c = classify({"subject": "Ihre Rechnung 11/2026", "text": "Betrag 49,90 € wird am 01.12.2026 abgebucht. Fällig am 1.12.26."}, today)
    assert c == {"kind": "Rechnung", "due": "2026-12-01", "amount": "49,90 €"}
    assert classify({"subject": "2. Mahnung", "text": "Bitte zahlen Sie bis zum 20.11.2026."}, today)["kind"] == "Mahnung"
    # Stichwort nur im Text: braucht Datum oder Betrag
    assert classify({"subject": "Hallo", "text": "Die Rechnung schicke ich später."}, today) is None
    assert classify({"subject": "Hallo", "text": "Die Rechnung über EUR 12,00 ist bezahlt."}, today)["amount"] == "12,00 €"
    # Werbung nie, vergangene und weit entfernte Daten zählen nicht als Frist
    assert classify({"subject": "Newsletter: Rechnung sparen mit 20 %", "text": "fällig am 01.12.2026"}, today) is None
    assert classify({"subject": "Rechnung", "text": "fällig am 01.01.2020"}, today)["due"] is None
    assert classify({"subject": "Kündigung bestätigt", "text": "Vertrag endet am 31.12.2026."}, today) == {"kind": "Frist", "due": "2026-12-31", "amount": ""}


def test_mailboxes_are_searched_in_parallel(client, monkeypatch):
    import asyncio
    import time
    from hauski.tools import Ctx, mailbox
    uid = db.scalar("SELECT id FROM users WHERE name='Anna'")
    for i in range(3):
        db.run("INSERT INTO accounts(user_id,kind,address,secret,config,created) VALUES(?,?,?,?,?,?)",
               (uid, "webde", f"p{i}@web.de", security.encrypt("x"), "{}", db.now()))

    def slow(acc, query, limit=6):
        time.sleep(0.6)
        return [{"id": f"{acc['id']}:SU5CT1g:1", "folder": "Posteingang", "ts": 1.0, "subject": acc["address"], "from": "x",
                 "date": "", "message_id": "", "text": ""}]
    monkeypatch.setattr(mailbox, "_imap_search", slow)
    t = time.time()
    res = asyncio.run(mailbox.search(Ctx(user=db.row("SELECT * FROM users WHERE id=?", (uid,)), perms={}, sources={"mail"}),
                                     {"query": "x", "account": "web.de"}))
    assert time.time() - t < 1.5, "Postfächer wurden nacheinander statt gleichzeitig durchsucht"
    assert {x["subject"] for x in res.text} >= {"p0@web.de", "p1@web.de", "p2@web.de"}
    db.run("DELETE FROM accounts WHERE kind='webde' AND address LIKE 'p_@web.de'")


def test_expired_sessions_are_removed(client):
    from hauski import scheduler
    db.run("INSERT INTO sessions(id,user_id,created,last_seen) VALUES('alt-1',1,?,?)", (db.now() - 40 * 86400, db.now() - 40 * 86400))
    db.run("INSERT INTO sessions(id,user_id,created,last_seen) VALUES('frisch-1',1,?,?)", (db.now(), db.now()))
    r = scheduler.retention()
    assert r["sessions"] >= 1
    assert not db.row("SELECT 1 FROM sessions WHERE id='alt-1'") and db.row("SELECT 1 FROM sessions WHERE id='frisch-1'")


def test_lost_microsoft_session_is_logged_once(client, monkeypatch):
    from hauski import auth
    count = lambda: db.scalar("SELECT COUNT(*) FROM audit WHERE text LIKE '%Sitzung kam nicht an%'")
    before = count()
    # Ohne vorherige Microsoft-Anmeldung: nichts ins Protokoll (Schutz gegen Spam von außen)
    assert _fresh().post("/auth/lost-session", json={"standalone": True}).json() == {"ok": False}
    assert count() == before

    async def fake_exchange(code, verifier, tenant=None):
        return {"id_token": "x", "access_token": "a", "refresh_token": "r", "expires_in": 3600}
    monkeypatch.setattr(auth, "exchange", fake_exchange)
    monkeypatch.setattr(auth, "validate_id_token", lambda tok, nonce: {"roles": ["HausKI.Member"], "oid": "oid-lost", "name": "Ella",
                                                                       "email": "ella@example.org", "nonce": "n"})
    db.kv_set("oidc:lost1", {"v": "v", "n": "n", "p": "login", "t": __import__("time").time(), "tenant": None})
    r = _fresh().get("/auth/callback?code=c&state=lost1", follow_redirects=False)
    assert r.headers["location"].startswith("/?angemeldet=")
    # Die App meldet sich ohne Cookie zurück: einmal protokollieren, mit Hinweis auf die Home-Bildschirm-App
    ios = {"user-agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 18_5 like Mac OS X) AppleWebKit/605.1.15"}
    assert _fresh().post("/auth/lost-session", json={"standalone": True}, headers=ios).json() == {"ok": True}
    assert count() == before + 1
    assert "iPhone/iPad, App vom Home-Bildschirm" in db.scalar("SELECT text FROM audit WHERE text LIKE '%Sitzung kam nicht an%' ORDER BY id DESC")
    assert _fresh().post("/auth/lost-session", json={"standalone": True}).json() == {"ok": False}
    assert count() == before + 1
