"""
tests/test_models.py
--------------------
Unit tests for data models. These tests have zero external dependencies
and run without a TMDB key or internet connection.
"""

from __future__ import annotations

import json
import pytest

from mov_cli.models.media import (
    MediaResult,
    MediaType,
    Quality,
    StreamSource,
    WatchHistoryEntry,
)


# ─── Quality parsing ───────────────────────────────────────────────────────────

class TestQuality:
    def test_parse_4k(self):
        assert Quality.from_string("Movie.2160p.BluRay") == Quality.Q_4K

    def test_parse_1080(self):
        assert Quality.from_string("Movie.1080p.WEB-DL") == Quality.Q_1080P

    def test_parse_720(self):
        assert Quality.from_string("movie.720p.x264") == Quality.Q_720P

    def test_parse_480(self):
        assert Quality.from_string("movie.480p") == Quality.Q_480P

    def test_parse_unknown(self):
        assert Quality.from_string("some-release") == Quality.UNKNOWN

    def test_parse_4k_keyword(self):
        assert Quality.from_string("Movie 4K HDR10") == Quality.Q_4K


# ─── MediaResult ───────────────────────────────────────────────────────────────

class TestMediaResult:
    def _make(self, **kwargs) -> MediaResult:
        defaults = dict(
            id=123,
            title="Inception",
            media_type=MediaType.MOVIE,
            year="2010-07-16",
            rating=8.8,
            overview="A thief who steals corporate secrets through dream-sharing.",
        )
        defaults.update(kwargs)
        return MediaResult(**defaults)

    def test_display_year(self):
        r = self._make(year="2010-07-16")
        assert r.display_year == "2010"

    def test_display_year_empty(self):
        r = self._make(year="")
        assert r.display_year == "N/A"

    def test_display_rating(self):
        r = self._make(rating=8.8)
        assert r.display_rating == "8.8/10"

    def test_roundtrip_dict(self):
        r = self._make()
        assert MediaResult.from_dict(r.to_dict()).title == r.title
        assert MediaResult.from_dict(r.to_dict()).media_type == r.media_type

    def test_roundtrip_json(self):
        r = self._make()
        r2 = MediaResult.from_json(r.to_json())
        assert r2.id == r.id
        assert r2.rating == r.rating

    def test_tv_type(self):
        r = self._make(media_type=MediaType.TV)
        d = r.to_dict()
        assert d["media_type"] == "tv"
        r2 = MediaResult.from_dict(d)
        assert r2.media_type == MediaType.TV


# ─── StreamSource ──────────────────────────────────────────────────────────────

class TestStreamSource:
    def test_is_torrent_magnet(self):
        src = StreamSource(title="test", magnet="magnet:?xt=urn:btih:abc", quality=Quality.Q_1080P)
        assert src.is_torrent is True

    def test_is_not_torrent_url(self):
        src = StreamSource(title="test", url="https://example.com/video.mp4", quality=Quality.Q_720P)
        assert src.is_torrent is False

    def test_stream_target_prefers_magnet(self):
        src = StreamSource(title="t", magnet="magnet:abc", url="https://example.com")
        assert src.stream_target == "magnet:abc"

    def test_stream_target_falls_back_to_url(self):
        src = StreamSource(title="t", url="https://example.com")
        assert src.stream_target == "https://example.com"

    def test_seeders_display_green(self):
        src = StreamSource(title="t", seeders=100)
        assert "green" in src.seeders_display

    def test_seeders_display_red(self):
        src = StreamSource(title="t", seeders=5)
        assert "red" in src.seeders_display

    def test_seeders_display_zero(self):
        src = StreamSource(title="t", seeders=0)
        assert "N/A" in src.seeders_display
