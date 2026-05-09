from textual.app import ComposeResult
from textual.binding import Binding
from textual.geometry import Spacing
from textual.widgets import Header, Footer, DataTable, Input, Button, Label, Log, RichLog
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
            yield RichLog(id="process_log", highlight=True, markup=True)
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
