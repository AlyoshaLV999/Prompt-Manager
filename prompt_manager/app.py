"""Application entry point."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication, QMessageBox

from .service import PromptService, default_data_directory, legacy_database_candidates
from .storage import PromptRepository, StorageError, migrate_legacy_database
from .ui import MainWindow


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
    args = build_parser().parse_args(argv)
    data_dir = (args.data_dir or default_data_directory()).expanduser()
    database_path = data_dir / "prompts.sqlite3"
    # argparse owns the application options; do not let Qt reinterpret them.
    application = QApplication([sys.argv[0]])
    application.setApplicationName("Prompt Manager")
    application.setOrganizationName("Prompt Manager")
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
