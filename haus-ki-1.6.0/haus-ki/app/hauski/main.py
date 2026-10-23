"""Haus-KI Webanwendung. Start: uvicorn hauski.main:app (hinter Caddy)."""
import asyncio
import logging
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from . import __version__, db, scheduler, settings, tools
from .api import admin, chats, user, voice as voice_api
from .auth import router as auth_router
from .config import config
from .jobs import queue
from .tools import knx

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.migrate()
    settings.import_bootstrap()
    tools.load_all()
    queue.start()
    bg = asyncio.create_task(scheduler.loop())
    from . import voice
    asyncio.create_task(voice.prefetch())
    yield
    bg.cancel()
    await queue.stop()
    await knx.stop()


app = FastAPI(title="Haus-KI", version=__version__, lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
app.include_router(auth_router)
app.include_router(user.router)
app.include_router(chats.router)
app.include_router(admin.router)
app.include_router(voice_api.router)

CSP = ("default-src 'self'; img-src 'self' data: blob:; media-src 'self' blob:; style-src 'self' 'unsafe-inline'; script-src 'self'; "
       "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self' https://login.microsoftonline.com")


@app.middleware("http")
async def headers(request: Request, call_next):
    resp = await call_next(request)
    resp.headers["Content-Security-Policy"] = CSP
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Referrer-Policy"] = "same-origin"
    if request.url.path.startswith("/api/"):
        resp.headers["Cache-Control"] = "no-store"
    return resp


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception):
    if isinstance(exc, (RuntimeError, PermissionError, ConnectionError, httpx.HTTPError)):
        # Erwartbar: eine Anbindung ist nicht eingerichtet oder nicht erreichbar.
        logging.getLogger("hauski").warning("%s: %s", request.url.path, exc)
        text = str(exc) or "Die Gegenstelle antwortet nicht."
        if isinstance(exc, httpx.HTTPError) and not str(exc):
            text = f"Verbindung fehlgeschlagen ({exc.__class__.__name__})."
        return JSONResponse({"detail": text[:300]}, status_code=502)
    logging.getLogger("hauski").exception("Unerwarteter Fehler bei %s", request.url.path)
    return JSONResponse({"detail": f"Unerwarteter Fehler: {exc}"[:300]}, status_code=500)


@app.get("/health")
def health():
    return {"ok": True, "version": __version__, "ollama": scheduler.health["ok"]}


@app.get("/agent/install.sh")
def agent_installer():
    return PlainTextResponse((config.agent_dir / "install-agent.sh").read_text().replace("__HAUSKI_URL__", config.base_url),
                             media_type="text/x-shellscript")


@app.get("/agent/haus-ki-agent.py")
def agent_script():
    return FileResponse(config.agent_dir / "haus-ki-agent.py", media_type="text/x-python")


@app.get("/manifest.webmanifest")
def manifest():
    return FileResponse(config.static_dir / "manifest.webmanifest", media_type="application/manifest+json",
                        headers={"Cache-Control": "no-cache"})


@app.get("/sw.js")
def service_worker():
    # Vom Wurzelpfad ausgeliefert, damit der Service Worker die ganze App abdeckt
    return FileResponse(config.static_dir / "sw.js", media_type="text/javascript",
                        headers={"Cache-Control": "no-cache", "Service-Worker-Allowed": "/"})


@app.get("/ca.crt")
def ca_cert():
    path = config.data_dir / "public" / "root.crt"
    if not path.exists():
        return PlainTextResponse("Zertifikat nicht gefunden.", status_code=404)
    return FileResponse(path, media_type="application/x-x509-ca-cert", filename="haus-ki-ca.crt")


app.mount("/static", StaticFiles(directory=config.static_dir), name="static")


@app.get("/{path:path}")
def spa(path: str):
    if path.startswith(("api/", "auth/")):
        return JSONResponse({"detail": "Nicht gefunden."}, status_code=404)
    return FileResponse(config.static_dir / "index.html", headers={"Cache-Control": "no-cache"})
