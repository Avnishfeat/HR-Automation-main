# app/core/logging.py
import logging.config
import logging
import os
import re
from pathlib import Path
from typing import List

# Create a 'logs' directory at the project root if it doesn't exist
log_dir = Path(__file__).resolve().parents[2] / 'logs'
log_dir.mkdir(exist_ok=True)


class SecretsFilter(logging.Filter):
    """
    Logging filter that masks secret values in log messages.
    Prevents accidental exposure of credentials in logs.
    """
    
    def __init__(self, name: str = ""):
        super().__init__(name)
        self._patterns = []
        self._initialized = False
    
    def _lazy_init(self):
        """Lazily initialize patterns to avoid circular imports."""
        if self._initialized:
            return
        
        try:
            # Import global settings via helper to avoid direct complexity
            from app.core.config import settings
            
            secret_values = []
            
            # Explicitly list keys we want to mask
            keys_to_mask = [
                "GEMINI_API_KEY",
                "OPENAI_API_KEY"
            ]
            
            for key in keys_to_mask:
                if hasattr(settings, key):
                   val = getattr(settings, key)
                   if val:
                       secret_values.append(str(val))

            # Also mask anything that looks like a key if needed, or rely on explicit list
            
            for value in secret_values:
                if value and len(value) > 4:
                    # Escape special regex characters
                    escaped = re.escape(value)
                    self._patterns.append(re.compile(escaped))
            
            self._initialized = True
        except ImportError:
            # Config module not yet loaded, will retry next time
            pass
        except Exception as e:
            # Fallback to prevent logging failure
            print(f"Warning: Failed to initialize SecretsFilter: {e}")
    
    def filter(self, record: logging.LogRecord) -> bool:
        """Mask any secret values in the log message."""
        self._lazy_init()
        
        if self._patterns and hasattr(record, 'msg'):
            msg = str(record.msg)
            for pattern in self._patterns:
                msg = pattern.sub("[REDACTED]", msg)
            record.msg = msg
        
        # Also check args for secret values
        if self._patterns and record.args:
            new_args = []
            for arg in record.args:
                if isinstance(arg, str):
                   arg_str = arg
                   for pattern in self._patterns:
                       arg_str = pattern.sub("[REDACTED]", arg_str)
                   new_args.append(arg_str)
                else:
                   # Preserve original type (int, float, etc.) to valid logging formatting
                   new_args.append(arg)
            record.args = tuple(new_args)
        
        return True  # Always allow the record (after masking)


LOGGING_CONFIG = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'default': {
            'format': '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            'datefmt': '%Y-%m-%d %H:%M:%S',
        },
    },
    'filters': {
        'secrets_filter': {
            '()': SecretsFilter,
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'default',
            'level': 'INFO',
            'stream': 'ext://sys.stdout',
            'filters': ['secrets_filter'],
        },
        'info_file_handler': {
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': os.path.join(log_dir, 'info.log'),
            'maxBytes': 10485760,  # 10 MB
            'backupCount': 5,
            'formatter': 'default',
            'level': 'INFO',
            'encoding': 'utf-8',
            'filters': ['secrets_filter'],
        },
        'error_file_handler': {
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': os.path.join(log_dir, 'error.log'),
            'maxBytes': 10485760,  # 10 MB
            'backupCount': 5,
            'formatter': 'default',
            'level': 'ERROR',
            'encoding': 'utf-8',
            'filters': ['secrets_filter'],
        },
    },
    'loggers': {
        # Suppress noisy libav errors
        'libav.libvpx': {
            'level': 'CRITICAL',
            'handlers': ['console'],
            'propagate': False,
        },
        'libav': {
            'level': 'CRITICAL',
            'handlers': ['console'],
            'propagate': False,
        },
        'streamlit_webrtc.shutdown': {
            'level': 'CRITICAL',
            'handlers': ['console'],
            'propagate': False,
        },
        'httpx': {
            'level': 'WARNING',
            'handlers': ['console'],
            'propagate': False,
        },
        'httpcore': {
            'level': 'WARNING',
            'handlers': ['console'],
            'propagate': False,
        },
    },
    'root': {
        'level': 'INFO',
        'handlers': ['console', 'info_file_handler', 'error_file_handler'],
    },
}

def setup_logging():
    """Applies the logging configuration with secrets filtering."""
    logging.config.dictConfig(LOGGING_CONFIG)
