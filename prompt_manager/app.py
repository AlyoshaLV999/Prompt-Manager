"""Application entry point."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

from .service import PromptService, default_data_directory
from .storage import PromptRepository
from .ui import MainWindow


def build_parser() -> argparse.ArgumentParser:
    """Build command-line options used by the desktop launcher."""

    parser = argparse.ArgumentParser(description="Prompt Manager")
    parser.add_argument(
        "--data-dir", type=Path, default=None,
        help="Override the directory used for the local SQLite database.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Start the GUI and return its process exit code."""

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = build_parser().parse_args(argv)
    data_dir = args.data_dir or default_data_directory()
    repository = PromptRepository(data_dir / "prompts.sqlite3")
    service = PromptService(repository)
    application = QApplication(sys.argv if argv is None else [sys.argv[0], *argv])
    application.setApplicationName("Prompt Manager")
    application.setOrganizationName("Prompt Manager")
    window = MainWindow(service)
    window.show()
    try:
        return application.exec()
    finally:
        repository.close()


if __name__ == "__main__":
    raise SystemExit(main())
