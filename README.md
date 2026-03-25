# 🎬 mov-cli

> A fast, modular, terminal-based CLI for searching and streaming movies & TV series.
> Inspired by [ani-cli](https://github.com/pystardust/ani-cli).

```
╭─────────────────────────────────────╮
│  🎬  mov-cli  — your terminal cinema  │
╰─────────────────────────────────────╯
```

---

## Features

| Feature | Status |
|---|---|
| Search movies & TV (TMDB) | ✅ |
| Rich interactive result tables | ✅ |
| Arrow-key / number selection | ✅ |
| Torrent sources (YTS + EZTV) | ✅ |
| mpv / VLC playback | ✅ |
| Magnet streaming (webtorrent / peerflix) | ✅ |
| SQLite search cache (TTL-based) | ✅ |
| Watch history | ✅ |
| Season / episode picker (TV) | ✅ |
| Trending movies & shows | ✅ |
| Pluggable provider system | ✅ |
| Config file | ✅ |

---

## Requirements

| Tool | Purpose | Install |
|---|---|---|
| Python 3.10+ | Runtime | — |
| mpv **or** VLC | Media playback | [mpv.io](https://mpv.io/installation/) |
| webtorrent-cli **or** peerflix | Magnet streaming | `npm i -g webtorrent-cli` |
| TMDB API key | Search | [themoviedb.org/settings/api](https://www.themoviedb.org/settings/api) |

---

## Installation

```bash
# From PyPI (once published)
pip install mov-cli

# From source
git clone https://github.com/Maron09/Mov-cli.git
cd mov-cli
pip install -e .
```

---

## Setup

### 1. Get a free TMDB API key

Register at <https://www.themoviedb.org/settings/api> (free, takes 30 seconds).

### 2. Configure the key

**Option A — environment variable (recommended)**
```bash
export TMDB_API_KEY=your_key_here
# Add to ~/.bashrc or ~/.zshrc to persist
```

**Option B — config file**
```bash
mov-cli config set tmdb_api_key your_key_here
```

### 3. Check your setup
```bash
mov-cli doctor
```

---

## Usage

### Search and stream

```bash
# Search all types
mov-cli search "Inception"

# Search movies only
mov-cli search "The Dark Knight" --type movie

# Search TV shows
mov-cli search "Breaking Bad" --type tv

# Jump straight to S3E4
mov-cli search "The Office" --type tv --season 3 --episode 4
```

### Trending

```bash
mov-cli trending
mov-cli trending --type movie --window week --play
```

### History

```bash
mov-cli history
mov-cli history --limit 50
mov-cli history --clear
```

### Config

```bash
mov-cli config show
mov-cli config set preferred_player vlc
mov-cli config set default_quality 1080p
mov-cli config set cache_ttl_hours 48
```

### Cache

```bash
mov-cli cache         # show cache status
mov-cli cache --clear # wipe cached search results
```

### System check

```bash
mov-cli doctor
mov-cli version
```

---

## Interactive flow

```
$ mov-cli search "Interstellar"

╭──────────────────────────────────────╮
│  🎬  mov-cli  — your terminal cinema  │
╰──────────────────────────────────────╯

Searching for 'Interstellar'…

╭───┬─────────────────┬───────┬──────┬──────────┬──────────────╮
│ # │ Title           │ Type  │ Year │ Rating   │ Overview     │
├───┼─────────────────┼───────┼──────┼──────────┼──────────────┤
│ 1 │ Interstellar    │ Movie │ 2014 │ 8.4/10   │ A team of…  │
│ 2 │ Interstellar…   │  TV   │ 2007 │ 6.2/10   │ …           │
╰───┴─────────────────┴───────┴──────┴──────────┴──────────────╯

Select title [1-2] (q to quit): 1

Fetching sources for Interstellar…

╭───┬──────────────────────────────────┬─────────┬─────────┬──────────╮
│ # │ Title                            │ Quality │ Seeders │ Size     │
├───┼──────────────────────────────────┼─────────┼─────────┼──────────┤
│ 1 │ Interstellar [1080p] [BLURAY]    │ 1080p   │    4821 │ 2.2 GB   │
│ 2 │ Interstellar [720p] [WEB]        │ 720p    │    2100 │ 1.1 GB   │
│ 3 │ Interstellar [4K] [REMUX]        │ 4K      │     340 │ 55.0 GB  │
╰───┴──────────────────────────────────┴─────────┴─────────┴──────────╯

Select source [1-3] (q to quit): 1

▶ Launching mpv for Interstellar [1080p]…
```

---

## Configuration reference

Config file: `~/.mov-cli/config.json`

| Key | Default | Description |
|---|---|---|
| `tmdb_api_key` | `""` | TMDB API key (env: `TMDB_API_KEY`) |
| `preferred_player` | `"mpv"` | `"mpv"` or `"vlc"` |
| `default_quality` | `"1080p"` | Preferred quality hint |
| `player_args` | `[]` | Extra flags passed to the player |
| `cache_enabled` | `true` | Enable/disable search cache |
| `cache_ttl_hours` | `24` | Hours before cached results expire |
| `request_timeout` | `10` | HTTP timeout in seconds |
| `max_search_results` | `10` | Maximum TMDB results shown |

Environment variables override config file values:
- `TMDB_API_KEY`
- `MOVCLI_<KEY_UPPERCASE>` (e.g. `MOVCLI_PREFERRED_PLAYER=vlc`)

---

## Architecture

```
mov_cli/
├── main.py               ← Typer CLI entry point & command definitions
├── cli/
│   └── commands.py       ← Interactive UI, table rendering, user prompts
├── services/
│   ├── tmdb_service.py   ← Async TMDB API client
│   ├── torrent_service.py← Pluggable source providers (YTS, EZTV, …)
│   └── player_service.py ← mpv / VLC launcher + torrent streamer detection
├── models/
│   └── media.py          ← MediaResult, StreamSource, WatchHistoryEntry
├── utils/
│   ├── cache.py          ← SQLite cache & watch history
│   └── config.py         ← Config file management
└── db/                   ← SQLite database lives here at runtime
```

### Adding a new source provider

```python
# mov_cli/services/torrent_service.py

class MyCustomProvider(SourceProvider):
    name = "MyProvider"

    async def fetch_sources(
        self,
        media: MediaResult,
        season=None,
        episode=None,
    ) -> list[StreamSource]:
        # ... query your source ...
        return [StreamSource(...)]

# Register it
aggregator.register(MyCustomProvider())
```

---

## Development

```bash
# Install with dev extras
pip install -e ".[dev]"

# Run tests
pytest tests/ -v

# Lint
ruff check mov_cli/
```

---

## Legal

mov-cli queries publicly available APIs and torrent indexes. It does not host, store, or distribute any copyrighted content. Users are responsible for complying with the laws of their jurisdiction.

---

## License

MIT © mov-cli contributors
