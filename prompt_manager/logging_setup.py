"""Process-wide, bounded diagnostic logging beside the application database."""

from __future__ import annotations

import logging
import os
import sys
import threading
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOG_NAME = "prompt_manager.log"
LOG_MAX_BYTES = 10 * 1024 * 1024
LOG_BACKUP_COUNT = 5
LOG_FORMAT = "%(asctime)s %(levelname)-7s [%(process)d:%(threadName)s] %(name)s: %(message)s"


class _PrivateRotatingFileHandler(RotatingFileHandler):
    """Create new log files with owner-only permissions on supported systems."""

    def _open(self):
        flags = os.O_CREAT | os.O_APPEND | os.O_WRONLY
        if hasattr(os, "O_BINARY"):
            flags |= os.O_BINARY
        descriptor = os.open(self.baseFilename, flags, 0o600)
        return os.fdopen(descriptor, self.mode, encoding=self.encoding, errors=self.errors)


def configure_logging(data_dir: Path) -> Path | None:
    """Record DEBUG and higher beside the database, retaining five rotated files.

    If the log cannot be opened, keep the application usable and report the
    failure on stderr. Repeated startup in one process replaces our old file
    handler so events are not duplicated or written to an outdated data dir.
    """

    root = logging.getLogger()
    for handler in list(root.handlers):
        if isinstance(handler, _PrivateRotatingFileHandler):
            root.removeHandler(handler)
            handler.close()
    if not root.handlers:
        console = logging.StreamHandler()
        console.setLevel(logging.INFO)
        console.setFormatter(logging.Formatter(LOG_FORMAT))
        root.addHandler(console)
    root.setLevel(logging.INFO)
    logging.getLogger("prompt_manager").setLevel(logging.DEBUG)
    path = data_dir / LOG_NAME
    file_handler: _PrivateRotatingFileHandler | None = None
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        file_handler = _PrivateRotatingFileHandler(
            path, maxBytes=LOG_MAX_BYTES, backupCount=LOG_BACKUP_COUNT,
            encoding="utf-8", errors="backslashreplace",
        )
        if os.name != "nt":
            path.chmod(0o600)
    except OSError as exc:
        if file_handler is not None:
            file_handler.close()
        logging.getLogger(__name__).warning("Cannot open diagnostic log in %s: %s", data_dir, exc)
        return None
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(LOG_FORMAT))
    root.addHandler(file_handler)
    logging.getLogger(__name__).info("Logging started: %s", path)
    return path


def install_exception_hooks() -> None:
    """Capture otherwise unhandled main and Python worker-thread exceptions."""

    if getattr(sys.excepthook, "_prompt_manager_logging_hook", False):
        return
    previous_main_hook = sys.excepthook
    previous_thread_hook = threading.excepthook

    def on_exception(exc_type, exc_value, traceback) -> None:
        logging.getLogger(__name__).critical(
            "Uncaught exception", exc_info=(exc_type, exc_value, traceback)
        )
        previous_main_hook(exc_type, exc_value, traceback)

    def on_thread_exception(args: threading.ExceptHookArgs) -> None:
        logging.getLogger(__name__).critical(
            "Uncaught Python thread exception in %s", args.thread.name if args.thread else "unknown",
            exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
        )
        previous_thread_hook(args)

    on_exception._prompt_manager_logging_hook = True  # type: ignore[attr-defined]
    sys.excepthook = on_exception
    threading.excepthook = on_thread_exception
