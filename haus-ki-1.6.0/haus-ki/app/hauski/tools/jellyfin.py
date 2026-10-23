"""Jellyfin: Filme und Serien finden, Vorschläge, Wiedergabe auf einem Gerät starten."""
import httpx

from .. import settings, users
from . import Cite, Ctx, Result, S, action, tool

TYPES = {"film": "Movie", "serie": "Series", "folge": "Episode", "musik": "MusicAlbum"}
FIELDS = "Overview,Genres,ProductionYear,CommunityRating,RunTimeTicks,OfficialRating"


def client() -> httpx.AsyncClient:
    url = settings.get("jellyfin.url").rstrip("/")
    if not url:
        raise RuntimeError("Jellyfin ist nicht eingerichtet.")
    key = settings.get("jellyfin.api_key")
    auth = f'MediaBrowser Client="Haus-KI", Device="haus-ki", DeviceId="haus-ki", Version="1.1", Token="{key}"'
    return httpx.AsyncClient(base_url=url, timeout=15, headers={"Authorization": auth})


def item_url(item_id: str) -> str:
    return f"{settings.get('jellyfin.url').rstrip('/')}/web/#/details?id={item_id}"


_ids: dict[str, str] = {}


def _uid(ctx: Ctx) -> str:
    """Jellyfin-Benutzer-ID. In der Administration darf auch der Benutzername stehen."""
    v = (users.perms(ctx.user).get("jellyfin_user") or "").strip()
    return _ids.get(v.lower(), v) if v else ""


async def resolve_users() -> None:
    """Benutzernamen (aus dem Installationsskript) in IDs übersetzen."""
    if not settings.get("jellyfin.url"):
        return
    try:
        _ids.update({u["name"].lower(): u["id"] for u in await users_list()})
    except Exception:  # noqa: BLE001 – Jellyfin gerade nicht erreichbar
        pass


def _fmt(items: list[dict]) -> tuple[list, list[Cite]]:
    out, cites = [], []
    for it in items:
        minutes = int((it.get("RunTimeTicks") or 0) / 600_000_000)
        played = (it.get("UserData") or {}).get("Played")
        out.append({"id": it["Id"], "name": it.get("Name"), "type": it.get("Type"), "year": it.get("ProductionYear"),
                    "genres": it.get("Genres", [])[:3], "minutes": minutes or None, "rating": it.get("CommunityRating"),
                    "age": it.get("OfficialRating"), "seen": played, "overview": (it.get("Overview") or "")[:300]})
        meta = ", ".join(str(x) for x in [it.get("ProductionYear"), f"{minutes} Min" if minutes else "",
                                           "gesehen" if played else ""] if x)
        cites.append(Cite("Jellyfin", it.get("Name", ""), meta, item_url(it["Id"]), "In Jellyfin öffnen"))
    return out, cites


@tool("jellyfin_search", "jellyfin",
      "Sucht in der Jellyfin-Mediathek nach Filmen, Serien, Folgen oder Musik.",
      {"query": S("Titel oder Stichwort"),
       "type": S("film, serie, folge oder musik", optional=True, enum=list(TYPES))})
async def search(ctx: Ctx, args: dict) -> Result:
    if not _ids:
        await resolve_users()
    params = {"searchTerm": args.get("query", ""), "Recursive": "true", "Limit": 8, "Fields": FIELDS,
              "IncludeItemTypes": TYPES.get(args.get("type") or "", "Movie,Series,Episode,MusicAlbum")}
    if _uid(ctx):
        params["userId"] = _uid(ctx)
    async with client() as c:
        r = await c.get("/Items", params=params)
        r.raise_for_status()
    items, cites = _fmt(r.json().get("Items", []))
    return Result(items or "Nichts gefunden.", cites, f"Jellyfin durchsucht: „{args.get('query', '')}“, {len(items)} Treffer")


@tool("jellyfin_recommend", "jellyfin",
      "Schlägt ungesehene Filme oder Serien aus der eigenen Mediathek vor, optional nach Genre und Länge.",
      {"type": S("film oder serie", optional=True, enum=["film", "serie"]),
       "genre": S("Genre, z. B. Komödie, Science-Fiction, Animation", optional=True),
       "max_minutes": S("Höchstlänge in Minuten", "integer", optional=True)})
async def recommend(ctx: Ctx, args: dict) -> Result:
    if not _ids:
        await resolve_users()
    params = {"Recursive": "true", "Limit": 30, "Fields": FIELDS, "SortBy": "Random",
              "IncludeItemTypes": TYPES.get(args.get("type") or "film", "Movie")}
    if args.get("genre"):
        params["Genres"] = args["genre"]
    if _uid(ctx):
        params["userId"] = _uid(ctx)
        params["Filters"] = "IsUnplayed"
    async with client() as c:
        r = await c.get("/Items", params=params)
        r.raise_for_status()
    items = r.json().get("Items", [])
    if args.get("max_minutes"):
        items = [i for i in items if (i.get("RunTimeTicks") or 0) / 600_000_000 <= int(args["max_minutes"])]
    out, cites = _fmt(items[:6])
    return Result(out or "Keine passenden ungesehenen Titel gefunden.", cites,
                  f"Jellyfin-Mediathek gelesen, {len(out)} Vorschläge")


@tool("jellyfin_play", "jellyfin",
      "Schlägt vor, einen Titel auf einem Jellyfin-Gerät (z. B. Fernseher) abzuspielen. "
      "Wird erst nach Bestätigung ausgeführt.",
      {"item_id": S("Jellyfin-ID des Titels"), "item_name": S("Name des Titels"),
       "device": S("Gerätename, z. B. Wohnzimmer", optional=True)}, kind="action")
async def play(ctx: Ctx, args: dict) -> Result:
    if not settings.get("jellyfin.playback"):
        return Result("Wiedergabe starten ist in Haus-KI nicht freigegeben.")
    async with client() as c:
        r = await c.get("/Sessions", params={"activeWithinSeconds": 1800})
        r.raise_for_status()
    sessions = [s for s in r.json() if s.get("SupportsRemoteControl")]
    if not sessions:
        return Result("Gerade ist kein Jellyfin-Gerät eingeschaltet, das sich fernsteuern lässt.")
    wanted = (args.get("device") or "").lower()
    s = next((s for s in sessions if wanted and wanted in s.get("DeviceName", "").lower()), sessions[0])
    return Result("Vorschlag erstellt.", action={
        "kind": "jellyfin_play", "summary": f"„{args.get('item_name')}“ auf {s.get('DeviceName')} abspielen?",
        "payload": {"session": s["Id"], "item": args["item_id"], "name": args.get("item_name"),
                    "device": s.get("DeviceName")}})


@action("jellyfin_play")
async def do_play(user: dict, p: dict) -> str:
    async with client() as c:
        r = await c.post(f"/Sessions/{p['session']}/Playing", params={"playCommand": "PlayNow", "itemIds": p["item"]})
        r.raise_for_status()
    return f"„{p['name']}“ läuft auf {p['device']}."


async def users_list() -> list[dict]:
    async with client() as c:
        r = await c.get("/Users")
        r.raise_for_status()
    return [{"id": u["Id"], "name": u["Name"]} for u in r.json()]
