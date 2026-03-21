"""
services/tmdb_service.py
------------------------
Thin async wrapper around the TMDB v3 REST API.

Docs: https://developers.themoviedb.org/3/getting-started

Key endpoints used:
  /search/multi        → search movies + TV simultaneously
  /search/movie        → movie-only search
  /search/tv           → TV-only search
  /trending/all/day    → trending content

A TMDB API key is required.  Obtain one for free at:
  https://www.themoviedb.org/settings/api
"""

from __future__ import annotations

import asyncio
from typing import Optional

import httpx

from mov_cli.models.media import MediaResult, MediaType
from mov_cli.utils.cache import SearchCache
from mov_cli.utils.config import config

TMDB_BASE = "https://api.themoviedb.org/3"
TMDB_IMG  = "https://image.tmdb.org/t/p/w200"


# ─── Helpers ───────────────────────────────────────────────────────────────────

def _parse_movie(item: dict) -> MediaResult:
    return MediaResult(
        id=item["id"],
        title=item.get("title") or item.get("name", "Unknown"),
        media_type=MediaType.MOVIE,
        year=item.get("release_date", ""),
        rating=item.get("vote_average", 0.0),
        overview=item.get("overview", ""),
        poster_path=item.get("poster_path"),
        genre_ids=item.get("genre_ids", []),
        vote_count=item.get("vote_count", 0),
    )


def _parse_tv(item: dict) -> MediaResult:
    return MediaResult(
        id=item["id"],
        title=item.get("name") or item.get("title", "Unknown"),
        media_type=MediaType.TV,
        year=item.get("first_air_date", ""),
        rating=item.get("vote_average", 0.0),
        overview=item.get("overview", ""),
        poster_path=item.get("poster_path"),
        genre_ids=item.get("genre_ids", []),
        vote_count=item.get("vote_count", 0),
    )


def _parse_multi(item: dict) -> Optional[MediaResult]:
    """Parse a /search/multi result (media_type field tells us what it is)."""
    mtype = item.get("media_type")
    if mtype == "movie":
        return _parse_movie(item)
    if mtype == "tv":
        return _parse_tv(item)
    return None  # skip 'person' results


# ─── Service ───────────────────────────────────────────────────────────────────

class TMDBService:
    """
    Async TMDB client.

    All public methods are coroutines; use asyncio.run() or await them
    from an async context.
    """

    def __init__(self, api_key: Optional[str] = None) -> None:
        self._api_key = api_key or config.tmdb_api_key
        self._timeout = config.request_timeout

    def _params(self, extra: Optional[dict] = None) -> dict:
        p = {"api_key": self._api_key, "language": "en-US"}
        if extra:
            p.update(extra)
        return p

    def has_api_key(self) -> bool:
        return bool(self._api_key)

    async def _get(self, client: httpx.AsyncClient, endpoint: str, params: dict) -> dict:
        url = f"{TMDB_BASE}{endpoint}"
        resp = await client.get(url, params=params, timeout=self._timeout)
        resp.raise_for_status()
        return resp.json()

    # ── Search ─────────────────────────────────────────────────────────────────

    async def search(
        self,
        query: str,
        media_type: str = "all",  # "all" | "movie" | "tv"
        page: int = 1,
    ) -> list[MediaResult]:
        """
        Search TMDB for movies and/or TV shows.
        Results are cached for config.cache_ttl_hours.
        """
        cache_key_type = media_type

        # Check cache first
        cached = SearchCache.get(query, cache_key_type)
        if cached is not None:
            return cached

        async with httpx.AsyncClient() as client:
            if media_type == "movie":
                endpoint = "/search/movie"
                raw = await self._get(client, endpoint, self._params({"query": query, "page": page}))
                results = [_parse_movie(i) for i in raw.get("results", [])]

            elif media_type == "tv":
                endpoint = "/search/tv"
                raw = await self._get(client, endpoint, self._params({"query": query, "page": page}))
                results = [_parse_tv(i) for i in raw.get("results", [])]

            else:
                # Default: multi-search (movies + TV combined)
                endpoint = "/search/multi"
                raw = await self._get(client, endpoint, self._params({"query": query, "page": page}))
                results = [
                    r for item in raw.get("results", [])
                    if (r := _parse_multi(item)) is not None
                ]

        # Sort by TMDB popularity score (already on the raw item) — keeps
        # well-known films at the top regardless of niche high-rated entries.
        # Fall back to rating if popularity wasn't stored.
        results.sort(key=lambda r: (r.vote_count * r.rating), reverse=True)
        results = results[:config.max_search_results]

        SearchCache.set(query, cache_key_type, results)
        return results

    # ── Trending ───────────────────────────────────────────────────────────────

    async def trending(
        self,
        media_type: str = "all",   # "all" | "movie" | "tv"
        time_window: str = "day",  # "day" | "week"
    ) -> list[MediaResult]:
        """Return TMDB trending content."""
        async with httpx.AsyncClient() as client:
            endpoint = f"/trending/{media_type}/{time_window}"
            raw = await self._get(client, endpoint, self._params())

        results: list[MediaResult] = []
        for item in raw.get("results", []):
            mtype = item.get("media_type", media_type)
            if mtype == "movie":
                results.append(_parse_movie(item))
            elif mtype == "tv":
                results.append(_parse_tv(item))

        return results[:config.max_search_results]

    # ── TV season/episode info ─────────────────────────────────────────────────

    async def get_seasons(self, tv_id: int) -> list[dict]:
        """Return list of seasons for a TV show."""
        async with httpx.AsyncClient() as client:
            raw = await self._get(client, f"/tv/{tv_id}", self._params())
        seasons = [
            {
                "season_number": s["season_number"],
                "name": s["name"],
                "episode_count": s["episode_count"],
                "air_date": s.get("air_date", ""),
            }
            for s in raw.get("seasons", [])
            if s["season_number"] > 0  # skip 'Specials'
        ]
        return seasons

    async def get_episodes(self, tv_id: int, season_number: int) -> list[dict]:
        """Return list of episodes for a specific season."""
        async with httpx.AsyncClient() as client:
            raw = await self._get(
                client,
                f"/tv/{tv_id}/season/{season_number}",
                self._params(),
            )
        return [
            {
                "episode_number": ep["episode_number"],
                "name": ep["name"],
                "air_date": ep.get("air_date", ""),
                "overview": ep.get("overview", ""),
                "runtime": ep.get("runtime"),
            }
            for ep in raw.get("episodes", [])
        ]


# ─── Module-level singleton ────────────────────────────────────────────────────

tmdb = TMDBService()