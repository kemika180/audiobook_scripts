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
from ui.screens import ProcessOutputScreen, ConfirmModal, ActivationBytesModal, LibraryPathModal

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
                return data
        except Exception:
            pass
    return {
        "theme": "tokyo-night", 
        "log_visible": True,
        "activation_bytes": "",
        "library_path": str(Path.cwd()),
        "sort_column": "title",
        "sort_reverse": False
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
        Binding(":", "command_palette", "Palette"),
        Binding("q", "quit", "Quit"),
    ]

    search_query = reactive("")

    def __init__(self):
        super().__init__()
        self.config = load_config()
        self.service = AudiobookService(self.config)
        self.full_library: List[Audiobook] = []
        self.active_logs: Dict[str, Dict] = {}
        self.task_queue: asyncio.Queue[str] = asyncio.Queue()
        self.status_col_key = None
        self.asin_col_key = None
        self.author_col_key = None
        self.title_col_key = None
        self.sort_column = self.config.get("sort_column", "title")
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
        yield StatusLog(id="log")
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

        table = self.query_one("#library_table", LibraryTable)
        # Store column keys for later reliable updates
        keys = table.add_columns("", "ASIN", "Author", "Title")
        self.status_col_key = keys[0]
        self.asin_col_key = keys[1]
        self.author_col_key = keys[2]
        self.title_col_key = keys[3]

        table.cursor_type = "row"
        table.fixed_columns = 1
        table.focus()

        self.action_refresh_library()
        
        # Start background workers
        self.set_interval(0.1, self.animate_spinners)
        self.process_queue()

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

    def animate_spinners(self) -> None:
        """Updates the spinner frame for all working books."""
        updated = False
        table = self.query_one("#library_table", LibraryTable)
        
        for row_key in table.rows:
            row_data = table.get_row(row_key)
            asin = row_data[1]
            
            # Find the book in our full library
            book = next((b for b in self.full_library if b.asin == asin), None)
            if book and book.working:
                book.spinner_frame = (book.spinner_frame + 1) % len(SPINNER_FRAMES)
                frame = SPINNER_FRAMES[book.spinner_frame]
                table.update_cell(row_key, self.status_col_key, f"[bold blue]{frame}[/]")
                updated = True
        
        if updated:
            table.refresh()

    @on(DataTable.HeaderSelected, "#library_table")
    def on_header_click(self, event: DataTable.HeaderSelected) -> None:
        """Handle clicking on a column header to sort."""
        # Map column keys back to Audiobook attributes
        column_map = {
            self.asin_col_key: "asin",
            self.author_col_key: "author",
            self.title_col_key: "title",
        }
        
        target_col = column_map.get(event.column_key)
        if not target_col:
            return

        if self.sort_column == target_col:
            # Toggle direction if clicking same column
            self.sort_reverse = not self.sort_reverse
        else:
            self.sort_column = target_col
            self.sort_reverse = False

        # Save to config
        self.config["sort_column"] = self.sort_column
        self.config["sort_reverse"] = self.sort_reverse
        save_config(self.config)

        self.log_message(f"Sorting by {target_col} ({'descending' if self.sort_reverse else 'ascending'})")
        
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

    @work(thread=True)
    def action_refresh_library(self) -> None:
        self.log_message("Fetching library...")
        try:
            self.full_library = self.service.fetch_library()
            self.call_from_thread(self.apply_filter, "")
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
            if any(filter_text in field.lower() for field in [book.asin, book.author, book.title])
        ]

        # Sort
        filtered_books.sort(
            key=lambda b: getattr(b, self.sort_column).lower(), 
            reverse=self.sort_reverse
        )

        for book in filtered_books:
            if book.working:
                status = f"[bold blue]{SPINNER_FRAMES[book.spinner_frame]}[/]"
            elif book.queued:
                if "⬇" in book.status: # Already has AAX
                    status = "[bold yellow]⚙[/]"
                else:
                    status = "[bold yellow]⬇[/]"
            else:
                status = book.status
            table.add_row(status, book.asin, book.author, book.title, key=book.asin)

    def log_message(self, message: str) -> None:
        self.query_one("#log", Log).write_line(message)
        
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
            found = False
            for row_key in table.rows:
                row_data = table.get_row(row_key)
                if str(row_data[1]) == str(asin):
                    title = row_data[3]
                    # Find the book in full_library to check working state
                    book = next((b for b in self.full_library if b.asin == asin), None)
                    new_status = self.service.get_status(asin, title)
                    
                    if book and book.working:
                        display_status = f"[bold blue]{SPINNER_FRAMES[book.spinner_frame]}[/]"
                    elif book and book.queued:
                        if "⬇" in new_status:
                            display_status = "[bold yellow]⚙[/]"
                        else:
                            display_status = "[bold yellow]⬇[/]"
                    else:
                        display_status = new_status
                    
                    table.update_cell(row_key, self.status_col_key, display_status, update_width=True)
                    
                    if book:
                        book.status = new_status
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

    @work(thread=True)
    def refresh_all_statuses(self) -> None:
        """Updates status for all visible rows in a worker thread."""
        try:
            # Pre-list directory for faster status checks
            lib = self.service.library_path
            file_set = {f.name for f in lib.iterdir()} if lib.exists() else set()

            # Create a lookup for full_library to fix O(N^2)
            library_lookup = {book.asin: book for book in self.full_library}
            
            table = self.query_one("#library_table", LibraryTable)
            for row_key in table.rows:
                row_data = table.get_row(row_key)
                asin = row_data[1]
                title = row_data[3]
                new_status = self.service.get_status(asin, title, file_set=file_set)
                
                # Update UI from thread
                self.call_from_thread(table.update_cell, row_key, self.status_col_key, new_status)
                
                # Sync with full_library
                if asin in library_lookup:
                    library_lookup[asin].status = new_status
            
            self.call_from_thread(table.refresh)
        except Exception as e:
            self.log_message(f"Error refreshing statuses: {e}")

    @on(DataTable.RowSelected, "#library_table")
    def on_row_selected(self, event: DataTable.RowSelected) -> None:
        row_data = event.data_table.get_row_at(event.cursor_row)
        asin = row_data[1]
        title = row_data[3]

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
            self.task_queue.put_nowait(asin)
            self.update_row_status(asin)
            self.notify(f"Added '{title}' to queue.", severity="information")

    async def download_book(self, asin: str) -> None:
        book = next((b for b in self.full_library if b.asin == asin), None)
        if book:
            book.working = True
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
                self.service.verify_file_exists(lib / f"{asin}*.aax")
            else:
                self.log_message(f"Download of {asin} failed with code {res}")
                log_handler(f"\n[bold red]Failed with code {res}[/]")
        finally:
            if book:
                book.working = False
            self.active_logs.pop(asin, None)
            self.update_row_status(asin)

    async def process_book(self, asin: str, title: str) -> None:
        # Find the book in full_library
        book = next((b for b in self.full_library if b.asin == asin), None)
        if not book:
            # Create a temporary one if not found (shouldn't happen)
            book = Audiobook(asin=asin, author="Unknown", title=title)

        book.working = True
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
                self.service.verify_file_exists(lib / f"{book.safe_title}.m4b")
                
                self.prompt_cleanup(asin, title)
            else:
                self.log_message(f"[bold red]Processing failed for {title}[/]")
        finally:
            book.working = False
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
