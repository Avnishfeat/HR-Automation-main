# File: tests/agents/question_generator/test_router.py

import pytest
import json
import io
import os
# <-- FIX: Add 'call' to the import list
from unittest.mock import MagicMock, AsyncMock, patch, mock_open, ANY, call 

from fastapi.testclient import TestClient
from app.services.llm_service import LLMService

ENDPOINT_URL = "/api/v1/question_generator/generate"

@pytest.fixture(autouse=True)
def reset_llm_mock(mock_llm_service: MagicMock):
    """
    Automatically resets the mock LLM service before each test in this module.
    This prevents test state leakage.
    """
    mock_llm_service.reset_mock()
    
    # Set default async mocks for methods that will be called
    mock_llm_service.upload_file = AsyncMock(
        return_value=MagicMock(name="MockUploadedFile")
    )
    mock_llm_service.generate_text = AsyncMock(
        return_value=json.dumps(["Default Question 1?"])
    )
    yield


class TestQuestionGeneratorRouter:

    def test_generate_success_200(self, api_client: TestClient, mock_llm_service: MagicMock):
        """Tests the happy path: valid inputs, file save, and 200 OK response."""
        # Arrange
        expected_qs = ["Generated Q1?", "Generated Q2?"]
        mock_llm_service.generate_text.return_value = json.dumps(expected_qs)
        
        mock_uploaded_file_obj = MagicMock(name="MockUploadedFile")
        mock_llm_service.upload_file.return_value = mock_uploaded_file_obj

        form_data = {
            "jd_text": "Senior Developer JD",
            "requirements": ["Python", "FastAPI"]
        }
        file_content = b"This is a fake PDF resume."
        files = {
            "resume_file": ("John_Doe_resume.pdf", file_content, "application/pdf")
        }

        # Act: Patch os.makedirs and builtins.open to test the file saving side-effect
        with patch("os.makedirs") as mock_makedirs, \
             patch("builtins.open", new_callable=mock_open) as mock_file_handle:
            
            response = api_client.post(ENDPOINT_URL, data=form_data, files=files)

        # Assert
        assert response.status_code == 200
        resp_json = response.json()
        assert resp_json["status"] is True
        assert resp_json["questions"] == expected_qs

        # Assert LLM service was called correctly
        mock_llm_service.upload_file.assert_called_once_with(
            file_bytes=file_content,
            display_name="John_Doe_resume.pdf"
        )
        mock_llm_service.generate_text.assert_called_once_with(
            ANY, # The prompt
            files=[mock_uploaded_file_obj]
        )

        # Assert file was saved correctly (with name cleaning)
        mock_makedirs.assert_called_once_with("saved_questions", exist_ok=True)
        
        expected_path = os.path.join("saved_questions", "John Doe_questions.txt")
        mock_file_handle.assert_called_once_with(
            expected_path, "w", encoding="utf-8"
        )
        
        # <-- FIX: Changed 'pytest.call' to just 'call'
        mock_file_handle().write.assert_has_calls([
            call("1. Generated Q1?\n"),
            call("2. Generated Q2?\n")
        ])

    def test_generate_invalid_file_type_400(self, api_client: TestClient, mock_llm_service: MagicMock):
        """Tests that an invalid MIME type is rejected with a 400 error."""
        # Arrange
        form_data = {"jd_text": "JD", "requirements": ["Python"]}
        files = {"resume_file": ("image.png", b"fake-png-bytes", "image/png")}

        # Act
        response = api_client.post(ENDPOINT_URL, data=form_data, files=files)

        # Assert
        assert response.status_code == 400
        assert "Invalid file type" in response.json()["detail"]
        mock_llm_service.upload_file.assert_not_called()

    def test_generate_missing_file_422(self, api_client: TestClient):
        """Tests that a request missing the 'resume_file' gets a 422 error."""
        # Arrange
        form_data = {"jd_text": "JD", "requirements": ["Python"]}

        # Act
        response = api_client.post(ENDPOINT_URL, data=form_data) # No files

        # Assert
        assert response.status_code == 422
        assert "Field required" in response.text

    def test_generate_llm_upload_fails_500(self, api_client: TestClient, mock_llm_service: MagicMock):
        """Tests a 500 error if llm_service.upload_file fails."""
        # Arrange
        mock_llm_service.upload_file.side_effect = Exception("Upload API Down")
        
        form_data = {"jd_text": "JD", "requirements": ["Python"]}
        files = {"resume_file": ("resume.pdf", b"bytes", "application/pdf")}

        # Act
        response = api_client.post(ENDPOINT_URL, data=form_data, files=files)

        # Assert
        assert response.status_code == 500
        assert "Upload API Down" in response.json()["detail"]

    def test_generate_llm_fails_bad_json_400(self, api_client: TestClient, mock_llm_service: MagicMock):
        """Tests a 400 error if the service raises ValueError (from bad JSON)."""
        # Arrange
        mock_llm_service.generate_text.return_value = "This is not valid JSON"
        
        form_data = {"jd_text": "JD", "requirements": ["Python"]}
        files = {"resume_file": ("resume.pdf", b"bytes", "application/pdf")}

        # Act
        response = api_client.post(ENDPOINT_URL, data=form_data, files=files)

        # Assert
        assert response.status_code == 400
        assert "The LLM returned an invalid format" in response.json()["detail"]

    def test_file_save_fails_gracefully(self, api_client: TestClient, mock_llm_service: MagicMock):
        """
        Tests that the request still succeeds (200 OK) even if saving the
        file to disk fails (e.g., due to permissions).
        """
        # Arrange
        expected_qs = ["Questions returned successfully"]
        mock_llm_service.generate_text.return_value = json.dumps(expected_qs)
        
        form_data = {"jd_text": "JD", "requirements": ["Python"]}
        files = {"resume_file": ("resume.pdf", b"bytes", "application/pdf")}

        # Act
        with patch("os.makedirs", side_effect=PermissionError("Access Denied")):
            response = api_client.post(ENDPOINT_URL, data=form_data, files=files)

        # Assert
        # The request *succeeds* even though the side-effect failed
        assert response.status_code == 200
        assert response.json()["questions"] == expected_qs

    def test_file_name_cleaning_with_cv_suffix(self, api_client: TestClient, mock_llm_service: MagicMock):
        """Tests that the name cleaning logic correctly removes '_cv'."""
        # Arrange
        form_data = {"jd_text": "JD", "requirements": ["Python"]}
        files = {"resume_file": ("Jane_Smith_cv.docx", b"bytes", "application/vnd.openxmlformats-officedocument.wordprocessingml.document")}

        # Act
        with patch("os.makedirs"), patch("builtins.open", new_callable=mock_open) as mock_file:
            response = api_client.post(ENDPOINT_URL, data=form_data, files=files)

        # Assert
        assert response.status_code == 200
        
        expected_path = os.path.join("saved_questions", "Jane Smith_questions.txt")
        mock_file.assert_called_once_with(
            expected_path, "w", encoding="utf-8"
        )