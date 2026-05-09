# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "textual",
#     "platformdirs",
#     "pytest",
# ]
# ///

import json
import shutil
import re
import asyncio
from typing import List, Dict, Iterable
from pathlib import Path

from platformdirs import user_config_dir
from textual.app import App, ComposeResult, SystemCommand
from textual.binding import Binding
from textual.widgets import Header, Footer, DataTable, Input, Log
from textual import work, on, events
from textual.reactive import reactive
from textual.screen import Screen

from models import Audiobook
from service import AudiobookService
from ui.widgets import LibraryTable, SearchInput, StatusLog
from ui.screens import ProcessOutputScreen, ConfirmModal, ActivationBytesModal, LibraryPathModal, ColumnSettingsModal, GeneralSettingsModal, QueueViewerModal

# Configuration
APP_NAME = "audiobook-manager"
CONFIG_DIR = Path(user_config_dir(APP_NAME))
CONFIG_FILE = CONFIG_DIR / "config.json"
LOG_FILE = CONFIG_DIR / "activity.log"
OLD_CONFIG_FILE = Path(__file__).parent / "audiobook_config.json"

SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

def load_config() -> Dict:
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
                return data
        except Exception:
            pass
    return {
        "theme": "tokyo-night", 
        "log_visible": True,
        "activation_bytes": "",
        "library_path": str(Path.cwd()),
        "sort_order": ["title", "author", "asin"],
        "sort_reverse": False,
        "visible_columns": ["Status", "ASIN", "Author", "Title", "Narrator", "Series", "Year"],
        "auto_cleanup": False,
        "auto_process": False
    }

def save_config(config: Dict):
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        with open(CONFIG_FILE, "w") as f:
            json.dump(config, f, indent=4)
        return True
    except Exception as e:
        return str(e)

class AudiobookManager(App):
    CSS = """
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
    """

    TITLE = "Audiobook Manager"
    COMMAND_PALETTE_BINDING = ":"

    BINDINGS = [
        Binding(":", "command_palette", "Command"),
        Binding("q", "quit", "Quit"),
    ]

    search_query = reactive("")

    def __init__(self):
        super().__init__()
        self.config = load_config()
        self.service = AudiobookService(self.config)
        self.full_library: List[Audiobook] = []
        self.active_logs: Dict[str, Dict] = {}
        self.task_queue = asyncio.Queue()
        self.col_keys = {}
        self.sort_order = self.config.get("sort_order", ["title", "author", "asin"])
        self.sort_reverse = self.config.get("sort_reverse", False)


    def watch_theme(self, theme: str) -> None:
        """Saves the theme to config whenever it changes."""
        if hasattr(self, "config"):
            if self.config.get("theme") != theme:
                self.config["theme"] = theme
                res = save_config(self.config)
                if res is not True:
                    self.log_message(f"Failed to save theme: {res}")
                else:
                    self.log_message(f"Theme saved: {theme}")

    def compose(self) -> ComposeResult:
        yield Header()
        yield SearchInput(placeholder="Filter library (ASIN, Author, or Title)...", id="search_input")
        yield LibraryTable(id="library_table")
        yield StatusLog(id="log", markup=True, highlight=True)
        yield Footer()

    def on_mount(self) -> None:
        # Check dependencies
        missing = []
        if not shutil.which("ffmpeg"):
            missing.append("ffmpeg")
        if not shutil.which("audible"):
            missing.append("audible-cli")
        
        if missing:
            self.notify(f"Missing dependencies: {', '.join(missing)}. Some features will not work.", severity="error")
            self.log_message(f"[bold red]ERROR: Missing dependencies: {', '.join(missing)}[/]")
            self.log_message("Please install them and restart the application.")

        # Check authentication
        self.check_authentication()

        # Apply the saved theme from config
        saved_theme = self.config.get("theme", "tokyo-night")
        if saved_theme == "dark":
            saved_theme = "tokyo-night"

        self.theme = saved_theme

        # Restore log visibility
        log = self.query_one("#log")
        log.display = self.config.get("log_visible", True)

        # If config didn't exist, create it now
        if not CONFIG_FILE.exists():
            save_config(self.config)

        self.rebuild_table_columns()

        self.action_refresh_library()
        
        # Start background workers
        self.set_interval(0.1, self.animate_spinners)
        self.process_queue()

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
            book = next((b for b in self.full_library if b.asin == asin), None)
            if not book:
                self.task_queue.task_done()
                continue
            
            book.queued = False
            title = book.title
            status = self.service.get_status(asin, title)

            if status == "": # Needs download
                await self.download_book(asin)
            elif "⬇" in status: # Needs processing
                await self.process_book(asin, title)
            
            self.task_queue.task_done()

    def _get_status_display(self, book: Audiobook) -> str:
        """Generates an ultra-compact (3 char) status string using symbols."""
        frame = SPINNER_FRAMES[book.spinner_frame]
        
        if book.working_mode == "downloading":
            return f" [blue]{frame}[/][bold blue]⬇[/]"
        elif book.working_mode == "processing":
            return f" [cyan]{frame}[/][bold cyan]⚙[/]"
        elif book.working_mode == "queued_download":
            return " [bold yellow]⬇[/] "
        elif book.working_mode == "queued_processing":
            return " [bold yellow]⚙[/] "
        elif book.working_mode == "queued": # Fallback
            return " ⏳ "
        
        # Static statuses
        if "✔" in book.status:
            return " [bold green]✔[/] "
        elif "⬇" in book.status:
            return " [bold green]⬇[/] "
        elif "⚙" in book.status:
            return " [bold yellow]⚙[/] "
            
        return "   "

    def animate_spinners(self) -> None:
        """Updates the spinner frame for all working books."""
        updated = False
        table = self.query_one("#library_table", LibraryTable)
        status_key = self.col_keys.get("Status")
        if not status_key:
            return

        asin_key = self.col_keys.get("ASIN")
        if not asin_key:
            return

        asin_idx = list(self.col_keys.values()).index(asin_key)
        
        for row_key in table.rows:
            row_data = table.get_row(row_key)
            asin = row_data[asin_idx]
            
            # Find the book in our full library
            book = next((b for b in self.full_library if b.asin == asin), None)
            if book and book.working_mode in ["downloading", "processing"]:
                book.spinner_frame = (book.spinner_frame + 1) % len(SPINNER_FRAMES)
                table.update_cell(row_key, status_key, self._get_status_display(book))
                updated = True
        
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
        self.config["sort_order"] = self.sort_order
        self.config["sort_reverse"] = self.sort_reverse
        save_config(self.config)

        self.log_message(f"Sorting by {target_label} ({'descending' if self.sort_reverse else 'ascending'})")
        
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
            "View all pending and active tasks",
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
            book = next((b for b in self.full_library if b.asin == asin), None)
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
        """Shows the current task queue in a modal."""
        self.push_screen(QueueViewerModal(self))

    def action_general_settings(self) -> None:
        """Opens the general settings modal."""
        def save_settings(results: dict | None) -> None:
            if results:
                self.config.update(results)
                save_config(self.config)
                self.notify("Automation settings updated.", severity="information")

        self.push_screen(GeneralSettingsModal(self.config), save_settings)

    def action_configure_columns(self) -> None:
        """Opens the column configuration modal."""
        all_cols = ["Status", "ASIN", "Author", "Title", "Narrator", "Series", "Year"]
        visible = self.config.get("visible_columns", ["Status", "ASIN", "Author", "Title", "Series"])
        
        def save_columns(new_visible: list[str] | None) -> None:
            if new_visible is not None:
                self.config["visible_columns"] = new_visible
                save_config(self.config)
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

                self.config["library_path"] = str(p)
                save_config(self.config)
                self.notify(f"Library path updated to: {p}", severity="information")
                self.log_message(f"Library path updated: {p}")
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
        self.query_one("#search_input").focus()

    def action_quit(self) -> None:
        self.exit()

    def action_set_activation_bytes(self) -> None:
        """Prompts the user to enter their activation bytes."""
        def check_input(bytes_val: str | None) -> None:
            if bytes_val:
                self.config["activation_bytes"] = bytes_val.strip()
                save_config(self.config)
                self.notify("Activation bytes saved.", severity="information")
                self.log_message(f"Activation bytes updated.")

        self.push_screen(ActivationBytesModal(self.config.get("activation_bytes", "")), check_input)

    def action_select_row(self) -> None:
        self.query_one("#library_table").action_select_cursor()

    def action_remove_from_queue(self) -> None:
        """Removes the selected book from the background task queue."""
        table = self.query_one("#library_table", LibraryTable)
        if table.cursor_row < 0:
            return

        row_data = table.get_row_at(table.cursor_row)
        asin_key = self.col_keys.get("ASIN")
        if not asin_key:
            return
        asin_idx = list(self.col_keys.values()).index(asin_key)
        asin = row_data[asin_idx]

        # Find the book
        book = next((b for b in self.full_library if b.asin == asin), None)
        if not book or not book.queued:
            self.notify("This book is not in the queue.", severity="warning")
            return

        # Rebuild the queue to remove the item
        # Since asyncio.Queue doesn't support removal, we drain and refill
        temp_items = []
        while not self.task_queue.empty():
            item = self.task_queue.get_nowait()
            if item != asin:
                temp_items.append(item)
            self.task_queue.task_done()

        for item in temp_items:
            self.task_queue.put_nowait(item)

        book.queued = False
        book.working_mode = ""
        self.update_row_status(asin)
        self.notify(f"Removed '{book.title}' from queue.", severity="information")
        self.log_message(f"Removed {asin} from task queue.")

    def action_toggle_log(self) -> None:
        try:
            log = self.query_one("#log")
            log.display = not log.display
            self.config["log_visible"] = log.display
            save_config(self.config)
        except Exception as e:
            self.log_message(f"Error toggling log: {e}")

    def prompt_cleanup(self, asin: str, title: str) -> None:
        """Prompts the user to delete source files."""
        msg = f"Conversion complete for '{title}'. Would you like to delete the source files (AAX, JSON, JPG)?"
        self.push_screen(ConfirmModal(msg), lambda result: self.handle_cleanup_response(result, asin, title))

    def handle_cleanup_response(self, delete: bool, asin: str, title: str) -> None:
        if delete:
            self.delete_source_files(asin, title)

    def delete_source_files(self, asin: str, title: str) -> None:
        """Deletes original files after conversion."""
        book = next((b for b in self.full_library if b.asin == asin), None)
        if not book:
            book = Audiobook(asin=asin, author="Unknown", title=title)

        count = self.service.cleanup_sources(book, self.log_message)

        if count > 0:
            self.log_message(f"Cleaned up {count} source files for '{title}'.")
            self.notify(f"Source files deleted for {title}", severity="information")
            self.refresh_all_statuses()

    @work
    async def action_refresh_library(self) -> None:
        self.log_message("Fetching library...")
        try:
            self.full_library = await self.service.fetch_library()
            self.apply_filter(self.search_query)
            self.log_message(f"Library refreshed ({len(self.full_library)} items).")
        except Exception as e:
            self.log_message(f"Error fetching library: {e}")

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
        self.search_query = event.value

    def watch_search_query(self, value: str) -> None:
        """Automatically called when search_query changes."""
        self.apply_filter(value)

    @on(Input.Submitted, "#search_input")
    def on_search_submitted(self) -> None:
        """Returns focus to the library when Enter is pressed in search."""
        self.query_one("#library_table").focus()

    def apply_filter(self, filter_text: str) -> None:
        table = self.query_one("#library_table", LibraryTable)
        table.clear()
        filter_text = filter_text.lower()

        # Filter
        filtered_books = [
            book for book in self.full_library 
            if any(filter_text in str(getattr(book, field, "")).lower() for field in ["asin", "author", "title", "narrator", "series_title", "year"])
        ]

        # Multi-level sort helper
        def get_sort_key(book: Audiobook):
            keys = []
            for col in self.sort_order:
                val = str(getattr(book, col, "")).lower()
                if col == "series_title":
                    # Sort by series title, then numerically by sequence
                    try:
                        # Extract the first number found (handles 1-3, Book 1, etc.)
                        match = re.search(r'(\d+\.?\d*)', book.series_sequence)
                        seq = float(match.group(1)) if match else 0.0
                    except (ValueError, IndexError):
                        seq = 0.0
                    keys.append(val)
                    keys.append(seq)
                else:
                    keys.append(val)
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

    def log_message(self, message: str) -> None:
        self.query_one("#log", StatusLog).write(message)
        
        # Mirror to persistent log file
        try:
            import datetime
            timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            # Strip Rich markup for the plain text file
            clean_msg = re.sub(r'\[.*?\]', '', message)
            
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            with open(LOG_FILE, "a") as f:
                f.write(f"[{timestamp}] {clean_msg}\n")
        except Exception:
            pass

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
                    book = next((b for b in self.full_library if b.asin == asin), None)
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
                for book in self.full_library:
                    if book.asin == asin:
                        book.status = self.service.get_status(asin, book.title)
                        break
        except Exception as e:
            self.log_message(f"Error updating row: {e}")

    @work
    async def refresh_all_statuses(self) -> None:
        """Updates status for all visible rows in a worker thread."""
        try:
            # Pre-list directory for faster status checks
            lib = self.service.library_path
            file_set = {f.name for f in lib.iterdir()} if lib.exists() else set()

            # Create a lookup for full_library to fix O(N^2)
            library_lookup = {book.asin: book for book in self.full_library}
            
            table = self.query_one("#library_table", LibraryTable)
            status_key = self.col_keys.get("Status")
            asin_key = self.col_keys.get("ASIN")
            if not status_key or not asin_key:
                return

            asin_idx = list(self.col_keys.values()).index(asin_key)
            # Find Title index
            title_idx = 0
            if "Title" in self.col_keys:
                title_idx = list(self.col_keys.values()).index(self.col_keys["Title"])

            for row_key in table.rows:
                row_data = table.get_row(row_key)
                asin = row_data[asin_idx]
                title = row_data[title_idx]
                new_status = self.service.get_status(asin, title, file_set=file_set)
                
                # Sync with full_library
                book = library_lookup.get(asin)
                if book:
                    book.status = new_status
                    display = self._get_status_display(book)
                    table.update_cell(row_key, status_key, display)
            
            table.refresh()
        except Exception as e:
            self.log_message(f"Error refreshing statuses: {e}")

    @on(DataTable.RowSelected, "#library_table")
    def on_row_selected(self, event: DataTable.RowSelected) -> None:
        row_data = event.data_table.get_row_at(event.cursor_row)
        
        asin_key = self.col_keys.get("ASIN")
        if not asin_key:
            return
        asin_idx = list(self.col_keys.values()).index(asin_key)
        asin = row_data[asin_idx]
        
        # Find Title
        title = "Unknown"
        if "Title" in self.col_keys:
            title_idx = list(self.col_keys.values()).index(self.col_keys["Title"])
            title = row_data[title_idx]

        # If the book is already working, show its output screen
        if asin in self.active_logs:
            log_data = self.active_logs[asin]
            self.push_screen(ProcessOutputScreen(log_data["title"], asin, log_data["history"]))
            return

        # If already queued, do nothing
        book = next((b for b in self.full_library if b.asin == asin), None)
        if book and book.queued:
            self.notify(f"'{title}' is already in the queue.", severity="information")
            return

        status = self.service.get_status(asin, title)
        if "✔" in status:
            if book:
                success, error = self.service.play_audiobook(book)
                if success:
                    self.notify(f"Opening '{title}'...", severity="information")
                    self.log_message(f"Opened '{title}' in default player.")
                else:
                    self.notify(f"Could not open file: {error}", severity="error")
                    self.log_message(f"Error opening '{title}': {error}")
            return

        # Add to queue
        if book:
            book.queued = True
            if "⬇" in status:
                book.working_mode = "queued_processing"
            else:
                book.working_mode = "queued_download"
                
            self.task_queue.put_nowait(asin)
            self.update_row_status(asin)
            self.notify(f"Added '{title}' to queue.", severity="information")

    async def download_book(self, asin: str) -> None:
        book = next((b for b in self.full_library if b.asin == asin), None)
        if book:
            book.working = True
            book.working_mode = "downloading"
            self.update_row_status(asin)

        self.log_message(f"Starting download for {asin}...")
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
                self.log_message(f"Download of {asin} complete.")
                log_handler("\n[bold green]Download Complete![/]")
                lib = self.service.library_path
                await self.service.verify_file_exists(lib / f"{asin}*.aax")

                if self.config.get("auto_process", False):
                    # Find the book again to get title
                    book = next((b for b in self.full_library if b.asin == asin), None)
                    if book:
                        await self.process_book(asin, book.title)
            else:

                self.log_message(f"Download of {asin} failed with code {res}")
                log_handler(f"\n[bold red]Failed with code {res}[/]")
        finally:
            if book:
                book.working = False
                book.working_mode = ""
            self.active_logs.pop(asin, None)
            self.update_row_status(asin)

    async def process_book(self, asin: str, title: str) -> None:
        # Find the book in full_library
        book = next((b for b in self.full_library if b.asin == asin), None)
        if not book:
            # Create a temporary one if not found (shouldn't happen)
            book = Audiobook(asin=asin, author="Unknown", title=title)

        book.working = True
        book.working_mode = "processing"
        self.update_row_status(asin)

        self.log_message(f"Starting process for {asin}...")
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
                 self.log_message(msg)

        try:
            success = await self.service.process_m4b(book, log_handler)
            if success:
                self.log_message(f"[bold green]M4B created successfully for {title}[/]")
                
                # Verify file renamed successfully before refreshing
                lib = self.service.library_path
                await self.service.verify_file_exists(lib / f"{book.safe_title}.m4b")

                if self.config.get("auto_cleanup", False):
                    self.delete_source_files(asin, title)
                else:
                    self.prompt_cleanup(asin, title)
            else:
                self.log_message(f"[bold red]Processing failed for {title}[/]")
        finally:
            book.working = False
            book.working_mode = ""
            self.active_logs.pop(asin, None)
            self.update_row_status(asin)

    @work
    async def check_authentication(self) -> None:
        """Verifies if the user is authenticated with audible-cli."""
        if await self.service.is_authenticated():
            self.log_message("[bold green]Audible authentication verified.[/]")
        else:
            self.notify("Audible-cli not authenticated. Please run 'audible login'.", severity="error")
            self.log_message("[bold red]ERROR: Audible-cli not authenticated.[/]")
            self.log_message("Please run 'audible login' in your terminal.")

if __name__ == "__main__":
    app = AudiobookManager()
    app.run()
