"""Application logging.

uvicorn configures only its own loggers (``uvicorn``, ``uvicorn.error``,
``uvicorn.access``). Everything the app itself logs propagates to the root
logger, which had no handler: Python's last-resort handler prints WARNING and
above to a bare unformatted stderr line and drops INFO/DEBUG entirely. In
production that meant "POST /api/v1/ingest/apple-pay HTTP/1.1 422" in the
container log with nothing saying *why*.

:func:`configure_logging` installs one stderr handler on the root logger at
the level from ``LOG_LEVEL``, so ``docker logs`` / Coolify show what the app
did. uvicorn's own loggers keep their config (``disable_existing_loggers`` is
off and their ``propagate`` flags are untouched), so access lines stay as they
were.
"""

import logging
import logging.config

from app.core.config import settings

LOG_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def configure_logging() -> None:
    """Install the app's stderr log handler. Safe to call more than once.

    Raises RuntimeError for a typo'd LOG_LEVEL: a silently ignored level
    would look exactly like "the app logs nothing".
    """
    level = str(settings.log_level).upper()
    if level not in logging.getLevelNamesMapping():
        raise RuntimeError(
            f"LOG_LEVEL '{settings.log_level}' is not a logging level "
            f"(use one of: {', '.join(sorted(logging.getLevelNamesMapping()))})."
        )
    logging.config.dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "default": {"format": LOG_FORMAT, "datefmt": DATE_FORMAT},
            },
            "handlers": {
                "console": {
                    "class": "logging.StreamHandler",
                    "stream": "ext://sys.stderr",
                    "formatter": "default",
                },
            },
            "root": {"handlers": ["console"], "level": level},
        }
    )
