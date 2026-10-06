"""Application entry point."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication, QMessageBox

from .icon import create_app_icon
from .service import PromptService, default_data_directory, legacy_database_candidates
from .storage import PromptRepository, StorageError, migrate_legacy_database
from .ui import MainWindow


# Stable, application-specific identifier used to tell Windows that this
# process is a distinct application.  Windows groups taskbar buttons by this
# value, so changing it would split the app's taskbar presence across two
# identities.  The string is intentionally free of any version suffix so that
# release upgrades keep the same taskbar identity and pinned shortcuts keep
# working.
WINDOWS_APP_USER_MODEL_ID = "PromptManager.Desktop"


def _configure_windows_taskbar_identity() -> None:
    """Assign an explicit AppUserModelID to the current Windows process.

    Windows groups taskbar buttons by AppUserModelID.  When the process has
    no explicit ID, the shell falls back to the executable path and paints
    the taskbar button with the icon embedded in the ``.exe``.  This makes
    ``QApplication.setWindowIcon`` appear to have no effect for PyInstaller
    builds, because the shell never consults the top-level window icon.

    Assigning a stable, application-specific ID makes Windows treat this
    process as its own application, so the taskbar button is drawn from the
    window icon the application installs via :func:`create_app_icon`.

    The function is a no-op on non-Windows platforms.  Any failure to reach
    the Windows shell API is logged and swallowed: the application remains
    fully usable without the identity hint.
    """

    if sys.platform != "win32":
        return
    try:
        import ctypes
    except ImportError:
        logging.getLogger(__name__).debug(
            "ctypes is unavailable; skipping Windows AppUserModelID setup"
        )
        return
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            WINDOWS_APP_USER_MODEL_ID
        )
    except (AttributeError, OSError) as exc:
        logging.getLogger(__name__).warning(
            "无法设置 Windows AppUserModelID，任务栏图标可能仍使用可执行文件图标: %s",
            exc,
        )


def build_parser() -> argparse.ArgumentParser:
    """Build command-line options used by the desktop launcher."""

    parser = argparse.ArgumentParser(description="Prompt Manager")
    parser.add_argument(
        "--data-dir", type=Path, default=None,
        help="Override the persistent directory used for the local SQLite database.",
    )
    parser.add_argument(
        "--migrate-from", type=Path, default=None,
        help="Import an existing legacy SQLite database on first launch.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Start the GUI and return its process exit code."""

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    # The AppUserModelID must be installed before the first top-level window
    # is shown; otherwise the taskbar button is created against the default
    # (exe-derived) identity and will not pick up the window icon.
    _configure_windows_taskbar_identity()
    args = build_parser().parse_args(argv)
    data_dir = (args.data_dir or default_data_directory()).expanduser()
    database_path = data_dir / "prompts.sqlite3"
    # argparse owns the application options; do not let Qt reinterpret them.
    application = QApplication([sys.argv[0]])
    application.setApplicationName("Prompt Manager")
    application.setOrganizationName("Prompt Manager")
    application.setWindowIcon(create_app_icon())
    try:
        migrated_from = migrate_legacy_database(
            database_path,
            legacy_database_candidates(args.migrate_from),
        )
        repository = PromptRepository(database_path)
    except StorageError as exc:
        logging.exception("无法准备提示词数据库")
        QMessageBox.critical(None, "无法打开数据", str(exc))
        return 1
    if migrated_from is not None:
        logging.info("已将旧数据库迁移到持久化数据目录: %s", migrated_from)
    service = PromptService(repository)
    window = MainWindow(service)
    window.show()
    try:
        return application.exec()
    finally:
        repository.close()


if __name__ == "__main__":
    raise SystemExit(main())