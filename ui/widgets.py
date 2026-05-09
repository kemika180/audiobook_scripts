from textual.widgets import DataTable, Input, Log
from textual.binding import Binding
from textual.geometry import Spacing

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

    def _scroll_cursor_into_view(self, animate: bool = False) -> None:
        """Override to implement scrolloff using row region."""
        try:
            row, _ = self.cursor_coordinate
            # Use _get_row_region since cursor_type is "row"
            region = self._get_row_region(row)
            # scrolloff of 5 rows, force=True ensures spacing is respected
            self.scroll_to_region(
                region, 
                spacing=Spacing(5, 0, 5, 0), 
                animate=animate,
                force=True
            )
        except Exception:
            super()._scroll_cursor_into_view(animate)

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
