# src/app/utils/logger.py
import logging
import os
import sys

# Determine if running in a test environment
IS_TEST_ENVIRONMENT = "pytest" in sys.modules

# Configure the logger
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()

# Basic configuration for the root logger
# This ensures that even loggers obtained via logging.getLogger() without specific handlers
# will output to the console, which is useful for development and debugging.
# For production, you might want more sophisticated handler setup (e.g., file, ELK, etc.)
logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    stream=sys.stdout  # Explicitly set stream to stdout
)

def get_logger(name: str) -> logging.Logger:
    """
    Retrieves a logger instance with the specified name.
    The logger will inherit the basic configuration.
    """
    logger = logging.getLogger(name)
    
    # If running in a test environment, you might want to suppress logging
    # or redirect it to a different handler to avoid cluttering test output.
    if IS_TEST_ENVIRONMENT:
        # Example: Disable logging for tests or set to a higher level
        # logger.setLevel(logging.CRITICAL + 1) # Effectively disables logging
        # Or add a NullHandler if you don't want any output during tests
        # logger.addHandler(logging.NullHandler())
        pass # For now, let test logs go through with INFO level

    return logger

# Example of a default logger for convenience, if desired.
# default_logger = get_logger("GenAICropsAnalyzerApp") 