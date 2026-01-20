# app/core/exceptions.py
"""
Custom exception classes for the interview bot system.
These exceptions provide structured error handling with context.
"""
from typing import Optional, Dict, Any


class InterviewBotException(Exception):
    """Base exception for all interview bot errors."""
    
    def __init__(
        self,
        message: str,
        error_code: str = "INTERNAL_ERROR",
        status_code: int = 500,
        details: Optional[Dict[str, Any]] = None,
        recoverable: bool = False
    ):
        self.message = message
        self.error_code = error_code
        self.status_code = status_code
        self.details = details or {}
        self.recoverable = recoverable
        super().__init__(self.message)


class ServiceInitializationError(InterviewBotException):
    """Raised when a service fails to initialize."""
    
    def __init__(self, service_name: str, reason: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(
            message=f"Failed to initialize {service_name}: {reason}",
            error_code="SERVICE_INIT_ERROR",
            status_code=503,
            details={"service": service_name, "reason": reason, **(details or {})},
            recoverable=False
        )


class SessionError(InterviewBotException):
    """Raised when there's an issue with a session."""
    
    def __init__(
        self,
        session_id: str,
        message: str,
        error_code: str = "SESSION_ERROR",
        status_code: int = 400,
        details: Optional[Dict[str, Any]] = None
    ):
        super().__init__(
            message=message,
            error_code=error_code,
            status_code=status_code,
            details={"session_id": session_id, **(details or {})},
            recoverable=True
        )


class SessionNotFoundError(SessionError):
    """Raised when a session is not found."""
    
    def __init__(self, session_id: str):
        super().__init__(
            session_id=session_id,
            message=f"Session {session_id} not found",
            error_code="SESSION_NOT_FOUND",
            status_code=404
        )


class InterviewExecutionError(InterviewBotException):
    """Raised when interview execution fails."""
    
    def __init__(
        self,
        session_id: str,
        stage: str,
        reason: str,
        details: Optional[Dict[str, Any]] = None
    ):
        super().__init__(
            message=f"Interview execution failed at {stage}: {reason}",
            error_code="INTERVIEW_EXECUTION_ERROR",
            status_code=500,
            details={
                "session_id": session_id,
                "stage": stage,
                "reason": reason,
                **(details or {})
            },
            recoverable=True
        )


class ExternalServiceError(InterviewBotException):
    """Raised when an external service (STT, TTS, LLM) fails."""
    
    def __init__(
        self,
        service_name: str,
        operation: str,
        reason: str,
        status_code: int = 503,
        details: Optional[Dict[str, Any]] = None,
        retryable: bool = True
    ):
        super().__init__(
            message=f"{service_name} service failed during {operation}: {reason}",
            error_code=f"{service_name.upper()}_SERVICE_ERROR",
            status_code=status_code,
            details={
                "service": service_name,
                "operation": operation,
                "reason": reason,
                "retryable": retryable,
                **(details or {})
            },
            recoverable=retryable
        )


class ValidationError(InterviewBotException):
    """Raised when input validation fails."""
    
    def __init__(
        self,
        field: str,
        reason: str,
        details: Optional[Dict[str, Any]] = None
    ):
        super().__init__(
            message=f"Validation failed for {field}: {reason}",
            error_code="VALIDATION_ERROR",
            status_code=400,
            details={"field": field, "reason": reason, **(details or {})},
            recoverable=True
        )


class DatabaseError(InterviewBotException):
    """Raised when database operations fail."""
    
    def __init__(
        self,
        operation: str,
        reason: str,
        details: Optional[Dict[str, Any]] = None,
        retryable: bool = True
    ):
        super().__init__(
            message=f"Database operation '{operation}' failed: {reason}",
            error_code="DATABASE_ERROR",
            status_code=503,
            details={
                "operation": operation,
                "reason": reason,
                "retryable": retryable,
                **(details or {})
            },
            recoverable=retryable
        )


class MeetConnectionError(InterviewBotException):
    """Raised when Google Meet connection fails."""
    
    def __init__(
        self,
        session_id: str,
        reason: str,
        details: Optional[Dict[str, Any]] = None
    ):
        super().__init__(
            message=f"Failed to connect to Google Meet: {reason}",
            error_code="MEET_CONNECTION_ERROR",
            status_code=503,
            details={"session_id": session_id, "reason": reason, **(details or {})},
            recoverable=True
        )


class AnalysisError(InterviewBotException):
    """Raised when analysis operations fail."""
    
    def __init__(
        self,
        analysis_type: str,
        session_id: str,
        reason: str,
        details: Optional[Dict[str, Any]] = None
    ):
        super().__init__(
            message=f"{analysis_type} analysis failed: {reason}",
            error_code="ANALYSIS_ERROR",
            status_code=500,
            details={
                "analysis_type": analysis_type,
                "session_id": session_id,
                "reason": reason,
                **(details or {})
            },
            recoverable=True
        )


class ResourceNotFoundError(InterviewBotException):
    """Raised when a required resource is not found."""
    
    def __init__(
        self,
        resource_type: str,
        resource_id: str,
        details: Optional[Dict[str, Any]] = None
    ):
        super().__init__(
            message=f"{resource_type} '{resource_id}' not found",
            error_code="RESOURCE_NOT_FOUND",
            status_code=404,
            details={"resource_type": resource_type, "resource_id": resource_id, **(details or {})},
            recoverable=False
        )

