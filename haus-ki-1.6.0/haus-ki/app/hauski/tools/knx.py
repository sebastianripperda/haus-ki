"""KNX direkt über die IP-Schnittstelle (xknx).

Jede Gruppenadresse hat eine Freigabe: none, read oder write. Haustür, Garagentor und
Alarmanlage werden beim Import erkannt und fest auf read gesetzt (locked).
"""
import asyncio
import logging
import re
import time

from xknx import XKNX
from xknx.core.value_reader import ValueReader
from xknx.dpt import DPTArray, DPTBase, DPTBinary
from xknx.io import ConnectionConfig, ConnectionType, SecureConfig
from xknx.telegram import GroupAddress, Telegram
from xknx.telegram.apci import GroupValueResponse, GroupValueWrite

from .. import db, settings, users
from ..config import config
from . import Ctx, Result, S, action, tool

log = logging.getLogger("hauski.knx")
LOCK_PATTERN = re.compile(r"(haust[üu]r|eingangst[üu]r|garage|tor\b|alarm|schlo(ss|ß)|t[üu]r[öo]ffner)", re.I)
_xknx: XKNX | None = None
_cache: dict[str, tuple[object, float]] = {}
_connect_lock = asyncio.Lock()


def keyring_path():
    return config.data_dir / "knx.knxkeys"


async def connection() -> XKNX:
    global _xknx
    async with _connect_lock:
        if _xknx is not None and _xknx.connection_manager.connected.is_set():
            return _xknx
        if _xknx is not None:
            await stop()
        if not settings.get("knx.enabled") or not settings.get("knx.gateway_ip") and settings.get("knx.mode") != "routing":
            raise RuntimeError("KNX ist nicht eingerichtet.")
        secure = settings.get("knx.secure")
        mode = settings.get("knx.mode")
        ctype = {("tunnel", False): ConnectionType.TUNNELING, ("tunnel", True): ConnectionType.TUNNELING_TCP_SECURE,
                 ("tunnel_tcp", False): ConnectionType.TUNNELING_TCP, ("tunnel_tcp", True): ConnectionType.TUNNELING_TCP_SECURE,
                 ("routing", False): ConnectionType.ROUTING, ("routing", True): ConnectionType.ROUTING_SECURE}[(mode, bool(secure))]
        cfg = ConnectionConfig(
            connection_type=ctype, gateway_ip=settings.get("knx.gateway_ip") or None,
            gateway_port=int(settings.get("knx.gateway_port") or 3671), local_ip=settings.get("knx.local_ip") or None,
            secure_config=SecureConfig(knxkeys_file_path=str(keyring_path()),
                                       knxkeys_password=settings.get("knx.keyring_password")) if secure else None)
        x = XKNX(connection_config=cfg)
        x.telegram_queue.register_telegram_received_cb(_on_telegram)
        await asyncio.wait_for(x.start(), timeout=15)
        _xknx = x
        return x


async def stop() -> None:
    global _xknx
    if _xknx is not None:
        try:
            await _xknx.stop()
        except Exception:  # noqa: BLE001
            pass
    _xknx = None


def _on_telegram(t: Telegram) -> None:
    if isinstance(t.payload, (GroupValueWrite, GroupValueResponse)):
        ga = db.row("SELECT dpt FROM knx_ga WHERE address=?", (str(t.destination_address),))
        if ga:
            _cache[str(t.destination_address)] = (_decode(ga["dpt"], t.payload.value), time.time())


def _transcoder(dpt: str | None):
    if not dpt:
        return None
    try:
        return DPTBase.parse_transcoder(dpt)
    except Exception:  # noqa: BLE001
        return None


def _decode(dpt: str | None, payload: DPTArray | DPTBinary):
    t = _transcoder(dpt)
    try:
        v = t.from_knx(payload) if t else (payload.value if isinstance(payload, DPTBinary) else list(payload.value))
    except Exception:  # noqa: BLE001
        return None
    v = getattr(v, "value", v)
    return round(v, 2) if isinstance(v, float) else v


async def read(address: str, max_age: float = 300) -> object:
    cached = _cache.get(address)
    if cached and time.time() - cached[1] < max_age:
        return cached[0]
    x = await connection()
    ga = db.row("SELECT dpt FROM knx_ga WHERE address=?", (address,))
    telegram = await ValueReader(x, GroupAddress(address), timeout_in_seconds=2).read()
    if telegram is None:
        return None
    value = _decode(ga["dpt"] if ga else None, telegram.payload.value)
    _cache[address] = (value, time.time())
    return value


async def write(address: str, value) -> None:
    ga = db.row("SELECT * FROM knx_ga WHERE address=?", (address,))
    if not ga or ga["permission"] != "write" or ga["locked"]:
        raise PermissionError("Diese Gruppenadresse darf Haus-KI nicht schalten.")
    t = _transcoder(ga["dpt"])
    if t is None:
        raise RuntimeError(f"Für {address} ist kein Datentyp bekannt. Bitte ETS-Projekt importieren.")
    payload = t.to_knx(value)
    x = await connection()
    x.telegrams.put_nowait(Telegram(destination_address=GroupAddress(address), payload=GroupValueWrite(payload)))
    _cache[address] = (value, time.time())


LIGHT = re.compile(r"licht|lampe|leuchte|spot|beleuchtung|led", re.I)
BLIND = re.compile(r"rollladen|rolllade|rollo|jalousie|raffstore|markise|beschattung", re.I)


def category(ga: dict) -> str:
    """Art des Geräts, für „ohne Rückfrage ausführen“. Im Zweifel „knx_other“ (immer mit Rückfrage)."""
    name, dpt = ga.get("name") or "", ga.get("dpt") or ""
    if BLIND.search(name):
        return "knx_blind"
    if LIGHT.search(name) and (dpt.startswith("1.") or dpt.startswith("5.")):
        return "knx_light"
    if dpt.startswith("9.001") and re.search(r"soll|temperatur|heiz", name, re.I):
        return "knx_climate"
    return "knx_other"


def allowed_gas(user: dict, want: str = "read") -> list[dict]:
    p = users.perms(user)
    if not p.get("knx"):
        return []
    rooms = p.get("knx_rooms") or []
    gas = db.rows("SELECT * FROM knx_ga WHERE permission!='none' ORDER BY room, name")
    if "*" not in rooms:
        gas = [g for g in gas if g["room"] in rooms]
    if want == "write":
        gas = [g for g in gas if g["permission"] == "write" and not g["locked"]]
    return gas


def _match(gas: list[dict], query: str) -> list[dict]:
    words = [w for w in re.findall(r"\w+", (query or "").lower()) if len(w) > 2]
    if not words:
        return gas
    return [g for g in gas if all(any(w in f for f in [(g["name"] or "").lower(), (g["room"] or "").lower()])
                                  for w in words)] or \
           [g for g in gas if any(w in (g["name"] + " " + (g["room"] or "")).lower() for w in words)]


def human(value, dpt: str | None) -> str:
    if value is None:
        return "keine Antwort"
    main = (dpt or "").split(".")[0]
    if main == "1":
        return "an" if value else "aus"
    if main == "9" and "001" in (dpt or ""):
        return f"{value} °C"
    if main == "5" and "001" in (dpt or ""):
        return f"{value} %"
    return str(value)


@tool("knx_status", "knx",
      "Liest aktuelle Zustände im Haus über KNX: Licht, Rollläden, Temperaturen, Fenster. "
      "Mit Raum oder Stichwort eingrenzen.",
      {"query": S("Raum oder Gerät, z. B. 'Wohnzimmer', 'Fenster', 'Temperatur Bad'", optional=True)})
async def status(ctx: Ctx, args: dict) -> Result:
    gas = _match(allowed_gas(ctx.user), args.get("query", ""))[:25]
    if not gas:
        return Result("Dafür gibt es keine freigegebenen KNX-Adressen.")
    values = await asyncio.gather(*(read(g["address"]) for g in gas), return_exceptions=True)
    out = [{"name": g["name"], "room": g["room"], "address": g["address"],
            "value": human(v if not isinstance(v, Exception) else None, g["dpt"]),
            "schaltbar": g["permission"] == "write" and not g["locked"]} for g, v in zip(gas, values)]
    return Result(out, step=f"KNX gelesen: {len(out)} Werte" + (f" für „{args['query']}“" if args.get("query") else ""))


@tool("knx_set", "knx",
      "Schlägt vor, ein Gerät über KNX zu schalten (Licht, Rollladen, Sollwert). "
      "Wird erst nach Bestätigung ausgeführt. Haustür, Garagentor und Alarm sind nie schaltbar.",
      {"address": S("Gruppenadresse aus knx_status, z. B. '1/2/3'"),
       "value": S("Neuer Wert: true/false für Schalter, Zahl für Prozent oder °C")}, kind="action")
async def set_value(ctx: Ctx, args: dict) -> Result:
    ga = next((g for g in allowed_gas(ctx.user, "write") if g["address"] == args.get("address")), None)
    if not ga:
        locked = db.row("SELECT name FROM knx_ga WHERE address=? AND locked=1", (args.get("address"),))
        return Result(f"„{locked['name']}“ kann Haus-KI nur anzeigen, nicht schalten." if locked
                      else "Diese Adresse ist für dich nicht schaltbar.")
    value = _parse_value(args.get("value"), ga["dpt"])
    return Result("Vorschlag erstellt.", action={
        "kind": "knx_write", "summary": f"{ga['name']}{' (' + ga['room'] + ')' if ga['room'] else ''}: "
                                        f"auf {human(value, ga['dpt'])} setzen?",
        "payload": {"address": ga["address"], "value": value, "name": ga["name"]}, "category": category(ga)})


def _parse_value(v, dpt: str | None):
    if isinstance(v, str):
        s = v.strip().lower()
        if s in ("true", "an", "ein", "on", "1", "auf"):
            return True if (dpt or "").startswith("1") else 1
        if s in ("false", "aus", "off", "0", "zu"):
            return False if (dpt or "").startswith("1") else 0
        try:
            return float(s.replace(",", ".").replace("°c", "").replace("%", ""))
        except ValueError:
            return v
    return v


@action("knx_write")
async def do_write(user: dict, p: dict) -> str:
    if not any(g["address"] == p["address"] for g in allowed_gas(user, "write")):
        raise PermissionError("Diese Adresse ist nicht (mehr) freigegeben. Es wurde nichts geändert.")
    await write(p["address"], p["value"])
    return f"{p['name']} gesetzt."


async def run_scene(name: str) -> str:
    scene = next((s for s in settings.get("knx.scenes") or [] if s.get("name") == name), None)
    if not scene:
        raise RuntimeError("Diese Szene gibt es nicht.")
    done = []
    for w in scene.get("writes", []):
        await write(w["address"], w["value"])
        done.append(w["address"])
    return f"Szene „{name}“ ausgeführt ({len(done)} Befehle)."


async def trip_check() -> list[dict]:
    """„Bevor wir fahren“: offene Fenster und eingeschaltete Lichter."""
    addresses = settings.get("knx.trip_check") or [g["address"] for g in db.rows(
        "SELECT address FROM knx_ga WHERE permission!='none' AND lower(name) LIKE '%fenster%'")]
    gas = [db.row("SELECT * FROM knx_ga WHERE address=?", (a,)) for a in addresses]
    gas = [g for g in gas if g]
    values = await asyncio.gather(*(read(g["address"], max_age=60) for g in gas), return_exceptions=True)
    return [{"name": g["name"], "room": g["room"], "value": human(v if not isinstance(v, Exception) else None, g["dpt"]),
             "open": bool(v) and not isinstance(v, Exception)} for g, v in zip(gas, values)]


def import_project(path: str, password: str | None) -> dict:
    """ETS-Projekt (.knxproj) einlesen. Bestehende Freigaben bleiben erhalten."""
    from xknxproject import XKNXProj
    project = XKNXProj(path=path, password=password or None, language="de-DE").parse()
    ranges = project.get("group_ranges", {})

    def range_name(addr: str) -> str:
        parts = addr.split("/")
        if len(parts) == 3:
            mid = ranges.get(parts[0], {}).get("group_ranges", {}).get(f"{parts[0]}/{parts[1]}", {})
            return mid.get("name", "")
        return ""

    added = updated = 0
    with db.tx() as conn:
        for addr, ga in project.get("group_addresses", {}).items():
            dpt = ga.get("dpt")
            dpt_s = f"{dpt['main']}.{dpt['sub']:03d}" if dpt and dpt.get("sub") is not None else (str(dpt["main"]) if dpt else None)
            name = ga.get("name", addr)
            locked = 1 if LOCK_PATTERN.search(name) else 0
            exists = conn.execute("SELECT permission FROM knx_ga WHERE address=?", (addr,)).fetchone()
            if exists:
                conn.execute("UPDATE knx_ga SET name=?, dpt=?, room=?, locked=?, "
                             "permission=CASE WHEN ?=1 AND permission='write' THEN 'read' ELSE permission END WHERE address=?",
                             (name, dpt_s, range_name(addr), locked, locked, addr))
                updated += 1
            else:
                conn.execute("INSERT INTO knx_ga(address,name,dpt,room,permission,locked) VALUES(?,?,?,?,?,?)",
                             (addr, name, dpt_s, range_name(addr), "read" if locked else "none", locked))
                added += 1
    return {"added": added, "updated": updated, "project": project.get("info", {}).get("name", "")}
