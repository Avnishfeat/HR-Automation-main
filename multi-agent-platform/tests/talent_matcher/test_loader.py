import pytest
import json
from unittest.mock import patch, mock_open
from app.agents.talent_matcher.loader import load_employees

# Mock file content for a .jsonl file
MOCK_JSONL_CONTENT = """{"name": "Alice"}
{"name": "Bob"}"""

def test_load_employees_happy_path():
    """Tests that a valid .jsonl file is loaded correctly."""
    with patch("builtins.open", mock_open(read_data=MOCK_JSONL_CONTENT)):
        employees = load_employees("fake/path.jsonl")
    
    assert len(employees) == 2
    assert employees[0] == {"name": "Alice"}
    assert employees[1] == {"name": "Bob"}

# --- NEW TEST ADDED FOR 100% COVERAGE ---
def test_load_employees_empty_file():
    """Tests that an empty file returns an empty list."""
    with patch("builtins.open", mock_open(read_data="")):
        employees = load_employees("fake/empty.jsonl")
    
    assert len(employees) == 0
    assert employees == []

def test_load_employees_file_not_found():
    """Tests that FileNotFoundError is raised when file doesn't exist."""
    with patch("builtins.open", side_effect=FileNotFoundError("File not found")):
        with pytest.raises(FileNotFoundError) as exc_info:
            load_employees("fake/path.jsonl")
        assert "File not found" in str(exc_info.value)

def test_load_employees_bad_json():
    """Tests that invalid JSON in the file raises JSONDecodeError."""
    bad_json_content = '{"name": "Alice"}\n{not valid json}\n'
    with patch("builtins.open", mock_open(read_data=bad_json_content)):
        with pytest.raises(json.JSONDecodeError):
            load_employees("fake/path.jsonl")