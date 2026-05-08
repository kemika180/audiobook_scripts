# Audiobook Manager TUI

A unified, keyboard-centric terminal user interface for managing your Audible library. Download audiobooks, convert them to M4B with chapters and cover art, and track your local collection—all from a single, streamlined interface.

## Features

- **Unified Workflow:** One interface to browse, download, and process your library.
- **Dynamic Action Key:** Press `Enter` to perform the next logical step (Download -> Process).
- **Full Vim-style Navigation:** Navigate your library using `h`, `j`, `k`, `l`, `u`, `d`, `g`, and `G`.
- **Real-time Filtering:** Fast, `fzf`-like search across ASIN, Author, and Title.
- **Visual Status Indicators:** Instant feedback on what's downloaded (⬇ ) and what's ready (✔).
- **Persistent Preferences:** Remembers your chosen theme and log visibility across sessions.
- **Detailed Terminal Output:** A pop-up modal shows real-time progress from underlying tools.

## Prerequisites

Before running the manager, ensure you have the following installed on your system:

### 1. FFmpeg

Used for converting files and embedding chapters/cover art.

- **Linux:** `sudo apt install ffmpeg` (or your distro's equivalent)
- **macOS:** `brew install ffmpeg`

### 2. Audible-CLI

The manager uses the `audible` command-line tool to interact with your library.

- **Installation:** `pip install audible-cli`
- **Setup:** You must be logged in for the manager to fetch your library. Run `audible login` to authenticate.

### 3. uv (Recommended)

This project uses `uv` to manage Python dependencies automatically.

- **Installation:** `curl -LsSf https://astral.sh/uv/install.sh | sh`

## Getting Started

Simply run the manager using `uv`:

```bash
uv run audiobook_manager.py
```

`uv` will automatically create a virtual environment, install `textual`, and launch the application.

## Key Bindings

| Key       | Action            | Description                                        |
| :-------- | :---------------- | :------------------------------------------------- |
| `Tab`     | **Tab**           | Cycle focus (Search -> Library -> Log)             |
| `Enter`   | **Action**        | Download (if missing) or Process (if AAX present)  |
| `j` / `k` | **Down / Up**     | Move selection one row                             |
| `d` / `u` | **PgDown / PgUp** | Jump a page down or up                             |
| `h` / `l` | **Left / Right**  | Scroll table horizontally                          |
| `g` / `G` | **Top / Bottom**  | Jump to the start or end of the list               |
| `/`       | **Search**        | Focus the filter input                             |
| `` ` ``   | **Log**           | Toggle the bottom status log                       |
| `r`       | **Refresh**       | Fetch latest library data from Audible             |
| `Ctrl+p`  | **Palette**       | Open Textual command palette (change themes, etc.) |
| `q`       | **Quit**          | Exit the application                               |

## Configuration

The application stores your theme preference and log visibility in `audiobook_config.json` located in the same directory as the script.

## Technical Details

- **M4B Conversion:** Uses `ffmpeg` with `-activation_bytes` to decrypt AAX files and map metadata/chapters correctly.
- **Sanitization:** Output filenames are automatically sanitized (spaces to underscores, invalid symbols to dashes) for maximum compatibility with media servers.
- **Stability:** Uses stable row keys (ASIN) to ensure the UI stays responsive and accurate during background processing.
