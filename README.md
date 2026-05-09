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

To convert your Audible files into `.m4b` format, you need your unique 8-character hex activation code.

- **Finding your bytes:** You can retrieve these using `audible-cli` by running `audible activation-bytes` in your terminal.
- **Setting your bytes:** In the manager, press `:` to open the Command Palette and select **Set Activation Bytes**. This only needs to be done once.

### Updating

To update the manager to the latest version, pull the latest changes from GitHub:

```bash
git pull
```

Since the project uses `uv`, it will automatically handle any new dependencies the next time you run the application.

## Usage

### Basic Workflow

1.  **Browse & Search:** Use the arrow keys or `j`/`k` to navigate your library. Press `/` to search for specific titles, authors, or ASINs.
2.  **Queue Tasks:** Press `Enter` on any book to add it to the background task queue.
    - If the book hasn't been downloaded, it will be queued for **Download** (Status: `⬇`).
    - If it's already downloaded, it will be queued for **Processing** (Status: `⚙`) to convert it to a standard M4B file with metadata and chapters.
3.  **Monitor Progress:** Press `~` to open the **Queue Viewer**, where you can see active and pending tasks with real-time progress. You can also toggle the bottom log with `` ` `` to see detailed activity.
4.  **Play:** Once a book is fully processed (Status: `✔`), press `Enter` to open it immediately in your system's default media player.

### Customizing Your Experience

The manager is highly configurable via the **Command Palette**. Press `:` at any time to open it and access the following settings:

- **Set Activation Bytes:** Enter your 8-character Audible activation code. This is required for converting downloads to M4B.
- **Set Library Directory:** Choose the local folder where your audiobooks, metadata, and covers will be stored.
- **General Automation Settings:** 
    - **Auto-process:** Automatically start the M4B conversion as soon as a download completes.
    - **Auto-cleanup:** Automatically delete the original Audible source files (AAX) after a successful conversion to save disk space.
- **Configure Library Columns:** Select which columns are visible in the main table (e.g., Narrator, Series, Year) to optimize for your terminal size.
- **Sorting:** Click on any column header to sort the library. The manager supports multi-level sorting and remembers your preferences between sessions.

## Key Bindings

| Key       | Action            | Description                                               |
| :-------- | :---------------- | :-------------------------------------------------------- |
| `Tab`     | **Tab**           | Cycle focus (Search -> Library -> Log)                    |
| `Enter`   | **Action**        | Queue Download/Process, View Active Log, or Play Finished |
| `x`       | **Dequeue**       | Remove a pending item from the task queue                 |
| `j` / `k` | **Down / Up**     | Move selection one row down or up (with 5-row scrolloff)  |
| `d` / `u` | **PgDown / PgUp** | Jump down or up a page                                    |
| `h` / `l` | **Left / Right**  | Scroll library view horizontally                          |
| `g` / `G` | **Top / Bottom**  | Jump to the start or end of the list                      |
| `/`       | **Search**        | Focus the search box                                      |
| `` ` ``   | **Log**           | Toggle the bottom status log                              |
| `r`       | **Refresh**       | Fetch latest library data from Audible                    |
| `~`       | **Queue**         | View the background task queue and progress               |
| `:`       | **Palette**       | Open Command Palette (Configure columns, settings, etc.)  |
| `q`       | **Quit**          | Exit the application                                      |

## Status Indicators (Compact 4-char Column)

- **`⠋⬇`** (Blue): Actively **Downloading**.
- **`⠋⚙`** (Cyan): Actively **Processing** (FFmpeg).
- **` ⬇`** (Yellow): Queued for download.
- **` ⚙`** (Yellow): Queued for processing.
- **` ⬇`** (Green): Downloaded & ready to process.
- **` ✔`** (Green): Fully processed and ready to play.

## Configuration

The application stores your theme preference, library path, and activation bytes in a standard config directory (e.g., `~/.config/audiobook-manager/config.json`).
