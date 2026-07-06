from textual.widgets import DataTable, Input, RichLog
from textual.binding import Binding
from textual.geometry import Spacing

class NavigationMixin:
    """A mixin to share common navigation and action bindings."""
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
        Binding("x", "remove_from_queue", "Dequeue", show=False),
        Binding("~", "show_queue", "Queue", show=False),
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

    def action_remove_from_queue(self) -> None:
        self.app.action_remove_from_queue()

    def action_show_queue(self) -> None:
        self.app.action_show_queue()

    def action_quit(self) -> None:
        self.app.action_quit()

class SearchInput(Input):
    """An Input with custom bindings for navigation."""
    BINDINGS = [
        ("escape", "focus_library", "Back"),
    ]
    def action_focus_library(self) -> None:
        self.app.query_one("#library_table").focus()

class StatusLog(RichLog):
    """A RichLog for displaying logs."""
    pass

class LibraryTable(DataTable):
    """A DataTable with custom bindings for the library."""
    COMPONENT_CLASSES = DataTable.COMPONENT_CLASSES | {"datatable--selected"}

    BINDINGS = [
        Binding("up,k", "cursor_up", "Cursor Up", show=False),
        Binding("down,j", "cursor_down", "Cursor Down", show=False),
        Binding("left,h", "cursor_left", "Cursor Left", show=False),
        Binding("right,l", "cursor_right", "Cursor Right", show=False),
        Binding("home,g", "scroll_top", "Scroll Top", show=False),
        Binding("end,G", "scroll_bottom", "Scroll Bottom", show=False),
        Binding("space,enter", "toggle_select", "Toggle Select", show=False),
        Binding("/", "focus_search", "Search", show=False),
    ]

    def _scroll_cursor_into_view(self, animate: bool = False) -> None:
        """Manually implement scrolloff to preserve horizontal scroll stability."""
        try:
            row, _ = self.cursor_coordinate
            # scrollable_content_region.height is the actual space for data rows,
            # accounting for headers and horizontal scrollbars.
            visible_rows = self.scrollable_content_region.height
            if visible_rows <= 0:
                return super()._scroll_cursor_into_view(animate)

            current_y = int(self.scroll_offset.y)
            current_x = int(self.scroll_offset.x)

            scrolloff = 5

            # Calculate target Y to satisfy scrolloff margin
            target_y = current_y
            if row < current_y + scrolloff:
                target_y = row - scrolloff
            elif row >= current_y + visible_rows - 6: # Use 6 for bottom to ensure 5 full rows
                target_y = row - visible_rows + 6 + 1

            target_y = max(0, target_y)
            # Apply the calculated scroll, forcing horizontal to stay at current_x.
            # Use animate=False to prevent "jarring" fighting with default movement.
            if target_y != current_y:
                self.scroll_to(x=current_x, y=target_y, animate=False)
            else:
                # Even if Y doesn't change, re-enforce X to prevent default reset
                self.scroll_to(x=current_x, animate=False)
        except Exception:
            super()._scroll_cursor_into_view(animate)


    def action_scroll_top(self) -> None:
        """Move cursor to the very first row."""
        self.move_cursor(row=0)

    def action_scroll_bottom(self) -> None:
        """Move cursor to the very last row."""
        self.move_cursor(row=self.row_count - 1)

    def action_toggle_select(self) -> None:
        """Toggles row selection via app controller."""
        self.app.action_toggle_select()

    def action_focus_search(self) -> None:
        """Focuses the search bar."""
        self.app.action_focus_search()

    def _get_row_style(self, row_index: int, base_style) -> "Style":
        from rich.style import Style
        row_style = super()._get_row_style(row_index, base_style)
        if row_index >= 0 and row_index < len(self.rows):
            try:
                row_key = list(self.rows.keys())[row_index]
                asin = str(row_key.value)
                if asin in self.app.selected_books:
                    selected_style = self.get_component_styles("datatable--selected").rich_style
                    row_style = row_style + selected_style
            except Exception:
                pass
        return row_style

    def add_row_class(self, row_key, class_name: str) -> None:
        """Visual selection highlight handler."""
        if class_name == "datatable--selected":
            try:
                row_index = self.get_row_index(row_key)
                self._clear_caches()
                self.refresh_row(row_index)
            except Exception:
                self._clear_caches()
                self.refresh()

    def remove_row_class(self, row_key, class_name: str) -> None:
        """Visual selection removal handler."""
        if class_name == "datatable--selected":
            try:
                row_index = self.get_row_index(row_key)
                self._clear_caches()
                self.refresh_row(row_index)
            except Exception:
                self._clear_caches()
                self.refresh()


class QueueTable(DataTable):
    """A DataTable with custom bindings for the queue tab."""
    BINDINGS = [
        Binding("up,k", "cursor_up", "Cursor Up", show=False),
        Binding("down,j", "cursor_down", "Cursor Down", show=False),
        Binding("left,h", "cursor_left", "Cursor Left", show=False),
        Binding("right,l", "cursor_right", "Cursor Right", show=False),
        Binding("home,g", "scroll_top", "Scroll Top", show=False),
        Binding("end,G", "scroll_bottom", "Scroll Bottom", show=False),
        Binding("/", "focus_search", "Search", show=False),
    ]

    def action_scroll_top(self) -> None:
        """Move cursor to the very first row."""
        self.move_cursor(row=0)

    def action_scroll_bottom(self) -> None:
        """Move cursor to the very last row."""
        self.move_cursor(row=self.row_count - 1)

    def action_focus_search(self) -> None:
        """Focuses the search bar."""
        self.app.action_focus_search()
