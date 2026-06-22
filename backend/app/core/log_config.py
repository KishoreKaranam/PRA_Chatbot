"""Structured logging configuration."""
import logging as _logging
import structlog
from app.core.settings import get_settings


def configure_logging() -> None:
    settings = get_settings()
    level = getattr(_logging, settings.log_level.upper(), _logging.INFO)

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.ConsoleRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
    )

    _logging.basicConfig(level=level)


def get_logger(name: str):
    return structlog.get_logger(name)
