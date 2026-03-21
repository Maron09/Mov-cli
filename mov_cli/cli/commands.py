"""
cli/commands.py
---------------
All Typer commands and interactive UI logic.

This module owns the "view" layer: it handles user input,
renders Rich tables/panels, and orchestrates the services.
"""

from __future__ import annotations

import asyncio
import sys
from typing import Optional

import typer
from prompt_toolkit import prompt
from prompt_toolkit.completion import WordCompleter
from rich import print as rprint
from rich.columns import Columns
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich import box

from mov_cli.models.media import MediaResult, MediaType, StreamSource
from mov_cli.services.player_service import player_service
from mov_cli.services.tmdb_service import tmdb
from mov_cli.services.torrent_service import aggregator
from mov_cli.utils.cache import WatchHistory, init_db
from mov_cli.utils.config import config

console = Console()

# ─── Theme constants ───────────────────────────────────────────────────────────

BRAND   = "[bold magenta]mov-cli[/bold magenta]"
ACCENT  = "magenta"
DIM     = "dim"
SUCCESS = "bold green"
WARN    = "bold yellow"
ERROR   = "bold red"

# ─── Helpers ───────────────────────────────────────────────────────────────────

def _header() -> None:
    console.print(
        Panel.fit(
            f"[bold magenta]🎬  mov-cli[/bold magenta]  [dim]— your terminal cinema[/dim]",
            border_style="magenta",
        )
    )


def _bail(msg: str) -> None:
    console.print(f"[{ERROR}]✗  {msg}[/{ERROR}]")
    raise typer.Exit(1)


def _run(coro) -> object:
    """Run a coroutine synchronously (Python 3.10+)."""
    return asyncio.run(coro)


# ─── Result display ────────────────────────────────────────────────────────────

def _render_results_table(results: list[MediaResult]) -> None:
    table = Table(
        show_header=True,
        header_style=f"bold {ACCENT}",
        border_style=ACCENT,
        box=box.ROUNDED,
        expand=False,
        show_lines=True,
    )
    table.add_column("#", style="dim", width=3, justify="right")
    table.add_column("Title", style="bold white", min_width=24)
    table.add_column("Type", width=6)
    table.add_column("Year", width=6)
    table.add_column("Rating", width=8)
    table.add_column("Overview", style="dim", max_width=52)

    watched_ids = _get_watched_ids([r.id for r in results])

    for idx, r in enumerate(results, 1):
        type_badge = (
            "[cyan]Movie[/cyan]" if r.media_type == MediaType.MOVIE
            else "[yellow] TV [/yellow]"
        )
        rating_color = (
            "green" if r.rating >= 7
            else "yellow" if r.rating >= 5
            else "red"
        )
        overview = r.overview[:100] + "…" if len(r.overview) > 100 else r.overview
        watched_mark = " [dim]✓[/dim]" if r.id in watched_ids else ""
        table.add_row(
            str(idx),
            r.title + watched_mark,
            type_badge,
            r.display_year,
            f"[{rating_color}]{r.display_rating}[/{rating_color}]",
            overview,
        )

    console.print(table)


def _get_watched_ids(ids: list[int]) -> set[int]:
    try:
        history = WatchHistory.get_recent(200)
        history_ids = {h.media_id for h in history}
        return {i for i in ids if i in history_ids}
    except Exception:
        return set()


def _render_sources_table(sources: list[StreamSource]) -> None:
    table = Table(
        show_header=True,
        header_style=f"bold {ACCENT}",
        border_style=ACCENT,
        box=box.ROUNDED,
        expand=False,
        show_lines=True,
    )
    table.add_column("#", style="dim", width=3, justify="right")
    table.add_column("Title", style="white", min_width=30, max_width=60)
    table.add_column("Quality", width=8)
    table.add_column("Seeders", width=8, justify="right")
    table.add_column("Size", width=10)
    table.add_column("Provider", style="dim", width=10)

    for idx, src in enumerate(sources, 1):
        q_color = {
            "4K": "bright_cyan",
            "1080p": "green",
            "720p": "yellow",
            "480p": "red",
        }.get(src.quality.value, "white")

        table.add_row(
            str(idx),
            src.title,
            f"[{q_color}]{src.quality.value}[/{q_color}]",
            src.seeders_display,
            src.size,
            src.provider,
        )

    console.print(table)


# ─── Prompt helpers ────────────────────────────────────────────────────────────

def _pick_from_list(prompt_text: str, count: int) -> Optional[int]:
    """Prompt the user to pick a number from 1..count. Returns 0-based index or None."""
    valid = [str(i) for i in range(1, count + 1)] + ["q", "0"]
    completer = WordCompleter(valid, ignore_case=True)
    while True:
        try:
            ans = prompt(f"\n{prompt_text} [1-{count}] (q to quit): ", completer=completer).strip()
        except (KeyboardInterrupt, EOFError):
            return None
        if ans.lower() in ("q", "0", ""):
            return None
        if ans.isdigit() and 1 <= int(ans) <= count:
            return int(ans) - 1
        console.print(f"[{WARN}]Please enter a number between 1 and {count}.[/{WARN}]")


# ─── Season / episode selection ────────────────────────────────────────────────

def _select_season_episode(media: MediaResult) -> tuple[Optional[int], Optional[int]]:
    """
    For TV shows: interactively pick season and episode.
    Returns (season_number, episode_number) or (None, None) on cancel.
    """
    console.print(f"\n[{ACCENT}]Fetching season info…[/{ACCENT}]")
    try:
        seasons = _run(tmdb.get_seasons(media.id))
    except Exception as exc:
        console.print(f"[{WARN}]Could not fetch season info: {exc}[/{WARN}]")
        return None, None

    if not seasons:
        return None, None

    # ── Season table ──────────────────────────────────────────────────────────
    s_table = Table(box=box.SIMPLE, header_style=f"bold {ACCENT}")
    s_table.add_column("#", style="dim", width=3)
    s_table.add_column("Season", style="bold white")
    s_table.add_column("Episodes", width=10)
    s_table.add_column("Air Date", width=12)
    for s in seasons:
        s_table.add_row(
            str(s["season_number"]),
            s["name"],
            str(s["episode_count"]),
            s.get("air_date", "N/A"),
        )
    console.print(s_table)

    season_idx = _pick_from_list("Select season", len(seasons))
    if season_idx is None:
        return None, None
    season_num = seasons[season_idx]["season_number"]

    # ── Episode table ─────────────────────────────────────────────────────────
    console.print(f"\n[{ACCENT}]Fetching episode list for Season {season_num}…[/{ACCENT}]")
    try:
        episodes = _run(tmdb.get_episodes(media.id, season_num))
    except Exception as exc:
        console.print(f"[{WARN}]Could not fetch episodes: {exc}[/{WARN}]")
        return season_num, None

    if not episodes:
        return season_num, None

    e_table = Table(box=box.SIMPLE, header_style=f"bold {ACCENT}")
    e_table.add_column("#", style="dim", width=3)
    e_table.add_column("Episode Title", style="bold white", min_width=30)
    e_table.add_column("Air Date", width=12)
    for ep in episodes:
        e_table.add_row(
            str(ep["episode_number"]),
            ep["name"],
            ep.get("air_date", "N/A"),
        )
    console.print(e_table)

    ep_idx = _pick_from_list("Select episode", len(episodes))
    if ep_idx is None:
        return season_num, None
    episode_num = episodes[ep_idx]["episode_number"]

    return season_num, episode_num


# ─── Core search + stream flow ─────────────────────────────────────────────────

def run_search_and_play(
    query: str,
    media_type: str = "all",
    season: Optional[int] = None,
    episode: Optional[int] = None,
) -> None:
    """
    End-to-end flow:
      1. Search TMDB
      2. User picks a result
      3. (TV) User picks season/episode
      4. Fetch sources
      5. User picks a source
      6. Launch player
    """
    _header()

    # ── Guard: TMDB key ───────────────────────────────────────────────────────
    if not tmdb.has_api_key():
        _bail(
            "TMDB API key not configured.\n"
            "  Set it via env:    export TMDB_API_KEY=your_key_here\n"
            "  Or in config:      ~/.mov-cli/config.json  →  \"tmdb_api_key\": \"your_key\"\n"
            "  Get a free key at: https://www.themoviedb.org/settings/api"
        )

    # ── Step 1: Search ────────────────────────────────────────────────────────
    console.print(f"\n[{ACCENT}]Searching for[/{ACCENT}] [bold]{query!r}[/bold]…")
    try:
        results: list[MediaResult] = _run(tmdb.search(query, media_type=media_type))
    except Exception as exc:
        _bail(f"TMDB search failed: {exc}")

    if not results:
        console.print(f"[{WARN}]No results found for {query!r}.[/{WARN}]")
        raise typer.Exit(0)

    _render_results_table(results)

    # ── Step 2: Pick result ───────────────────────────────────────────────────
    pick = _pick_from_list("Select title", len(results))
    if pick is None:
        raise typer.Exit(0)
    media = results[pick]

    console.print(
        Panel(
            f"[bold]{media.title}[/bold]  ({media.display_year})\n"
            f"[dim]{media.overview[:200]}[/dim]",
            border_style=ACCENT,
            title="[bold magenta]Selected[/bold magenta]",
        )
    )

    # ── Step 3 (TV): Season / episode ────────────────────────────────────────
    if media.media_type == MediaType.TV and season is None and episode is None:
        season, episode = _select_season_episode(media)

    # ── Step 4: Fetch sources ─────────────────────────────────────────────────
    ep_info = ""
    if season:
        ep_info = f" S{season:02d}"
    if episode:
        ep_info += f"E{episode:02d}"

    console.print(f"\n[{ACCENT}]Fetching sources for[/{ACCENT}] [bold]{media.title}{ep_info}[/bold]…")
    try:
        sources: list[StreamSource] = _run(
            aggregator.get_sources(media, season=season, episode=episode)
        )
    except Exception as exc:
        _bail(f"Source fetch failed: {exc}")

    if not sources:
        console.print(
            f"[{WARN}]No streaming sources found.\n"
            f"This can happen when:\n"
            f"  • The content is too new or too old\n"
            f"  • Provider APIs are temporarily unreachable\n"
            f"  • The title is region-locked[/{WARN}]"
        )
        raise typer.Exit(0)

    _render_sources_table(sources)

    # Warn if everything has 0 seeders
    alive_count = sum(1 for s in sources if s.seeders > 0)
    if alive_count == 0:
        console.print(
            f"[{WARN}]⚠  All sources have 0 seeders — streams may hang. "
            f"Try a different title or come back later.[/{WARN}]"
        )
    elif alive_count < len(sources):
        console.print(
            f"[dim]{alive_count}/{len(sources)} sources have active seeders. "
            f"Pick a green seeder count for best results.[/dim]"
        )

    # ── Step 5: Pick source ───────────────────────────────────────────────────
    src_pick = _pick_from_list("Select source", len(sources))
    if src_pick is None:
        raise typer.Exit(0)
    source = sources[src_pick]

    target = source.stream_target
    if not target:
        _bail("Selected source has no valid stream URI.")

    # ── Step 6: Launch player ─────────────────────────────────────────────────
    console.print(
        f"\n[{SUCCESS}]▶ Launching {config.preferred_player} for "
        f"[bold]{media.title}[/bold] [{source.quality.value}]…[/{SUCCESS}]"
    )

    try:
        ret = player_service.play(target, title=f"{media.title}{ep_info}")
    except RuntimeError as exc:
        _bail(str(exc))
    except Exception as exc:
        _bail(f"Unexpected player error: {exc}")

    if ret == 0:
        # Persist to watch history
        try:
            WatchHistory.add(media, quality=source.quality.value, provider=source.provider)
        except Exception:
            pass  # history failure must never interrupt the user
        console.print(f"[{SUCCESS}]✓  Finished watching {media.title}[/{SUCCESS}]")
    else:
        console.print(f"[{WARN}]Player exited with code {ret}[/{WARN}]")
