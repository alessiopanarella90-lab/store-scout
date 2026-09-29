"""Database SQLite: un file solo, facile da spostare poi su Cloudflare D1."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS extensions (
    ext_id        TEXT PRIMARY KEY,
    url           TEXT NOT NULL,
    name          TEXT,
    users         INTEGER,
    rating        REAL,
    rating_count  INTEGER,
    updated       TEXT,
    version       TEXT,
    category      TEXT,
    first_seen    TEXT NOT NULL,
    last_fetched  TEXT,
    fetch_status  INTEGER,
    removed_at    TEXT,
    reported_at   TEXT
);
CREATE INDEX IF NOT EXISTS idx_fetch ON extensions(last_fetched);
CREATE TABLE IF NOT EXISTS user_history (
    ext_id  TEXT NOT NULL,
    day     TEXT NOT NULL,
    users   INTEGER,
    PRIMARY KEY (ext_id, day)
);
CREATE TABLE IF NOT EXISTS runs (
    started   TEXT, finished TEXT, fetched INTEGER, parsed_ok INTEGER, errors INTEGER, note TEXT
);
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(path: str | Path) -> sqlite3.Connection:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    return con


def upsert_urls(con: sqlite3.Connection, items: list[tuple[str, str]]) -> int:
    """items = [(ext_id, url)]. Ritorna quante estensioni nuove."""
    before = con.execute("SELECT COUNT(*) FROM extensions").fetchone()[0]
    ts = now()
    con.executemany(
        "INSERT OR IGNORE INTO extensions(ext_id, url, first_seen) VALUES (?,?,?)",
        [(i, u, ts) for i, u in items],
    )
    con.commit()
    return con.execute("SELECT COUNT(*) FROM extensions").fetchone()[0] - before


def next_batch(con: sqlite3.Connection, limit: int, refresh_days: int) -> list[sqlite3.Row]:
    """Prima le mai lette, poi le piu' vecchie oltre refresh_days. Salta le rimosse."""
    return con.execute(
        """
        SELECT ext_id, url FROM extensions
        WHERE removed_at IS NULL
          AND (last_fetched IS NULL OR last_fetched < datetime('now', ?))
        ORDER BY last_fetched IS NOT NULL, last_fetched
        LIMIT ?
        """,
        (f"-{refresh_days} days", limit),
    ).fetchall()


def save_listing(con: sqlite3.Connection, data: dict, status: int) -> None:
    ts = now()
    con.execute(
        """
        UPDATE extensions SET name=COALESCE(:name,name), users=COALESCE(:users,users),
            rating=COALESCE(:rating,rating), rating_count=COALESCE(:rating_count,rating_count),
            updated=COALESCE(:updated,updated), version=COALESCE(:version,version),
            category=COALESCE(:category,category), last_fetched=:ts, fetch_status=:status
        WHERE ext_id=:ext_id
        """,
        {**data, "ts": ts, "status": status},
    )
    if data.get("users") is not None:
        con.execute(
            "INSERT OR REPLACE INTO user_history(ext_id, day, users) VALUES (?, date('now'), ?)",
            (data["ext_id"], data["users"]),
        )


def mark_removed(con: sqlite3.Connection, ext_id: str, status: int) -> None:
    ts = now()
    con.execute(
        "UPDATE extensions SET removed_at=COALESCE(removed_at, ?), last_fetched=?, fetch_status=? WHERE ext_id=?",
        (ts, ts, status, ext_id),
    )


def mark_error(con: sqlite3.Connection, ext_id: str, status: int) -> None:
    con.execute(
        "UPDATE extensions SET last_fetched=?, fetch_status=? WHERE ext_id=?", (now(), status, ext_id)
    )
