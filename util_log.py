"""
Logging setup for nsclient_test_base.
Call setup_logging() once at startup before any other module logs.
"""

import logging
import sys
from pathlib import Path

LOG_FORMAT = "%(asctime)s [%(levelname)-7s] %(name)s - %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

NOISY_LOGGERS = ("urllib3", "requests", "chardet", "charset_normalizer")


def setup_logging(verbose: bool = False, log_file: Path | None = None) -> None:
    """
    Configure the root logger with a console handler and an optional file handler.

    Args:
        verbose: If True, set root level to DEBUG; otherwise INFO.
        log_file: Optional path to a log file.  Parent directory must exist.
    """
    level = logging.DEBUG if verbose else logging.INFO

    root = logging.getLogger()
    root.setLevel(level)

    # Avoid adding duplicate handlers on repeated calls
    if not root.handlers:
        _add_console_handler(root, level)

    if log_file is not None:
        _add_file_handler(root, log_file, level)

    for name in NOISY_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)


def _add_console_handler(logger: logging.Logger, level: int) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(level)
    handler.setFormatter(logging.Formatter(LOG_FORMAT, DATE_FORMAT))
    logger.addHandler(handler)


def _add_file_handler(logger: logging.Logger, log_file: Path, level: int) -> None:
    handler = logging.FileHandler(log_file, encoding="utf-8")
    handler.setLevel(level)
    handler.setFormatter(logging.Formatter(LOG_FORMAT, DATE_FORMAT))
    logger.addHandler(handler)
