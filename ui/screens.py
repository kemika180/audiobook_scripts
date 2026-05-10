from textual.app import ComposeResult
from textual.binding import Binding
from textual.geometry import Spacing
from textual.widgets import Header, Footer, DataTable, Input, Button, Label, RichLog, Checkbox
from textual.containers import Vertical, Horizontal
from textual.screen import ModalScreen
from textual import on

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

    def __init__(self, title: str, asin: str, log_history: list[str]):
        super().__init__()
        self.process_title = title
        self.asin = asin
        self.log_history = log_history

    def compose(self) -> ComposeResult:
        with Vertical(id="process_modal"):
            yield Label(self.process_title, id="modal_title")
            yield RichLog(id="process_log", highlight=False, markup=True)
            yield Button("Close", id="close_btn", variant="primary")

    def on_mount(self) -> None:
        """Populate log with existing history."""
        log = self.query_one(RichLog)
        for line in self.log_history:
            log.write(line)

    @on(Button.Pressed, "#close_btn")
    def close_modal(self) -> None:
        self.app.pop_screen()

    def action_close_modal(self) -> None:
        self.close_modal()

    def append_log(self, text: str) -> None:
        """Called by the manager if this screen is active."""
        try:
            self.query_one(RichLog).write(text)
        except Exception:
            pass

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

class GeneralSettingsModal(ModalScreen):
    """A modal for general automation settings."""
    CSS = """
    GeneralSettingsModal {
        align: center middle;
    }
    #settings_modal {
        width: 50;
        height: auto;
        background: $surface;
        border: thick $primary;
        padding: 1;
    }
    #settings_title {
        text-align: center;
        width: 100%;
        margin-bottom: 1;
    }
    Checkbox {
        margin: 0 1;
    }
    """
    BINDINGS = [
        ("escape", "cancel", "Cancel"),
    ]

    def __init__(self, config: dict):
        super().__init__()
        self.config = config

    def compose(self) -> ComposeResult:
        with Vertical(id="settings_modal"):
            yield Label("General Settings:", id="settings_title")
            yield Checkbox("Auto-process after download", value=self.config.get("auto_process", False), id="cb_auto_process")
            yield Checkbox("Auto-cleanup after processing", value=self.config.get("auto_cleanup", False), id="cb_auto_cleanup")
            with Horizontal(classes="modal_buttons"):
                yield Button("Save", id="btn_save", variant="success")
                yield Button("Cancel", id="btn_cancel", variant="primary")

    def action_cancel(self) -> None:
        self.dismiss(None)

    @on(Button.Pressed, "#btn_save")
    def on_save(self) -> None:
        results = {
            "auto_process": self.query_one("#cb_auto_process", Checkbox).value,
            "auto_cleanup": self.query_one("#cb_auto_cleanup", Checkbox).value,
        }
        self.dismiss(results)

    @on(Button.Pressed, "#btn_cancel")
    def on_cancel(self) -> None:
        self.dismiss(None)

class QueueViewerModal(ModalScreen):
    """A modal for viewing the current task queue."""
    CSS = """
    QueueViewerModal {
        align: center middle;
    }
    #queue_modal {
        width: 70;
        height: 60%;
        background: $surface;
        border: thick $primary;
        padding: 1;
    }
    #queue_title {
        text-align: center;
        width: 100%;
        margin-bottom: 1;
    }
    DataTable {
        height: 1fr;
        border: tall $surface;
    }
    #close_btn {
        margin-top: 1;
        width: 100%;
    }
    """
    BINDINGS = [
        ("escape", "close", "Close"),
        ("enter", "close", "Close"),
    ]

    def __init__(self, app_ref):
        super().__init__()
        self.app_ref = app_ref

    def compose(self) -> ComposeResult:
        with Vertical(id="queue_modal"):
            yield Label("Current Task Queue:", id="queue_title")
            yield DataTable()
            yield Button("Close", id="close_btn", variant="primary")

    def on_mount(self) -> None:
        table = self.query_one(DataTable)
        table.add_columns("Pos", "Action", "Progress", "Title", "ASIN")
        table.cursor_type = "row"
        self.update_queue()
        # Refresh every second
        self.set_interval(1.0, self.update_queue)

    def update_queue(self) -> None:
        """Polls the app state and updates the table."""
        table = self.query_one(DataTable)
        
        items = []
        # Active items
        for asin, log_data in self.app_ref.active_logs.items():
            book = next((b for b in self.app_ref.full_library if b.asin == asin), None)
            progress = self.app_ref._extract_progress(asin)
            items.append({
                "asin": asin,
                "title": book.title if book else "Unknown",
                "action": "Processing" if "Processing" in log_data["title"] else "Downloading",
                "progress": progress if progress else "..."
            })
        
        # Queued items
        queued_books = [b for b in self.app_ref.full_library if b.queued]
        for book in queued_books:
            status = self.app_ref.service.get_status(book.asin, book.title)
            action = "Download" if status == "" else "Process"
            items.append({
                "asin": book.asin,
                "title": book.title,
                "action": f"Queued ({action})",
                "progress": ""
            })

        # Save current state
        scroll_x, scroll_y = table.scroll_offset
        cursor_coord = table.cursor_coordinate

        table.clear()

        if not items:
            table.add_row("-", "Queue is empty", "-", "-", "-")
        else:
            for i, item in enumerate(items, 1):
                table.add_row(
                    str(i),
                    item.get("action", ""),
                    item.get("progress", ""),
                    item.get("title", ""),
                    item.get("asin", "")
                )

        # Restore state
        table.scroll_to(x=scroll_x, y=scroll_y, animate=False)
        if cursor_coord:
            try:
                table.move_cursor(row=cursor_coord.row, column=cursor_coord.column)
            except Exception:
                # Row might have been removed
                pass
    def action_close(self) -> None:
        self.dismiss()

    @on(Button.Pressed, "#close_btn")
    def on_close(self) -> None:
        self.dismiss()

class ColumnSettingsModal(ModalScreen):
    """A modal for selecting visible columns."""
    CSS = """
    ColumnSettingsModal {
        align: center middle;
    }
    #column_modal {
        width: 40;
        height: auto;
        background: $surface;
        border: thick $primary;
        padding: 1;
    }
    #column_title {
        text-align: center;
        width: 100%;
        margin-bottom: 1;
    }
    Checkbox {
        margin: 0 1;
    }
    """
    BINDINGS = [
        ("escape", "cancel", "Cancel"),
    ]

    def __init__(self, all_columns: list[str], visible_columns: list[str]):
        super().__init__()
        self.all_columns = all_columns
        self.visible_columns = visible_columns

    def compose(self) -> ComposeResult:
        with Vertical(id="column_modal"):
            yield Label("Select Visible Columns:", id="column_title")
            for col in self.all_columns:
                # Sanitize id for Textual
                safe_id = f"cb_{col.lower().replace(' ', '_').replace('#', 'seq')}"
                yield Checkbox(col, value=(col in self.visible_columns), id=safe_id)
            with Horizontal(classes="modal_buttons"):
                yield Button("Save", id="btn_save", variant="success")
                yield Button("Cancel", id="btn_cancel", variant="primary")

    def action_cancel(self) -> None:
        self.dismiss(None)

    @on(Button.Pressed, "#btn_save")
    def on_save(self) -> None:
        new_visible = []
        for col in self.all_columns:
            safe_id = f"#cb_{col.lower().replace(' ', '_').replace('#', 'seq')}"
            cb = self.query_one(safe_id, Checkbox)
            if cb.value:
                new_visible.append(col)
        self.dismiss(new_visible)

    @on(Button.Pressed, "#btn_cancel")
    def on_cancel(self) -> None:
        self.dismiss(None)
