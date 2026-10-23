#!/usr/bin/env python3
"""Haus-KI-Agent für den Ollama-Container (oder eine Ollama-Container).

Kleiner HTTPS-Dienst ohne Fremdbibliotheken. Er kann genau vier Dinge:
Ollama-Umgebungsvariablen schreiben, Ollama neu starten, Ollama aktualisieren
und Status sowie Logs liefern. Zugriff nur mit Token, nur von Haus-KI aus.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import socket
import ssl
import subprocess
import sys
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

VERSION = "1.0.0"
CONFIG = os.environ.get("HAUSKI_AGENT_CONFIG", "/etc/haus-ki-agent/config.json")
OVERRIDE = "/etc/systemd/system/ollama.service.d/haus-ki.conf"
KEY_RE = re.compile(r"^OLLAMA_[A-Z0-9_]{1,40}$")
VAL_RE = re.compile(r'^[^"\n\r\\]{0,200}$')
update_state = {"status": "idle", "output": "", "version": ""}
GUARD_FILE = "/etc/haus-ki-agent/guard.nft"
IP_RE = re.compile(r"^(\d{1,3}\.){3}\d{1,3}(/\d{1,2})?$")


# ------------------------------------------------------------------ Schutz für Ollama
def guard_rules(allow: list[str]) -> str:
    """Port 11434 nur für die erlaubten Adressen und den Container selbst."""
    v4 = ", ".join(["127.0.0.1"] + allow)
    return f"""table inet hauski_guard
delete table inet hauski_guard
table inet hauski_guard {{
  chain input {{
    type filter hook input priority 0; policy accept;
    tcp dport 11434 ip saddr {{ {v4} }} accept
    tcp dport 11434 ip6 saddr ::1 accept
    tcp dport 11434 drop
  }}
}}
"""


def guard_apply(cfg: dict) -> dict:
    allow = [a for a in cfg.get("ollama_allow", []) if IP_RE.match(a)]
    if not cfg.get("guard"):
        run(["nft", "delete", "table", "inet", "hauski_guard"])
        return {"enabled": False, "active": False, "allow": allow}
    with open(GUARD_FILE, "w") as f:
        f.write(guard_rules(allow))
    # „delete table“ schlägt beim ersten Mal fehl, wenn die Tabelle fehlt: vorher anlegen
    run(["nft", "add", "table", "inet", "hauski_guard"])
    code, out = run(["nft", "-f", GUARD_FILE])
    return {"enabled": True, "active": code == 0, "allow": allow, "error": "" if code == 0 else out[-300:]}


def guard_status(cfg: dict) -> dict:
    code, out = run(["nft", "list", "table", "inet", "hauski_guard"])
    return {"enabled": bool(cfg.get("guard")), "active": code == 0 and "11434" in out,
            "allow": cfg.get("ollama_allow", [])}


def load_config() -> dict:
    with open(CONFIG) as f:
        return json.load(f)


def run(cmd: list[str], timeout: int = 60) -> tuple[int, str]:
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return p.returncode, (p.stdout + p.stderr).strip()


def ollama_version() -> str:
    try:
        return json.load(urllib.request.urlopen("http://127.0.0.1:11434/api/version", timeout=3)).get("version", "")
    except Exception:  # noqa: BLE001
        return ""


def read_env() -> dict:
    env = {}
    if os.path.exists(OVERRIDE):
        for line in open(OVERRIDE):
            m = re.match(r'\s*Environment="([A-Z0-9_]+)=(.*)"\s*$', line)
            if m:
                env[m[1]] = m[2]
    return env


def write_env(env: dict) -> None:
    for k, v in env.items():
        if not KEY_RE.match(k) or not VAL_RE.match(str(v)):
            raise ValueError(f"Ungültige Variable: {k}")
    os.makedirs(os.path.dirname(OVERRIDE), exist_ok=True)
    body = "# Verwaltet von Haus-KI. Änderungen hier werden überschrieben.\n[Service]\n" + \
           "".join(f'Environment="{k}={v}"\n' for k, v in sorted(env.items()))
    tmp = OVERRIDE + ".tmp"
    with open(tmp, "w") as f:
        f.write(body)
    os.replace(tmp, OVERRIDE)  # ganz oder gar nicht
    code, out = run(["systemctl", "daemon-reload"])
    if code:
        raise RuntimeError(out)


def restart() -> dict:
    code, out = run(["systemctl", "restart", "ollama"], timeout=120)
    if code:
        raise RuntimeError(out or "Neustart fehlgeschlagen")
    for _ in range(60):
        v = ollama_version()
        if v:
            return {"ok": True, "version": v}
        time.sleep(1)
    raise RuntimeError("Ollama ist nach dem Neustart nicht erreichbar.")


def do_update() -> None:
    update_state.update(status="running", output="")
    try:
        p = subprocess.run("curl -fsSL https://ollama.com/install.sh | sh", shell=True, capture_output=True, text=True, timeout=1800)
        update_state["output"] = (p.stdout + p.stderr)[-4000:]
        if p.returncode:
            update_state["status"] = "error"
            return
        restart()
        update_state.update(status="done", version=ollama_version())
    except Exception as e:  # noqa: BLE001
        update_state.update(status="error", output=str(e))


def health() -> dict:
    mem = {}
    for line in open("/proc/meminfo"):
        k, v = line.split(":")
        mem[k] = int(v.split()[0]) * 1024
    code, _ = run(["systemctl", "is-active", "--quiet", "ollama"])
    try:
        guard = guard_status(load_config())
    except Exception as e:  # noqa: BLE001
        guard = {"enabled": False, "active": False, "error": str(e)}
    return {"version": VERSION, "hostname": socket.gethostname(), "ollama_active": code == 0, "ollama_version": ollama_version(),
            "mem_total": mem.get("MemTotal"), "mem_available": mem.get("MemAvailable"), "load": os.getloadavg(), "guard": guard}


class Handler(BaseHTTPRequestHandler):
    server_version = "HausKIAgent/" + VERSION

    def log_message(self, fmt, *args):
        sys.stderr.write("%s %s\n" % (self.address_string(), fmt % args))

    def _auth(self) -> bool:
        auth = self.headers.get("Authorization", "")
        token = auth[7:].strip() if auth.startswith("Bearer ") else ""
        digest = hashlib.sha256(token.encode()).hexdigest()
        if not hmac.compare_digest(digest, self.server.cfg["token_sha256"]):
            self._send(401, {"error": "Nicht berechtigt"})
            return False
        allowed = self.server.cfg.get("allowed_ips") or []
        if allowed and self.client_address[0] not in allowed:
            self._send(403, {"error": "Diese Adresse darf den Agenten nicht nutzen"})
            return False
        return True

    def _send(self, code: int, data: dict) -> None:
        body = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}") if n else {}

    def do_GET(self):
        if not self._auth():
            return
        u = urlparse(self.path)
        try:
            if u.path == "/health":
                return self._send(200, health())
            if u.path == "/ollama/env":
                return self._send(200, {"vars": read_env(), "path": OVERRIDE, "hostname": socket.gethostname(), "ollama_version": ollama_version()})
            if u.path == "/ollama/update":
                return self._send(200, update_state)
            if u.path == "/ollama/guard":
                return self._send(200, guard_status(load_config()))
            if u.path == "/ollama/logs":
                lines = min(int(parse_qs(u.query).get("lines", ["200"])[0]), 1000)
                _, out = run(["journalctl", "-u", "ollama", "-n", str(lines), "--no-pager", "-o", "short-iso"])
                return self._send(200, {"lines": out})
        except Exception as e:  # noqa: BLE001
            return self._send(500, {"error": str(e)})
        self._send(404, {"error": "Unbekannt"})

    def do_PUT(self):
        if not self._auth():
            return
        if self.path == "/ollama/env":
            try:
                write_env(self._body().get("vars", {}))
                return self._send(200, {"ok": True, "vars": read_env()})
            except Exception as e:  # noqa: BLE001
                return self._send(400, {"error": str(e)})
        if self.path == "/ollama/guard":
            body = self._body()
            allow = [a.strip() for a in body.get("allow", []) if IP_RE.match(a.strip())]
            cfg = load_config()
            # Die Adresse von Haus-KI darf nie herausfallen, sonst sperrt man sich selbst aus
            for keep in cfg.get("allowed_ips", []):
                if keep not in allow:
                    allow.insert(0, keep)
            cfg.update(guard=bool(body.get("enabled", True)), ollama_allow=allow)
            with open(CONFIG + ".tmp", "w") as f:
                json.dump(cfg, f, indent=2)
            os.replace(CONFIG + ".tmp", CONFIG)
            return self._send(200, guard_apply(cfg))
        self._send(404, {"error": "Unbekannt"})

    def do_POST(self):
        if not self._auth():
            return
        try:
            if self.path == "/ollama/restart":
                return self._send(200, restart())
            if self.path == "/ollama/update":
                if update_state["status"] == "running":
                    return self._send(409, {"error": "Aktualisierung läuft bereits"})
                threading.Thread(target=do_update, daemon=True).start()
                return self._send(202, {"ok": True})
        except Exception as e:  # noqa: BLE001
            return self._send(500, {"error": str(e)})
        self._send(404, {"error": "Unbekannt"})


def main() -> None:
    cfg = load_config()
    if cfg.get("guard"):
        print("Schutz für Ollama:", guard_apply(cfg), flush=True)
    srv = ThreadingHTTPServer((cfg.get("bind", "0.0.0.0"), int(cfg.get("port", 8765))), Handler)
    srv.cfg = cfg
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.load_cert_chain(cfg["cert"], cfg["key"])
    srv.socket = ctx.wrap_socket(srv.socket, server_side=True)
    print(f"Haus-KI-Agent {VERSION} lauscht auf Port {cfg.get('port', 8765)}", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--apply-guard":
        r = guard_apply(load_config())
        print("aktiv" if r.get("active") else ("aus" if not r.get("enabled") else "Fehler: " + r.get("error", "")))
        sys.exit(0 if r.get("active") or not r.get("enabled") else 1)
    main()
