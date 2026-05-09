# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "textual",
#     "platformdirs",
#     "pytest",
# ]
# ///

import os
import json
import subprocess
import glob
import re
import shutil
import tempfile
from typing import List, Dict, Iterable, Optional
from pathlib import Path
from dataclasses import dataclass

from platformdirs import user_config_dir
from textual.app import App, ComposeResult, SystemCommand
from textual.binding import Binding
from textual.widgets import Header, Footer, DataTable, Input, Button, Label, Log, RichLog, Static
from textual.containers import Vertical, Horizontal
from textual import work, on, events
from textual.reactive import reactive
from textual.screen import ModalScreen, Screen

# Configuration
APP_NAME = "audiobook-manager"
CONFIG_DIR = Path(user_config_dir(APP_NAME))
CONFIG_FILE = CONFIG_DIR / "config.json"
LOG_FILE = CONFIG_DIR / "activity.log"
OLD_CONFIG_FILE = Path(__file__).parent / "audiobook_config.json"

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

class ProcessOutputScreen(ModalScreen):
    """A modal screen that shows the output of a process."""

    CSS = """
    ProcessOutputScreen {
        align: center middle;
    }
    #process_modal {
        width: 80%;
        height: 80%;
        background: $surface;
        border: thick $primary;
        padding: 1;
    }
    #modal_title {
        text-align: center;
        width: 100%;
        background: $primary;
        color: $text;
        margin-bottom: 1;
    }
    RichLog {
        height: 1fr;
        border: tall $surface;
    }
    #close_btn {
        margin-top: 1;
        width: 100%;
    }
    """

    BINDINGS = [
        ("enter", "close_modal", "Action"),
        ("q", "close_modal", "Quit"),
        ("escape", "close_modal", "Close"),
    ]

    def __init__(self, title: str):
        super().__init__()
        self.process_title = title

    def compose(self) -> ComposeResult:
        with Vertical(id="process_modal"):
            yield Label(self.process_title, id="modal_title")
            yield RichLog(id="process_log", highlight=True, markup=True)
            yield Button("Close", id="close_btn", variant="primary")

    @on(Button.Pressed, "#close_btn")
    def close_modal(self) -> None:
        self.app.pop_screen()

    def action_close_modal(self) -> None:
        self.close_modal()

    def append_log(self, text: str) -> None:
        self.query_one(RichLog).write(text)

class ConfirmModal(ModalScreen):
    """A modal screen for confirmation."""

    CSS = """
    ConfirmModal {
        align: center middle;
    }
    #confirm_modal {
        width: 60;
        height: auto;
        background: $surface;
        border: thick $primary;
        padding: 1;
    }
    #confirm_msg {
        text-align: center;
        width: 100%;
        margin-bottom: 1;
    }
    .modal_buttons {
        height: auto;
        align: center middle;
    }
    """

    def __init__(self, message: str):
        super().__init__()
        self.message = message

    def compose(self) -> ComposeResult:
        with Vertical(id="confirm_modal"):
            yield Label(self.message, id="confirm_msg")
            with Horizontal(classes="modal_buttons"):
                yield Button("Yes", id="btn_yes", variant="error")
                yield Button("No", id="btn_no", variant="primary")

    @on(Button.Pressed, "#btn_yes")
    def on_yes(self) -> None:
        self.dismiss(True)

    @on(Button.Pressed, "#btn_no")
    def on_no(self) -> None:
        self.dismiss(False)

class SearchInput(Input):
    """An Input with custom bindings for navigation."""
    BINDINGS = [
        ("escape", "focus_library", "Back"),
    ]
    def action_focus_library(self) -> None:
        self.app.query_one("#library_table").focus()

class ActivationBytesModal(ModalScreen):
    """A modal for entering activation bytes."""
    CSS = """
    ActivationBytesModal {
        align: center middle;
    }
    #bytes_modal {
        width: 60;
        height: auto;
        background: $surface;
        border: thick $primary;
        padding: 1;
    }
    #bytes_title {
        text-align: center;
        width: 100%;
        margin-bottom: 1;
    }
    """
    BINDINGS = [
        ("escape", "cancel", "Cancel"),
    ]

    def __init__(self, current_value: str = ""):
        super().__init__()
        self.current_value = current_value

    def compose(self) -> ComposeResult:
        with Vertical(id="bytes_modal"):
            yield Label("Enter Audible Activation Bytes (8 hex chars):", id="bytes_title")
            yield Input(value=self.current_value, placeholder="e.g. 1a2b3c4d", id="bytes_input")
            with Horizontal(classes="modal_buttons"):
                yield Button("Save", id="btn_save", variant="success")
                yield Button("Cancel", id="btn_cancel", variant="primary")

    def action_cancel(self) -> None:
        self.dismiss(None)

    @on(Button.Pressed, "#btn_save")
    def on_save(self) -> None:
        val = self.query_one("#bytes_input", Input).value
        self.dismiss(val)

    @on(Button.Pressed, "#btn_cancel")
    def on_cancel(self) -> None:
        self.dismiss(None)

    @on(Input.Submitted, "#bytes_input")
    def on_submit(self) -> None:
        self.on_save()

class LibraryPathModal(ModalScreen):
    """A modal for entering the library directory path."""
    CSS = """
    LibraryPathModal {
        align: center middle;
    }
    #path_modal {
        width: 80;
        height: auto;
        background: $surface;
        border: thick $primary;
        padding: 1;
    }
    #path_title {
        text-align: center;
        width: 100%;
        margin-bottom: 1;
    }
    """
    BINDINGS = [
        ("escape", "cancel", "Cancel"),
    ]

    def __init__(self, current_value: str = ""):
        super().__init__()
        self.current_value = current_value

    def compose(self) -> ComposeResult:
        with Vertical(id="path_modal"):
            yield Label("Enter Library Directory Path:", id="path_title")
            yield Input(value=self.current_value, placeholder="e.g. /home/user/Audiobooks", id="path_input")
            with Horizontal(classes="modal_buttons"):
                yield Button("Save", id="btn_save", variant="success")
                yield Button("Cancel", id="btn_cancel", variant="primary")

    def action_cancel(self) -> None:
        self.dismiss(None)

    @on(Button.Pressed, "#btn_save")
    def on_save(self) -> None:
        val = self.query_one("#path_input", Input).value
        self.dismiss(val)

    @on(Button.Pressed, "#btn_cancel")
    def on_cancel(self) -> None:
        self.dismiss(None)

    @on(Input.Submitted, "#path_input")
    def on_submit(self) -> None:
        self.on_save()

class StatusLog(Log):
    """A Log with custom bindings for the footer."""
    BINDINGS = [
        ("enter", "perform_action", "Action"),
        ("j", "cursor_down", "Down"),
        ("k", "cursor_up", "Up"),
        ("h", "cursor_left", "Left"),
        ("l", "cursor_right", "Right"),
        ("d", "page_down", "PgDown"),
        ("u", "page_up", "PgUp"),
        ("g", "scroll_top", "Top"),
        ("G", "scroll_bottom", "Bottom"),
        ("/", "focus_search", "Search"),
        Binding("tab", "focus_next", "Tab", show=False),
        ("r", "refresh_library", "Refresh"),
        ("`,grave,backtick", "toggle_log", "Log"),
        ("q", "quit", "Quit"),
    ]


    def action_perform_action(self) -> None:
        self.app.action_select_row()

    def action_toggle_log(self) -> None:
        self.app.action_toggle_log()

    def action_focus_search(self) -> None:
        self.app.action_focus_search()

    def action_refresh_library(self) -> None:
        self.app.action_refresh_library()

    def action_quit(self) -> None:
        self.app.action_quit()

class LibraryTable(DataTable):
    """A DataTable with custom bindings for the footer."""
    BINDINGS = [
        ("enter", "perform_action", "Action"),
        ("j", "cursor_down", "Down"),
        ("k", "cursor_up", "Up"),
        ("h", "cursor_left", "Left"),
        ("l", "cursor_right", "Right"),
        ("d", "page_down", "PgDown"),
        ("u", "page_up", "PgUp"),
        ("g", "scroll_top", "Top"),
        ("G", "scroll_bottom", "Bottom"),
        ("/", "focus_search", "Search"),
        Binding("tab", "focus_next", "Tab", show=False),
        ("r", "refresh_library", "Refresh"),
        ("`,grave,backtick", "toggle_log", "Log"),
        ("q", "quit", "Quit"),
    ]


    def action_scroll_top(self) -> None:
        """Move cursor to the very first row."""
        self.move_cursor(row=0)

    def action_scroll_bottom(self) -> None:
        """Move cursor to the very last row."""
        self.move_cursor(row=self.row_count - 1)

    def action_perform_action(self) -> None:
        self.app.action_select_row()

    def action_toggle_log(self) -> None:
        self.app.action_toggle_log()

    def action_focus_search(self) -> None:
        self.app.action_focus_search()

    def action_refresh_library(self) -> None:
        self.app.action_refresh_library()

    def action_quit(self) -> None:
        self.app.action_quit()

@dataclass
class Audiobook:
    asin: str
    author: str
    title: str
    status: str = ""

    @property
    def safe_title(self) -> str:
        return sanitize_filename(self.title)

class AudiobookService:
    def __init__(self, config: Dict):
        self.config = config

    @property
    def library_path(self) -> Path:
        return Path(self.config.get("library_path", str(Path.cwd())))

    @property
    def activation_bytes(self) -> str:
        return self.config.get("activation_bytes", "")

    def get_status(self, asin: str, title: str) -> str:
        """Checks the filesystem for the status of a book."""
        safe_title = sanitize_filename(title)
        lib = self.library_path

        # Check for M4B (sanitized title or ASIN)
        if (lib / f"{safe_title}.m4b").exists() or (lib / f"{asin}.m4b").exists():
            return "[bold green]✔[/]"

        # Check for AAX
        aax_patterns = [f"{asin}*.aax", f"{safe_title}*.aax"]
        for pattern in aax_patterns:
            if any(lib.glob(pattern)):
                return "[bold yellow]⬇[/]"

        return ""

    def verify_file_exists(self, path: Path, timeout: float = 2.0) -> bool:
        """Polls for a file's existence for a limited time."""
        import time
        start = time.time()
        while time.time() - start < timeout:
            if path.exists():
                return True
            time.sleep(0.1)
        return False

    def fetch_library(self) -> List[Audiobook]:
        """Fetches the library using audible-cli with a robust regex parser."""
        try:
            output = subprocess.check_output(
                ["audible", "library", "list"], 
                text=True, 
                stderr=subprocess.PIPE
            )
            books = []
            
            # Pattern: ASIN: Author: Title
            # We use a non-greedy match for ASIN and Author, and take the rest as Title
            # ASIN is usually 10 chars, Author/Title can contain colons
            # Typical line: "B002V0QIT2: Stephen King: IT"
            # Note: audible-cli output format can vary, but this is the standard list format.
            pattern = re.compile(r'^([^:]+):\s*([^:]+):\s*(.*)$')
            
            for line in output.strip().split('\n'):
                if not line: continue
                
                match = pattern.match(line)
                if match:
                    asin, author, title = match.groups()
                    status = self.get_status(asin.strip(), title.strip())
                    books.append(Audiobook(
                        asin=asin.strip(), 
                        author=author.strip(), 
                        title=title.strip(), 
                        status=status
                    ))
                else:
                    # Fallback for lines that don't match the 3-part format
                    parts = line.split(': ', 1)
                    if len(parts) == 2:
                        asin, title = parts
                        status = self.get_status(asin.strip(), title.strip())
                        books.append(Audiobook(
                            asin=asin.strip(), 
                            author="Unknown", 
                            title=title.strip(), 
                            status=status
                        ))
                    
            return books
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"Audible CLI failed: {e.stderr.strip() if e.stderr else e}") from e
        except Exception as e:
            raise RuntimeError(f"Unexpected error fetching library: {e}") from e

    def download(self, asin: str, log_callback):
        """Runs the audible download command."""
        cmd = ["audible", "download", "-a", asin, "--aax", "--cover", "--chapter", "--filename-mode", "asin_only", "-y"]
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, cwd=str(self.library_path))
        if process.stdout:
            for line in process.stdout:
                log_callback(line.strip())
        process.wait()
        return process.returncode

    def process_m4b(self, book: Audiobook, log_callback) -> bool:
        """Converts AAX to M4B with chapters and cover art."""
        if not self.activation_bytes:
            log_callback("[bold red]Activation bytes not set![/]")
            return False

        lib = self.library_path
        safe_title = book.safe_title
        
        # 1. Find Chapter JSON
        json_path = None
        for pattern in [f"{book.asin}*.json", f"{safe_title}*.json"]:
            matches = [m for m in lib.glob(pattern) if m.suffix == ".json"]
            if matches:
                json_path = matches[0]
                break
        if not json_path:
            log_callback("[bold red]Chapter JSON not found.[/]")
            return False

        # 2. Find AAX
        aax_path = None
        for pattern in [f"{book.asin}*.aax", f"{safe_title}*.aax"]:
            matches = list(lib.glob(pattern))
            if matches:
                aax_path = matches[0]
                break
        if not aax_path:
            log_callback("[bold red]AAX file not found.[/]")
            return False

        # 3. Find Cover
        cover_path = None
        for pattern in [f"{book.asin}*.jpg", f"{safe_title}*.jpg"]:
            matches = list(lib.glob(pattern))
            if matches:
                cover_path = matches[0]
                break

        # 4. Prepare Metadata
        try:
            with open(json_path, 'r') as f:
                json_data = json.load(f)
            ffmetadata = convert_chapters_json_to_ffmetadata(json_data)
            
            with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as tmp_meta:
                tmp_meta.write('\n'.join(ffmetadata))
                meta_path = Path(tmp_meta.name)
            log_callback(f"Prepared metadata: {meta_path.name}")
        except Exception as e:
            log_callback(f"[bold red]Metadata error: {e}[/]")
            return False

        # 5. Build FFmpeg command
        output_path = lib / f"{book.asin}.m4b"
        cmd = ["ffmpeg", "-y", "-activation_bytes", self.activation_bytes, "-i", str(aax_path), "-i", str(meta_path)]
        if cover_path:
            cmd.extend(["-i", str(cover_path), "-map_metadata", "0", "-map_chapters", "1", "-map", "0:a", "-map", "2:v", "-c:a", "copy", "-c:v", "copy", "-disposition:v:0", "attached_pic"])
        else:
            cmd.extend(["-map_metadata", "0", "-map_chapters", "1", "-map", "0:a", "-c:a", "copy"])
        cmd.append(str(output_path))

        # 6. Run FFmpeg
        try:
            process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            if process.stdout:
                for line in process.stdout:
                    log_callback(line.strip())
            process.wait()
            
            if meta_path.exists(): meta_path.unlink()

            if process.returncode == 0:
                final_path = lib / f"{safe_title}.m4b"
                try:
                    output_path.rename(final_path)
                except Exception:
                    pass
                return True
            return False
        except Exception as e:
            if 'meta_path' in locals() and meta_path.exists(): meta_path.unlink()
            log_callback(f"[bold red]FFmpeg error: {e}[/]")
            return False

    def cleanup_sources(self, book: Audiobook, log_callback):
        """Deletes original files after conversion."""
        lib = self.library_path
        count = 0
        for pattern in [f"{book.asin}*", f"{book.safe_title}*"]:
            for ext in [".aax", ".json", ".jpg"]:
                for match in lib.glob(f"{pattern}{ext}"):
                    try:
                        match.unlink()
                        count += 1
                        log_callback(f"Deleted: {match.name}")
                    except Exception:
                        pass
        return count

def sanitize_filename(text: str) -> str:
    """
    Sanitizes a string for use as a filename:
    1. Removes or replaces characters that are generally problematic on Windows/Linux/macOS.
    2. Replaces spaces with underscores.
    3. Collapses multiple dashes/underscores.
    4. Truncates to a reasonable length.
    """
    if not text:
        return "unnamed_audiobook"
        
    # Replace characters that are invalid in Windows or problematic elsewhere
    # < > : " / \ | ? *
    text = re.sub(r'[<>:"/\\|?*]', '-', text)
    
    # Replace other non-alphanumeric (except . - _) with a dash
    text = re.sub(r'[^\w\.\- ]', '-', text)
    
    # Replace spaces with underscores
    text = text.replace(' ', '_')
    
    # Collapse multiple dashes or underscores
    text = re.sub(r'[\-_]{2,}', '_', text)
    
    # Remove leading/trailing dashes or underscores
    text = text.strip('-_')
    
    # Truncate to avoid issues with long paths (leaving room for extension)
    return text[:200] if text else "unnamed_audiobook"

def convert_chapters_json_to_ffmetadata(json_data: Dict) -> List[str]:
    """Converts Audible chapter JSON to FFMETADATA format."""
    def _convert_recursive(chapters: List[Dict]) -> List[str]:
        output = []
        for item in chapters:
            start_time = int(item['start_offset_ms'])
            duration = int(item['length_ms'])
            end_time = start_time + duration
            title_str = str(item['title'])
            # Escape special characters for FFMETADATA
            title_str = title_str.translate(
                str.maketrans({
                    "\\": r"\\",
                    "\n": r"\\n",
                    "#":  r"\#",
                    ";":  r"\;",
                    "=":  r"\="
                }))
            output.append("")
            output.append("[CHAPTER]")
            output.append("TIMEBASE=1/1000")
            output.append(f"START={start_time}")
            output.append(f"END={end_time}")
            output.append(f"TITLE={title_str}")
            if "chapters" in item:
                output.extend(_convert_recursive(item['chapters']))
        return output

    chapters = json_data['content_metadata']['chapter_info']['chapters']
    output_list = [";FFMETADATA1"]
    output_list.extend(_convert_recursive(chapters))
    return output_list

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
            table.add_row(book.status, book.asin, book.author, book.title, key=book.asin)

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
                    new_status = self.service.get_status(asin, title)
                    table.update_cell(row_key, self.status_col_key, new_status, update_width=True)
                    self.log_message(f"Updated status for '{title}' to {new_status}")
                    
                    # Also update the full_library data
                    for book in self.full_library:
                        if book.asin == asin:
                            book.status = new_status
                            break
                    found = True
                    break

            if not found:
                self.log_message(f"ASIN {asin} not in current view, status will update on next search.")
        except Exception as e:
            self.log_message(f"Error updating row: {e}")

    def refresh_all_statuses(self) -> None:
        """Updates status for all visible rows."""
        try:
            table = self.query_one("#library_table", LibraryTable)
            for row_key in table.rows:
                row_data = table.get_row(row_key)
                asin = row_data[1]
                title = row_data[3]
                new_status = self.service.get_status(asin, title)
                table.update_cell(row_key, self.status_col_key, new_status)
                
                # Sync with full_library
                for book in self.full_library:
                    if book.asin == asin:
                        book.status = new_status
                        break
            table.refresh()
        except Exception as e:
            self.log_message(f"Error refreshing statuses: {e}")

    @on(DataTable.RowSelected, "#library_table")
    def on_row_selected(self, event: DataTable.RowSelected) -> None:
        row_data = event.data_table.get_row_at(event.cursor_row)
        asin = row_data[1]
        title = row_data[3]
        status = self.service.get_status(asin, title)

        if status == "": # Not downloaded
            self.download_book(asin)
        elif "⬇" in status: # Downloaded (AAX) but not processed
            self.process_book(asin, title)
        elif "✔" in status: # Already processed
            self.log_message(f"'{title}' is already processed.")

    @work(thread=True)
    def download_book(self, asin: str) -> None:
        self.log_message(f"Starting download for {asin}...")
        screen = ProcessOutputScreen(f"Downloading {asin}")
        self.call_from_thread(self.push_screen, screen)

        res = self.service.download(asin, lambda msg: self.call_from_thread(screen.append_log, msg))
        
        if res == 0:
            self.log_message(f"Download of {asin} complete.")
            self.call_from_thread(screen.append_log, "\n[bold green]Download Complete![/]")
            
            # Verify any expected file appeared before refreshing
            lib = self.service.library_path
            self.service.verify_file_exists(lib / f"{asin}.aax")
            
            self.call_from_thread(self.update_row_status, asin)
        else:
            self.log_message(f"Download of {asin} failed with code {res}")
            self.call_from_thread(screen.append_log, f"\n[bold red]Failed with code {res}[/]")

    @work(thread=True)
    def process_book(self, asin: str, title: str) -> None:
        # Find the book in full_library
        book = next((b for b in self.full_library if b.asin == asin), None)
        if not book:
            # Create a temporary one if not found (shouldn't happen)
            book = Audiobook(asin=asin, author="Unknown", title=title)

        self.log_message(f"Starting process for {asin}...")
        screen = ProcessOutputScreen(f"Processing {title}")
        self.call_from_thread(self.push_screen, screen)

        def process_log_callback(msg: str):
            # Log everything to the modal screen
            self.call_from_thread(screen.append_log, msg)
            
            # Only log errors or major milestones to the status log (and thus the file)
            # We filter out typical FFmpeg progress lines to avoid clutter
            if "error" in msg.lower() or "failed" in msg.lower() or "successfully" in msg.lower() or "Prepared" in msg:
                 self.log_message(msg)

        success = self.service.process_m4b(book, process_log_callback)

        if success:
            self.log_message(f"[bold green]M4B created successfully for {title}[/]")
            
            # Verify file renamed successfully before refreshing
            lib = self.service.library_path
            self.service.verify_file_exists(lib / f"{book.safe_title}.m4b")
            
            self.call_from_thread(self.update_row_status, asin)
            self.call_from_thread(self.prompt_cleanup, asin, title)
        else:
            self.log_message(f"[bold red]Processing failed for {title}[/]")

if __name__ == "__main__":
    app = AudiobookManager()
    app.run()
