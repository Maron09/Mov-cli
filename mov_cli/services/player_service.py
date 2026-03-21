"""
services/player_service.py
--------------------------
Abstraction layer for launching media players.

Supported players (in priority order):
  1. mpv  — preferred; supports magnet links natively when built with libtorrent
  2. vlc  — fallback; robust but fewer magnet features out-of-the-box

Torrent streaming:
  When mpv cannot stream a magnet link directly (no libtorrent build),
  we attempt to launch webtorrent-cli or peerflix as a streaming proxy
  and pass the resulting HTTP URL to mpv/vlc.

  webtorrent: https://github.com/webtorrent/webtorrent-cli
  peerflix:   https://github.com/mafintosh/peerflix
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import time
from typing import Optional

from rich.console import Console

from mov_cli.utils.config import config

console = Console()


# ─── Player detection ──────────────────────────────────────────────────────────

def _find_binary(*names: str) -> Optional[str]:
    """Return the first binary name found in PATH, or None."""
    for name in names:
        path = shutil.which(name)
        if path:
            return path
    return None


def get_player() -> Optional[str]:
    """
    Determine which player to use.
    Respects config.preferred_player, falls back to whatever is installed.
    """
    preferred = config.preferred_player.lower()
    if preferred == "mpv":
        path = _find_binary("mpv")
        if path:
            return "mpv"
        # fallthrough to VLC
    if preferred in ("vlc", "mpv"):
        path = _find_binary("vlc", "cvlc")
        if path:
            return "vlc"
    # Last resort: whichever comes first
    for player in ("mpv", "vlc"):
        if _find_binary(player):
            return player
    return None


def get_torrent_streamer() -> Optional[str]:
    """
    Check for CLI-based torrent streaming tools.
    Returns 'webtorrent' | 'peerflix' | None
    """
    if _find_binary("webtorrent"):
        return "webtorrent"
    if _find_binary("peerflix"):
        return "peerflix"
    return None


# ─── Player launcher ───────────────────────────────────────────────────────────

class PlayerService:
    """Launches the user's preferred player with the given URI."""

    def __init__(self) -> None:
        self.player = get_player()
        self.streamer = get_torrent_streamer()
        self.extra_args: list[str] = config.get("player_args", [])

    def play(self, uri: str, title: str = "") -> int:
        """
        Stream `uri` (URL or magnet link).
        Returns the player's exit code (0 = success).
        Raises RuntimeError if no player is available.
        """
        if not self.player:
            raise RuntimeError(
                "No supported media player found.\n"
                "Install mpv: https://mpv.io/installation/\n"
                "       VLC: https://www.videolan.org/"
            )

        is_magnet = uri.startswith("magnet:")

        if is_magnet:
            return self._play_magnet(uri, title)
        return self._play_direct(uri, title)

    def _play_direct(self, url: str, title: str) -> int:
        """Play a direct HTTP/HTTPS stream."""
        cmd = self._build_cmd(self.player, url, title)
        console.print(f"[dim]▶ Launching {self.player}…[/dim]")
        return subprocess.call(cmd)

    def _play_magnet(self, magnet: str, title: str) -> int:
        """
        Attempt to stream a magnet link.

        Strategy:
          1. Try mpv directly (works when mpv is built with libtorrent)
          2. Fall back to webtorrent-cli or peerflix as a streaming proxy
          3. Print a helpful error if nothing works
        """
        # ── Option 1: mpv native magnet support ──────────────────────────────
        if self.player == "mpv":
            console.print("[dim]▶ Trying native magnet stream via mpv…[/dim]")
            cmd = self._build_cmd("mpv", magnet, title)
            ret = subprocess.call(cmd)
            if ret == 0:
                return 0
            console.print("[yellow]mpv could not stream magnet directly.[/yellow]")

        # ── Option 2: webtorrent-cli ──────────────────────────────────────────
        if self.streamer == "webtorrent":
            player_flag = f"--{self.player}" if self.player else "--mpv"
            console.print(f"[dim]▶ Streaming via webtorrent ({player_flag})…[/dim]")
            cmd = ["webtorrent", "download", magnet, player_flag]
            return subprocess.call(cmd)

        # ── Option 3: peerflix ───────────────────────────────────────────────
        if self.streamer == "peerflix":
            player_flag = f"--{self.player}" if self.player else "--mpv"
            console.print(f"[dim]▶ Streaming via peerflix ({player_flag})…[/dim]")
            cmd = ["peerflix", magnet, player_flag]
            return subprocess.call(cmd)

        # ── Nothing worked ───────────────────────────────────────────────────
        console.print(
            "[bold red]Cannot stream magnet link.[/bold red]\n"
            "Install one of the following torrent streaming tools:\n"
            "  [cyan]npm install -g webtorrent-cli[/cyan]\n"
            "  [cyan]npm install -g peerflix[/cyan]\n"
            "Or rebuild mpv with libtorrent support."
        )
        console.print(f"\n[dim]Magnet link (copy to your torrent client):\n{magnet}[/dim]")
        return 1

    def _build_cmd(self, player: str, uri: str, title: str) -> list[str]:
        """Build the subprocess command list for the given player."""
        if player == "mpv":
            cmd = ["mpv"]
            if title:
                cmd += [f"--title={title}"]
            cmd += ["--no-terminal"] if not sys.stdout.isatty() else []
            cmd += self.extra_args
            cmd.append(uri)
        elif player == "vlc":
            cmd = ["vlc"]
            if title:
                cmd += ["--meta-title", title]
            cmd += self.extra_args
            cmd.append(uri)
        else:
            cmd = [player, uri]
        return cmd

    def status_report(self) -> dict:
        return {
            "player": self.player or "not found",
            "streamer": self.streamer or "not found",
        }


# ─── Module-level singleton ────────────────────────────────────────────────────

player_service = PlayerService()
