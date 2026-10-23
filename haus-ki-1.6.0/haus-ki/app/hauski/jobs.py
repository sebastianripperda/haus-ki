"""Warteschlange für alles, was Ollama rechnen lässt.

Ollama läuft auf der CPU und bearbeitet sinnvoll nur eine Anfrage zur Zeit. Diese Schlange
sorgt für eine faire Reihenfolge: Fragen (0) vor geplanten Prompts (5) vor Nachtaufgaben (9).
Ereignisse eines Auftrags werden zwischengespeichert, damit ein Browser nach dem Neuladen
wieder einsteigen kann.
"""
import asyncio
import itertools
import time
from typing import Awaitable, Callable

from . import settings

INTERACTIVE, SCHEDULED, NIGHT = 0, 5, 9
_ids = itertools.count(1)


class Job:
    def __init__(self, user_id: int, priority: int, label: str, run: Callable[["Job"], Awaitable[None]],
                 chat_id: int | None = None):
        self.id = next(_ids)
        self.user_id, self.priority, self.label, self.run, self.chat_id = user_id, priority, label, run, chat_id
        self.created = time.time()
        self.started: float | None = None
        self.status = "queued"
        self.events: list[dict] = []
        self.listeners: set[asyncio.Queue] = set()
        self.task: asyncio.Task | None = None
        self.done = asyncio.Event()

    def emit(self, event: dict) -> None:
        if event.get("type") == "delta" and self.events and self.events[-1].get("type") == "delta" \
                and self.events[-1].get("key") == event.get("key"):
            self.events[-1] = {**self.events[-1], "text": self.events[-1]["text"] + event["text"]}
        else:
            self.events.append(event)
        for q in list(self.listeners):
            q.put_nowait(event)


class JobQueue:
    def __init__(self) -> None:
        self.waiting: list[Job] = []
        self.running: list[Job] = []
        self.jobs: dict[int, Job] = {}
        self._wake = asyncio.Event()
        self._workers: list[asyncio.Task] = []
        self._durations: list[float] = []

    def start(self) -> None:
        n = max(1, int(settings.get("ollama.parallel") or 1))
        self._workers = [asyncio.create_task(self._worker()) for _ in range(n)]

    async def stop(self) -> None:
        for w in self._workers:
            w.cancel()

    def submit(self, job: Job) -> Job:
        self.jobs[job.id] = job
        self.waiting.append(job)
        self.waiting.sort(key=lambda j: (j.priority, j.created))
        self._broadcast_positions()
        self._wake.set()
        return job

    def cancel(self, job: Job) -> None:
        if job in self.waiting:
            self.waiting.remove(job)
            job.status = "cancelled"
            job.emit({"type": "cancelled"})
            job.done.set()
            self._broadcast_positions()
        elif job.task:
            job.task.cancel()

    def avg_seconds(self) -> float:
        return sum(self._durations) / len(self._durations) if self._durations else 45.0

    def position(self, job: Job) -> int:
        return self.waiting.index(job) + 1 if job in self.waiting else 0

    def status(self) -> dict:
        return {"running": [{"user_id": j.user_id, "label": j.label, "priority": j.priority} for j in self.running],
                "waiting": len(self.waiting),
                "waiting_interactive": sum(1 for j in self.waiting if j.priority == INTERACTIVE),
                "avg_seconds": round(self.avg_seconds())}

    def _broadcast_positions(self) -> None:
        avg = self.avg_seconds()
        for i, j in enumerate(self.waiting):
            ahead = i + len(self.running)
            j.emit({"type": "queue", "position": i + 1, "ahead": ahead, "eta": round(ahead * avg)})

    async def _worker(self) -> None:
        while True:
            if not self.waiting:
                self._wake.clear()
                await self._wake.wait()
                continue
            job = self.waiting.pop(0)
            self.running.append(job)
            self._broadcast_positions()
            job.status, job.started = "running", time.time()
            job.emit({"type": "start"})
            job.task = asyncio.create_task(job.run(job))
            try:
                await job.task
                job.status = "done"
            except asyncio.CancelledError:
                if not job.task.cancelled():
                    raise  # der Arbeiter selbst wird beendet (Herunterfahren)
                job.status = "cancelled"
                job.emit({"type": "cancelled"})
            except Exception as e:  # noqa: BLE001 – Fehler gehen als Ereignis an den Browser
                job.status = "error"
                job.emit({"type": "error", "text": str(e) or e.__class__.__name__})
            if job in self.running:
                self.running.remove(job)
            if job.priority == INTERACTIVE and job.status == "done":
                self._durations = (self._durations + [time.time() - job.started])[-20:]
            job.emit({"type": "end", "status": job.status})
            job.done.set()
            self._broadcast_positions()
            self._gc()

    def _gc(self) -> None:
        cutoff = time.time() - 3600
        for jid, j in list(self.jobs.items()):
            if j.done.is_set() and j.created < cutoff:
                del self.jobs[jid]


queue = JobQueue()
