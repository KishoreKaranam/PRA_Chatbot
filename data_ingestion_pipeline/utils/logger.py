# Shared helper to create simple file-based loggers.
# Every script calls get_logger(__name__) once and reuses the returned logger.
# All scripts write to the same logs/app.log file so you only have to check
# one place; the logger name in each line tells you which script logged it.

import logging
import os
from config.settings import LOG_DIR

LOG_FILE = os.path.join(LOG_DIR, "app.log")


def get_logger(name):
    """Return a logger that writes to the shared logs/app.log file."""

    logger = logging.getLogger(name)

    # Avoid adding duplicate handlers if get_logger is called more than once.
    if logger.handlers:
        return logger

    logger.setLevel(logging.INFO)

    file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")

    # Simple, readable log line: time, level, logger name, message.
    formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s")
    file_handler.setFormatter(formatter)

    logger.addHandler(file_handler)
    return logger
