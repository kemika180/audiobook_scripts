import pytest
import argparse
import sys
import asyncio
from unittest.mock import AsyncMock, patch, MagicMock, ANY
from pathlib import Path

from audiobook_manager import run_cli, main, AudiobookManager
from models import Audiobook

@pytest.mark.asyncio
async def test_cli_list_command():
    # Setup mock arguments
    args = argparse.Namespace(
        subcommand="list",
        library_path="/tmp/audiobooks",
        activation_bytes="12345678",
        status=None,
        query=None
    )
    
    # Mock AudiobookService methods
    with patch("service.AudiobookService.is_authenticated", return_value=True) as mock_auth, \
         patch("service.AudiobookService.fetch_library") as mock_fetch, \
         patch("pathlib.Path.exists", return_value=True), \
         patch("rich.console.Console.print") as mock_print:
         
        mock_fetch.return_value = [
            Audiobook(asin="B01N26S3S6", title="Oathbringer", author="Sanderson", status="[bold green]✔[/]")
        ]
        
        await run_cli(args)
        
        mock_auth.assert_called_once()
        mock_fetch.assert_called_once()
        # Verify it printed the table
        assert mock_print.call_count > 0

@pytest.mark.asyncio
async def test_cli_download_command():
    args = argparse.Namespace(
        subcommand="download",
        library_path="/tmp/audiobooks",
        activation_bytes="12345678",
        asins=["B01N26S3S6"],
        auto_process=True,
        auto_cleanup=True
    )
    
    with patch("service.AudiobookService.is_authenticated", return_value=True) as mock_auth, \
         patch("service.AudiobookService.fetch_library") as mock_fetch, \
         patch("service.AudiobookService.download", return_value=0) as mock_download, \
         patch("service.AudiobookService.verify_file_exists", return_value=True), \
         patch("service.AudiobookService.process_m4b", return_value=True) as mock_process, \
         patch("service.AudiobookService.cleanup_sources", return_value=1) as mock_cleanup, \
         patch("pathlib.Path.exists", return_value=True), \
         patch("rich.console.Console.print"):
         
        mock_fetch.return_value = [
            Audiobook(asin="B01N26S3S6", title="Oathbringer", author="Sanderson")
        ]
        
        await run_cli(args)
        
        mock_auth.assert_called_once()
        mock_fetch.assert_called_once()
        mock_download.assert_called_once_with("B01N26S3S6", ANY)
        mock_process.assert_called_once()
        mock_cleanup.assert_called_once()

@pytest.mark.asyncio
async def test_cli_process_command():
    args = argparse.Namespace(
        subcommand="process",
        library_path="/tmp/audiobooks",
        activation_bytes="12345678",
        asins=["B01N26S3S6"],
        cleanup=True,
        no_cleanup=False
    )
    
    with patch("service.AudiobookService.fetch_library") as mock_fetch, \
         patch("service.AudiobookService.process_m4b", return_value=True) as mock_process, \
         patch("service.AudiobookService.cleanup_sources", return_value=2) as mock_cleanup, \
         patch("pathlib.Path.exists", return_value=True), \
         patch("rich.console.Console.print"):
         
        mock_fetch.return_value = [
            Audiobook(asin="B01N26S3S6", title="Oathbringer", author="Sanderson")
        ]
        
        await run_cli(args)
        
        mock_fetch.assert_called_once()
        mock_process.assert_called_once()
        mock_cleanup.assert_called_once()

@pytest.mark.asyncio
async def test_cli_sync_command():
    args = argparse.Namespace(
        subcommand="sync",
        library_path="/tmp/audiobooks",
        activation_bytes="12345678",
        asins=["B01N26S3S6"],
        cleanup=True
    )
    
    with patch("service.AudiobookService.is_authenticated", return_value=True) as mock_auth, \
         patch("service.AudiobookService.fetch_library") as mock_fetch, \
         patch("service.AudiobookService.download", return_value=0) as mock_download, \
         patch("service.AudiobookService.verify_file_exists", return_value=True), \
         patch("service.AudiobookService.process_m4b", return_value=True) as mock_process, \
         patch("service.AudiobookService.cleanup_sources", return_value=3) as mock_cleanup, \
         patch("pathlib.Path.exists", return_value=True), \
         patch("rich.console.Console.print"):
         
        mock_fetch.return_value = [
            Audiobook(asin="B01N26S3S6", title="Oathbringer", author="Sanderson")
        ]
        
        await run_cli(args)
        
        mock_auth.assert_called_once()
        mock_fetch.assert_called_once()
        mock_download.assert_called_once_with("B01N26S3S6", ANY)
        mock_process.assert_called_once()
        mock_cleanup.assert_called_once()

def test_main_tui_fallback():
    # If no subcommand, it should call AudiobookManager.run()
    with patch("argparse.ArgumentParser.parse_args") as mock_args, \
         patch.object(AudiobookManager, "run") as mock_run:
         
        mock_args.return_value = argparse.Namespace(
            subcommand=None,
            library_path=None,
            activation_bytes=None
        )
        
        main()
        mock_run.assert_called_once()
