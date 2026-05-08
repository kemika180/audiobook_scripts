# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "textual",
# ]
# ///

import os
import json
import subprocess
import glob
import re
from typing import List, Dict, Optional
from pathlib import Path

from textual.app import App, ComposeResult
from textual.widgets import Header, Footer, DataTable, TabbedContent, TabPane, Input, Button, Label, Log, Static, RichLog
from textual.containers import Vertical, Horizontal, Container
from textual import work, on, events
from textual.screen import ModalScreen

# Configuration
ACTIVATION_BYTES = "9c06a105"
CONFIG_FILE = Path(__file__).parent / "audiobook_config.json"

def load_config() -> Dict:
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r") as f:
                data = json.load(f)
                return data
        except Exception:
            pass
    return {"theme": "textual-dark", "log_visible": True}

def save_config(config: Dict):
    try:
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
        ("tab", "focus_next", "Tab"),
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
        ("tab", "focus_next", "Tab"),
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

def sanitize_filename(text: str) -> str:
    r"""
    Sanitizes a string for use as a filename:
    1. Replaces invalid symbols (not \w, -, .) with a dash.
    2. If a space follows an invalid symbol, that space is ignored.
    3. Replaces remaining spaces with underscores.
    """
    # Replace invalid symbols followed by optional spaces with a single dash
    text = re.sub(r'[^\w\-\. ]\s*', '-', text)
    # Replace remaining spaces with underscores
    text = text.replace(' ', '_')
    return text

def get_local_status(asin: str, title: str) -> str:
    """Checks the filesystem for the status of a book."""
    safe_title = sanitize_filename(title)
    
    # Check for M4B
    m4b_path = Path(f"{safe_title}.m4b")
    if m4b_path.exists():
        return "[bold green]✔[/]"
    
    # Check for AAX
    aax_matches = glob.glob(f"{asin}*.aax") or glob.glob(f"{safe_title}*.aax")
    if aax_matches:
        return "[bold yellow]⬇[/]"
    
    return ""

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
    BINDINGS = []

    def __init__(self):
        super().__init__()
        self.full_library_data = []
        self.config = load_config()
        self.status_col_key = None
        self.asin_col_key = None
        self.author_col_key = None
        self.title_col_key = None

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
        # Apply the saved theme from config
        saved_theme = self.config.get("theme", "textual-dark")
        if saved_theme == "dark":
            saved_theme = "textual-dark"
        
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
        table.focus()
        
        # Now check if we should show search bar
        self.update_search_visibility()
        
        self.action_refresh_library()

    def on_focus(self) -> None:
        """Refresh statuses whenever the app gets focus."""
        self.refresh_all_statuses()

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
        safe_title = sanitize_filename(title)
        prefixes = [asin, safe_title]
        deleted_count = 0
        
        # Files to target
        extensions = [".aax", ".json", "-chapters.txt"]
        
        for prefix in prefixes:
            # Delete matched extensions
            for ext in extensions:
                matches = glob.glob(f"{prefix}*{ext}")
                for match in matches:
                    try:
                        os.remove(match)
                        deleted_count += 1
                    except Exception as e:
                        self.log_message(f"Error deleting {match}: {e}")
            
            # Specifically target JPGs (often have (500) in name)
            jpg_matches = glob.glob(f"{prefix}*.jpg")
            for match in jpg_matches:
                try:
                    os.remove(match)
                    deleted_count += 1
                except Exception as e:
                    self.log_message(f"Error deleting {match}: {e}")

        if deleted_count > 0:
            self.log_message(f"Cleaned up {deleted_count} source files for '{title}'.")
            self.notify(f"Source files deleted for {title}", severity="information")
            self.refresh_all_statuses()

    @work(thread=True)
    def action_refresh_library(self) -> None:
        self.log_message("Fetching library...")
        try:
            output = subprocess.check_output(["audible", "library", "list"], text=True)
            self.full_library_data = []
            for line in output.strip().split('\n'):
                if not line: continue
                parts = line.split(': ', 2)
                if len(parts) >= 3:
                    self.full_library_data.append((parts[0], parts[1], parts[2]))
                elif len(parts) == 2:
                     self.full_library_data.append((parts[0], "Unknown", parts[1]))
            
            self.call_from_thread(self.apply_filter, "")
            self.log_message("Library refreshed.")
        except Exception as e:
            self.log_message(f"Error fetching library: {e}")

    def on_descendant_focus(self, event: events.DescendantFocus) -> None:
        """Triggers search visibility update whenever focus changes."""
        self.update_search_visibility()

    def on_descendant_blur(self, event: events.DescendantBlur) -> None:
        """Triggers search visibility update whenever focus changes."""
        self.update_search_visibility()

    @on(Input.Changed, "#search_input")
    def on_search_changed(self, event: Input.Changed) -> None:
        self.apply_filter(event.value)
        self.update_search_visibility()

    @on(Input.Submitted, "#search_input")
    def on_search_submitted(self) -> None:
        """Returns focus to the library when Enter is pressed in search."""
        self.query_one("#library_table").focus()

    def update_search_visibility(self) -> None:
        """Shows the search input only if it's focused or has content."""
        try:
            search_input = self.query_one("#search_input", SearchInput)
            # Display if focused OR has text
            search_input.display = search_input.has_focus or len(search_input.value) > 0
        except Exception:
            pass

    def apply_filter(self, filter_text: str) -> None:
        table = self.query_one("#library_table", LibraryTable)
        table.clear()
        filter_text = filter_text.lower()
        
        for row in self.full_library_data:
            asin, author, title = row
            if any(filter_text in field.lower() for field in row):
                status = get_local_status(asin, title)
                table.add_row(status, asin, author, title, key=asin)

    def log_message(self, message: str) -> None:
        self.query_one("#log", Log).write_line(message)

    def update_row_status(self, asin: str) -> None:
        """Updates the status symbol for a specific ASIN in the table."""
        try:
            table = self.query_one("#library_table", LibraryTable)
            found = False
            for row_key in table.rows:
                row_data = table.get_row(row_key)
                if str(row_data[1]) == str(asin):
                    title = row_data[3]
                    new_status = get_local_status(asin, title)
                    table.update_cell(row_key, self.status_col_key, new_status, update_width=True)
                    self.log_message(f"Updated status for '{title}' to {new_status}")
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
                new_status = get_local_status(asin, title)
                table.update_cell(row_key, self.status_col_key, new_status)
            table.refresh()
        except Exception as e:
            self.log_message(f"Error refreshing statuses: {e}")

    @on(DataTable.RowSelected, "#library_table")
    def on_row_selected(self, event: DataTable.RowSelected) -> None:
        row_data = event.data_table.get_row_at(event.cursor_row)
        asin = row_data[1]
        title = row_data[3]
        
        status = get_local_status(asin, title)
        
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
        
        try:
            cmd = ["audible", "download", "-a", asin, "--aax", "--cover", "--chapter", "--filename-mode", "asin_only", "-y"]
            process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            for line in process.stdout:
                msg = line.strip()
                self.call_from_thread(screen.append_log, msg)
            process.wait()
            if process.returncode == 0:
                self.log_message(f"Download of {asin} complete.")
                self.call_from_thread(screen.append_log, "\n[bold green]Download Complete![/]")
                # Refresh status in the table without clearing it
                import time
                time.sleep(0.5)
                self.call_from_thread(self.update_row_status, asin)
            else:
                self.log_message(f"Download of {asin} failed with code {process.returncode}")
                self.call_from_thread(screen.append_log, f"\n[bold red]Failed with code {process.returncode}[/]")
        except Exception as e:
            self.log_message(f"Error downloading: {e}")
            self.call_from_thread(screen.append_log, f"\n[bold red]Error: {e}[/]")

    @work(thread=True)
    def process_book(self, asin: str, title: str) -> None:
        self.log_message(f"Starting process for {asin}...")
        screen = ProcessOutputScreen(f"Processing {title}")
        self.call_from_thread(self.push_screen, screen)
        
        def log_to_both(msg: str):
            self.log_message(msg)
            self.call_from_thread(screen.append_log, msg)

        # Determine prefix (could be ASIN or Title)
        safe_title = sanitize_filename(title)
        potential_prefixes = [asin, safe_title]
        
        json_path = None
        for prefix in potential_prefixes:
            matches = glob.glob(f"{prefix}*.json")
            if matches:
                # Exclude the metadata txt file we might have created previously
                matches = [m for m in matches if m.endswith(".json")]
                if matches:
                    json_path = Path(matches[0])
                    break
        
        if not json_path:
            log_to_both("[bold red]Chapter JSON not found. Please download first.[/]")
            return

        try:
            with open(json_path, 'r') as f:
                json_data = json.load(f)
            ffmetadata = convert_chapters_json_to_ffmetadata(json_data)
            meta_path = Path(f"{asin}-chapters.txt")
            with open(meta_path, 'w') as f:
                f.write('\n'.join(ffmetadata))
            log_to_both(f"Chapters converted to {meta_path}")
        except Exception as e:
            log_to_both(f"[bold red]Error converting chapters: {e}[/]")
            return

        # 2. Find AAX and Cover
        aax_path = None
        for prefix in potential_prefixes:
            matches = glob.glob(f"{prefix}*.aax")
            if matches:
                aax_path = Path(matches[0])
                break

        if not aax_path:
             log_to_both(f"[bold red]AAX not found for {asin} or {safe_title}[/]")
             return
        
        cover_path = None
        for prefix in potential_prefixes:
            matches = glob.glob(f"{prefix}*.jpg")
            if matches:
                cover_path = Path(matches[0])
                break
        
        if cover_path:
            log_to_both(f"Found cover at {cover_path}")
        
        # 3. Build M4B
        output_path = Path(f"{asin}.m4b")
        cmd = [
            "ffmpeg", "-y",
            "-activation_bytes", ACTIVATION_BYTES,
            "-i", str(aax_path),
            "-i", str(meta_path)
        ]
        
        if cover_path:
            cmd.extend(["-i", str(cover_path)])
            cmd.extend([
                "-map_metadata", "0",
                "-map_chapters", "1",
                "-map", "0:a",
                "-map", "2:v",
                "-c:a", "copy",
                "-c:v", "copy",
                "-disposition:v:0", "attached_pic"
            ])
        else:
            cmd.extend([
                "-map_metadata", "0",
                "-map_chapters", "1",
                "-map", "0:a",
                "-c:a", "copy"
            ])
            
        cmd.append(str(output_path))
        
        log_to_both(f"Running ffmpeg: {' '.join(cmd)}")
        try:
            process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            for line in process.stdout:
                self.call_from_thread(screen.append_log, line.strip())
            process.wait()
            if process.returncode == 0:
                log_to_both(f"[bold green]M4B created successfully: {output_path}[/]")
                # Use sanitized title for the final filename
                final_path = Path(f"{sanitize_filename(title)}.m4b")
                output_path.rename(final_path)
                log_to_both(f"Renamed to {final_path}")
                # Refresh status in the table without clearing it
                import time
                time.sleep(0.5)
                self.call_from_thread(self.update_row_status, asin)
                
                # Prompt for cleanup
                self.call_from_thread(self.prompt_cleanup, asin, title)
            else:
                log_to_both(f"[bold red]ffmpeg failed with code {process.returncode}[/]")
        except Exception as e:
            log_to_both(f"[bold red]Error running ffmpeg: {e}[/]")

if __name__ == "__main__":
    app = AudiobookManager()
    app.run()
