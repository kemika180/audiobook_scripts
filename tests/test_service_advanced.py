
import pytest
import asyncio
from unittest.mock import AsyncMock, patch, MagicMock
from pathlib import Path
from service import AudiobookService
from models import Audiobook

@pytest.mark.asyncio
async def test_merge_aax_parts_success():
    service = AudiobookService({"library_path": "/tmp/audiobooks"})
    aax_files = [Path("/tmp/part1.aax"), Path("/tmp/part2.aax")]
    
    with patch.object(service, "_run_process") as mock_run, \
         patch("builtins.open", MagicMock()), \
         patch("pathlib.Path.exists", return_value=True), \
         patch("pathlib.Path.unlink", MagicMock()):
        
        mock_process = AsyncMock()
        mock_process.wait.return_value = 0
        mock_process.returncode = 0
        mock_process.stdout.read.side_effect = [b"FFmpeg output\n", b""]
        mock_run.return_value = mock_process
        
        # We expect 3 subprocess calls: 2 for decryption, 1 for merging
        result = await service.merge_aax_parts(aax_files, "12345678", lambda x: None)
        
        assert result == Path("/tmp/part1.merged.tmp.m4a")
        assert mock_run.call_count == 3

@pytest.mark.asyncio
async def test_merge_aax_parts_failure():
    service = AudiobookService({"library_path": "/tmp/audiobooks"})
    aax_files = [Path("/tmp/part1.aax")]
    
    with patch.object(service, "_run_process") as mock_run:
        mock_process = AsyncMock()
        mock_process.wait.return_value = 1
        mock_process.returncode = 1
        mock_run.return_value = mock_process
        
        result = await service.merge_aax_parts(aax_files, "12345678", lambda x: None)
        assert result is None

@pytest.mark.asyncio
async def test_process_m4b_multipart_flow():
    service = AudiobookService({"library_path": "/tmp/audiobooks", "activation_bytes": "12345678"})
    book = Audiobook(asin="B01N26S3S6", title="Oathbringer", author="Sanderson", parts=["PART1", "PART2"])
    
    with patch("pathlib.Path.glob") as mock_glob, \
         patch("pathlib.Path.exists", return_value=True), \
         patch("pathlib.Path.unlink", MagicMock()), \
         patch("builtins.open", MagicMock()), \
         patch("json.load", return_value={
             "content_metadata": {
                 "chapter_info": {
                     "chapters": [{"title": "Chapter 1", "start_offset_ms": 0, "length_ms": 1000}]
                 }
             }
         }), \
         patch("tempfile.NamedTemporaryFile") as mock_temp, \
         patch.object(service, "merge_aax_parts") as mock_merge, \
         patch.object(service, "_run_process") as mock_run:
        
        mock_temp.return_value.__enter__.return_value.name = "temp.ffmetadata"
        mock_merge.return_value = Path("/tmp/merged.m4a")
        
        # Mock glob to find JSON and multiple AAX files
        def side_effect(pattern):
            if ".json" in pattern: return [Path("/tmp/audiobooks/B01N26S3S6.json")]
            if "*.aax" in pattern: return [Path("/tmp/audiobooks/PART1.aax"), Path("/tmp/audiobooks/PART2.aax")]
            if ".jpg" in pattern: return [Path("/tmp/audiobooks/B01N26S3S6.jpg")]
            return []
        mock_glob.side_effect = side_effect
        
        mock_process = AsyncMock()
        mock_process.wait.return_value = 0
        mock_process.returncode = 0
        mock_process.stdout.read.side_effect = [b"FFmpeg output\n", b""]
        mock_run.return_value = mock_process
        
        with patch("pathlib.Path.rename"):
            success = await service.process_m4b(book, lambda x: None)
            assert success is True
            mock_merge.assert_called_once()

def test_play_audiobook_fallback_logic():
    service = AudiobookService({"library_path": Path("/tmp/audiobooks")})
    book = Audiobook(asin="B01N26S3S6", title="Title With Spaces", author="Author")
    
    # Mocking Path.exists to fail for title-based path but succeed for ASIN-based path
    # Using create=True because os.startfile doesn't exist on non-Windows
    with patch("pathlib.Path.exists") as mock_exists, \
         patch("platform.system", return_value="Windows"), \
         patch("os.startfile", create=True) as mock_startfile:
        
        # 1st call: Title.m4b exists? (False)
        # 2nd call: ASIN.m4b exists? (True)
        mock_exists.side_effect = [False, True]
        
        success, error = service.play_audiobook(book)
        
        assert success is True
        assert error is None
        # Should have called startfile with the ASIN-based path
        mock_startfile.assert_called_once_with(str(Path("/tmp/audiobooks/B01N26S3S6.m4b")))

@pytest.mark.asyncio
async def test_shutdown_cleanup():
    service = AudiobookService({})
    
    mock_p1 = AsyncMock()
    mock_p1.returncode = None
    mock_p1.terminate = MagicMock()
    mock_p1.kill = MagicMock()
    mock_p1.wait = AsyncMock(return_value=0)
    
    service._active_processes = [mock_p1]
    
    # We want to trigger the kill branch, so we mock pending as non-empty
    with patch("asyncio.wait", return_value=(set(), {mock_p1})):
        await service.shutdown()
        
        mock_p1.terminate.assert_called_once()
        mock_p1.kill.assert_called_once()
        assert len(service._active_processes) == 0
