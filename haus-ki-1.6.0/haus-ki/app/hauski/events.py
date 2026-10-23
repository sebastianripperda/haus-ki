"""Protokoll, Benachrichtigungen und Live-Ereignisse an offene Browser."""
import asyncio
from collections import defaultdict

from . import db


class Hub:
    """Verteilt Ereignisse an alle offenen Tabs eines Benutzers (Server-Sent Events)."""

    def __init__(self) -> None:
        self._subs: dict[int, set[asyncio.Queue]] = defaultdict(set)

    def subscribe(self, user_id: int) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=200)
        self._subs[user_id].add(q)
        return q

    def unsubscribe(self, user_id: int, q: asyncio.Queue) -> None:
        self._subs[user_id].discard(q)

    def publish(self, user_id: int, event: dict) -> None:
        for q in list(self._subs.get(user_id, ())):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                pass

    def online(self, user_id: int) -> bool:
        return bool(self._subs.get(user_id))


hub = Hub()


def audit(user: str, category: str, text: str) -> None:
    """Kategorien: Aktion, Einstellung, Anmeldung, Einsicht, System, Sicherung."""
    db.run("INSERT INTO audit(ts,user,category,text) VALUES(?,?,?,?)", (db.now(), user, category, text))


def notify(user_id: int, text: str, link: str = "", level: str = "info") -> None:
    nid = db.run("INSERT INTO notifications(user_id,text,link,level,created) VALUES(?,?,?,?,?)",
                 (user_id, text, link, level, db.now()))
    hub.publish(user_id, {"type": "notification", "id": nid, "text": text, "link": link, "level": level})
    from . import push
    push.send_later(user_id, "Haus-KI", text, link)


def notify_admins(text: str, link: str = "", level: str = "warn") -> None:
    for u in db.rows("SELECT id FROM users WHERE role='admin' AND disabled=0"):
        notify(u["id"], text, link, level)
