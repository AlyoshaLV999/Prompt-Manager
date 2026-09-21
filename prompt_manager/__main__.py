"""Allow ``python -m prompt_manager`` to start the application."""

from .app import main


if __name__ == "__main__":
    raise SystemExit(main())
