import pytest
from unittest.mock import MagicMock, patch
from audiobook_manager import AudiobookManager
from models import Audiobook

def test_selected_books_initialization():
    with patch("audiobook_manager.ConfigManager.load_config", return_value={}):
        app = AudiobookManager()
        assert hasattr(app, "selected_books")
        assert len(app.selected_books) == 0

def test_select_all_deselect_all():
    with patch("audiobook_manager.ConfigManager.load_config", return_value={}), \
         patch("audiobook_manager.AudiobookService") as mock_service:
        
        app = AudiobookManager()
        # Mock library lookup and full_library
        book1 = Audiobook(asin="ASIN1", author="Author 1", title="Title 1")
        book2 = Audiobook(asin="ASIN2", author="Author 2", title="Title 2")
        book3 = Audiobook(asin="ASIN3", author="Author 3", title="Title 3") # Completed book
        
        app.full_library = [book1, book2, book3]
        app._library_lookup = {"ASIN1": book1, "ASIN2": book2, "ASIN3": book3}
        
        # Mock service get_status to return completed for ASIN3
        def get_status(asin, title):
            if asin == "ASIN3":
                return "✔"
            return ""
        app.service.get_status = get_status
        
        # Mock query_one to return a mock table and label
        mock_table = MagicMock()
        mock_table.rows = [MagicMock(value="ASIN1"), MagicMock(value="ASIN2"), MagicMock(value="ASIN3")]
        mock_label = MagicMock()
        
        def mock_query_one(query, *args, **kwargs):
            if "library_table" in query:
                return mock_table
            if "library-status" in query:
                return mock_label
            return MagicMock()
            
        app.query_one = mock_query_one
        
        # Test select all
        app.action_select_all()
        # Completed book ASIN3 should not be selected
        assert "ASIN1" in app.selected_books
        assert "ASIN2" in app.selected_books
        assert "ASIN3" not in app.selected_books
        
        # Test deselect all
        app.action_deselect_all()
        assert len(app.selected_books) == 0

def test_process_selected():
    with patch("audiobook_manager.ConfigManager.load_config", return_value={}), \
         patch("audiobook_manager.AudiobookService") as mock_service:
        
        app = AudiobookManager()
        book1 = Audiobook(asin="ASIN1", author="Author 1", title="Title 1")
        book2 = Audiobook(asin="ASIN2", author="Author 2", title="Title 2")
        
        app.full_library = [book1, book2]
        app._library_lookup = {"ASIN1": book1, "ASIN2": book2}
        app.service.get_status = MagicMock(return_value="")
        
        mock_table = MagicMock()
        mock_label = MagicMock()
        mock_tabbed = MagicMock()
        mock_queue = MagicMock()
        mock_queue.scroll_offset = (0, 0)
        mock_queue.cursor_coordinate = None
        
        def mock_query_one(query, *args, **kwargs):
            if "library_table" in query:
                return mock_table
            if "library-status" in query:
                return mock_label
            if "TabbedContent" in query or "tabbed" in query.lower():
                return mock_tabbed
            if "queue-table" in query:
                return mock_queue
            return MagicMock()
            
        app.query_one = mock_query_one
        
        # Add to selected
        app.selected_books.add("ASIN1")
        app.selected_books.add("ASIN2")
        
        app.action_process_selected()
        
        # Should be removed from selected_books
        assert len(app.selected_books) == 0
        # Should be added to task queue
        assert book1.queued is True
        assert book2.queued is True
        assert app.task_queue.pending_count == 2
