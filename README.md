# Audiobook Manager TUI

A unified, keyboard-centric terminal user interface for managing your Audible library. Download audiobooks, convert them to M4B with chapters and cover art, and track your local collection—all from a single, streamlined interface.  
<br/><img width="1916" height="1028" alt="audiobook tui 2" src="https://github.com/user-attachments/assets/512af169-652d-4466-97da-1e0d249b641e" />

## Features

- **Robust JSON API:** Transitioned from fragile regex parsing to the official Audible JSON API, providing rich metadata including series, narrators, and release years.
- **Sequential Queuing:** Select multiple books to queue them for download or encoding. Processes run one-by-one in the background.
- **Dynamic Queue Viewer:** View all active and pending tasks with real-time progress percentages (calculated from logs and file durations).
- **Customizable Library:** Use the command palette to toggle columns like ASIN, Author, Narrator, Series, and Year. Your preferences are saved automatically.
- **Multi-Level Natural Sorting:** Sort by any column with persistent history. Series sorting is "human-aware," correctly handling numerical sequences and grouped installments like `(1-3)`.
- **Advanced Automation:** Enable "Auto-process after download" and "Auto-cleanup source files" to streamline your full library conversion.
- **Hardened DRM Removal:** Uses a clean "strip-and-replace" metadata strategy to ensure M4B files are truly DRM-free and compatible with all media players.
- **One-Click Playback:** Press `Enter` on a finalized book (✔) to open it immediately in your system's default media player.
- **Vim-style Navigation:** Full support for `h/j/k/l`, `u/d`, `g/G`, plus rock-solid **Vim-style scrolloff** that preserves horizontal scroll.

## Prerequisites

Before running the manager, ensure you have the following installed on your system:

### 1. FFmpeg

Used for converting files and embedding chapters/cover art.

- **Linux:** `sudo apt install ffmpeg` (or your distro's equivalent)
- **macOS:** `brew install ffmpeg`

### 2. Audible-CLI

The manager uses the `audible` command-line tool to interact with your library.

- **Installation:** `pip install audible-cli` or `uv tool install audible-cli`
- **Setup:** You must be logged in for the manager to fetch your library. Run `audible login` to authenticate.

### 3. uv (Recommended)

This project uses `uv` to manage Python dependencies automatically.

- **Installation:** `curl -LsSf https://astral.sh/uv/install.sh | sh`

## Getting Started

First, clone the repository to your local machine:

```bash
git clone https://github.com/kemika180/audiobook_scripts.git
cd audiobook_scripts
```

Then, simply run the manager using `uv`:

```bash
uv run audiobook_manager.py
```

`uv` will automatically create a virtual environment, install all dependencies, and launch the application.

### Activation Bytes

To convert your Audible files into DRM-free `.m4b` format, you need your unique 8-character hex activation code. 

- **Finding your bytes:** You can retrieve these using `audible-cli` by running `audible activation-bytes` in your terminal.
- **Setting your bytes:** In the manager, press `:` to open the Command Palette and select **Set Activation Bytes**. This only needs to be done once.

### Updating

To update the manager to the latest version, pull the latest changes from GitHub:

```bash
git pull
```

Since the project uses `uv`, it will automatically handle any new dependencies the next time you run the application.

## Key Bindings

| Key       | Action            | Description                                              |
| :-------- | :---------------- | :------------------------------------------------------- |
| `Tab`     | **Tab**           | Cycle focus (Search -> Library -> Log)                   |
| `Enter`   | **Action**        | Queue Download/Process, View Active Log, or Play Finished |
| `x`       | **Dequeue**       | Remove a pending item from the task queue                |
| `j` / `k` | **Down / Up**     | Move selection one row down or up (with 5-row scrolloff) |
| `d` / `u` | **PgDown / PgUp** | Jump down or up a page                                   |
| `h` / `l` | **Left / Right**  | Scroll library view horizontally                         |
| `g` / `G` | **Top / Bottom**  | Jump to the start or end of the list                     |
| `/`       | **Search**        | Focus the search box                                     |
| `` ` ``   | **Log**           | Toggle the bottom status log                             |
| `r`       | **Refresh**       | Fetch latest library data from Audible                   |
| `~`       | **Queue**         | View the background task queue and progress              |
| `:`       | **Palette**       | Open Command Palette (Configure columns, settings, etc.) |
| `q`       | **Quit**          | Exit the application                                     |

## Status Indicators (Compact 4-char Column)

- **` ⠋⬇ `** (Blue): Actively **Downloading**.
- **` ⠋⚙ `** (Cyan): Actively **Processing** (FFmpeg).
- **`  ⬇ `** (Yellow): Queued for download.
- **`  ⚙ `** (Yellow): Queued for processing.
- **`  ⬇ `** (Green): Downloaded & ready to process.
- **`  ✔ `** (Green): Fully processed and ready to play.

## Configuration

The application stores your theme preference, library path, and activation bytes in a standard config directory (e.g., `~/.config/audiobook-manager/config.json`).

### New Command Palette Actions (`:`)
- **Configure Library Columns:** Select exactly which metadata you want to see.
- **General Automation Settings:** Toggle auto-processing and auto-cleanup.
- **Show Task Queue:** View the live dashboard of all pending background tasks.
- **Set Activation Bytes:** Enter your Audible bytes to enable DRM removal.
