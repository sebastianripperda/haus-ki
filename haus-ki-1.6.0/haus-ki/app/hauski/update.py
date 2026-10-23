"""Nach neuen Versionen suchen und sie installieren, ohne Paket von Hand hochzuladen.

Quelle (Administration › Updates und Sicherung):
  github:besitzer/repo           neueste Veröffentlichung auf GitHub. Erwartet die Dateien
                                 haus-ki-<version>.tar.gz und haus-ki-<version>.tar.gz.sha256
  https://…/latest.json          eigene Ablage mit {"version", "url", "sha256", "notes"}

Ohne passende Prüfsumme wird nichts installiert.
"""
import hashlib
import json
import re
import time

import httpx

from . import __version__, db, settings
from .config import config


def _ver(v: str) -> tuple:
    return tuple(int(x) for x in re.findall(r"\d+", v or "")[:3]) or (0,)


async def _github(repo: str, c: httpx.AsyncClient) -> dict:
    r = await c.get(f"https://api.github.com/repos/{repo}/releases/latest", headers={"Accept": "application/vnd.github+json"})
    r.raise_for_status()
    rel = r.json()
    assets = {a["name"]: a["browser_download_url"] for a in rel.get("assets", [])}
    tar = next((n for n in assets if re.fullmatch(r"haus-ki-[\d.]+\.tar\.gz", n)), None)
    if not tar:
        raise RuntimeError("In der neuesten Veröffentlichung fehlt das Paket haus-ki-<version>.tar.gz.")
    sha = ""
    if tar + ".sha256" in assets:
        sha = (await c.get(assets[tar + ".sha256"])).text.split()[0]
    else:
        m = re.search(r"sha256[:\s]+([0-9a-f]{64})", rel.get("body") or "", re.I)
        sha = m.group(1) if m else ""
    return {"version": rel.get("tag_name", "").lstrip("v") or tar[8:-7], "url": assets[tar], "sha256": sha,
            "notes": (rel.get("body") or "")[:2000]}


async def check() -> dict:
    src = (settings.get("update.source") or "").strip()
    if not src:
        return {"configured": False}
    async with httpx.AsyncClient(timeout=20, follow_redirects=True) as c:
        if src.startswith("github:"):
            info = await _github(src[7:], c)
        elif src.startswith("https://"):
            r = await c.get(src)
            r.raise_for_status()
            info = r.json()
        else:
            raise RuntimeError("Unbekannte Update-Quelle. Erlaubt sind github:besitzer/repo oder eine https-Adresse.")
    info.update(configured=True, current=__version__, checked=time.time(),
                available=_ver(info.get("version", "")) > _ver(__version__))
    db.kv_set("update_info", info)
    return info


def last_info() -> dict:
    return db.kv_get("update_info", {}) or {}


async def install_available(by: str) -> dict:
    info = last_info() or await check()
    if not info.get("available"):
        raise RuntimeError("Es gibt keine neuere Version.")
    if not re.fullmatch(r"[0-9a-f]{64}", info.get("sha256", "") or ""):
        raise RuntimeError("Für diese Version fehlt die Prüfsumme (sha256). Aus Sicherheitsgründen wird nichts installiert.")
    config.update_dir.mkdir(parents=True, exist_ok=True)
    target = config.update_dir / "incoming.tar.gz"
    h = hashlib.sha256()
    async with httpx.AsyncClient(timeout=httpx.Timeout(20, read=300), follow_redirects=True) as c:
        async with c.stream("GET", info["url"]) as r:
            r.raise_for_status()
            with open(target, "wb") as f:
                async for chunk in r.aiter_bytes(1 << 16):
                    h.update(chunk)
                    f.write(chunk)
    if h.hexdigest() != info["sha256"].lower():
        target.unlink(missing_ok=True)
        raise RuntimeError("Die Prüfsumme des heruntergeladenen Pakets stimmt nicht. Nichts installiert.")
    (config.update_dir / "request").write_text(json.dumps({"action": "install", "by": by, "ts": time.time(),
                                                           "version": info.get("version")}))
    return {"ok": True, "version": info.get("version")}
