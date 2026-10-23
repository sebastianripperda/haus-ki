"""Schlanker Client für die Ollama-API im Ollama-Container."""
import json
from typing import AsyncIterator

import httpx

from . import settings


def base() -> str:
    return settings.get("ollama.url").rstrip("/")


def options(overrides: dict | None = None) -> dict:
    o = {
        "temperature": settings.get("req.temperature"),
        "top_p": settings.get("req.top_p"),
        "top_k": settings.get("req.top_k"),
        "repeat_penalty": settings.get("req.repeat_penalty"),
        "num_ctx": settings.get("req.num_ctx"),
        "num_predict": settings.get("req.num_predict"),
    }
    if settings.get("req.seed"):
        o["seed"] = settings.get("req.seed")
    if settings.get("req.num_thread"):
        o["num_thread"] = settings.get("req.num_thread")
    for k, v in (overrides or {}).items():
        if v is not None and v != "":
            o[k] = v
    return o


def keep_alive():
    v = str(settings.get("req.keep_alive"))
    try:
        return int(v)
    except ValueError:
        return v


async def chat_stream(model: str, messages: list, tools: list | None = None, opts: dict | None = None,
                      think: bool | None = None, fmt=None) -> AsyncIterator[dict]:
    body = {"model": model, "messages": messages, "stream": True, "options": options(opts),
            "keep_alive": keep_alive()}
    if tools:
        body["tools"] = tools
    if think is not None:
        body["think"] = think
    if fmt:
        body["format"] = fmt
    async with httpx.AsyncClient(timeout=httpx.Timeout(10, read=600)) as c:
        async with c.stream("POST", base() + "/api/chat", json=body) as r:
            if r.status_code != 200:
                text = (await r.aread()).decode(errors="replace")
                raise OllamaError(_error_text(r.status_code, text, model))
            async for line in r.aiter_lines():
                if not line.strip():
                    continue
                data = json.loads(line)
                if "error" in data:
                    raise OllamaError(data["error"])
                yield data


async def complete_json(model: str, prompt: str, system: str = "", num_predict: int = 600) -> dict | list | None:
    """Kurze strukturierte Antwort, z. B. für Vorschläge oder Fristen."""
    msgs = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": prompt}]
    out = ""
    async for chunk in chat_stream(model, msgs, opts={"temperature": 0.2, "num_predict": num_predict},
                                   think=False if model.startswith("qwen3") else None, fmt="json"):
        out += chunk.get("message", {}).get("content", "")
    try:
        return json.loads(out)
    except ValueError:
        return None


async def get(path: str, timeout: float = 10):
    async with httpx.AsyncClient(timeout=timeout) as c:
        r = await c.get(base() + path)
        r.raise_for_status()
        return r.json()


async def post(path: str, body: dict, timeout: float = 30):
    async with httpx.AsyncClient(timeout=timeout) as c:
        r = await c.request("POST" if path != "/api/delete" else "DELETE", base() + path, json=body)
        r.raise_for_status()
        return r.json() if r.content else {}


async def pull_stream(model: str) -> AsyncIterator[dict]:
    async with httpx.AsyncClient(timeout=httpx.Timeout(10, read=3600)) as c:
        async with c.stream("POST", base() + "/api/pull", json={"model": model, "stream": True}) as r:
            async for line in r.aiter_lines():
                if line.strip():
                    yield json.loads(line)


async def create_model(name: str, from_model: str, system: str, params: dict) -> None:
    body = {"model": name, "from": from_model, "stream": False}
    if system:
        body["system"] = system
    if params:
        body["parameters"] = params
    await post("/api/create", body, timeout=600)


class OllamaError(Exception):
    pass


def _error_text(status: int, text: str, model: str) -> str:
    try:
        msg = json.loads(text).get("error", text)
    except ValueError:
        msg = text
    if "not found" in msg:
        return f"Das Modell {model} ist in Ollama nicht installiert."
    if "memory" in msg.lower():
        return f"{model} passt gerade nicht in den Arbeitsspeicher des Ollama-Containers."
    return f"Ollama meldet Fehler {status}: {msg[:200]}"
