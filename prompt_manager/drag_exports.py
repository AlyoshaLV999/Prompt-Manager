"""Create and expire Markdown files used only while dragging saved prompts."""

from __future__ import annotations

import logging
import os
import re
import time
from pathlib import Path
from uuid import uuid4

from PySide6.QtCore import QCoreApplication, QObject, QTimer

from .service import PromptService, ValidationError
from .storage import StorageError

logger = logging.getLogger(__name__)

CLEANUP_INTERVAL_MS = 30_000
DEFAULT_RETENTION_MINUTES = 2
MIN_RETENTION_MINUTES = 1
MAX_RETENTION_MINUTES = 1_440
MAX_FILENAME_BYTES = 180
_INVALID_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_WINDOWS_RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{number}" for number in range(1, 10)),
    *(f"LPT{number}" for number in range(1, 10)),
}


class DragExportError(OSError):
    """Raised when a saved prompt cannot be exposed as a temporary file."""


class PromptDragExportManager(QObject):
    """Own temporary Markdown exports for prompt-list drag operations.

    Exports live beside the application log in a dedicated directory. The
    database remains the source of truth; files exist only to provide a local
    file URL to applications that accept dragged files.
    """

    def __init__(self, service: PromptService, log_directory: Path, retention_minutes: int,
                 parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._service = service
        self.directory = log_directory / "drag_export_md"
        self._retention_seconds = self._normalize_retention(retention_minutes) * 60
        self._timer = QTimer(self)
        self._timer.setInterval(CLEANUP_INTERVAL_MS)
        self._timer.timeout.connect(self.cleanup_expired)
        self._cleanup_expired()
        self._timer.start()
        application = QCoreApplication.instance()
        if application is not None:
            application.aboutToQuit.connect(self.shutdown)

    @staticmethod
    def _normalize_retention(minutes: int) -> int:
        """Clamp persisted or programmatic retention values to supported limits."""

        return max(MIN_RETENTION_MINUTES, min(MAX_RETENTION_MINUTES, int(minutes)))

    def set_retention_minutes(self, minutes: int) -> None:
        """Apply a newly saved expiry period without recreating the timer."""

        self._retention_seconds = self._normalize_retention(minutes) * 60
        self.cleanup_expired()

    def export_prompt(self, prompt_id: int) -> Path:
        """Write a prompt's current Markdown content and return its file path.

        Repeated drags of the same named entry replace its previous export.

        :param prompt_id: Database identifier of the saved prompt.
        :return: Absolute path of the temporary Markdown file.
        :raises DragExportError: If the prompt is missing or file I/O fails.
        """

        prompt = self._service.get_prompt(prompt_id)
        if prompt is None:
            raise DragExportError(f"条目 {prompt_id} 已不存在，无法导出")
        try:
            content = self._service.render_with_remembered_values(prompt)
            self._ensure_directory()
            target = self.directory / f"{self._safe_stem(prompt.name, prompt_id)}.md"
            temporary = self.directory / f".{uuid4().hex}.tmp"
            try:
                with temporary.open("x", encoding="utf-8", newline="") as output:
                    output.write(content)
                    output.flush()
                    os.fsync(output.fileno())
                if os.name != "nt":
                    temporary.chmod(0o600)
                os.replace(temporary, target)
            finally:
                temporary.unlink(missing_ok=True)
            logger.info("Temporary drag export written prompt_id=%d content_chars=%d", prompt_id, len(content))
            return target
        except (OSError, StorageError, ValidationError) as exc:
            logger.warning("Temporary drag export failed prompt_id=%d error=%s", prompt_id, type(exc).__name__)
            raise DragExportError(f"无法创建临时 Markdown 文件：{exc}") from exc

    @staticmethod
    def _safe_stem(name: str, prompt_id: int) -> str:
        """Return a cross-platform safe filename component based on the title."""

        stem = _INVALID_FILENAME_CHARS.sub("_", name).strip().rstrip(". ")
        while stem and len(stem.encode("utf-8")) > MAX_FILENAME_BYTES:
            stem = stem[:-1].rstrip(". ")
        if not stem:
            stem = f"prompt-{prompt_id}"
        if stem.split(".", 1)[0].upper() in _WINDOWS_RESERVED_NAMES:
            stem = f"_{stem}"
        return stem

    def cleanup_expired(self) -> None:
        """Remove exports older than the configured age, using modification time."""

        self._cleanup_expired()

    def _cleanup_expired(self) -> None:
        if not self.directory.exists():
            return
        if self.directory.is_symlink() or not self.directory.is_dir():
            logger.warning("Drag export path is not a regular directory")
            return
        cutoff = time.time() - self._retention_seconds
        try:
            for path in self.directory.iterdir():
                try:
                    if path.is_symlink():
                        if path.lstat().st_mtime < cutoff:
                            path.unlink()
                    elif path.is_file() and path.stat().st_mtime < cutoff:
                        path.unlink()
                except OSError as exc:
                    logger.warning("Cannot remove expired drag export path=%s error=%s", path.name, type(exc).__name__)
        except OSError as exc:
            logger.warning("Cannot scan drag export directory error=%s", type(exc).__name__)

    def shutdown(self) -> None:
        """Stop periodic cleanup and remove all remaining temporary exports."""

        self._timer.stop()
        if not self.directory.exists():
            return
        if self.directory.is_symlink() or not self.directory.is_dir():
            logger.warning("Cannot clean drag export path because it is not a regular directory")
            return
        try:
            for path in self.directory.iterdir():
                try:
                    if path.is_symlink() or path.is_file():
                        path.unlink()
                except OSError as exc:
                    logger.warning("Cannot remove drag export at shutdown path=%s error=%s", path.name, type(exc).__name__)
            self.directory.rmdir()
        except OSError as exc:
            logger.warning("Cannot clean drag export directory at shutdown error=%s", type(exc).__name__)

    def _ensure_directory(self) -> None:
        """Create a private export directory and refuse symlink redirection."""

        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        if self.directory.is_symlink() or not self.directory.is_dir():
            raise OSError("临时文件目录不是普通目录")
        if os.name != "nt":
            self.directory.chmod(0o700)
