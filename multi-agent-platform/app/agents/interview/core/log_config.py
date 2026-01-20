# app/core/log_config.py
import logging.config
import logging
import os
import re
from pathlib import Path

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
            from app.config.secrets import secrets
            
            # Get all secret values for masking
            secret_values = secrets.get_all_values_for_masking()
            
            for value in secret_values:
                if value and len(value) > 4:
                    # Escape special regex characters
                    escaped = re.escape(value)
                    self._patterns.append(re.compile(escaped))
            
            self._initialized = True
        except ImportError:
            # Secrets module not yet loaded, will retry next time
            pass
    
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
                arg_str = str(arg)
                for pattern in self._patterns:
                    arg_str = pattern.sub("[REDACTED]", arg_str)
                new_args.append(arg_str)
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
        # Suppress noisy libav errors (video decoding issues are common and non-critical)
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
        # Suppress streamlit_webrtc shutdown errors (harmless event loop warnings)
        'streamlit_webrtc.shutdown': {
            'level': 'CRITICAL',
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