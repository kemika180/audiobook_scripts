import pytest
import json
from unittest.mock import AsyncMock, patch, MagicMock
from pathlib import Path
from service import AudiobookService
from models import Audiobook

@pytest.mark.asyncio
async def test_fetch_library_json():
    config = {"library_path": "/tmp/audiobooks"}
    service = AudiobookService(config)
    
    # Mock data from audible api
    mock_json = {
        "items": [
            {
                "asin": "B01N26S3S6",
                "title": "Oathbringer",
                "authors": [{"name": "Brandon Sanderson"}],
                "series": [{"title": "The Stormlight Archive", "sequence": "3"}]
            }
        ]
    }
    
    with patch("asyncio.create_subprocess_exec") as mock_exec:
        mock_process = AsyncMock()
        mock_process.communicate.return_value = (json.dumps(mock_json).encode(), b"")
        mock_process.returncode = 0
        mock_exec.return_value = mock_process
        
        # Mock get_status to avoid filesystem checks
        with patch.object(AudiobookService, "get_status", return_value="✔"):
            books = await service.fetch_library()
            
            assert len(books) == 1
            book = books[0]
            assert book.asin == "B01N26S3S6"
            assert book.title == "Oathbringer"
            assert book.author == "Brandon Sanderson"
            assert book.series_title == "The Stormlight Archive"
            assert book.series_sequence == "3"
            assert book.status == "✔"

@pytest.mark.asyncio
async def test_verify_file_exists_async():
    config = {"library_path": "/tmp/audiobooks"}
    service = AudiobookService(config)
    
    mock_path = MagicMock(spec=Path)
    mock_path.exists.side_effect = [False, True]
    
    # This should wait for the second check
    result = await service.verify_file_exists(mock_path, timeout=1.0)
    assert result is True
    assert mock_path.exists.call_count == 2
