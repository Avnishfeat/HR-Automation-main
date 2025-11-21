# File: tests/services/test_llm_service.py

import pytest
import os
import asyncio
import logging
from unittest.mock import patch, MagicMock, AsyncMock
from fastapi import HTTPException

from app.services.llm_service import LLMService
from app.core.config import Settings

@pytest.fixture
def mock_settings():
    return Settings(
        GEMINI_API_KEY="fake-key", 
        GENAI_MODEL="gemini-test",
        MONGODB_URL="mongodb://test",
        DATABASE_NAME="test"
    )

def test_init_no_api_key(mock_settings: Settings, caplog):
    """Tests that init logs a critical error if API key is missing."""
    mock_settings.GEMINI_API_KEY = None
    with caplog.at_level(logging.CRITICAL):
        with patch("google.generativeai.configure"):
            service = LLMService(mock_settings)
    assert service.model is None
    assert "GEMINI_API_KEY not found in settings" in caplog.text

def test_init_model_fallback(mock_settings: Settings):
    """Tests that the fallback model 'gemini-2.5-flash' is used."""
    mock_settings.GENAI_MODEL = None 
    with patch("google.generativeai.configure"):
        with patch("google.generativeai.GenerativeModel") as mock_gen_model:
            service = LLMService(mock_settings)
    mock_gen_model.assert_called_once_with("gemini-2.5-flash")

def test_init_generic_exception(mock_settings: Settings, caplog):
    """Tests the general except block in __init__."""
    with caplog.at_level(logging.CRITICAL):
        with patch("google.generativeai.configure", side_effect=Exception("Auth error")):
            service = LLMService(mock_settings)
    assert service.model is None
    assert "Fatal error during LLMService initialization: Auth error" in caplog.text

# --- NEW TEST TO COVER 1 MISSING LINE ---
@pytest.mark.asyncio
async def test_upload_file_success(mock_settings: Settings):
    """Tests the successful path for upload_file."""
    with patch("google.generativeai.configure"):
        service = LLMService(mock_settings)

    mock_uploaded_file = MagicMock()
    mock_uploaded_file.name = "gemini-file-name"

    with patch("tempfile.NamedTemporaryFile") as mock_temp_file:
        mock_file_obj = MagicMock()
        mock_file_obj.name = "fake/temp/path.pdf"
        mock_temp_file.return_value.__enter__.return_value = mock_file_obj
        
        with patch("os.path.exists", return_value=True):
            with patch("os.remove"):
                # Mock asyncio.to_thread to return a successful upload
                with patch("asyncio.to_thread", return_value=mock_uploaded_file) as mock_async_upload:
                    
                    result = await service.upload_file(b"pdf-bytes", "test.pdf")
                    
                    # Assert success
                    assert result is mock_uploaded_file
                    mock_async_upload.assert_called_once()
# --- END NEW TEST ---

@pytest.mark.asyncio
async def test_upload_file_cleanup_on_failure(mock_settings: Settings):
    """Tests that the temporary file is deleted even if the upload fails."""
    with patch("google.generativeai.configure"):
        service = LLMService(mock_settings)

    with patch("tempfile.NamedTemporaryFile") as mock_temp_file:
        mock_file_obj = MagicMock()
        mock_file_obj.name = "fake/temp/path.pdf"
        mock_temp_file.return_value.__enter__.return_value = mock_file_obj
        
        with patch("os.path.exists", return_value=True) as mock_exists:
            with patch("os.remove") as mock_remove:
                with patch("asyncio.to_thread", side_effect=Exception("Upload Failed")):
                    
                    with pytest.raises(HTTPException) as e:
                        await service.upload_file(b"pdf-bytes", "test.pdf")
                    
                    assert e.value.status_code == 500
                    mock_exists.assert_called_with("fake/temp/path.pdf")
                    mock_remove.assert_called_with("fake/temp/path.pdf")

@pytest.mark.asyncio
async def test_generate_text_success_with_files(mock_settings: Settings):
    """Tests the successful path for generate_text with the `if files:` block."""
    with patch("google.generativeai.configure"):
        service = LLMService(mock_settings)

    mock_response = MagicMock()
    mock_response.text = " Mocked AI Response "
    service.model.generate_content_async = AsyncMock(return_value=mock_response)
    mock_file = MagicMock()
    prompt = "Test prompt"
    
    result = await service.generate_text(prompt, files=[mock_file])
    
    assert result == "Mocked AI Response"
    service.model.generate_content_async.assert_called_once_with([prompt, mock_file])

# --- NEW TEST TO COVER 1 MISSING LINE ---
@pytest.mark.asyncio
async def test_generate_text_success_no_files(mock_settings: Settings):
    """
    Tests the successful path for generate_text *without* files.
    Covers the `if files:` (False) path.
    """
    with patch("google.generativeai.configure"):
        service = LLMService(mock_settings)

    mock_response = MagicMock()
    mock_response.text = " Response without files "
    service.model.generate_content_async = AsyncMock(return_value=mock_response)
    prompt = "Test prompt"
    
    # Act
    result = await service.generate_text(prompt, files=None)
    
    # Assert
    assert result == "Response without files"
    # Check that contents were just the prompt
    service.model.generate_content_async.assert_called_once_with([prompt])
# --- END NEW TEST ---

@pytest.mark.asyncio
async def test_generate_text_no_model(mock_settings: Settings):
    """Tests that generate_text raises 503 if model failed to init."""
    with patch("google.generativeai.configure"):
        service = LLMService(mock_settings)
    service.model = None 
    
    with pytest.raises(HTTPException) as e:
        await service.generate_text("test")
    assert e.value.status_code == 503

@pytest.mark.asyncio
async def test_generate_text_api_fails(mock_settings: Settings):
    """Tests that a generic exception from the API is caught."""
    with patch("google.generativeai.configure"):
        service = LLMService(mock_settings)

    service.model.generate_content_async = AsyncMock(
        side_effect=Exception("API Call Failed")
    )
    
    with pytest.raises(HTTPException) as e:
        await service.generate_text("test")
    assert e.value.status_code == 502