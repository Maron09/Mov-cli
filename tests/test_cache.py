"""
tests/test_cache.py
-------------------
Tests for SearchCache and WatchHistory.
Uses a temporary SQLite DB to avoid polluting the user's real history.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

# ── Redirect DB to a temp file before importing cache ──────────────────────────
@pytest.fixture(autouse=True)
def tmp_db(tmp_path, monkeypatch):
    db = tmp_path / "test_history.db"
    monkeypatch.setattr("mov_cli.utils.cache.DB_PATH", db)
    # Re-initialise the schema against the temp DB
    from mov_cli.utils.cache import init_db
    init_db()
    yield db


from mov_cli.models.media import MediaResult, MediaType
from mov_cli.utils.cache import SearchCache, WatchHistory


def _make_result(id: int = 1, title: str = "Inception") -> MediaResult:
    return MediaResult(
        id=id,
        title=title,
        media_type=MediaType.MOVIE,
        year="2010",
        rating=8.8,
        overview="Dream heist.",
    )


# ─── SearchCache ───────────────────────────────────────────────────────────────

class TestSearchCache:
    def test_miss_on_empty(self):
        assert SearchCache.get("Inception", "all") is None

    def test_set_and_get(self):
        results = [_make_result()]
        SearchCache.set("Inception", "all", results)
        cached = SearchCache.get("Inception", "all")
        assert cached is not None
        assert cached[0].title == "Inception"

    def test_case_insensitive_key(self):
        results = [_make_result()]
        SearchCache.set("inception", "all", results)
        cached = SearchCache.get("INCEPTION", "all")
        assert cached is not None

    def test_clear_all(self):
        SearchCache.set("Inception", "all", [_make_result()])
        SearchCache.clear_all()
        assert SearchCache.get("Inception", "all") is None

    def test_delete(self):
        SearchCache.set("Inception", "all", [_make_result()])
        SearchCache.delete("Inception", "all")
        assert SearchCache.get("Inception", "all") is None


# ─── WatchHistory ──────────────────────────────────────────────────────────────

class TestWatchHistory:
    def test_add_and_retrieve(self):
        r = _make_result()
        WatchHistory.add(r, quality="1080p", provider="YTS")
        entries = WatchHistory.get_recent(10)
        assert len(entries) == 1
        assert entries[0].title == "Inception"
        assert entries[0].quality == "1080p"

    def test_most_recent_first(self):
        WatchHistory.add(_make_result(id=1, title="First"))
        WatchHistory.add(_make_result(id=2, title="Second"))
        entries = WatchHistory.get_recent(10)
        assert entries[0].title == "Second"

    def test_was_watched(self):
        r = _make_result(id=42)
        assert not WatchHistory.was_watched(42)
        WatchHistory.add(r)
        assert WatchHistory.was_watched(42)

    def test_clear_all(self):
        WatchHistory.add(_make_result())
        WatchHistory.clear_all()
        assert WatchHistory.get_recent(10) == []

    def test_limit(self):
        for i in range(5):
            WatchHistory.add(_make_result(id=i, title=f"Movie {i}"))
        entries = WatchHistory.get_recent(3)
        assert len(entries) == 3
