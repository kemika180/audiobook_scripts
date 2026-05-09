# Audiobook Manager TUI

A unified, keyboard-centric terminal user interface for managing your Audible library. Download audiobooks, convert them to M4B with chapters and cover art, and track your local collection—all from a single, streamlined interface.  
<br/><img width="1916" height="1028" alt="audiobook tui 2" src="https://github.com/user-attachments/assets/512af169-652d-4466-97da-1e0d249b641e" />

## Features

- **Sequential Queuing:** Select multiple books to queue them for download or encoding. Processes run one-by-one in the background.
- **Async Background Tasks:** Downloads and FFmpeg conversions are non-blocking async processes with real-time log streaming.
- **One-Click Playback:** Press `Enter` on a finalized book (✔) to open it immediately in your system's default media player.
- **Smart Status Indicators:**
  - `⬇` (Yellow): Queued for download.
  - `⚙` (Yellow): Queued for encoding.
  - `Animated Spinner` (Blue): Actively processing.
  - `✔` (Green): Fully processed and ready to play.
- **Persistent Progress Logging:** View detailed logs for any active task by selecting it. History is preserved even if you close the modal.
- **Vim-style Navigation:** Full support for `h/j/k/l`, `u/d`, `g/G`, plus **Vim-style scrolloff** (5 rows of context).
- **Optimized Performance:** High-performance library refreshes using $O(1)$ filesystem lookups and background status workers.

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

Simply run the manager using `uv`:

```bash
uv run audiobook_manager.py
```

`uv` will automatically create a virtual environment, install `textual`, and launch the application.

## Key Bindings

| Key       | Action            | Description                                              |
| :-------- | :---------------- | :------------------------------------------------------- |
| `Tab`     | **Tab**           | Cycle focus (Search -> Library -> Log)                   |
| `Enter`   | **Action**        | Queue Download/Process, View Active Log, or Play Finished |
| `j` / `k` | **Down / Up**     | Move selection one row down or up (with scrolloff)       |
| `d` / `u` | **PgDown / PgUp** | Jump down or up a page                                   |
| `h` / `l` | **Left / Right**  | Scroll library view horizontally                         |
| `g` / `G` | **Top / Bottom**  | Jump to the start or end of the list                     |
| `/`       | **Search**        | Focus the search box                                     |
| `` ` ``   | **Log**           | Toggle the bottom status log                             |
| `r`       | **Refresh**       | Fetch latest library data from Audible                   |
| `:`       | **Palette**       | Open Textual command palette (change themes, etc.)       |
| `q`       | **Quit**          | Exit the application                                     |

## Configuration

The application stores your theme preference, library path, and activation bytes in a standard config directory (e.g., `~/.config/audiobook-manager/config.json`).

### Setting Activation Bytes
To decrypt and convert Audible files, you must provide your 8-character hex activation bytes:
1. Launch the manager: `uv run audiobook_manager.py`
2. Open the **Command Palette** using `:` and type `Set Activation Bytes`.
3. Enter your 8-character hex code and select **Save**.

## Technical Details

- **Modular Architecture:** Split into clean modules (`models`, `service`, `ui`, `utils`) for easier maintenance.
- **Asynchronous I/O:** Uses `asyncio` subprocesses to handle high-bandwidth tool output without UI stutter.
- **Safe State Management:** Background workers use `try...finally` to ensure UI state consistency even if tools fail.
- **Cross-Platform Playback:** Uses `xdg-open`, `open`, or `os.startfile` based on the host OS.
