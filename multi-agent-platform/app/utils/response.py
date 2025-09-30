from typing import Any, Optional

class APIResponse:
    """Standardized API response formatter"""
    
    @staticmethod
    def success(data: Any, message: str = "Success") -> dict:
        """Success response"""
        return {
            "success": True,
            "message": message,
            "data": data
        }
    
    @staticmethod
    def error(message: str, error_code: Optional[str] = None) -> dict:
        """Error response"""
        return {
            "success": False,
            "message": message,
            "error_code": error_code,
            "data": None
        }
