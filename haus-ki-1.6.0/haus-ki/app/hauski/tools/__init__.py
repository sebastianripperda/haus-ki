"""Werkzeuge, die das Modell aufrufen darf, und Aktionen, die erst nach Bestätigung laufen.

Jedes Werkzeug gehört zu einer Quelle (paperless, jellyfin, knx, m365, mail, web).
Lesende Werkzeuge liefern Text und Quellenkarten. Schreibende Werkzeuge liefern nur einen
Vorschlag; ausgeführt wird er erst, wenn der Mensch im Chat bestätigt.
"""
from dataclasses import dataclass, field
from typing import Awaitable, Callable


@dataclass
class Ctx:
    user: dict
    perms: dict
    sources: set
    chat_id: int | None = None
    web_tainted: bool = False
    model: str = ""


@dataclass
class Cite:
    source: str
    title: str
    meta: str = ""
    url: str = ""
    open_label: str = ""


@dataclass
class Result:
    text: str
    cites: list[Cite] = field(default_factory=list)
    step: str = ""
    action: dict | None = None  # {"kind", "summary", "payload"}


@dataclass
class Tool:
    name: str
    source: str
    description: str
    params: dict
    handler: Callable[[Ctx, dict], Awaitable[Result]]
    kind: str = "read"  # read | action | web
    admin_only: bool = False

    def schema(self) -> dict:
        return {"type": "function", "function": {
            "name": self.name, "description": self.description,
            "parameters": {"type": "object", "properties": self.params,
                           "required": [k for k, v in self.params.items() if not v.get("optional")]}}}


TOOLS: dict[str, Tool] = {}
ACTIONS: dict[str, Callable[[dict, dict], Awaitable[str]]] = {}


def tool(name, source, description, params=None, kind="read", admin_only=False):
    def deco(fn):
        clean = {k: {kk: vv for kk, vv in v.items() if kk != "optional"} | ({"optional": True} if v.get("optional") else {})
                 for k, v in (params or {}).items()}
        TOOLS[name] = Tool(name, source, description, clean, fn, kind, admin_only)
        return fn
    return deco


def action(kind):
    def deco(fn):
        ACTIONS[kind] = fn
        return fn
    return deco


def S(desc, typ="string", optional=False, **extra):
    d = {"type": typ, "description": desc, **extra}
    if optional:
        d["optional"] = True
    return d


def available(ctx: Ctx) -> list[Tool]:
    from .. import users
    out = []
    for t in TOOLS.values():
        if t.source not in ctx.sources:
            continue
        if t.admin_only and not users.is_admin(ctx.user):
            continue
        out.append(t)
    return out


def schemas(tools: list[Tool]) -> list[dict]:
    result = []
    for t in tools:
        s = t.schema()
        for p in s["function"]["parameters"]["properties"].values():
            p.pop("optional", None)
        result.append(s)
    return result


def load_all() -> None:
    from . import paperless, jellyfin, knx, m365, mailbox, web, memory  # noqa: F401
