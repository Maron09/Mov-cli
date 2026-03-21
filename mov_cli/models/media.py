"""
models/media.py
---------------
Core data models for mov-cli. Using dataclasses for lightweight,
typed, serialisation-friendly structures with no ORM overhead.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Optional
import json


class MediaType(str, Enum):
    MOVIE = "movie"
    TV = "tv"


class Quality(str, Enum):
    Q_4K = "4K"
    Q_1080P = "1080p"
    Q_720P = "720p"
    Q_480P = "480p"
    UNKNOWN = "Unknown"

    @classmethod
    def from_string(cls, s: str) -> "Quality":
        """Parse a quality string from a torrent title."""
        s_upper = s.upper()
        if "2160" in s_upper or "4K" in s_upper:
            return cls.Q_4K
        if "1080" in s_upper:
            return cls.Q_1080P
        if "720" in s_upper:
            return cls.Q_720P
        if "480" in s_upper:
            return cls.Q_480P
        return cls.UNKNOWN


@dataclass
class MediaResult:
    """A single search result from TMDB."""

    id: int
    title: str
    media_type: MediaType
    year: str
    rating: float
    overview: str
    poster_path: Optional[str] = None
    genre_ids: list[int] = field(default_factory=list)
    vote_count: int = 0

    @property
    def display_year(self) -> str:
        return self.year[:4] if self.year else "N/A"

    @property
    def display_rating(self) -> str:
        return f"{self.rating:.1f}/10" if self.rating else "N/A"

    def to_dict(self) -> dict:
        d = asdict(self)
        d["media_type"] = self.media_type.value
        return d

    @classmethod
    def from_dict(cls, data: dict) -> "MediaResult":
        data["media_type"] = MediaType(data["media_type"])
        return cls(**data)

    @classmethod
    def from_json(cls, json_str: str) -> "MediaResult":
        return cls.from_dict(json.loads(json_str))

    def to_json(self) -> str:
        return json.dumps(self.to_dict())


@dataclass
class StreamSource:
    """A single streamable source (torrent or direct URL)."""

    title: str
    magnet: Optional[str] = None
    url: Optional[str] = None
    quality: Quality = Quality.UNKNOWN
    seeders: int = 0
    size: str = "Unknown"
    provider: str = "unknown"

    @property
    def is_torrent(self) -> bool:
        return self.magnet is not None

    @property
    def stream_target(self) -> Optional[str]:
        """Returns the best URI to pass to a player."""
        return self.magnet or self.url

    @property
    def seeders_display(self) -> str:
        if self.seeders == 0:
            return "[dim]N/A[/dim]"
        color = "green" if self.seeders > 50 else "yellow" if self.seeders > 10 else "red"
        return f"[{color}]{self.seeders}[/{color}]"


@dataclass
class WatchHistoryEntry:
    """Persisted record of a previously watched item."""

    media_id: int
    title: str
    media_type: str
    year: str
    watched_at: str  # ISO-8601
    quality: str = "Unknown"
    source_provider: str = "unknown"
