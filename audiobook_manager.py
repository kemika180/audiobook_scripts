# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "textual",
#     "platformdirs",
#     "pytest",
#     "watchdog",
# ]
# ///

import json
import shutil
import re
import asyncio
import logging
import argparse
import sys
from typing import List, Dict, Iterable, Callable
from pathlib import Path

from platformdirs import user_config_dir
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from textual.app import App, ComposeResult, SystemCommand
from textual.binding import Binding
from textual.widgets import Header, Footer, DataTable, Input, TabbedContent, TabPane, Label
from textual import work, on, events
from textual.reactive import reactive
from textual.screen import Screen
from textual.theme import Theme

from models import Audiobook
from service import AudiobookService
from ui.widgets import LibraryTable, SearchInput, StatusLog, QueueTable
from ui.screens import ProcessOutputScreen, ConfirmModal, ActivationBytesModal, LibraryPathModal, ColumnSettingsModal, GeneralSettingsModal

# Constants
APP_NAME = "tome"
CONFIG_DIR = Path(user_config_dir(APP_NAME))
CONFIG_FILE = CONFIG_DIR / "config.json"
LOG_FILE = CONFIG_DIR / "activity.log"
OLD_CONFIG_FILE = Path(__file__).parent / "audiobook_config.json"
OLD_MANAGER_CONFIG_FILE = Path(user_config_dir("audiobook-manager")) / "config.json"

SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

logger = logging.getLogger("tome")
logger.setLevel(logging.INFO)

class TuiLogHandler(logging.Handler):
    """Custom logging handler that writes to the Textual StatusLog widget."""
    def __init__(self, log_widget):
        super().__init__()
        self.log_widget = log_widget

    def emit(self, record):
        try:
            msg = self.format(record)
            # Add Rich coloring based on level
            if record.levelno >= logging.ERROR:
                msg = f"[bold red]{msg}[/]"
            elif record.levelno >= logging.WARNING:
                msg = f"[bold yellow]{msg}[/]"
            elif record.levelno >= logging.INFO:
                if "successfully" in msg.lower() or "complete" in msg.lower():
                    msg = f"[bold green]{msg}[/]"
            
            self.log_widget.write(msg)
        except Exception:
            self.handleError(record)

class LibraryWatcher(FileSystemEventHandler):
    """Watches the library directory for changes and triggers UI updates."""
    def __init__(self, callback: Callable[[], None]):
        self.callback = callback
        self._loop = asyncio.get_event_loop()

    def on_any_event(self, event):
        # We only care about file creation, deletion, or renaming
        if event.is_directory:
            return
        
        # Debounce slightly to avoid multiple refreshes for a single multi-file operation
        if hasattr(self, "_timer"):
            self._loop.call_soon_threadsafe(self._timer.cancel)
        
        self._timer = self._loop.call_later(0.5, self._trigger_callback)

    def _trigger_callback(self):
        self.callback()

class ConfigManager:
    """Manages application configuration loading, saving, and migrations."""

    DEFAULT_CONFIG = {
        "theme": "kemika-purple", 
        "log_visible": True,
        "activation_bytes": "",
        "library_path": str(Path.cwd()),
        "sort_order": ["title", "author", "asin"],
        "sort_reverse": False,
        "visible_columns": ["Status", "ASIN", "Author", "Title", "Narrator", "Series", "Year"],
        "auto_cleanup": False,
        "auto_process": False
    }

    def __init__(self):
        self._config = self.load_config()

    def load_config(self) -> Dict:
        # Migration: Check if old audiobook-manager config exists and move it
        if OLD_MANAGER_CONFIG_FILE.exists() and not CONFIG_FILE.exists():
            try:
                CONFIG_DIR.mkdir(parents=True, exist_ok=True)
                shutil.copy(str(OLD_MANAGER_CONFIG_FILE), str(CONFIG_FILE))
            except Exception:
                pass

        # Migration: Check if old config exists and move it
        if OLD_CONFIG_FILE.exists() and not CONFIG_FILE.exists():
            try:
                CONFIG_DIR.mkdir(parents=True, exist_ok=True)
                shutil.move(str(OLD_CONFIG_FILE), str(CONFIG_FILE))
            except Exception:
                pass

        if CONFIG_FILE.exists():
            try:
                with open(CONFIG_FILE, "r") as f:
                    data = json.load(f)
                    # Migration for secondary sorting
                    if "sort_column" in data and "sort_order" not in data:
                        col = data["sort_column"]
                        data["sort_order"] = [col] + [c for c in ["title", "author", "series_title", "asin"] if c != col]

                    # Ensure all default keys exist
                    for key, val in self.DEFAULT_CONFIG.items():
                        if key not in data:
                            data[key] = val
                    return data
            except Exception:
                pass
        return self.DEFAULT_CONFIG.copy()

    def save(self):
        try:
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            with open(CONFIG_FILE, "w") as f:
                json.dump(self._config, f, indent=4)
            return True
        except Exception as e:
            return str(e)

    def get(self, key, default=None):
        return self._config.get(key, default)

    def update(self, mapping):
        self._config.update(mapping)
        self.save()

    def set(self, key, value):
        self._config[key] = value
        self.save()

    def __getitem__(self, key):
        return self._config[key]

    def __setitem__(self, key, value):
        self._config[key] = value
        self.save()

class TaskQueueManager:
    """Manages the background task queue and book state tracking."""

    def __init__(self):
        self.items: list[str] = []
        self.pending_asins: set[str] = set()
        self._event = asyncio.Event()

    def put(self, asin: str) -> bool:
        """Adds an ASIN to the end of the queue if not already present."""
        if asin not in self.pending_asins:
            self.pending_asins.add(asin)
            self.items.append(asin)
            self._event.set()
            return True
        return False

    async def get(self) -> str:
        """Wait for and return the next ASIN in the queue."""
        while not self.items:
            self._event.clear()
            await self._event.wait()
        
        asin = self.items.pop(0)
        self.pending_asins.discard(asin)
        return asin

    def remove(self, asin: str) -> bool:
        """Removes an ASIN from the queue if present."""
        if asin in self.pending_asins:
            self.pending_asins.remove(asin)
            try:
                self.items.remove(asin)
                if not self.items:
                    self._event.clear()
                return True
            except ValueError:
                pass
        return False

    def is_empty(self) -> bool:
        """Returns True if the queue is empty."""
        return not self.items

    @property
    def pending_count(self) -> int:
        """Returns the number of items in the queue."""
        return len(self.items)

kemika_purple_theme = Theme(
    name="kemika-purple",
    primary="#5c3b8a",
    secondary="#2f2c4a",
    background="#0f0f15",
    surface="#141320",
    panel="#12121a",
    foreground="#e2e2e9",
    accent="#cbb2ff",
    boost="#1e1d32",
    success="#b53580",
    variables={
        "scrollbar": "#5c3b8a",
        "scrollbar-hover": "#7b52ab",
        "scrollbar-active": "#cbb2ff",
        "scrollbar-background": "#0d0c15",
        "scrollbar-background-hover": "#0d0c15",
        "scrollbar-background-active": "#0d0c15",
        "scrollbar-corner-color": "#0d0c15",
    },
    dark=True,
)

class AudiobookManager(App):
    CSS = """
    Screen {
        overflow: hidden;
        scrollbar-size: 0 0;
    }
    TabbedContent {
        height: 1fr;
    }
    TabbedContent, ContentSwitcher, TabPane {
        overflow: hidden;
    }
    Widget {
        scrollbar-size: 1 2;
    }
    DataTable {
        height: 1fr;
    }
    #log {
        height: 8;
        background: $surface;
        color: $text;
        border: tall $primary;
        margin: 1;
    }
    #search_input {
        margin: 0 1;
        display: none;
    }
    .status-label {
        margin: 0 1;
        color: $text-muted;
    }
    LibraryTable > .datatable--selected {
        background: $success;
        color: $foreground;
    }
    """

    TITLE = "Audiobook Manager"
    COMMAND_PALETTE_BINDING = ":"

    BINDINGS = [
        Binding("q", "quit", "Quit", show=True),
        Binding("s", "refresh_library", "Sync/Scan", show=True),
        Binding("d", "process_selected", "Process Selected", show=True),
        Binding("a", "select_all", "Select All", show=True),
        Binding("u", "deselect_all", "Deselect All", show=True),
        Binding("x", "remove_from_queue", "Dequeue", show=True),
        Binding("/", "focus_search", "Search", show=True),
        Binding("`,grave,backtick", "toggle_log", "Toggle Log", show=False),
        Binding("H,shift+h", "prev_tab", "Prev Tab", show=False),
        Binding("L,shift+l", "next_tab", "Next Tab", show=False),
        Binding(":", "command_palette", "Command", show=False),
    ]

    search_query = reactive("")
    def __init__(self):
        super().__init__()
        self.config = ConfigManager()
        self.service = AudiobookService(self.config)
        self.full_library: List[Audiobook] = []
        self._library_lookup: Dict[str, Audiobook] = {}
        self.active_logs: Dict[str, Dict] = {}
        self.task_queue = TaskQueueManager()
        self.col_keys = {}
        self.sort_order = self.config.get("sort_order", ["title", "author", "asin"])
        self.sort_reverse = self.config.get("sort_reverse", False)
        self.selected_books = set()
        
        # Filesystem watcher
        self.observer = None

    def setup_logging(self) -> None:
        """Sets up the standard logging system."""
        # File handler (Plain text)
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(LOG_FILE)
        file_handler.setFormatter(logging.Formatter('[%(asctime)s] %(levelname)s: %(message)s', '%Y-%m-%d %H:%M:%S'))
        logger.addHandler(file_handler)

        # TUI handler (Rich formatted)
        tui_handler = TuiLogHandler(self.query_one("#log"))
        tui_handler.setFormatter(logging.Formatter('%(message)s'))
        logger.addHandler(tui_handler)

    def watch_theme(self, theme: str) -> None:
        """Saves the theme to config whenever it changes."""
        if hasattr(self, "config"):
            if self.config.get("theme") != theme:
                self.config.set("theme", theme)
                logger.info(f"Theme saved: {theme}")

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with TabbedContent(initial="library-tab"):
            with TabPane("Library", id="library-tab"):
                yield SearchInput(placeholder="Filter library (ASIN, Author, or Title)...", id="search_input")
                yield LibraryTable(id="library_table")
                yield Label("0 books selected | 0 books loaded", id="library-status", classes="status-label")
                
            with TabPane("Queue", id="queue-tab"):
                yield QueueTable(id="queue-table")

        yield StatusLog(id="log", markup=True, highlight=False)
        yield Footer()

    def on_mount(self) -> None:
        self.setup_logging()
        
        # Check dependencies
        missing = []
        if not shutil.which("ffmpeg"):
            missing.append("ffmpeg")
        if not shutil.which("audible"):
            missing.append("audible-cli")

        if missing:
            msg = f"Missing dependencies: {', '.join(missing)}. Some features will not work."
            self.notify(msg, severity="error")
            logger.error(msg)
            logger.info("Please install them and restart the application.")

        # Check authentication
        self.check_authentication()

        self.register_theme(kemika_purple_theme)
        # Apply the saved theme from config
        saved_theme = self.config.get("theme", "kemika-purple")
        self.theme = saved_theme

        # Restore log visibility
        log = self.query_one("#log")
        log.display = self.config.get("log_visible", True)

        # Initialize QueueTable columns
        queue_table = self.query_one("#queue-table", QueueTable)
        queue_table.add_columns("Pos", "Action", "Progress", "Title", "ASIN")
        queue_table.cursor_type = "row"

        self.rebuild_table_columns()
        self.action_refresh_library()

        # Start background workers
        self.set_interval(0.1, self.animate_spinners)
        self.set_interval(1.0, self.update_queue_table)
        self.process_queue()

        # Start filesystem watcher
        lib_path = self.service.library_path
        if lib_path.exists():
            self.observer = Observer()
            self.observer.schedule(LibraryWatcher(self.refresh_all_statuses), str(lib_path), recursive=False)
            self.observer.start()

    async def on_unmount(self) -> None:
        """Clean up background resources."""
        if self.observer:
            self.observer.stop()
            self.observer.join()

        # Shutdown service (terminate subprocesses)
        await self.service.shutdown()

    def rebuild_table_columns(self) -> None:
        """Rebuilds the DataTable columns based on config."""
        table = self.query_one("#library_table", LibraryTable)
        table.clear(columns=True)
        self.col_keys = {}

        visible = self.config.get("visible_columns", ["Status", "ASIN", "Author", "Title", "Series"])

        for col in visible:
            label = "" if col == "Status" else col
            # Ultra-compact status column (3 chars)
            width = 3 if col == "Status" else None
            key = table.add_column(label, width=width)
            self.col_keys[col] = key

        table.cursor_type = "row"
        if len(visible) > 0:
            table.fixed_columns = 1
        table.focus()

    @work
    async def process_queue(self) -> None:
        """Background worker that processes tasks from the queue sequentially."""
        while True:
            asin = await self.task_queue.get()

            # Find the book
            book = self._library_lookup.get(asin)
            if not book:
                continue

            book.queued = False
            title = book.title
            status = self.service.get_status(asin, title)

            if status == "": # Needs download
                await self.download_book(asin)
            elif "⬇" in status: # Needs processing
                await self.process_book(asin, title)

    def _get_status_display(self, book: Audiobook) -> str:
        """Generates an ultra-compact (3 char) status string using symbols."""
        frame = SPINNER_FRAMES[book.spinner_frame]

        if book.working_mode == "downloading":
            return f" [blue]{frame}[/][bold blue]⬇[/]"
        elif book.working_mode == "processing":
            return f" [cyan]{frame}[/][bold cyan]⚙[/]"
        elif book.working_mode == "queued_download":
            return "  [bold yellow]⬇[/] "
        elif book.working_mode == "queued_processing":
            return "  [bold yellow]⚙[/] "
        elif book.working_mode == "queued": # Fallback
            return "  ⏳"

        # Static statuses
        if "✔" in book.status:
            return " [bold green]✔[/] "
        elif "⬇" in book.status:
            return "  [bold green]⬇[/] "
        elif "⚙" in book.status:
            return "  [bold yellow]⚙[/] "

        return "   "

    def animate_spinners(self) -> None:
        """Updates the spinner frame for all working books."""
        if not self.active_logs:
            return

        table = self.query_one("#library_table", LibraryTable)
        status_key = self.col_keys.get("Status")
        if not status_key:
            return

        updated = False
        # Use the cached lookup instead of recreating it every 0.1s
        for asin in self.active_logs.keys():
            book = self._library_lookup.get(asin)
            if book and book.working_mode in ["downloading", "processing"]:
                book.spinner_frame = (book.spinner_frame + 1) % len(SPINNER_FRAMES)

                # Find the row for this ASIN
                try:
                    # Textual DataTable supports getting row by key if we set it
                    # In apply_filter we set key=book.asin
                    table.update_cell(asin, status_key, self._get_status_display(book))
                    updated = True
                except Exception:
                    # Row might not be in the current filtered view
                    pass

        if updated:
            table.refresh()

    @on(DataTable.HeaderSelected, "#library_table")
    def on_header_click(self, event: DataTable.HeaderSelected) -> None:
        """Handle clicking on a column header to sort."""
        # Map column keys back to Audiobook attributes
        column_map = {
            "ASIN": "asin",
            "Author": "author",
            "Title": "title",
            "Narrator": "narrator",
            "Series": "series_title",
            "Year": "year"
        }

        # Find which column was clicked
        target_label = None
        for label, key in self.col_keys.items():
            if key == event.column_key:
                target_label = label
                break

        target_col = column_map.get(target_label)
        if not target_col:
            return

        if self.sort_order[0] == target_col:
            # Toggle direction if clicking same column
            self.sort_reverse = not self.sort_reverse
        else:
            # Move to front (Primary)
            if target_col in self.sort_order:
                self.sort_order.remove(target_col)
            self.sort_order.insert(0, target_col)
            self.sort_reverse = False

        # Save to config
        self.config.set("sort_order", self.sort_order)
        self.config.set("sort_reverse", self.sort_reverse)

        logger.info(f"Sorting by {target_label} ({'descending' if self.sort_reverse else 'ascending'})")

        # Re-apply filter which includes sorting

        search_val = self.query_one("#search_input", Input).value
        self.apply_filter(search_val)

    def on_focus(self) -> None:
        """Refresh statuses whenever the app gets focus."""
        self.refresh_all_statuses()

    def get_system_commands(self, screen: Screen) -> Iterable[SystemCommand]:
        yield from super().get_system_commands(screen)
        yield SystemCommand(
            "Set Activation Bytes",
            "Enter your Audible activation bytes for decryption",
            self.action_set_activation_bytes
        )
        yield SystemCommand(
            "Set Library Directory",
            "Choose where your audiobooks are stored",
            self.action_set_library_path
        )
        yield SystemCommand(
            "Configure Library Columns",
            "Select which columns are visible in the library table",
            self.action_configure_columns
        )
        yield SystemCommand(
            "General Automation Settings",
            "Configure auto-processing and cleanup options",
            self.action_general_settings
        )
        yield SystemCommand(
            "Show Task Queue",
            "Switch to the Queue tab",
            self.action_show_queue
        )

    def _extract_progress(self, asin: str) -> str:
        """Parses the latest log lines for progress information."""
        log_data = self.active_logs.get(asin)
        if not log_data or not log_data["history"]:
            return ""

        # Look at last few lines for efficiency
        history = log_data["history"][-10:]
        action = "Processing" if "Processing" in log_data["title"] else "Downloading"

        if action == "Downloading":
            # Search for percentage (e.g. 45%)
            for line in reversed(history):
                match = re.search(r'(\d+)%', line)
                if match:
                    return f"{match.group(1)}%"
        else:
            # FFmpeg: time=00:00:00.00
            book = self._library_lookup.get(asin)
            total_ms = book.duration_ms if book else 0

            for line in reversed(history):
                match = re.search(r'time=(\d+):(\d+):(\d+)\.(\d+)', line)
                if match and total_ms > 0:
                    h, m, s, ms = map(int, match.groups())
                    current_ms = (h * 3600 + m * 60 + s) * 1000 + ms * 10
                    percent = (current_ms / total_ms) * 100
                    return f"{min(99, int(percent))}%"
        return ""

    def action_show_queue(self) -> None:
        """Switches to the Queue tab."""
        try:
            self.query_one(TabbedContent).active = "queue-tab"
        except Exception:
            pass

    def action_general_settings(self) -> None:
        """Opens the general settings modal."""
        def save_settings(results: dict | None) -> None:
            if results:
                self.config.update(results)
                self.notify("Automation settings updated.", severity="information")

        self.push_screen(GeneralSettingsModal(self.config._config), save_settings)

    def action_configure_columns(self) -> None:
        """Opens the column configuration modal."""
        all_cols = ["Status", "ASIN", "Author", "Title", "Narrator", "Series", "Year"]
        visible = self.config.get("visible_columns", ["Status", "ASIN", "Author", "Title", "Series"])

        def save_columns(new_visible: list[str] | None) -> None:
            if new_visible is not None:
                self.config.set("visible_columns", new_visible)
                self.rebuild_table_columns()
                self.apply_filter(self.search_query)
                self.notify("Library columns updated.", severity="information")

        self.push_screen(ColumnSettingsModal(all_cols, visible), save_columns)

    def action_set_library_path(self) -> None:
        """Prompts the user to set the library path."""
        def check_path(path_val: str | None) -> None:
            if path_val:
                p = Path(path_val.strip()).expanduser().resolve()
                if not p.exists():
                    try:
                        p.mkdir(parents=True, exist_ok=True)
                        self.notify(f"Created directory: {p}", severity="information")
                    except Exception as e:
                        self.notify(f"Could not create directory: {e}", severity="error")
                        return

                self.config.set("library_path", str(p))
                self.notify(f"Library path updated to: {p}", severity="information")
                logger.info(f"Library path updated: {p}")
                self.refresh_all_statuses()

        self.push_screen(LibraryPathModal(self.config.get("library_path", str(Path.cwd()))), check_path)

    def action_cursor_down(self) -> None:
        self.query_one("#library_table").action_cursor_down()

    def action_cursor_up(self) -> None:
        self.query_one("#library_table").action_cursor_up()

    def action_cursor_left(self) -> None:
        self.query_one("#library_table").action_cursor_left()

    def action_cursor_right(self) -> None:
        self.query_one("#library_table").action_cursor_right()

    def action_page_down(self) -> None:
        self.query_one("#library_table").action_page_down()

    def action_page_up(self) -> None:
        self.query_one("#library_table").action_page_up()

    def action_scroll_top(self) -> None:
        self.query_one("#library_table").action_scroll_top()

    def action_scroll_bottom(self) -> None:
        self.query_one("#library_table").action_scroll_bottom()

    def action_focus_search(self) -> None:
        try:
            self.query_one(TabbedContent).active = "library-tab"
            search_input = self.query_one("#search_input")
            search_input.display = True
            search_input.focus()
        except Exception:
            pass

    def action_quit(self) -> None:
        self.exit()

    def action_set_activation_bytes(self) -> None:
        """Prompts the user to enter their activation bytes."""
        def check_input(bytes_val: str | None) -> None:
            if bytes_val:
                self.config.set("activation_bytes", bytes_val.strip())
                self.notify("Activation bytes saved.", severity="information")
                logger.info(f"Activation bytes updated.")

        self.push_screen(ActivationBytesModal(self.config.get("activation_bytes", "")), check_input)

    def action_select_row(self) -> None:
        self.query_one("#library_table").action_select_cursor()

    def action_toggle_select(self) -> None:
        """Toggles selection on the highlighted row, or plays the book if it is already processed."""
        table = self.query_one("#library_table", LibraryTable)
        if table.cursor_row is None or table.cursor_row < 0 or table.cursor_row >= len(table.rows):
            return
            
        row_key = list(table.rows.keys())[table.cursor_row]
        book_id = str(row_key.value)
        book = self._library_lookup.get(book_id)
        if not book:
            return
            
        # Check if the book is already processed (✔)
        status = self.service.get_status(book_id, book.title)
        if "✔" in status:
            # Play the book
            success, error = self.service.play_audiobook(book)
            if success:
                self.notify(f"Opening '{book.title}'...", severity="information")
                logger.info(f"Opened [bold green]'{book.title}'[/] in default player.")
            else:
                self.notify(f"Could not open file: {error}", severity="error")
                logger.error(f"[bold red]Error opening[/] [bold green]'{book.title}'[/]: {error}")
            return
            
        # Toggle selection
        if book_id in self.selected_books:
            self.selected_books.remove(book_id)
            table.remove_row_class(row_key, "datatable--selected")
        else:
            self.selected_books.add(book_id)
            table.add_row_class(row_key, "datatable--selected")
            
        self.update_status_label()

    def update_status_label(self) -> None:
        """Updates the status label under the library table."""
        try:
            selected_count = len(self.selected_books)
            loaded_count = len(self.full_library)
            status_label = self.query_one("#library-status", Label)
            status_label.update(f"{selected_count} books selected | {loaded_count} books loaded")
        except Exception:
            pass

    def action_process_selected(self) -> None:
        """Queues all selected books for processing."""
        if not self.selected_books:
            self.notify("No books selected to process.", severity="warning")
            return

        table = self.query_one("#library_table", LibraryTable)
        queued_count = 0
        for asin in list(self.selected_books):
            book = self._library_lookup.get(asin)
            if not book:
                continue
            
            if book.queued or book.working_mode:
                continue
                
            status = self.service.get_status(asin, book.title)
            if "✔" in status:
                continue
                
            book.queued = True
            if "⬇" in status:
                book.working_mode = "queued_processing"
            else:
                book.working_mode = "queued_download"
                
            self.task_queue.put(asin)
            self.update_row_status(asin)
            queued_count += 1
            
        if queued_count > 0:
            self.notify(f"Added {queued_count} books to queue.", severity="information")
            logger.info(f"Queued {queued_count} books for background processing.")
        
        # Clear selected_books and reset highlights
        for asin in list(self.selected_books):
            try:
                table.remove_row_class(asin, "datatable--selected")
            except Exception:
                pass
        self.selected_books.clear()
        self.update_status_label()
        
        # Switch to Queue tab and update
        try:
            self.query_one(TabbedContent).active = "queue-tab"
            self.query_one("#queue-table").focus()
        except Exception:
            pass
        self.update_queue_table()

    def action_select_all(self) -> None:
        """Selects all currently visible audiobooks in the library table."""
        table = self.query_one("#library_table", LibraryTable)
        visible_asins = []
        for row_key in table.rows:
            visible_asins.append(str(row_key.value))
            
        for asin in visible_asins:
            book = self._library_lookup.get(asin)
            if book:
                status = self.service.get_status(asin, book.title)
                if "✔" in status:
                    continue
                self.selected_books.add(asin)
                try:
                    table.add_row_class(asin, "datatable--selected")
                except Exception:
                    pass
                
        self.update_status_label()
        table.refresh()

    def action_deselect_all(self) -> None:
        """Deselects all selected audiobooks."""
        table = self.query_one("#library_table", LibraryTable)
        for asin in list(self.selected_books):
            try:
                table.remove_row_class(asin, "datatable--selected")
            except Exception:
                pass
        self.selected_books.clear()
        self.update_status_label()
        table.refresh()

    def update_queue_table(self) -> None:
        """Updates the queue table in the Queue tab."""
        try:
            table = self.query_one("#queue-table", QueueTable)
        except Exception:
            return
            
        items = []
        # Active items
        for asin, log_data in self.active_logs.items():
            book = self._library_lookup.get(asin)
            progress = self._extract_progress(asin)
            items.append({
                "asin": asin,
                "title": book.title if book else "Unknown",
                "action": "Processing" if "Processing" in log_data["title"] else "Downloading",
                "progress": progress if progress else "..."
            })
            
        # Queued items
        queued_books = [b for b in self.full_library if b.queued]
        for book in queued_books:
            status = self.service.get_status(book.asin, book.title)
            action = "Download" if status == "" else "Process"
            items.append({
                "asin": book.asin,
                "title": book.title,
                "action": f"Queued ({action})",
                "progress": ""
            })
            
        # Save state
        scroll_x, scroll_y = table.scroll_offset
        cursor_coord = table.cursor_coordinate
        
        table.clear()
        
        for i, item in enumerate(items, 1):
            table.add_row(
                str(i),
                item.get("action", ""),
                item.get("progress", ""),
                item.get("title", ""),
                item.get("asin", ""),
                key=item.get("asin")
            )
            
        # Restore state
        table.scroll_to(x=scroll_x, y=scroll_y, animate=False)
        if cursor_coord and table.row_count > 0:
            try:
                table.move_cursor(row=min(cursor_coord.row, table.row_count - 1), column=cursor_coord.column)
            except Exception:
                pass

    def action_prev_tab(self) -> None:
        """Switch to previous tab in TabbedContent."""
        try:
            self.query_one(TabbedContent).query_one("Tabs").action_previous_tab()
        except Exception:
            pass

    def action_next_tab(self) -> None:
        """Switch to next tab in TabbedContent."""
        try:
            self.query_one(TabbedContent).query_one("Tabs").action_next_tab()
        except Exception:
            pass

    def action_remove_from_queue(self) -> None:
        """Removes the selected book from the background task queue."""
        try:
            tabbed_content = self.query_one(TabbedContent)
            active_tab = tabbed_content.active
        except Exception:
            active_tab = "library-tab"
            
        asin = None
        if active_tab == "queue-tab":
            try:
                table = self.query_one("#queue-table", QueueTable)
                if table.cursor_row is not None and table.cursor_row >= 0 and table.cursor_row < len(table.rows):
                    row_data = table.get_row_at(table.cursor_row)
                    if len(row_data) > 4:
                        asin = row_data[4]
            except Exception:
                pass
        else:
            try:
                table = self.query_one("#library_table", LibraryTable)
                if table.cursor_row is not None and table.cursor_row >= 0 and table.cursor_row < len(table.rows):
                    row_data = table.get_row_at(table.cursor_row)
                    asin_key = self.col_keys.get("ASIN")
                    if asin_key:
                        asin_idx = list(self.col_keys.values()).index(asin_key)
                        asin = row_data[asin_idx]
            except Exception:
                pass
                
        if not asin:
            return

        # Find the book
        book = self._library_lookup.get(asin)
        if not book or not book.queued:
            self.notify("This book is not in the queue.", severity="warning")
            return

        if self.task_queue.remove(asin):
            book.queued = False
            book.working_mode = ""
            self.update_row_status(asin)
            self.update_queue_table()
            self.notify(f"Removed '{book.title}' from queue.", severity="information")
            logger.info(f"Removed [bold cyan]{asin}[/] from task queue.")
        else:
            self.notify("Could not remove from queue.", severity="error")

    def action_toggle_log(self) -> None:
        try:
            log = self.query_one("#log")
            log.display = not log.display
            self.config.set("log_visible", log.display)
        except Exception as e:
            logger.error(f"Error toggling log: {e}")

    def prompt_cleanup(self, asin: str, title: str) -> None:
        """Prompts the user to delete source files."""
        msg = f"Conversion complete for '{title}'. Would you like to delete the source files (AAX, JSON, JPG)?"
        self.push_screen(ConfirmModal(msg), lambda result: self.handle_cleanup_response(result, asin, title))

    def handle_cleanup_response(self, delete: bool, asin: str, title: str) -> None:
        if delete:
            self.delete_source_files(asin, title)

    def delete_source_files(self, asin: str, title: str) -> None:
        """Deletes original files after conversion."""
        book = self._library_lookup.get(asin)
        if not book:
            book = Audiobook(asin=asin, author="Unknown", title=title)

        count = self.service.cleanup_sources(book, logger.info)

        if count > 0:
            logger.info(f"Cleaned up [bold cyan]{count}[/] source files for [bold green]'{title}'[/].")
            self.notify(f"Source files deleted for {title}", severity="information")
            self.refresh_all_statuses()

    @work
    async def action_refresh_library(self) -> None:
        logger.info("Fetching library...")
        try:
            self.full_library = await self.service.fetch_library()
            self._library_lookup = {b.asin: b for b in self.full_library}
            self.apply_filter(self.search_query)
            logger.info(f"Library refreshed ([bold cyan]{len(self.full_library)}[/] items).")
        except Exception as e:
            logger.error(f"Error fetching library: {e}")

    def on_descendant_focus(self, event: events.DescendantFocus) -> None:
        """Triggers search visibility update whenever focus changes."""
        if isinstance(event.widget, SearchInput):
            event.widget.display = True

    def on_descendant_blur(self, event: events.DescendantBlur) -> None:
        """Triggers search visibility update whenever focus changes."""
        if isinstance(event.widget, SearchInput):
            event.widget.display = len(event.widget.value) > 0

    @on(Input.Changed, "#search_input")
    def on_search_changed(self, event: Input.Changed) -> None:
        """Debounced search to improve performance."""
        # Using a timer to delay search until user stops typing
        if hasattr(self, "_search_timer"):
            self._search_timer.stop()

        # 300ms delay is usually a good balance
        self._search_timer = self.set_timer(0.3, lambda: setattr(self, "search_query", event.value))

    def watch_search_query(self, value: str) -> None:
        """Automatically called when search_query changes."""
        self.apply_filter(value)

    @on(Input.Submitted, "#search_input")
    def on_search_submitted(self) -> None:
        """Returns focus to the library when Enter is pressed in search."""
        self.query_one("#library_table").focus()

    @on(TabbedContent.TabActivated)
    def on_tab_activated(self, event: TabbedContent.TabActivated) -> None:
        """Ensures that the appropriate table is focused when switching tabs."""
        try:
            if event.tab.id == "library-tab":
                self.query_one("#library_table").focus()
            elif event.tab.id == "queue-tab":
                self.query_one("#queue-table").focus()
        except Exception:
            pass

    def apply_filter(self, filter_text: str) -> None:
        table = self.query_one("#library_table", LibraryTable)
        table.clear()
        filter_text = filter_text.lower()

        # Filter using pre-calculated search text
        filtered_books = [
            book for book in self.full_library 
            if filter_text in book._search_text
        ]

        # Multi-level sort helper
        def get_sort_key(book: Audiobook):
            keys = []
            for col in self.sort_order:
                if col == "series_title":
                    keys.append(book.series_title.lower())
                    keys.append(book._series_seq_num)
                else:
                    keys.append(str(getattr(book, col, "")).lower())
            return tuple(keys)

        # Sort
        filtered_books.sort(key=get_sort_key, reverse=self.sort_reverse)

        visible = self.config.get("visible_columns", ["Status", "ASIN", "Author", "Title", "Series"])
        for book in filtered_books:
            row_data = []
            for col in visible:
                if col == "Status":
                    row_data.append(self._get_status_display(book))
                elif col == "ASIN":
                    row_data.append(book.asin)
                elif col == "Author":
                    authors = book.author.split(", ")
                    if len(authors) > 2:
                        row_data.append(", ".join(authors[:2]) + ", ...")
                    else:
                        row_data.append(book.author)
                elif col == "Title":
                    row_data.append(book.title)
                elif col == "Narrator":
                    narrators = book.narrator.split(", ")
                    if len(narrators) > 2:
                        row_data.append(", ".join(narrators[:2]) + ", ...")
                    else:
                        row_data.append(book.narrator)
                elif col == "Series":
                    display = book.series_title
                    if display and book.series_sequence:
                        display = f"{display} ({book.series_sequence})"
                    row_data.append(display)
                elif col == "Year":
                    row_data.append(book.year)

            table.add_row(*row_data, key=book.asin)

        # Re-apply selected class for selected books
        for row_key in table.rows:
            asin = str(row_key.value)
            if asin in self.selected_books:
                try:
                    table.add_row_class(row_key, "datatable--selected")
                except Exception:
                    pass

        self.update_status_label()

    def update_row_status(self, asin: str) -> None:
        """Updates the status symbol for a specific ASIN in the table."""
        try:
            table = self.query_one("#library_table", LibraryTable)
            status_key = self.col_keys.get("Status")
            asin_key = self.col_keys.get("ASIN")
            if not status_key or not asin_key:
                return

            asin_idx = list(self.col_keys.values()).index(asin_key)

            found = False
            for row_key in table.rows:
                row_data = table.get_row(row_key)
                if str(row_data[asin_idx]) == str(asin):
                    # Find Title index
                    title_idx = 0
                    if "Title" in self.col_keys:
                        title_idx = list(self.col_keys.values()).index(self.col_keys["Title"])

                    title = row_data[title_idx]

                    # Find the book in full_library to check working state
                    book = self._library_lookup.get(asin)
                    new_status = self.service.get_status(asin, title)
                    if book:
                        book.status = new_status
                        display_status = self._get_status_display(book)
                    else:
                        # Fallback padding if book not found (unlikely)
                        display_status = f"  {new_status}  " if new_status else "     "

                    table.update_cell(row_key, status_key, display_status, update_width=False)
                    found = True
                    break

            if not found:
                # If not in table, still update full_library
                book = self._library_lookup.get(asin)
                if book:
                    book.status = self.service.get_status(asin, book.title)
        except Exception as e:
            logger.error(f"Error updating row: {e}")

    @work
    async def refresh_all_statuses(self) -> None:
        """Updates status for all visible rows in a worker thread."""
        try:
            # Use the efficient batch status checker
            status_map = self.service.get_status_map(self.full_library)

            table = self.query_one("#library_table", LibraryTable)
            status_key = self.col_keys.get("Status")
            asin_key = self.col_keys.get("ASIN")
            if not status_key or not asin_key:
                return

            asin_idx = list(self.col_keys.values()).index(asin_key)

            for row_key in table.rows:
                row_data = table.get_row(row_key)
                asin = row_data[asin_idx]
                new_status = status_map.get(asin, "")

                # Sync with full_library using cached lookup
                book = self._library_lookup.get(asin)
                if book:
                    book.status = new_status
                    display = self._get_status_display(book)
                    table.update_cell(row_key, status_key, display)

            table.refresh()
        except Exception as e:
            logger.error(f"Error refreshing statuses: {e}")

    @on(DataTable.RowSelected, "#library_table")
    def on_row_selected(self, event: DataTable.RowSelected) -> None:
        row_data = event.data_table.get_row_at(event.cursor_row)

        asin_key = self.col_keys.get("ASIN")
        if not asin_key:
            return
        asin_idx = list(self.col_keys.values()).index(asin_key)
        asin = row_data[asin_idx]

        # If the book is already working, show its output screen
        if asin in self.active_logs:
            log_data = self.active_logs[asin]
            self.push_screen(ProcessOutputScreen(log_data["title"], asin, log_data["history"]))
            return

        self.action_toggle_select()

    @on(DataTable.RowSelected, "#queue-table")
    def on_queue_row_selected(self, event: DataTable.RowSelected) -> None:
        row_data = event.data_table.get_row_at(event.cursor_row)
        if len(row_data) > 4:
            asin = row_data[4]
            if asin in self.active_logs:
                log_data = self.active_logs[asin]
                self.push_screen(ProcessOutputScreen(log_data["title"], asin, log_data["history"]))

    async def download_book(self, asin: str) -> None:
        book = self._library_lookup.get(asin)
        if book:
            book.working_mode = "downloading"
            self.update_row_status(asin)

        logger.info(f"Starting download for [bold cyan]{asin}[/]...")
        self.active_logs[asin] = {
            "title": f"Downloading {asin}",
            "history": []
        }

        def log_handler(msg: str) -> None:
            if asin in self.active_logs:
                self.active_logs[asin]["history"].append(msg)
            # Propagate to visible screen if it's the right one
            if isinstance(self.screen, ProcessOutputScreen) and self.screen.asin == asin:
                self.screen.append_log(msg)

        try:
            res = await self.service.download(asin, log_handler)
            if res == 0:
                logger.info(f"Download of [bold cyan]{asin}[/] complete.")
                log_handler("\n[bold green]Download Complete![/]")
                lib = self.service.library_path
                await self.service.verify_file_exists(lib / f"{asin}*.aax")

                if self.config.get("auto_process", False):
                    # Find the book again to get title
                    book = self._library_lookup.get(asin)
                    if book:
                        await self.process_book(asin, book.title)
            else:

                logger.error(f"[bold red]Download of [/][bold cyan]{asin}[/] [bold red]failed with code {res}[/]")
                log_handler(f"\n[bold red]Failed with code {res}[/]")
        finally:
            if book:
                book.working_mode = ""
            self.active_logs.pop(asin, None)
            self.update_row_status(asin)

    async def process_book(self, asin: str, title: str) -> None:
        # Find the book in full_library
        book = self._library_lookup.get(asin)
        if not book:
            # Create a temporary one if not found (shouldn't happen)
            book = Audiobook(asin=asin, author="Unknown", title=title)

        book.working_mode = "processing"
        self.update_row_status(asin)

        logger.info(f"Processing [bold cyan]{asin}[/]...")
        self.active_logs[asin] = {
            "title": f"Processing {title}",
            "history": []
        }

        def log_handler(msg: str):
            if asin in self.active_logs:
                self.active_logs[asin]["history"].append(msg)

            # Propagate to visible screen if it's the right one
            if isinstance(self.screen, ProcessOutputScreen) and self.screen.asin == asin:
                self.screen.append_log(msg)

            # Only log errors or major milestones to the status log (and thus the file)
            if "error" in msg.lower() or "failed" in msg.lower() or "successfully" in msg.lower() or "Prepared" in msg:
                 logger.info(msg)

        try:
            success = await self.service.process_m4b(book, log_handler)
            if success:
                logger.info(f"M4B created successfully for {title}")

                # Verify file renamed successfully before refreshing
                lib = self.service.library_path
                await self.service.verify_file_exists(lib / f"{book.safe_title}.m4b")

                if self.config.get("auto_cleanup", False):
                    self.delete_source_files(asin, title)
                else:
                    self.prompt_cleanup(asin, title)
            else:
                logger.error(f"Processing failed for {title}")
        finally:
            book.working_mode = ""
            self.active_logs.pop(asin, None)
            self.update_row_status(asin)

    @work
    async def check_authentication(self) -> None:
        """Verifies if the user is authenticated with audible-cli."""
        if await self.service.is_authenticated():
            logger.info("[bold green]Audible authentication verified.[/]")
        else:
            self.notify("Audible-cli not authenticated. Please run 'audible login'.", severity="error")
            logger.error("[bold red]Audible-cli not authenticated.[/]")
            logger.info("Please run [bold cyan]'audible login'[/] in your terminal.")

async def run_cli(args):
    import sys
    from rich.console import Console
    from rich.table import Table
    console = Console()
    
    # Load config
    config_manager = ConfigManager()
    config = config_manager._config
    
    # Apply overrides
    if args.library_path:
        config["library_path"] = args.library_path
    if args.activation_bytes:
        config["activation_bytes"] = args.activation_bytes
        
    service = AudiobookService(config)
    
    # Check library directory
    lib_path = Path(service.library_path)
    if not lib_path.exists():
        try:
            lib_path.mkdir(parents=True, exist_ok=True)
            console.print(f"[green]Created library directory:[/] {lib_path}")
        except Exception as e:
            console.print(f"[bold red]Error:[/] Library directory '{lib_path}' does not exist and could not be created: {e}")
            sys.exit(1)
            
    if args.subcommand == "list":
        if not await service.is_authenticated():
            console.print("[bold red]Error:[/] Audible-cli not authenticated. Please run 'audible login' first.")
            sys.exit(1)
            
        console.print("[yellow]Fetching library from Audible...[/]")
        try:
            books = await service.fetch_library()
        except Exception as e:
            console.print(f"[bold red]Error fetching library:[/] {e}")
            sys.exit(1)
            
        filtered_books = []
        for book in books:
            # Query filter
            if args.query:
                q = args.query.lower()
                matches = (
                    q in book.title.lower() or 
                    q in book.author.lower() or 
                    q in book.asin.lower() or 
                    (book.series_title and q in book.series_title.lower()) or
                    (book.narrator and q in book.narrator.lower())
                )
                if not matches:
                    continue
            
            # Status filter
            if args.status:
                s = args.status.lower()
                is_match = False
                if s == "processed":
                    is_match = "[bold green]" in book.status
                elif s == "downloaded":
                    is_match = "[bold yellow]" in book.status
                elif s == "missing":
                    is_match = book.status == ""
                if not is_match:
                    continue
                    
            filtered_books.append(book)
            
        if not filtered_books:
            console.print("[yellow]No books found matching the filters.[/]")
            return
            
        table = Table(title="Audible Library")
        table.add_column("Status", width=12, justify="center")
        table.add_column("ASIN", width=12)
        table.add_column("Title", style="cyan")
        table.add_column("Author", style="magenta")
        table.add_column("Series", style="dim")
        table.add_column("Year", justify="right")
        
        for book in filtered_books:
            # Format status nicely for table
            if "[bold green]" in book.status:
                status_display = "[green]Processed[/]"
            elif "[bold yellow]" in book.status:
                status_display = "[yellow]Downloaded[/]"
            else:
                status_display = "[dim]Missing[/]"
                
            series_display = f"{book.series_title} #{book.series_sequence}" if book.series_title else "-"
            table.add_row(
                status_display,
                book.asin,
                book.title,
                book.author,
                series_display,
                book.year if book.year else "-"
            )
        console.print(table)
        
    elif args.subcommand == "download":
        if not await service.is_authenticated():
            console.print("[bold red]Error:[/] Audible-cli not authenticated. Please run 'audible login' first.")
            sys.exit(1)
            
        if args.auto_process and not service.activation_bytes:
            console.print("[bold red]Error:[/] Activation bytes are not configured. Use -a <bytes> or configure them in the GUI.")
            sys.exit(1)

        console.print("[yellow]Fetching library details...[/]")
        try:
            books = await service.fetch_library()
            library_map = {b.asin: b for b in books}
        except Exception as e:
            console.print(f"[bold red]Error fetching library:[/] {e}")
            sys.exit(1)

        for asin in args.asins:
            book = library_map.get(asin)
            if not book:
                console.print(f"[bold red]Error:[/] Book with ASIN '{asin}' was not found in your Audible library.")
                continue
                
            console.print(f"\n[bold cyan]Downloading: {book.title} ({asin})[/]")
            res = await service.download(asin, lambda msg: console.print(f"  {msg}"))
            
            if res == 0:
                console.print(f"[bold green]Successfully downloaded: {book.title}[/]")
                await service.verify_file_exists(service.library_path / f"{asin}*.aax")
                
                if args.auto_process:
                    console.print(f"[bold cyan]Processing: {book.title} ({asin})[/]")
                    success = await service.process_m4b(book, lambda msg: console.print(f"  {msg}"))
                    if success:
                        console.print(f"[bold green]Successfully processed to M4B: {book.title}[/]")
                        if args.auto_cleanup:
                            console.print(f"[yellow]Cleaning up source files...[/]")
                            count = service.cleanup_sources(book, lambda msg: console.print(f"  {msg}"))
                            console.print(f"[green]Cleaned up {count} source files.[/]")
                    else:
                        console.print(f"[bold red]Failed to process: {book.title}[/]")
            else:
                console.print(f"[bold red]Failed to download ASIN {asin} with exit code {res}.[/]")
                
    elif args.subcommand == "process":
        if not service.activation_bytes:
            console.print("[bold red]Error:[/] Activation bytes are not configured. Use -a <bytes> or configure them in the GUI.")
            sys.exit(1)
            
        console.print("[yellow]Fetching library details...[/]")
        try:
            books = await service.fetch_library()
            library_map = {b.asin: b for b in books}
        except Exception as e:
            console.print(f"[bold red]Error fetching library:[/] {e}")
            sys.exit(1)
            
        for asin in args.asins:
            book = library_map.get(asin)
            if not book:
                console.print(f"[bold red]Error:[/] Book with ASIN '{asin}' was not found in your Audible library.")
                continue
                
            console.print(f"\n[bold cyan]Processing: {book.title} ({asin})[/]")
            success = await service.process_m4b(book, lambda msg: console.print(f"  {msg}"))
            if success:
                console.print(f"[bold green]Successfully processed to M4B: {book.title}[/]")
                
                should_cleanup = config.get("auto_cleanup", False)
                if args.cleanup:
                    should_cleanup = True
                elif args.no_cleanup:
                    should_cleanup = False
                    
                if should_cleanup:
                    console.print(f"[yellow]Cleaning up source files...[/]")
                    count = service.cleanup_sources(book, lambda msg: console.print(f"  {msg}"))
                    console.print(f"[green]Cleaned up {count} source files.[/]")
            else:
                console.print(f"[bold red]Failed to process: {book.title}[/]")
                
    elif args.subcommand == "sync":
        if not await service.is_authenticated():
            console.print("[bold red]Error:[/] Audible-cli not authenticated. Please run 'audible login' first.")
            sys.exit(1)
            
        if not service.activation_bytes:
            console.print("[bold red]Error:[/] Activation bytes are not configured. Use -a <bytes> or configure them in the GUI.")
            sys.exit(1)

        console.print("[yellow]Fetching library details...[/]")
        try:
            books = await service.fetch_library()
            library_map = {b.asin: b for b in books}
        except Exception as e:
            console.print(f"[bold red]Error fetching library:[/] {e}")
            sys.exit(1)

        for asin in args.asins:
            book = library_map.get(asin)
            if not book:
                console.print(f"[bold red]Error:[/] Book with ASIN '{asin}' was not found in your Audible library.")
                continue
                
            console.print(f"\n[bold cyan]Downloading: {book.title} ({asin})[/]")
            res = await service.download(asin, lambda msg: console.print(f"  {msg}"))
            
            if res == 0:
                console.print(f"[bold green]Successfully downloaded: {book.title}[/]")
                await service.verify_file_exists(service.library_path / f"{asin}*.aax")
                
                console.print(f"[bold cyan]Processing: {book.title} ({asin})[/]")
                success = await service.process_m4b(book, lambda msg: console.print(f"  {msg}"))
                if success:
                    console.print(f"[bold green]Successfully processed to M4B: {book.title}[/]")
                    if args.cleanup or config.get("auto_cleanup", False):
                        console.print(f"[yellow]Cleaning up source files...[/]")
                        count = service.cleanup_sources(book, lambda msg: console.print(f"  {msg}"))
                        console.print(f"[green]Cleaned up {count} source files.[/]")
                else:
                    console.print(f"[bold red]Failed to process: {book.title}[/]")
            else:
                console.print(f"[bold red]Failed to download ASIN {asin} with exit code {res}.[/]")

def main():
    parser = argparse.ArgumentParser(
        description="Audiobook Manager CLI & TUI",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    # Global options
    parser.add_argument("-l", "--library-path", help="Override the library directory path")
    parser.add_argument("-a", "--activation-bytes", help="Override the 8-character Audible activation bytes")
    
    subparsers = parser.add_subparsers(dest="subcommand", help="CLI Subcommands (omitting launches the TUI)")
    
    # Subcommand: list
    list_parser = subparsers.add_parser("list", help="List audiobooks in your Audible library and their local status")
    list_parser.add_argument("-s", "--status", choices=["processed", "downloaded", "missing"], help="Filter by status (processed/downloaded/missing)")
    list_parser.add_argument("-q", "--query", help="Filter by search query (title, author, series, ASIN)")
    
    # Subcommand: download
    download_parser = subparsers.add_parser("download", help="Download audiobook(s) from Audible by ASIN")
    download_parser.add_argument("asins", nargs="+", help="One or more audiobook ASINs to download")
    download_parser.add_argument("--auto-process", action="store_true", help="Automatically process/convert the book after downloading")
    download_parser.add_argument("--auto-cleanup", action="store_true", help="Automatically delete source files after processing (if --auto-process is set)")
    
    # Subcommand: process
    process_parser = subparsers.add_parser("process", help="Process/convert downloaded AAX files to M4B by ASIN")
    process_parser.add_argument("asins", nargs="+", help="One or more audiobook ASINs to process")
    process_parser.add_argument("--cleanup", action="store_true", help="Automatically delete original AAX files after successful processing")
    process_parser.add_argument("--no-cleanup", action="store_true", help="Do not delete original AAX files after processing")
    
    # Subcommand: sync
    sync_parser = subparsers.add_parser("sync", help="Download and process/convert audiobook(s) by ASIN")
    sync_parser.add_argument("asins", nargs="+", help="One or more audiobook ASINs to sync")
    sync_parser.add_argument("--cleanup", action="store_true", help="Automatically delete original AAX files after successful processing")

    args = parser.parse_args()
    
    if args.subcommand is None:
        app = AudiobookManager()
        app.run()
    else:
        try:
            asyncio.run(run_cli(args))
        except KeyboardInterrupt:
            print("\nOperation cancelled by user.")
            sys.exit(130)

if __name__ == "__main__":
    main()
