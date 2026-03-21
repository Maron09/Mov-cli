"""
main.py
-------
Entry point for mov-cli.  Defines the Typer application and
registers all sub-commands.

Usage:
  mov-cli search "Inception"
  mov-cli search "Breaking Bad" --type tv
  mov-cli trending
  mov-cli history
  mov-cli config show
  mov-cli doctor
"""

from __future__ import annotations

from typing import Optional
import asyncio
import json

import typer
from rich import print as rprint
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich import box

from mov_cli.cli.commands import run_search_and_play, _header, _bail, _run, ACCENT
from mov_cli.services.tmdb_service import tmdb
from mov_cli.services.player_service import player_service, get_player, get_torrent_streamer
from mov_cli.utils.cache import WatchHistory, SearchCache, init_db
from mov_cli.utils.config import config

# ─── App setup ─────────────────────────────────────────────────────────────────

app = typer.Typer(
    name="mov-cli",
    help="🎬  mov-cli — your fast, modular terminal cinema",
    no_args_is_help=True,
    rich_markup_mode="rich",
    add_completion=True,
)

console = Console()

# Initialise DB on every run (idempotent)
init_db()


# ─── search ────────────────────────────────────────────────────────────────────

@app.command()
def search(
    query: str = typer.Argument(..., help="Movie or TV show title to search for"),
    type: str = typer.Option(
        "all",
        "--type", "-t",
        help="Filter by type: [bold]all[/bold] | [bold]movie[/bold] | [bold]tv[/bold]",
        show_default=True,
    ),
    season: Optional[int] = typer.Option(
        None,
        "--season", "-s",
        help="(TV only) Jump directly to this season number",
    ),
    episode: Optional[int] = typer.Option(
        None,
        "--episode", "-e",
        help="(TV only) Jump directly to this episode number",
    ),
) -> None:
    """
    [bold magenta]Search[/bold magenta] for a movie or TV show and stream it interactively.

    Examples:

      [dim]mov-cli search "Inception"[/dim]

      [dim]mov-cli search "The Office" --type tv[/dim]

      [dim]mov-cli search "Stranger Things" -t tv -s 3 -e 1[/dim]
    """
    if type not in ("all", "movie", "tv"):
        _bail("--type must be one of: all, movie, tv")
    run_search_and_play(query, media_type=type, season=season, episode=episode)


# ─── trending ──────────────────────────────────────────────────────────────────

@app.command()
def trending(
    type: str = typer.Option(
        "all",
        "--type", "-t",
        help="Filter: [bold]all[/bold] | [bold]movie[/bold] | [bold]tv[/bold]",
    ),
    window: str = typer.Option(
        "day",
        "--window", "-w",
        help="Time window: [bold]day[/bold] | [bold]week[/bold]",
    ),
    play: bool = typer.Option(
        False,
        "--play", "-p",
        help="Interactively pick and stream from trending list",
    ),
) -> None:
    """
    [bold magenta]Trending[/bold magenta] movies and TV shows right now.

    Examples:

      [dim]mov-cli trending[/dim]

      [dim]mov-cli trending --type movie --window week --play[/dim]
    """
    if not tmdb.has_api_key():
        _bail(
            "TMDB API key required.  Set TMDB_API_KEY env var or update ~/.mov-cli/config.json."
        )

    _header()
    console.print(f"\n[{ACCENT}]Fetching trending {type} ({window})…[/{ACCENT}]")

    try:
        results = _run(tmdb.trending(media_type=type, time_window=window))
    except Exception as exc:
        _bail(f"Failed to fetch trending: {exc}")

    if not results:
        console.print("[yellow]No trending content available right now.[/yellow]")
        raise typer.Exit(0)

    from mov_cli.cli.commands import _render_results_table, _pick_from_list
    _render_results_table(results)

    if play:
        pick = _pick_from_list("Select title to stream", len(results))
        if pick is not None:
            media = results[pick]
            from mov_cli.cli.commands import run_search_and_play
            run_search_and_play(media.title, media_type=media.media_type.value)


# ─── history ───────────────────────────────────────────────────────────────────

@app.command()
def history(
    limit: int = typer.Option(20, "--limit", "-n", help="Number of entries to show"),
    clear: bool = typer.Option(False, "--clear", help="Clear the entire watch history"),
) -> None:
    """
    [bold magenta]History[/bold magenta] — view or clear your watch history.

    Examples:

      [dim]mov-cli history[/dim]

      [dim]mov-cli history --limit 50[/dim]

      [dim]mov-cli history --clear[/dim]
    """
    if clear:
        typer.confirm("This will permanently delete your watch history. Continue?", abort=True)
        WatchHistory.clear_all()
        console.print("[bold green]✓  Watch history cleared.[/bold green]")
        return

    entries = WatchHistory.get_recent(limit)
    if not entries:
        console.print("[dim]No watch history yet.  Start with:[/dim]  mov-cli search \"<title>\"")
        return

    _header()
    table = Table(
        box=box.ROUNDED,
        header_style=f"bold {ACCENT}",
        border_style=ACCENT,
        show_lines=True,
    )
    table.add_column("#", style="dim", width=3, justify="right")
    table.add_column("Title", style="bold white", min_width=24)
    table.add_column("Type", width=6)
    table.add_column("Year", width=6)
    table.add_column("Quality", width=8)
    table.add_column("Provider", style="dim", width=10)
    table.add_column("Watched At", style="dim", width=22)

    for idx, e in enumerate(entries, 1):
        type_badge = (
            "[cyan]Movie[/cyan]" if e.media_type == "movie" else "[yellow] TV [/yellow]"
        )
        table.add_row(
            str(idx),
            e.title,
            type_badge,
            e.year or "N/A",
            e.quality,
            e.source_provider,
            e.watched_at[:19].replace("T", " "),
        )

    console.print(f"\n[bold]Watch History[/bold]  [dim](last {len(entries)} entries)[/dim]")
    console.print(table)


# ─── config sub-commands ───────────────────────────────────────────────────────

config_app = typer.Typer(help="[bold magenta]Config[/bold magenta] — view and update configuration")
app.add_typer(config_app, name="config")


@config_app.command("show")
def config_show() -> None:
    """Show the current configuration."""
    cfg = config.all()
    table = Table(
        box=box.SIMPLE,
        header_style=f"bold {ACCENT}",
        show_header=True,
    )
    table.add_column("Key", style="bold white", min_width=28)
    table.add_column("Value", style="cyan")
    for k, v in sorted(cfg.items()):
        # Mask API keys
        if "api_key" in k and v:
            v = v[:4] + "****"
        table.add_row(k, str(v))
    console.print(Panel(table, title="[bold magenta]~/.mov-cli/config.json[/bold magenta]", border_style=ACCENT))


@config_app.command("set")
def config_set(
    key: str = typer.Argument(..., help="Config key to set"),
    value: str = typer.Argument(..., help="Value to assign"),
) -> None:
    """Set a configuration value."""
    config.set(key, value)
    console.print(f"[bold green]✓[/bold green]  Set [bold]{key}[/bold] = [cyan]{value}[/cyan]")


# ─── cache ─────────────────────────────────────────────────────────────────────

@app.command()
def cache(
    clear: bool = typer.Option(False, "--clear", help="Clear the search cache"),
) -> None:
    """
    [bold magenta]Cache[/bold magenta] — manage search result cache.
    """
    if clear:
        SearchCache.clear_all()
        console.print("[bold green]✓  Search cache cleared.[/bold green]")
    else:
        console.print(
            f"Cache is [bold]{'enabled' if config.cache_enabled else 'disabled'}[/bold]  "
            f"(TTL: {config.cache_ttl_hours}h)\n"
            f"DB location: [dim]{config.CONFIG_DIR / 'history.db'}[/dim]\n"
            f"Use [bold]--clear[/bold] to wipe cached search results."
        )


# ─── doctor ────────────────────────────────────────────────────────────────────

@app.command()
def doctor() -> None:
    """
    [bold magenta]Doctor[/bold magenta] — check your mov-cli environment and dependencies.
    """
    _header()
    console.print("\n[bold]System Check[/bold]\n")

    checks = [
        ("TMDB API key",         "✓ configured" if tmdb.has_api_key() else "✗ missing — set TMDB_API_KEY", tmdb.has_api_key()),
        ("Media player",         get_player() or "✗ not found (install mpv or vlc)",          bool(get_player())),
        ("Torrent streamer",     get_torrent_streamer() or "✗ not found (install webtorrent or peerflix)", bool(get_torrent_streamer())),
        ("Cache enabled",        str(config.cache_enabled), True),
        ("Config dir",           str(config.CONFIG_DIR),    True),
        ("DB path",              str(config.CONFIG_DIR / "history.db"), True),
    ]

    for label, status, ok in checks:
        icon = "[bold green]✓[/bold green]" if ok else "[bold red]✗[/bold red]"
        console.print(f"  {icon}  {label:<28} [dim]{status}[/dim]")

    console.print()
    if not tmdb.has_api_key():
        console.print(
            "[yellow]Get a free TMDB API key at:[/yellow]\n"
            "  [cyan]https://www.themoviedb.org/settings/api[/cyan]\n"
            "Then run:  [bold]export TMDB_API_KEY=your_key[/bold]\n"
            "Or:        [bold]mov-cli config set tmdb_api_key your_key[/bold]"
        )
    if not get_player():
        console.print(
            "[yellow]Install mpv:[/yellow] https://mpv.io/installation/\n"
            "[yellow]Install vlc:[/yellow] https://www.videolan.org/"
        )
    if not get_torrent_streamer():
        console.print(
            "[yellow]Install a torrent streamer for magnet-link support:[/yellow]\n"
            "  [bold]npm install -g webtorrent-cli[/bold]   (recommended)\n"
            "  [bold]npm install -g peerflix[/bold]"
        )


# ─── version ───────────────────────────────────────────────────────────────────

@app.command()
def version() -> None:
    """Show mov-cli version."""
    from importlib.metadata import version as pkg_version, PackageNotFoundError
    try:
        v = pkg_version("mov-cli")
    except PackageNotFoundError:
        v = "dev"
    console.print(f"[bold magenta]mov-cli[/bold magenta] [bold]{v}[/bold]")


# ─── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app()
