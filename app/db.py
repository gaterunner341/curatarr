"""SQLite persistence for settings, collections and sync history."""
import json
import os
import sqlite3
import threading
import uuid
from datetime import datetime, timezone

from . import config

_lock = threading.RLock()
_conn: sqlite3.Connection | None = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
);
CREATE TABLE IF NOT EXISTS collections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    config TEXT NOT NULL,
    plex_rating_key TEXT,
    poster_applied TEXT,
    art_applied TEXT,
    last_run TEXT,
    last_status TEXT,
    last_message TEXT,
    created TEXT
);
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    collection_id INTEGER,
    collection_name TEXT,
    trigger TEXT,
    started TEXT,
    finished TEXT,
    status TEXT,
    source_count INTEGER DEFAULT 0,
    matched INTEGER DEFAULT 0,
    added INTEGER DEFAULT 0,
    removed INTEGER DEFAULT 0,
    requested INTEGER DEFAULT 0,
    missing TEXT,
    message TEXT
);
CREATE INDEX IF NOT EXISTS runs_collection ON runs (collection_id, id);
"""

RUN_HISTORY_LIMIT = 2000


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect() -> sqlite3.Connection:
    global _conn
    with _lock:
        if _conn is None:
            os.makedirs(config.CONFIG_DIR, exist_ok=True)
            os.makedirs(config.IMAGE_DIR, exist_ok=True)
            _conn = sqlite3.connect(config.DB_PATH, check_same_thread=False)
            _conn.row_factory = sqlite3.Row
            _conn.execute("PRAGMA journal_mode=WAL")
            _conn.executescript(SCHEMA)
            _migrate(_conn)
            _conn.commit()
        return _conn


def _migrate(conn: sqlite3.Connection) -> None:
    """Add columns introduced after the first release."""
    columns = {r[1] for r in conn.execute("PRAGMA table_info(collections)")}
    if "plex_owned" not in columns:     # 0.5.3: 1 = Curatarr may remove titles / delete it
        conn.execute("ALTER TABLE collections ADD COLUMN plex_owned INTEGER")
    run_columns = {r[1] for r in conn.execute("PRAGMA table_info(runs)")}
    for column in ("added_items", "removed_items"):    # 0.7.0: which titles a sync changed
        if column not in run_columns:
            conn.execute(f"ALTER TABLE runs ADD COLUMN {column} TEXT")


def close() -> None:
    global _conn
    with _lock:
        if _conn is not None:
            _conn.close()
            _conn = None


def _execute(sql: str, params: tuple = ()) -> sqlite3.Cursor:
    with _lock:
        conn = connect()
        cur = conn.execute(sql, params)
        conn.commit()
        return cur


def _query(sql: str, params: tuple = ()) -> list[dict]:
    with _lock:
        return [dict(r) for r in connect().execute(sql, params).fetchall()]


# --- settings -----------------------------------------------------------------

def get_settings() -> dict[str, str]:
    """Saved settings merged over defaults, with blanks filled from the environment."""
    values = dict(config.DEFAULT_SETTINGS)
    for row in _query("SELECT key, value FROM settings"):
        values[row["key"]] = row["value"] or ""
    for key, env in config.ENV_SETTINGS.items():
        if not values.get(key) and os.environ.get(env):
            values[key] = os.environ[env]
    return values


def save_settings(values: dict[str, str]) -> None:
    with _lock:
        conn = connect()
        for key, value in values.items():
            conn.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, "" if value is None else str(value)),
            )
        conn.commit()


def plex_client_identifier() -> str:
    row = _query("SELECT value FROM settings WHERE key = ?", (config.PLEX_CLIENT_ID_KEY,))
    if row and row[0]["value"]:
        return row[0]["value"]
    ident = f"curatarr-{uuid.uuid4()}"
    save_settings({config.PLEX_CLIENT_ID_KEY: ident})
    return ident


# --- collections --------------------------------------------------------------

def _decode_collection(row: dict) -> dict:
    row["config"] = json.loads(row["config"])
    return row


def list_collections() -> list[dict]:
    return [_decode_collection(r) for r in _query("SELECT * FROM collections ORDER BY id")]


def get_collection(collection_id: int) -> dict | None:
    rows = _query("SELECT * FROM collections WHERE id = ?", (collection_id,))
    return _decode_collection(rows[0]) if rows else None


def create_collection(cfg: dict) -> int:
    cur = _execute(
        "INSERT INTO collections (config, created) VALUES (?, ?)", (json.dumps(cfg), now())
    )
    return int(cur.lastrowid)


def update_collection_config(collection_id: int, cfg: dict) -> None:
    _execute("UPDATE collections SET config = ? WHERE id = ?", (json.dumps(cfg), collection_id))


_STATE_COLUMNS = {
    "plex_rating_key",
    "plex_owned",
    "poster_applied",
    "art_applied",
    "last_run",
    "last_status",
    "last_message",
}


def update_collection_state(collection_id: int, **fields) -> None:
    fields = {k: v for k, v in fields.items() if k in _STATE_COLUMNS}
    if not fields:
        return
    assignments = ", ".join(f"{k} = ?" for k in fields)
    _execute(
        f"UPDATE collections SET {assignments} WHERE id = ?",
        (*fields.values(), collection_id),
    )


def delete_collection(collection_id: int) -> None:
    _execute("DELETE FROM collections WHERE id = ?", (collection_id,))


# --- runs ---------------------------------------------------------------------

def record_run(run: dict) -> int:
    cols = [
        "collection_id", "collection_name", "trigger", "started", "finished", "status",
        "source_count", "matched", "added", "removed", "requested", "missing", "message",
        "added_items", "removed_items",
    ]
    counters = {"source_count", "matched", "added", "removed", "requested"}
    values = [run.get(c) or 0 if c in counters else run.get(c) for c in cols]
    for c in _JSON_RUN_COLUMNS:
        values[cols.index(c)] = json.dumps(run.get(c) or [])
    cur = _execute(
        f"INSERT INTO runs ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})",
        tuple(values),
    )
    _execute(
        "DELETE FROM runs WHERE id <= (SELECT MAX(id) FROM runs) - ?", (RUN_HISTORY_LIMIT,)
    )
    return int(cur.lastrowid)


def list_runs(collection_id: int | None = None, limit: int = 100) -> list[dict]:
    if collection_id is None:
        rows = _query("SELECT * FROM runs ORDER BY id DESC LIMIT ?", (limit,))
    else:
        rows = _query(
            "SELECT * FROM runs WHERE collection_id = ? ORDER BY id DESC LIMIT ?",
            (collection_id, limit),
        )
    return [_decode_run(r) for r in rows]


def last_change(collection_id: int) -> dict | None:
    """The latest successful run of a collection that added or removed titles."""
    rows = _query(
        "SELECT * FROM runs WHERE collection_id = ? AND status IN ('success', 'warning') "
        "AND (added > 0 OR removed > 0) ORDER BY id DESC LIMIT 1", (collection_id,))
    if not rows:
        return None
    run = _decode_run(rows[0])
    # Runs from before 0.7.0 didn't record which titles changed.
    return run if run["added_items"] or run["removed_items"] else None


_JSON_RUN_COLUMNS = ("missing", "added_items", "removed_items")


def _decode_run(row: dict) -> dict:
    for c in _JSON_RUN_COLUMNS:
        row[c] = json.loads(row.get(c) or "[]")
    return row
