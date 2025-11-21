# File: tests/services/test_logger.py

import logging
from app.services.logger import setup_logger

def test_setup_logger():
    """
    Tests that the setup_logger function runs and returns a logger instance.
    This will cover the 4 missing lines.
    """
    logger = setup_logger()
    assert isinstance(logger, logging.Logger)