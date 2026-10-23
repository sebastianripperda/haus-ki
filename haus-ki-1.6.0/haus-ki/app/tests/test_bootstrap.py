"""Installationsskript legt Personen vorab an; die Ersteinrichtung übernimmt die passende Person."""
import json
import os
import subprocess
import sys
import tempfile
import textwrap

SCRIPT = textwrap.dedent("""
    import json, os
    from fastapi.testclient import TestClient
    from hauski.main import app
    from hauski import db, users, settings
    with TestClient(app) as c:
        c.headers["x-haus-ki"] = "1"
        st = c.get("/api/setup/status").json()
        assert st["needs_setup"] is True, st
        assert settings.get("jellyfin.enabled") and settings.get("paperless.write_tags")
        r = c.post("/api/setup", json={"code": "C-1", "name": "anna", "password": "sehr-geheim-123"})
        assert r.status_code == 200, r.text
        rows = {u["name"]: u for u in db.rows("SELECT * FROM users")}
        assert len(rows) == 4, rows.keys()
        assert rows["Anna"]["pw_hash"] and rows["Anna"]["role"] == "admin"
        assert users.perms(rows["Mia"])["learn"] is True and rows["Mia"]["role"] == "member"
        assert users.perms(rows["Leo"])["jellyfin_user"] == "leo"
        assert c.get("/api/setup/status").json()["needs_setup"] is False
        assert c.post("/api/setup", json={"code": "C-1", "name": "x", "password": "y" * 12}).status_code == 409
    print("OK")
""")


def test_bootstrap_people_and_setup():
    d = tempfile.mkdtemp()
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    people = json.load(open(os.path.join(root, "install", "haus-ki-personen.example.json")))
    boot = os.path.join(d, "bootstrap.json")
    json.dump({"ollama.url": "http://127.0.0.1:9", "jellyfin.enabled": True, "jellyfin.url": "http://127.0.0.1:9",
               "jellyfin.api_key": "k", "paperless.write_tags": True, "users": people}, open(boot, "w"))
    env = dict(os.environ, HAUSKI_DEV="1", HAUSKI_DATA=d, HAUSKI_SETUP_CODE="C-1", HAUSKI_BOOTSTRAP=boot)
    out = subprocess.run([sys.executable, "-c", SCRIPT], cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         env=env, capture_output=True, text=True, timeout=60)
    assert "OK" in out.stdout, out.stdout + out.stderr
