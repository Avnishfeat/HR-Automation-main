# File: tests/services/test_file_service.py

import pytest
import os
from unittest.mock import patch, MagicMock, mock_open, AsyncMock
from app.services.file_service import FileService
from fastapi import UploadFile

# --- FIX: Corrected fixture for async context manager ---
@pytest.fixture
def mock_aiofiles():
    mock_file_handle = AsyncMock()
    mock_file_handle.read = AsyncMock(return_value=b"file content")

    # Create a *regular* MagicMock for the context manager
    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_file_handle)
    mock_cm.__aexit__ = AsyncMock()
    
    # Patch aiofiles.open to be a *function* that *returns* the context manager
    with patch("aiofiles.open", return_value=mock_cm) as mock_open_call:
        yield mock_open_call, mock_file_handle
# --- END FIX ---

@pytest.fixture
def file_service():
    with patch("pathlib.Path.mkdir"):
        service = FileService(upload_dir="./test_uploads")
    return service

@pytest.mark.asyncio
async def test_save_file_with_subfolder(file_service: FileService, mock_aiofiles: tuple):
    """
    Tests saving a file into a specified subfolder.
    Covers the `if subfolder:` block.
    """
    mock_open, mock_file = mock_aiofiles
    
    mock_upload_file = MagicMock(spec=UploadFile)
    mock_upload_file.filename = "test.txt"
    mock_upload_file.read = AsyncMock(return_value=b"test data")

    with patch("pathlib.Path.mkdir") as mock_mkdir:
        result = await file_service.save_file(mock_upload_file, subfolder="invoices")
    
    mock_mkdir.assert_called_with(parents=True, exist_ok=True)
    assert "invoices" in str(mock_open.call_args[0][0])
    mock_file.write.assert_called_once_with(b"test data")

@pytest.mark.asyncio
async def test_save_file_no_subfolder(file_service: FileService, mock_aiofiles: tuple):
    """
    Tests saving a file without a subfolder.
    Covers the `else:` block in save_file.
    """
    mock_open, mock_file = mock_aiofiles
    
    mock_upload_file = MagicMock(spec=UploadFile)
    mock_upload_file.filename = "test.txt"
    mock_upload_file.read = AsyncMock(return_value=b"no subfolder")

    with patch("pathlib.Path.mkdir"):
        result = await file_service.save_file(mock_upload_file, subfolder=None)
    
    # Assert path does NOT contain the 'invoices' subfolder
    assert "invoices" not in str(mock_open.call_args[0][0])
    assert "test_uploads" in str(mock_open.call_args[0][0])
    mock_file.write.assert_called_once_with(b"no subfolder")

@pytest.mark.asyncio
async def test_read_file(file_service: FileService, mock_aiofiles: tuple):
    """Tests reading a file. Covers the `read_file` method."""
    mock_open, mock_file = mock_aiofiles
    
    content = await file_service.read_file("fake/path.txt")
    
    assert content == b"file content"
    mock_open.assert_called_once_with("fake/path.txt", 'rb')

def test_delete_file_success(file_service: FileService):
    """Tests successful file deletion. Covers `delete_file` try block."""
    with patch("os.remove") as mock_remove:
        result = file_service.delete_file("fake/path.txt")
        assert result is True

def test_delete_file_fails(file_service: FileService):
    """Tests graceful failure on file deletion. Covers `except` block."""
    with patch("os.remove", side_effect=OSError("Permission denied")):
        result = file_service.delete_file("fake/path.txt")
        assert result is False