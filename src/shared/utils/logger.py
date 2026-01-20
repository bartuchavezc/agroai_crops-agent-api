# src/shared/utils/logger.py
"""
Logging configuration for the application.
"""
import logging
import os
import sys

# Determine if running in a test environment
IS_TEST_ENVIRONMENT = "pytest" in sys.modules

# Configure the logger
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()

# Basic configuration for the root logger
logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    stream=sys.stdout
)


def get_logger(name: str) -> logging.Logger:
    """
    Retrieves a logger instance with the specified name.
    The logger will inherit the basic configuration.
    """
    logger = logging.getLogger(name)
    
    if IS_TEST_ENVIRONMENT:
        # For tests, you might want to suppress or redirect logging
        pass

    return logger
