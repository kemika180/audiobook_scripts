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
async def test_fetch_library_multipart():
    config = {"library_path": "/tmp/audiobooks"}
    service = AudiobookService(config)
    
    mock_json = {
        "items": [
            {
                "asin": "B00WNBF0RM",
                "title": "Seveneves",
                "authors": [{"name": "Neal Stephenson"}],
                "relationships": [
                    {"asin": "B00WNBF5UE", "relationship_type": "component", "sort": "1"},
                    {"asin": "B00WNBFB62", "relationship_type": "component", "sort": "2"},
                    {"asin": "B00WNBFHFM", "relationship_type": "component", "sort": "3"},
                    {"asin": "B096Z883H3", "relationship_type": "series"} # Should be ignored for parts
                ]
            }
        ]
    }
    
    with patch("asyncio.create_subprocess_exec") as mock_exec:
        mock_process = AsyncMock()
        mock_process.communicate.return_value = (json.dumps(mock_json).encode(), b"")
        mock_process.returncode = 0
        mock_exec.return_value = mock_process
        
        with patch.object(AudiobookService, "get_status", return_value=""):
            books = await service.fetch_library()
            
            assert len(books) == 1
            book = books[0]
            assert len(book.parts) == 3
            assert book.parts == ["B00WNBF5UE", "B00WNBFB62", "B00WNBFHFM"]

def test_get_status_map_efficiency():
    config = {"library_path": "/tmp/audiobooks"}
    service = AudiobookService(config)
    
    # Mock filesystem
    with patch("pathlib.Path.exists", return_value=True), \
         patch("pathlib.Path.iterdir") as mock_iterdir:
        
        # Simulate files in directory
        mock_iterdir.return_value = [
            Path("B00WNBF0RM.m4b"), # Downloaded and converted
            Path("B01N26S3S6.aax"),  # Downloaded but not converted
            Path("B00WNBF5UE.aax")   # Part 1 of another book
        ]
        
        books = [
            Audiobook(asin="B00WNBF0RM", title="Seveneves", author="Neal Stephenson", parts=["B00WNBF5UE"]),
            Audiobook(asin="B01N26S3S6", title="Oathbringer", author="Brandon Sanderson"),
            Audiobook(asin="B000000000", title="Missing Book", author="Nobody")
        ]
        
        status_map = service.get_status_map(books)
        
        assert status_map["B00WNBF0RM"] == "[bold green]✔[/]"
        assert status_map["B01N26S3S6"] == "[bold yellow]⬇[/]"
        assert status_map["B000000000"] == ""

@pytest.mark.asyncio
async def test_process_m4b_command_generation():
    # This test verifies that process_m4b generates the correct FFmpeg command
    # for a standard single-part audiobook.
    config = {
        "library_path": "/tmp/audiobooks",
        "activation_bytes": "12345678"
    }
    service = AudiobookService(config)
    book = Audiobook(asin="B01N26S3S6", title="Oathbringer", author="Sanderson")
    
    # Mocking filesystem and external processes
    with patch("pathlib.Path.glob") as mock_glob, \
         patch("pathlib.Path.exists", return_value=True), \
         patch("pathlib.Path.unlink", MagicMock()), \
         patch("builtins.open", MagicMock()), \
         patch("json.load", return_value={"content_metadata": {"chapter_info": {"chapters": []}}}), \
         patch("tempfile.NamedTemporaryFile") as mock_temp:
        
        mock_temp.return_value.__enter__.return_value.name = "temp.ffmetadata"
        
        # Simulate finding files
        def side_effect(pattern):
            if ".json" in pattern: return [Path("/tmp/audiobooks/B01N26S3S6.json")]
            if "*.aax" in pattern: return [Path("/tmp/audiobooks/B01N26S3S6.aax")]
            if ".jpg" in pattern: return [Path("/tmp/audiobooks/B01N26S3S6.jpg")]
            return []
        mock_glob.side_effect = side_effect
        
        with patch("asyncio.create_subprocess_exec") as mock_exec:
            mock_process = AsyncMock()
            mock_process.communicate.return_value = (b"", b"")
            mock_process.wait.return_value = 0
            mock_process.returncode = 0
            mock_process.stdout = None
            mock_exec.return_value = mock_process
            
            # We also need to mock Path.rename to avoid actual move
            with patch("pathlib.Path.rename"):
                success = await service.process_m4b(book, lambda x: None)
                
                assert success is True
                # Verify FFmpeg command
                args, _ = mock_exec.call_args
                assert "ffmpeg" in args
                assert "-activation_bytes" in args
                assert "12345678" in args
                assert "/tmp/audiobooks/B01N26S3S6.aax" in args
                assert "temp.ffmetadata" in args

@pytest.mark.asyncio
async def test_series_parsing_priority():
    config = {"library_path": "/tmp/audiobooks"}
    service = AudiobookService(config)
    
    # Mock data with multiple series, one with sequence, one without
    mock_json = {
        "items": [
            {
                "asin": "B00HWF0MHW",
                "title": "Words of Radiance",
                "authors": [{"name": "Brandon Sanderson"}],
                "series": [
                    {"title": "The Cosmere", "sequence": ""},
                    {"title": "The Stormlight Archive", "sequence": "2"}
                ]
            }
        ]
    }
    
    with patch.object(service, "_run_process") as mock_run:
        mock_process = AsyncMock()
        mock_process.communicate.return_value = (json.dumps(mock_json).encode(), b"")
        mock_process.returncode = 0
        mock_run.return_value = mock_process
        
        with patch.object(AudiobookService, "get_status", return_value=""):
            books = await service.fetch_library()
            assert len(books) == 1
            # Should prioritize the one with sequence
            assert books[0].series_title == "The Stormlight Archive"
            assert books[0].series_sequence == "2"

@pytest.mark.asyncio
async def test_active_process_tracking():
    config = {"library_path": "/tmp/audiobooks"}
    service = AudiobookService(config)
    
    with patch("asyncio.create_subprocess_exec") as mock_exec:
        mock_process = AsyncMock()
        mock_process.returncode = None
        mock_process.terminate = MagicMock() # Should not be async
        mock_exec.return_value = mock_process
        
        # Run a process through the tracker
        proc = await service._run_process("ls")
        
        assert len(service._active_processes) == 1
        assert service._active_processes[0] == mock_process
        
        # Test shutdown
        await service.shutdown()
        mock_process.terminate.assert_called_once()

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
