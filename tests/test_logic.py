import pytest
import re
from utils import sanitize_filename, convert_chapters_json_to_ffmetadata

def test_audible_parsing_regex():
    # Simulate the regex used in the service
    pattern = re.compile(r'^([^:]+):\s*([^:]+):\s*(.*)$')
    
    # Standard line
    line1 = "B002V0QIT2: Stephen King: IT"
    m1 = pattern.match(line1)
    assert m1.groups() == ("B002V0QIT2", "Stephen King", "IT")
    
    # Title with colon
    line2 = "B01N26S3S6: Brandon Sanderson: Oathbringer: Stormlight Archive, Book 3"
    m2 = pattern.match(line2)
    assert m2.groups() == ("B01N26S3S6", "Brandon Sanderson", "Oathbringer: Stormlight Archive, Book 3")

    # Author with colon (unlikely but possible)
    line3 = "ASIN12345: Author: Name: Title"
    m3 = pattern.match(line3)
    assert m3.groups() == ("ASIN12345", "Author", "Name: Title")

def test_sanitize_filename_basic():
    assert sanitize_filename("Normal Title") == "Normal_Title"
    assert sanitize_filename("Title with Space") == "Title_with_Space"

def test_sanitize_filename_special_chars():
    assert "Invalid" in sanitize_filename("Invalid: Title?")
    assert ":" not in sanitize_filename("Invalid: Title?")
    assert "?" not in sanitize_filename("Invalid: Title?")
    assert "/" not in sanitize_filename("Path/To/Title")

def test_sanitize_filename_empty():
    assert sanitize_filename("") == "unnamed_audiobook"
    assert sanitize_filename(None) == "unnamed_audiobook"

def test_sanitize_filename_truncation():
    long_title = "a" * 300
    sanitized = sanitize_filename(long_title)
    assert len(sanitized) == 200

def test_convert_chapters_json_to_ffmetadata():
    sample_json = {
        "content_metadata": {
            "chapter_info": {
                "chapters": [
                    {
                        "start_offset_ms": 0,
                        "length_ms": 1000,
                        "title": "Chapter 1"
                    },
                    {
                        "start_offset_ms": 1000,
                        "length_ms": 2000,
                        "title": "Chapter 2",
                        "chapters": [
                            {
                                "start_offset_ms": 1000,
                                "length_ms": 500,
                                "title": "Subchapter 2.1"
                            }
                        ]
                    }
                ]
            }
        }
    }
    result = convert_chapters_json_to_ffmetadata(sample_json)
    
    assert result[0] == ";FFMETADATA1"
    assert "[CHAPTER]" in result
    assert "TIMEBASE=1/1000" in result
    assert "START=0" in result
    assert "END=1000" in result
    assert "TITLE=Chapter 1" in result
    # Check recursive
    assert "TITLE=Subchapter 2.1" in result
    assert "START=1000" in result
    assert "END=1500" in result

def test_convert_chapters_with_tags():
    sample_json = {
        "content_metadata": {
            "chapter_info": {
                "chapters": [
                    {
                        "start_offset_ms": 0,
                        "length_ms": 1000,
                        "title": "Chapter 1"
                    }
                ]
            }
        }
    }
    tags = {"title": "My Book", "artist": "The Author"}
    result = convert_chapters_json_to_ffmetadata(sample_json, tags=tags)
    
    assert "TITLE=My Book" in result
    assert "ARTIST=The Author" in result
    # Check that tags come before chapters usually (per my implementation)
    assert result.index("TITLE=My Book") < result.index("[CHAPTER]")
