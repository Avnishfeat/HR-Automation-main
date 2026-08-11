"""Collect interview-scoped error logs for final webhook delivery."""

from contextvars import ContextVar, Token
from datetime import datetime, timezone
import logging
from threading import Lock

_current_session_id: ContextVar[str | None] = ContextVar("interview_session_id", default=None)
_errors_by_session: dict[str, list[dict[str, str]]] = {}
_errors_lock = Lock()
_MAX_ERRORS_PER_SESSION = 100
_MAX_MESSAGE_LENGTH = 2_000


def set_error_tracking_session(session_id: str) -> Token:
    """Associate error logs in this async task (and its child tasks) with a session."""
    return _current_session_id.set(session_id)


def reset_error_tracking_session(token: Token) -> None:
    _current_session_id.reset(token)


def record_session_error(
    session_id: str,
    component: str,
    message: str,
    error_type: str = "AgentError",
) -> None:
    """Store a sanitized, bounded error event for a single interview."""
    event = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "component": component,
        "type": error_type,
        "message": str(message)[:_MAX_MESSAGE_LENGTH],
    }
    with _errors_lock:
        events = _errors_by_session.setdefault(session_id, [])
        if len(events) < _MAX_ERRORS_PER_SESSION:
            events.append(event)


def get_session_errors(session_id: str) -> list[dict[str, str]]:
    """Return a copy so callers cannot mutate the stored events."""
    with _errors_lock:
        return list(_errors_by_session.get(session_id, []))


def clear_session_errors(session_id: str) -> None:
    with _errors_lock:
        _errors_by_session.pop(session_id, None)


class _SessionErrorLogHandler(logging.Handler):
    """Capture ERROR/CRITICAL records emitted by interview-agent code."""

    _is_session_error_handler = True

    def emit(self, record: logging.LogRecord) -> None:
        session_id = _current_session_id.get()
        if not session_id or record.levelno < logging.ERROR:
            return
        if not record.name.startswith("app.agents.interview"):
            return

        try:
            error_type = "LoggedError"
            if record.exc_info and record.exc_info[0]:
                error_type = record.exc_info[0].__name__
            record_session_error(session_id, record.name, record.getMessage(), error_type)
        except Exception:
            # Error collection must never interfere with application logging.
            self.handleError(record)


def install_session_error_log_handler() -> None:
    """Install the collector once, even when application setup is repeated in tests."""
    root_logger = logging.getLogger()
    if any(getattr(handler, "_is_session_error_handler", False) for handler in root_logger.handlers):
        return
    root_logger.addHandler(_SessionErrorLogHandler(level=logging.ERROR))
