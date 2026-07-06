import pytest
import asyncio
import json
from pathlib import Path
from unittest.mock import patch, MagicMock
from audiobook_manager import ConfigManager, TaskQueueManager

def test_config_manager_defaults():
    # Test that ConfigManager loads defaults when no file exists
    with patch("pathlib.Path.exists", return_value=False):
        cm = ConfigManager()
        assert cm.get("theme") == "kemika-purple"
        assert cm.get("auto_cleanup") is False
        assert cm["sort_reverse"] is False

def test_config_manager_persistence(tmp_path):
    # Test saving and loading from a real file in a temp directory
    config_file = tmp_path / "config.json"
    
    with patch("audiobook_manager.CONFIG_FILE", config_file), \
         patch("audiobook_manager.CONFIG_DIR", tmp_path), \
         patch("audiobook_manager.OLD_CONFIG_FILE", tmp_path / "old.json"):
        
        cm = ConfigManager()
        cm.set("theme", "nord")
        cm.set("auto_process", True)
        
        # Verify it saved to disk
        assert config_file.exists()
        with open(config_file, "r") as f:
            data = json.load(f)
            assert data["theme"] == "nord"
            assert data["auto_process"] is True
        
        # Verify a new instance loads it
        cm2 = ConfigManager()
        assert cm2["theme"] == "nord"
        assert cm2.get("auto_process") is True

@pytest.mark.asyncio
async def test_task_queue_manager_basic():
    tqm = TaskQueueManager()
    assert tqm.is_empty() is True
    
    tqm.put("ASIN1")
    assert tqm.is_empty() is False
    assert "ASIN1" in tqm.pending_asins
    
    asin = await tqm.get()
    assert asin == "ASIN1"
    assert "ASIN1" not in tqm.pending_asins

@pytest.mark.asyncio
async def test_task_queue_manager_remove():
    tqm = TaskQueueManager()
    tqm.put("ASIN1")
    tqm.put("ASIN2")
    tqm.put("ASIN3")
    
    # Remove middle item
    success = tqm.remove("ASIN2")
    assert success is True
    assert "ASIN2" not in tqm.pending_asins
    
    # Verify remaining items are in order
    asin1 = await tqm.get()
    assert asin1 == "ASIN1"
    asin3 = await tqm.get()
    assert asin3 == "ASIN3"
    
    assert tqm.is_empty() is True

@pytest.mark.asyncio
async def test_task_queue_manager_duplicates():
    tqm = TaskQueueManager()
    tqm.put("ASIN1")
    # Duplicate put should be ignored
    added = tqm.put("ASIN1")
    assert added is False
    
    await tqm.get()
    assert tqm.is_empty() is True
