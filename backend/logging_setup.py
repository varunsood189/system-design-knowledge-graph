"""Central logging configuration for the app and MCP subprocess."""

from __future__ import annotations

import logging
import os
import sys


def configure_logging() -> None:
    level_name = (os.getenv("LOG_LEVEL") or "INFO").strip().upper()
    level = getattr(logging, level_name, logging.INFO)

    fmt = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
    datefmt = "%H:%M:%S"

    root = logging.getLogger()
    if root.handlers:
        root.setLevel(level)
        return

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter(fmt=fmt, datefmt=datefmt))
    root.addHandler(handler)
    root.setLevel(level)

    for name in ("uvicorn", "uvicorn.access", "uvicorn.error"):
        logging.getLogger(name).setLevel(level)

    logging.getLogger(__name__).info("Logging configured level=%s", level_name)
