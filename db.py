"""Source registry backed by SQLite at ~/.podcaster/sources.db."""

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

DB_PATH = Path.home() / ".podcaster" / "sources.db"

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS sources (
    id       TEXT PRIMARY KEY,
    name     TEXT NOT NULL,
    path     TEXT NOT NULL,
    added_at TEXT NOT NULL
)
"""


@dataclass
class Source:
    id: str
    name: str
    path: str
    added_at: str


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute(_CREATE_TABLE)
    conn.commit()
    return conn


def add_source(epub_path: Path, name: str) -> Source:
    """Register an epub file in the source registry.

    Args:
        epub_path: Absolute resolved path to the epub file.
        name: Display name (typically the epub's title metadata).

    Returns:
        The newly created Source record.
    """
    source = Source(
        id=uuid4().hex[:8],
        name=name,
        path=str(epub_path),
        added_at=datetime.now(timezone.utc).isoformat(),
    )
    with _connect() as conn:
        conn.execute(
            "INSERT INTO sources (id, name, path, added_at) VALUES (?, ?, ?, ?)",
            (source.id, source.name, source.path, source.added_at),
        )
    return source


def list_sources() -> list[Source]:
    """Return all registered sources, ordered by registration time."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT id, name, path, added_at FROM sources ORDER BY added_at"
        ).fetchall()
    return [Source(*row) for row in rows]


def rename_source(query: str, new_name: str) -> Source | None:
    """Rename a registered source identified by ID or name substring.

    Args:
        query: Exact source ID or a substring of the current source name.
        new_name: Replacement display name.

    Returns:
        The updated Source, or None if no matching source was found.
    """
    source = find_source(query)
    if source is None:
        return None
    with _connect() as conn:
        conn.execute("UPDATE sources SET name = ? WHERE id = ?", (new_name, source.id))
    source.name = new_name
    return source


def find_source(query: str) -> Source | None:
    """Find a source by exact ID or name substring (case-insensitive).

    Args:
        query: Exact source ID or a substring of the source name.

    Returns:
        The matching Source, or None if not found.
    """
    with _connect() as conn:
        row = conn.execute(
            "SELECT id, name, path, added_at FROM sources WHERE id = ?", (query,)
        ).fetchone()
        if row:
            return Source(*row)

        row = conn.execute(
            "SELECT id, name, path, added_at FROM sources"
            " WHERE lower(name) LIKE lower(?)",
            (f"%{query}%",),
        ).fetchone()
        if row:
            return Source(*row)

    return None
