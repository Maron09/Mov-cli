"""
services/torrent_service.py
---------------------------
Pluggable torrent source system.

Providers:
  - PirateBayProvider : TPB via apibay.org (official JSON API, no scraping)
  - TorrentGalaxyProvider: TGx search API
  - EZTVProvider      : TV shows via eztv.re
  - SourceAggregator  : fans out concurrently, merges + ranks results
"""

from __future__ import annotations

import asyncio
import re
from abc import ABC, abstractmethod
from typing import Optional
from urllib.parse import quote_plus, quote

import httpx

from mov_cli.models.media import MediaResult, MediaType, Quality, StreamSource
from mov_cli.utils.config import config


# ─── Abstract base ─────────────────────────────────────────────────────────────

class SourceProvider(ABC):
    name: str = "abstract"

    @abstractmethod
    async def fetch_sources(
        self,
        media: MediaResult,
        season: Optional[int] = None,
        episode: Optional[int] = None,
    ) -> list[StreamSource]:
        ...


# ─── Pirate Bay via apibay.org ─────────────────────────────────────────────────

class PirateBayProvider(SourceProvider):
    """
    Uses apibay.org — the official TPB JSON API.
    Returns torrent results with hash, seeders, size.
    Category 200 = Video, 201 = Movies, 205 = TV
    """

    name = "TPB"
    API_URL = "https://apibay.org/q.php"

    # Tracker list for building magnet links
    TRACKERS = [
        "udp://tracker.opentrackr.org:1337/announce",
        "udp://open.tracker.cl:1337/announce",
        "udp://open.demonii.com:1337/announce",
        "udp://tracker.openbittorrent.com:80/announce",
        "udp://tracker.torrent.eu.org:451/announce",
        "udp://tracker.coppersurfer.tk:6969/announce",
        "udp://p4p.arenabg.com:1337/announce",
        "udp://tracker.leechers-paradise.org:6969/announce",
    ]

    async def fetch_sources(
        self,
        media: MediaResult,
        season: Optional[int] = None,
        episode: Optional[int] = None,
    ) -> list[StreamSource]:

        query = self._build_query(media, season, episode)
        cat   = "205" if media.media_type == MediaType.TV else "200"

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    self.API_URL,
                    params={"q": query, "cat": cat},
                    timeout=config.request_timeout,
                    headers={"User-Agent": "mov-cli/1.0"},
                )
                resp.raise_for_status()
                results = resp.json()
        except Exception:
            return []

        # apibay returns [{"id":"0","name":"No results returned","…"}] on miss
        if not results or results[0].get("id") == "0":
            return []

        sources: list[StreamSource] = []
        for item in results[:20]:
            info_hash = item.get("info_hash", "").strip()
            name      = item.get("name", "Unknown")
            seeders   = int(item.get("seeders", 0))
            size      = self._format_size(int(item.get("size", 0)))

            if not info_hash or info_hash == "0" * 40:
                continue

            magnet = self._build_magnet(info_hash, name)
            sources.append(
                StreamSource(
                    title=name,
                    magnet=magnet,
                    quality=Quality.from_string(name),
                    seeders=seeders,
                    size=size,
                    provider=self.name,
                )
            )

        return sorted(sources, key=lambda s: s.seeders, reverse=True)

    @staticmethod
    def _build_query(
        media: MediaResult,
        season: Optional[int],
        episode: Optional[int],
    ) -> str:
        q = media.title
        if season is not None:
            q += f" S{season:02d}"
        if episode is not None:
            q += f"E{episode:02d}"
        return q

    def _build_magnet(self, info_hash: str, name: str) -> str:
        tracker_str = "&".join(f"tr={quote_plus(t)}" for t in self.TRACKERS)
        return (
            f"magnet:?xt=urn:btih:{info_hash}"
            f"&dn={quote_plus(name)}"
            f"&{tracker_str}"
        )

    @staticmethod
    def _format_size(size_bytes: int) -> str:
        if not size_bytes:
            return "Unknown"
        for unit in ["B", "KB", "MB", "GB"]:
            if size_bytes < 1024:
                return f"{size_bytes:.1f} {unit}"
            size_bytes /= 1024
        return f"{size_bytes:.1f} TB"


# ─── TorrentGalaxy ─────────────────────────────────────────────────────────────

class TorrentGalaxyProvider(SourceProvider):
    """
    TorrentGalaxy public search — good coverage for movies & TV.
    Scrapes the JSON embedded in search results.
    """

    name = "TGx"
    SEARCH_URL = "https://torrentgalaxy.to/torrents.php"

    TRACKERS = [
        "udp://tracker.opentrackr.org:1337/announce",
        "udp://open.tracker.cl:1337/announce",
        "udp://tracker.openbittorrent.com:80/announce",
        "udp://tracker.torrent.eu.org:451/announce",
    ]

    async def fetch_sources(
        self,
        media: MediaResult,
        season: Optional[int] = None,
        episode: Optional[int] = None,
    ) -> list[StreamSource]:

        query = media.title
        if season is not None:
            query += f" S{season:02d}"
        if episode is not None:
            query += f"E{episode:02d}"

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    self.SEARCH_URL,
                    params={"search": query, "sort": "seeders", "order": "desc"},
                    timeout=config.request_timeout,
                    headers={
                        "User-Agent": (
                            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                            "AppleWebKit/537.36 (KHTML, like Gecko) "
                            "Chrome/120.0.0.0 Safari/537.36"
                        )
                    },
                    follow_redirects=True,
                )
                html = resp.text
        except Exception:
            return []

        # Parse magnet links and titles from HTML
        magnets = re.findall(r'href="(magnet:\?xt=urn:btih:[^"]+)"', html)
        names   = re.findall(
            r'class="txlight"[^>]*>([^<]{10,80})</a>', html
        )
        seeders_raw = re.findall(
            r'<span[^>]*class="[^"]*tgxtablecell[^"]*"[^>]*>\s*<b>(\d+)</b>', html
        )

        sources: list[StreamSource] = []
        for i, magnet in enumerate(magnets[:15]):
            name    = names[i].strip()   if i < len(names)       else f"Result {i+1}"
            seeders = int(seeders_raw[i]) if i < len(seeders_raw) else 0

            sources.append(
                StreamSource(
                    title=name,
                    magnet=magnet,
                    quality=Quality.from_string(name),
                    seeders=seeders,
                    size="Unknown",
                    provider=self.name,
                )
            )

        return sorted(sources, key=lambda s: s.seeders, reverse=True)


# ─── EZTV (TV only) ────────────────────────────────────────────────────────────

class EZTVProvider(SourceProvider):
    """EZTV public JSON API — TV episodes only."""

    name = "EZTV"
    API_URL = "https://eztv.re/api/get-torrents"

    async def fetch_sources(
        self,
        media: MediaResult,
        season: Optional[int] = None,
        episode: Optional[int] = None,
    ) -> list[StreamSource]:
        if media.media_type != MediaType.TV:
            return []

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    self.API_URL,
                    params={"limit": 100, "page": 1},
                    timeout=config.request_timeout,
                )
                resp.raise_for_status()
                data = resp.json()
        except Exception:
            return []

        sources: list[StreamSource] = []
        for torrent in data.get("torrents", []) or []:
            filename: str = torrent.get("filename", "") or torrent.get("title", "")
            if not self._title_matches(filename, media.title):
                continue
            if season is not None and not self._season_matches(filename, season):
                continue
            if episode is not None and not self._episode_matches(filename, episode):
                continue

            magnet = torrent.get("magnet_url") or ""
            if not magnet:
                continue

            sources.append(
                StreamSource(
                    title=filename,
                    magnet=magnet,
                    quality=Quality.from_string(filename),
                    seeders=torrent.get("seeds", 0),
                    size=self._format_size(torrent.get("size_bytes", 0)),
                    provider=self.name,
                )
            )

        return sorted(sources, key=lambda s: s.seeders, reverse=True)[:15]

    @staticmethod
    def _title_matches(filename: str, title: str) -> bool:
        words = re.sub(r"[^a-z0-9 ]", "", title.lower()).split()
        if not words:
            return False
        pattern = r"[\W_]+".join(re.escape(w) for w in words[:4])
        return bool(re.search(pattern, filename, re.IGNORECASE))

    @staticmethod
    def _season_matches(filename: str, season: int) -> bool:
        return bool(re.search(rf"[Ss]0*{season}[Ee]", filename))

    @staticmethod
    def _episode_matches(filename: str, episode: int) -> bool:
        return bool(re.search(rf"[Ee]0*{episode}(\b|[^0-9])", filename))

    @staticmethod
    def _format_size(size_bytes: int) -> str:
        if not size_bytes:
            return "Unknown"
        for unit in ["B", "KB", "MB", "GB"]:
            if size_bytes < 1024:
                return f"{size_bytes:.1f} {unit}"
            size_bytes /= 1024
        return f"{size_bytes:.1f} TB"


# ─── Aggregator ────────────────────────────────────────────────────────────────

class SourceAggregator:
    """Fans out to all providers concurrently, merges and ranks results."""

    def __init__(self) -> None:
        self._providers: list[SourceProvider] = [
            PirateBayProvider(),
            TorrentGalaxyProvider(),
            EZTVProvider(),
        ]

    def register(self, provider: SourceProvider) -> None:
        self._providers.append(provider)

    async def get_sources(
        self,
        media: MediaResult,
        season: Optional[int] = None,
        episode: Optional[int] = None,
    ) -> list[StreamSource]:
        tasks = [
            p.fetch_sources(media, season=season, episode=episode)
            for p in self._providers
        ]
        results_per_provider = await asyncio.gather(*tasks, return_exceptions=True)

        sources: list[StreamSource] = []
        for result in results_per_provider:
            if isinstance(result, list):
                sources.extend(result)

        quality_rank = {
            Quality.Q_4K:    0,
            Quality.Q_1080P: 1,
            Quality.Q_720P:  2,
            Quality.Q_480P:  3,
            Quality.UNKNOWN: 4,
        }
        sources.sort(key=lambda s: (quality_rank[s.quality], -s.seeders))

        # Separate into alive (seeders > 0) and dead (seeders == 0)
        # Show alive sources first; include dead ones at the bottom so the
        # user can still try them but knows they may hang.
        alive = [s for s in sources if s.seeders > 0]
        dead  = [s for s in sources if s.seeders == 0]

        # Re-label dead sources so user knows
        for s in dead:
            s.title = f"[NO SEEDERS] {s.title}"

        return alive + dead


# ─── Module-level singleton ────────────────────────────────────────────────────

aggregator = SourceAggregator()