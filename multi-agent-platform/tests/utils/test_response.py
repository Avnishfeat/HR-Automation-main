# File: tests/utils/test_response.py

from app.utils.response import APIResponse

def test_api_response_success():
    """
    Tests the success response formatter.
    """
    response = APIResponse.success(data={"id": 1}, message="Created")
    
    assert response == {
        "success": True,
        "message": "Created",
        "data": {"id": 1}
    }

def test_api_response_error():
    """
    Tests the error response formatter.
    This covers the 2 missing lines.
    """
    response = APIResponse.error(message="Not found", error_code="404")
    
    assert response == {
        "success": False,
        "message": "Not found",
        "error_code": "404",
        "data": None
    }