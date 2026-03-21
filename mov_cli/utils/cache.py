"""
utils/cache.py
--------------
SQLite-backed cache for search results and watch history.

Two tables:
  - search_cache   : stores serialised JSON results keyed by query string
  - watch_history  : persists every stream the user plays

All timestamps are UTC ISO-8601 strings.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Generator, Optional

from mov_cli.models.media import MediaResult, WatchHistoryEntry
from mov_cli.utils.config import config

# ─── Database path ─────────────────────────────────────────────────────────────

DB_PATH = Path.home() / ".mov-cli" / "history.db"


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


# ─── Connection helper ─────────────────────────────────────────────────────────

@contextmanager
def _connect() -> Generator[sqlite3.Connection, None, None]:
    """Context manager that opens, yields, and commits/closes a connection."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


# ─── Schema initialisation ─────────────────────────────────────────────────────

def init_db() -> None:
    """Create tables if they don't exist. Safe to call on every startup."""
    with _connect() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS search_cache (
                cache_key   TEXT PRIMARY KEY,
                results_json TEXT NOT NULL,
                cached_at   TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS watch_history (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                media_id        INTEGER NOT NULL,
                title           TEXT NOT NULL,
                media_type      TEXT NOT NULL,
                year            TEXT,
                watched_at      TEXT NOT NULL,
                quality         TEXT DEFAULT 'Unknown',
                source_provider TEXT DEFAULT 'unknown'
            );

            CREATE INDEX IF NOT EXISTS idx_watch_history_media_id
                ON watch_history(media_id);
            CREATE INDEX IF NOT EXISTS idx_watch_history_watched_at
                ON watch_history(watched_at DESC);
        """)


# ─── Search cache ──────────────────────────────────────────────────────────────

class SearchCache:
    """Read/write search results with TTL-based invalidation."""

    @staticmethod
    def _make_key(query: str, media_type: str) -> str:
        return f"{media_type}::{query.strip().lower()}"

    @classmethod
    def get(cls, query: str, media_type: str) -> Optional[list[MediaResult]]:
        """Return cached results or None if missing / expired."""
        if not config.cache_enabled:
            return None

        key = cls._make_key(query, media_type)
        cutoff = (
            datetime.now(timezone.utc) - timedelta(hours=config.cache_ttl_hours)
        ).isoformat()

        with _connect() as conn:
            row = conn.execute(
                "SELECT results_json, cached_at FROM search_cache WHERE cache_key = ?",
                (key,),
            ).fetchone()

        if row is None:
            return None
        if row["cached_at"] < cutoff:
            # Expired — delete and signal miss
            SearchCache.delete(query, media_type)
            return None

        raw: list[dict] = json.loads(row["results_json"])
        return [MediaResult.from_dict(d) for d in raw]

    @classmethod
    def set(cls, query: str, media_type: str, results: list[MediaResult]) -> None:
        if not config.cache_enabled:
            return
        key = cls._make_key(query, media_type)
        data = json.dumps([r.to_dict() for r in results])
        with _connect() as conn:
            conn.execute(
                """INSERT INTO search_cache(cache_key, results_json, cached_at)
                   VALUES(?, ?, ?)
                   ON CONFLICT(cache_key) DO UPDATE SET
                       results_json = excluded.results_json,
                       cached_at    = excluded.cached_at""",
                (key, data, _now_utc()),
            )

    @classmethod
    def delete(cls, query: str, media_type: str) -> None:
        key = cls._make_key(query, media_type)
        with _connect() as conn:
            conn.execute("DELETE FROM search_cache WHERE cache_key = ?", (key,))

    @staticmethod
    def clear_all() -> None:
        with _connect() as conn:
            conn.execute("DELETE FROM search_cache")


# ─── Watch history ─────────────────────────────────────────────────────────────

class WatchHistory:
    """Append and query the user's watch history."""

    @staticmethod
    def add(
        result: MediaResult,
        quality: str = "Unknown",
        provider: str = "unknown",
    ) -> None:
        with _connect() as conn:
            conn.execute(
                """INSERT INTO watch_history
                       (media_id, title, media_type, year, watched_at, quality, source_provider)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    result.id,
                    result.title,
                    result.media_type.value,
                    result.display_year,
                    _now_utc(),
                    quality,
                    provider,
                ),
            )

    @staticmethod
    def get_recent(limit: int = 20) -> list[WatchHistoryEntry]:
        with _connect() as conn:
            rows = conn.execute(
                """SELECT media_id, title, media_type, year,
                          watched_at, quality, source_provider
                   FROM watch_history
                   ORDER BY watched_at DESC
                   LIMIT ?""",
                (limit,),
            ).fetchall()
        return [WatchHistoryEntry(**dict(r)) for r in rows]

    @staticmethod
    def clear_all() -> None:
        with _connect() as conn:
            conn.execute("DELETE FROM watch_history")

    @staticmethod
    def was_watched(media_id: int) -> bool:
        with _connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM watch_history WHERE media_id = ? LIMIT 1",
                (media_id,),
            ).fetchone()
        return row is not None
