
import pytest
import json
from pathlib import Path
from unittest.mock import patch, MagicMock
from audiobook_manager import ConfigManager

def test_config_default_values():
    with patch("audiobook_manager.CONFIG_FILE") as mock_file, \
         patch("audiobook_manager.OLD_CONFIG_FILE") as mock_old, \
         patch("audiobook_manager.OLD_MANAGER_CONFIG_FILE") as mock_old_mgr:
        mock_file.exists.return_value = False
        mock_old.exists.return_value = False
        mock_old_mgr.exists.return_value = False
        
        manager = ConfigManager()
        assert manager.get("theme") == "tokyo-night"
        assert manager.get("auto_cleanup") is False

def test_config_save_load(tmp_path):
    config_file = tmp_path / "config.json"
    config_dir = tmp_path
    
    with patch("audiobook_manager.CONFIG_FILE", config_file), \
         patch("audiobook_manager.CONFIG_DIR", config_dir), \
         patch("audiobook_manager.OLD_CONFIG_FILE", tmp_path / "old.json"), \
         patch("audiobook_manager.OLD_MANAGER_CONFIG_FILE", tmp_path / "old_mgr.json"):
        
        manager = ConfigManager()
        manager.set("theme", "dracula")
        manager.save()
        
        assert config_file.exists()
        
        # New manager should load the saved value
        new_manager = ConfigManager()
        assert new_manager.get("theme") == "dracula"

def test_config_migration(tmp_path):
    old_file = tmp_path / "old.json"
    new_file = tmp_path / "config.json"
    config_dir = tmp_path
    
    old_data = {"theme": "monokai", "sort_column": "author"}
    with open(old_file, "w") as f:
        json.dump(old_data, f)
        
    with patch("audiobook_manager.CONFIG_FILE", new_file), \
         patch("audiobook_manager.CONFIG_DIR", config_dir), \
         patch("audiobook_manager.OLD_CONFIG_FILE", old_file), \
         patch("audiobook_manager.OLD_MANAGER_CONFIG_FILE", tmp_path / "old_mgr.json"):
        
        manager = ConfigManager()
        assert manager.get("theme") == "monokai"
        # Verify sort_order migration
        assert manager.get("sort_order")[0] == "author"
        assert not old_file.exists()
        assert new_file.exists()
