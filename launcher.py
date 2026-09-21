"""PyInstaller entry point kept outside the package for reliable imports."""

from prompt_manager.app import main


if __name__ == "__main__":
    raise SystemExit(main())
