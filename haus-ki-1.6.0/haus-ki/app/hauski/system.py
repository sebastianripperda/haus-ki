"""Proxmox-API (Status und Steuerung des Ollama-Gasts, Container oder VM) und der Agent darin."""
import asyncio
import hashlib
import socket
import ssl
from urllib.parse import urlparse

import httpx

from . import settings


# ------------------------------------------------------------ Proxmox
def _pve() -> httpx.AsyncClient:
    url = settings.get("proxmox.url").rstrip("/")
    if not url:
        raise RuntimeError("Proxmox ist nicht eingerichtet.")
    token = f"PVEAPIToken={settings.get('proxmox.token_id')}={settings.get('proxmox.token_secret')}"
    return httpx.AsyncClient(base_url=url + "/api2/json", timeout=10, verify=bool(settings.get("proxmox.verify_tls")),
                             headers={"Authorization": token})


async def pve_guests() -> list[dict]:
    async with _pve() as c:
        nodes = (await c.get("/nodes")).json()["data"]
        out = []
        for n in nodes:
            for kind in ("qemu", "lxc"):
                r = await c.get(f"/nodes/{n['node']}/{kind}")
                if r.status_code == 200:
                    out += [{"node": n["node"], "kind": kind, "vmid": g["vmid"], "name": g.get("name", ""),
                             "status": g.get("status")} for g in r.json()["data"]]
        return sorted(out, key=lambda g: g["vmid"])


def _kind() -> str:
    return "qemu" if settings.get("proxmox.kind") == "qemu" else "lxc"


async def vm_status() -> dict:
    node, vmid, kind = settings.get("proxmox.node"), settings.get("proxmox.vmid"), _kind()
    if not node or not vmid:
        raise RuntimeError("Der Ollama-Container ist in Proxmox nicht ausgewählt.")
    async with _pve() as c:
        r = await c.get(f"/nodes/{node}/{kind}/{vmid}/status/current")
        r.raise_for_status()
        d = r.json()["data"]
    return {"status": d.get("status"), "cpu": round(d.get("cpu", 0) * 100), "cpus": d.get("cpus"),
            "mem": d.get("mem", 0), "maxmem": d.get("maxmem", 0), "uptime": d.get("uptime", 0), "name": d.get("name"), "kind": _kind()}


async def vm_control(command: str) -> None:
    if command not in ("start", "shutdown", "reboot"):
        raise ValueError(command)
    async with _pve() as c:
        r = await c.post(f"/nodes/{settings.get('proxmox.node')}/{_kind()}/{settings.get('proxmox.vmid')}/status/{command}")
        r.raise_for_status()


# ------------------------------------------------------------ Agent im Ollama-Container
def _peer_fingerprint(host: str, port: int) -> str:
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    with socket.create_connection((host, port), timeout=5) as sock:
        with ctx.wrap_socket(sock, server_hostname=host) as tls:
            return hashlib.sha256(tls.getpeercert(binary_form=True)).hexdigest()


async def agent(method: str, path: str, json: dict | None = None, timeout: float = 30) -> dict:
    """Aufruf an den Agenten. Sein Zertifikat wird beim ersten Kontakt gemerkt (Pinning)."""
    url = settings.get("agent.url").rstrip("/")
    if not url or not settings.get("agent.token"):
        raise RuntimeError("Der Agent im Ollama-Container ist nicht eingerichtet.")
    u = urlparse(url)
    fp = await asyncio.to_thread(_peer_fingerprint, u.hostname, u.port or 8765)
    pinned = settings.get("agent.fingerprint")
    if not pinned:
        settings.set_many({"agent.fingerprint": fp})
    elif pinned != fp:
        raise RuntimeError("Das Zertifikat des Agenten hat sich geändert. Wenn der Agent neu installiert wurde, "
                           "setze den Fingerabdruck in der Administration zurück.")
    async with httpx.AsyncClient(timeout=timeout, verify=False) as c:
        r = await c.request(method, url + path, json=json,
                            headers={"Authorization": f"Bearer {settings.get('agent.token')}"})
    if r.status_code >= 400:
        raise RuntimeError(f"Agent meldet {r.status_code}: {r.text[:200]}")
    return r.json() if r.content else {}
