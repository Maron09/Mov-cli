"""
utils/config.py
---------------
Configuration management for mov-cli.
Config is stored at ~/.mov-cli/config.json and is created with
sensible defaults on first run.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

# ─── Default configuration ────────────────────────────────────────────────────

DEFAULT_CONFIG: dict[str, Any] = {
    # Playback
    "preferred_player": "mpv",          # "mpv" | "vlc"
    "default_quality": "1080p",         # "4K" | "1080p" | "720p" | "480p"
    "player_args": [],                  # Extra CLI flags forwarded to the player

    # Cache
    "cache_enabled": True,
    "cache_ttl_hours": 24,

    # TMDB
    # Users should supply their own key from https://www.themoviedb.org/settings/api
    # The env var TMDB_API_KEY takes precedence over this value.
    "tmdb_api_key": "",

    # Subtitles (optional)
    "subtitles_enabled": False,
    "opensubtitles_api_key": "",
    "subtitle_language": "en",

    # Network
    "request_timeout": 10,              # seconds
    "max_search_results": 10,
}

# ─── Config manager ────────────────────────────────────────────────────────────

class Config:
    """
    Singleton-style config manager.

    Priority (highest → lowest):
      1. Environment variables  (MOVCLI_<KEY> or TMDB_API_KEY)
      2. ~/.mov-cli/config.json
      3. DEFAULT_CONFIG
    """

    CONFIG_DIR = Path.home() / ".mov-cli"
    CONFIG_FILE = CONFIG_DIR / "config.json"

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}
        self._load()

    # ── Internal helpers ───────────────────────────────────────────────────────

    def _load(self) -> None:
        """Load config from disk, creating defaults if absent."""
        self.CONFIG_DIR.mkdir(parents=True, exist_ok=True)

        if not self.CONFIG_FILE.exists():
            self._data = dict(DEFAULT_CONFIG)
            self._save()
        else:
            with open(self.CONFIG_FILE) as f:
                stored = json.load(f)
            # Merge stored values over defaults so new keys are always present
            self._data = {**DEFAULT_CONFIG, **stored}

    def _save(self) -> None:
        with open(self.CONFIG_FILE, "w") as f:
            json.dump(self._data, f, indent=2)

    # ── Public API ─────────────────────────────────────────────────────────────

    def get(self, key: str, default: Any = None) -> Any:
        """
        Retrieve a config value.
        Env var MOVCLI_<KEY_UPPER> always wins.
        Special-case: TMDB_API_KEY maps to tmdb_api_key.
        """
        # Special env-var mappings
        env_map = {
            "tmdb_api_key": os.getenv("TMDB_API_KEY", ""),
        }
        if key in env_map and env_map[key]:
            return env_map[key]

        # Generic env-var override: MOVCLI_PREFERRED_PLAYER etc.
        env_key = f"MOVCLI_{key.upper()}"
        env_val = os.getenv(env_key)
        if env_val is not None:
            return env_val

        return self._data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        """Persist a value to the config file."""
        self._data[key] = value
        self._save()

    def all(self) -> dict[str, Any]:
        """Return a copy of the full config dict."""
        return dict(self._data)

    @property
    def tmdb_api_key(self) -> str:
        return self.get("tmdb_api_key", "")

    @property
    def preferred_player(self) -> str:
        return self.get("preferred_player", "mpv")

    @property
    def default_quality(self) -> str:
        return self.get("default_quality", "1080p")

    @property
    def cache_enabled(self) -> bool:
        val = self.get("cache_enabled", True)
        if isinstance(val, str):
            return val.lower() not in ("false", "0", "no")
        return bool(val)

    @property
    def cache_ttl_hours(self) -> int:
        return int(self.get("cache_ttl_hours", 24))

    @property
    def request_timeout(self) -> int:
        return int(self.get("request_timeout", 10))

    @property
    def max_search_results(self) -> int:
        return int(self.get("max_search_results", 10))


# ─── Module-level singleton ────────────────────────────────────────────────────

config = Config()
