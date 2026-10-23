"""SQLite-Zugriff: eine Datei, WAL-Modus, Migrationen über user_version."""
import json
import sqlite3
import threading
import time
from contextlib import contextmanager

from .config import config

SCHEMA = [
    """
    CREATE TABLE users (
        id INTEGER PRIMARY KEY, name TEXT NOT NULL, email TEXT, oid TEXT UNIQUE,
        role TEXT NOT NULL DEFAULT 'member', color TEXT, pw_hash TEXT,
        perms TEXT NOT NULL DEFAULT '{}', prefs TEXT NOT NULL DEFAULT '{}',
        disabled INTEGER NOT NULL DEFAULT 0, failed_logins INTEGER NOT NULL DEFAULT 0,
        locked_until REAL NOT NULL DEFAULT 0, created REAL NOT NULL);
    CREATE TABLE sessions (
        id TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        created REAL NOT NULL, last_seen REAL NOT NULL, ip TEXT, ua TEXT, method TEXT);
    CREATE TABLE projects (
        id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        title TEXT NOT NULL, description TEXT NOT NULL DEFAULT '', notes TEXT NOT NULL DEFAULT '',
        system TEXT NOT NULL DEFAULT '', docs TEXT NOT NULL DEFAULT '[]', created REAL NOT NULL);
    CREATE TABLE chats (
        id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        project_id INTEGER REFERENCES projects(id) ON DELETE SET NULL,
        title TEXT NOT NULL, pinned INTEGER NOT NULL DEFAULT 0, kind TEXT NOT NULL DEFAULT 'chat',
        shared_by INTEGER, created REAL NOT NULL, updated REAL NOT NULL);
    CREATE INDEX chats_user ON chats(user_id, updated);
    CREATE TABLE messages (
        id INTEGER PRIMARY KEY, chat_id INTEGER NOT NULL REFERENCES chats(id) ON DELETE CASCADE,
        role TEXT NOT NULL, content TEXT NOT NULL, meta TEXT NOT NULL DEFAULT '{}', created REAL NOT NULL);
    CREATE INDEX messages_chat ON messages(chat_id, id);
    CREATE TABLE templates (
        id INTEGER PRIMARY KEY, owner_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
        title TEXT NOT NULL, prompt TEXT NOT NULL, system TEXT NOT NULL DEFAULT '',
        model TEXT NOT NULL DEFAULT '', json_mode INTEGER NOT NULL DEFAULT 0, created REAL NOT NULL);
    CREATE TABLE memory (
        id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        text TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 1, created REAL NOT NULL);
    CREATE TABLE accounts (
        id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        kind TEXT NOT NULL, address TEXT NOT NULL, secret TEXT, drafts INTEGER NOT NULL DEFAULT 0,
        created REAL NOT NULL);
    CREATE TABLE ms_tokens (
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, audience TEXT NOT NULL,
        refresh TEXT, access TEXT, expires REAL NOT NULL DEFAULT 0, PRIMARY KEY (user_id, audience));
    CREATE TABLE schedules (
        id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        name TEXT NOT NULL, prompt TEXT NOT NULL, options TEXT NOT NULL DEFAULT '{}',
        freq TEXT NOT NULL, day TEXT, time TEXT NOT NULL, deliver TEXT NOT NULL DEFAULT 'notify',
        enabled INTEGER NOT NULL DEFAULT 1, last_run REAL NOT NULL DEFAULT 0, created REAL NOT NULL);
    CREATE TABLE insights (
        id INTEGER PRIMARY KEY, user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
        kind TEXT NOT NULL, ref TEXT, data TEXT NOT NULL, done INTEGER NOT NULL DEFAULT 0,
        created REAL NOT NULL);
    CREATE INDEX insights_user ON insights(user_id, kind);
    CREATE TABLE actions (
        id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, chat_id INTEGER, message_id INTEGER,
        kind TEXT NOT NULL, summary TEXT NOT NULL, payload TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending', result TEXT, created REAL NOT NULL, decided REAL);
    CREATE TABLE audit (
        id INTEGER PRIMARY KEY, ts REAL NOT NULL, user TEXT NOT NULL, category TEXT NOT NULL, text TEXT NOT NULL);
    CREATE INDEX audit_ts ON audit(ts);
    CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
    CREATE TABLE feedback (
        message_id INTEGER NOT NULL, user_id INTEGER NOT NULL, value INTEGER NOT NULL, created REAL NOT NULL,
        PRIMARY KEY (message_id, user_id));
    CREATE TABLE knx_ga (
        address TEXT PRIMARY KEY, name TEXT NOT NULL, dpt TEXT, room TEXT,
        permission TEXT NOT NULL DEFAULT 'none', locked INTEGER NOT NULL DEFAULT 0);
    CREATE TABLE notifications (
        id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        text TEXT NOT NULL, link TEXT, level TEXT NOT NULL DEFAULT 'info', read INTEGER NOT NULL DEFAULT 0,
        created REAL NOT NULL);
    CREATE TABLE night_runs (
        id INTEGER PRIMARY KEY, night TEXT NOT NULL, task TEXT NOT NULL, started REAL NOT NULL,
        finished REAL, status TEXT NOT NULL DEFAULT 'running', detail TEXT);
    CREATE TABLE kv (key TEXT PRIMARY KEY, value TEXT NOT NULL);
    """,
    # Version 2: Personenfarben für das neue helle und dunkle Design
    """
    UPDATE users SET color = CASE color
        WHEN '#9db6c7' THEN '#3f4a5a' WHEN '#c4b5fd' THEN '#7c5cc4' WHEN '#86efac' THEN '#1a7f37'
        WHEN '#fcd34d' THEN '#b45309' WHEN '#f9a8d4' THEN '#c2417a' WHEN '#93c5fd' THEN '#1f6fb2'
        WHEN '#fdba74' THEN '#0f766e' ELSE color END;
    """,
    # Version 3: Werkzeug-Protokoll, Kommentare zu Bewertungen, Paperless-Index, Push
    """
    CREATE TABLE tool_log (
        id INTEGER PRIMARY KEY, ts REAL NOT NULL, tool TEXT NOT NULL, ok INTEGER NOT NULL, ms INTEGER NOT NULL,
        error TEXT, model TEXT);
    CREATE INDEX tool_log_ts ON tool_log(ts);
    ALTER TABLE feedback ADD COLUMN comment TEXT;
    CREATE TABLE paperless_chunks (
        doc_id INTEGER NOT NULL, chunk INTEGER NOT NULL, title TEXT, text TEXT NOT NULL, vec BLOB NOT NULL,
        modified TEXT, PRIMARY KEY (doc_id, chunk));
    CREATE TABLE push_subs (
        endpoint TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        p256dh TEXT NOT NULL, auth TEXT NOT NULL, ua TEXT, created REAL NOT NULL);
    """,
    # Version 4: Suche in alten Chats, gemeinsames Familienwissen
    """
    CREATE TABLE chat_chunks (
        msg_id INTEGER PRIMARY KEY REFERENCES messages(id) ON DELETE CASCADE,
        chat_id INTEGER NOT NULL REFERENCES chats(id) ON DELETE CASCADE,
        user_id INTEGER NOT NULL, text TEXT NOT NULL, vec BLOB NOT NULL, created REAL NOT NULL);
    CREATE INDEX chat_chunks_user ON chat_chunks(user_id);
    CREATE TABLE family_facts (
        id INTEGER PRIMARY KEY, text TEXT NOT NULL, created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
        enabled INTEGER NOT NULL DEFAULT 1, created REAL NOT NULL);
    """,
    # Version 5: Vermerk, wie eine Aktion bestätigt wurde (Knopf, per Sprache, ohne Rückfrage)
    """
    ALTER TABLE actions ADD COLUMN via TEXT;
    """,
]

_local = threading.local()
_lock = threading.RLock()


def connect() -> sqlite3.Connection:
    conn = getattr(_local, "conn", None)
    if conn is None:
        config.data_dir.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(config.db_path, timeout=30, isolation_level=None, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=30000")
        _local.conn = conn
    return conn


def close() -> None:
    conn = getattr(_local, "conn", None)
    if conn is not None:
        conn.close()
        _local.conn = None


def migrate() -> None:
    conn = connect()
    with _lock:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        for i, script in enumerate(SCHEMA[version:], start=version + 1):
            conn.executescript("BEGIN;" + script + f"PRAGMA user_version={i}; COMMIT;")


@contextmanager
def tx():
    conn = connect()
    with _lock:
        conn.execute("BEGIN IMMEDIATE")
        try:
            yield conn
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise


def run(sql: str, args=()) -> int:
    with _lock:
        return connect().execute(sql, args).lastrowid


def rows(sql: str, args=()) -> list[dict]:
    return [dict(r) for r in connect().execute(sql, args).fetchall()]


def row(sql: str, args=()) -> dict | None:
    r = connect().execute(sql, args).fetchone()
    return dict(r) if r else None


def scalar(sql: str, args=()):
    r = connect().execute(sql, args).fetchone()
    return r[0] if r else None


def now() -> float:
    return time.time()


def jload(s, default=None):
    if s is None or s == "":
        return default
    try:
        return json.loads(s)
    except (TypeError, ValueError):
        return default


def jdump(v) -> str:
    return json.dumps(v, ensure_ascii=False)


def kv_get(key: str, default=None):
    r = row("SELECT value FROM kv WHERE key=?", (key,))
    return jload(r["value"], default) if r else default


def kv_set(key: str, value) -> None:
    run("INSERT INTO kv(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, jdump(value)))
