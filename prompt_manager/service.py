"""Application use cases and validation around the storage layer."""

from __future__ import annotations

import os
import re
import sys
from collections.abc import Mapping
from pathlib import Path

from .models import Prompt
from .placeholders import IMPORT_PATTERN, PlaceholderError, extract_imports, extract_placeholders, render_replacements
from .storage import PromptRepository, StorageError


class ValidationError(ValueError):
    """Raised when user input violates a prompt contract."""


class PromptService:
    """Coordinate validation, persistence, and recursive prompt rendering."""

    MAX_NAME_LENGTH = 200
    MAX_CONTENT_LENGTH = 2_000_000
    VALID_KINDS = {"prompt", "fixed"}

    def __init__(self, repository: PromptRepository) -> None:
        self.repository = repository

    def list_prompts(self, kind: str | None = None) -> list[Prompt]:
        """Return all prompts or one category."""

        if kind is not None and kind not in self.VALID_KINDS:
            raise ValidationError("未知提示词类别")
        return self.repository.list_prompts(kind)

    def get_prompt(self, prompt_id: int) -> Prompt | None:
        """Return a prompt by id."""

        return self.repository.get_prompt(prompt_id)

    def find_prompt_by_name(self, name: str, kind: str | None = None) -> Prompt | None:
        """Find a named prompt, optionally restricting the category."""

        return self.repository.find_prompt_by_name(name.strip(), kind)

    def create_prompt(self, name: str, content: str, kind: str = "prompt") -> Prompt:
        """Validate and create a prompt."""

        clean_name, clean_content, clean_kind = self._validate_prompt(name, content, kind)
        try:
            return self.repository.create_prompt(clean_name, clean_content, clean_kind)
        except StorageError as exc:
            raise ValidationError(str(exc)) from exc

    def update_prompt(self, prompt_id: int, name: str, content: str, kind: str) -> Prompt:
        """Validate and update a prompt."""

        clean_name, clean_content, clean_kind = self._validate_prompt(name, content, kind)
        try:
            return self.repository.update_prompt(prompt_id, clean_name, clean_content, clean_kind)
        except StorageError as exc:
            raise ValidationError(str(exc)) from exc

    def delete_prompt(self, prompt_id: int) -> None:
        """Delete one prompt and its remembered values."""

        self.repository.delete_prompt(prompt_id)

    def placeholders_for(self, prompt: Prompt | str) -> list[str]:
        """Return ordered unique replacement titles."""

        try:
            return extract_placeholders(prompt.content if isinstance(prompt, Prompt) else prompt)
        except PlaceholderError as exc:
            raise ValidationError(str(exc)) from exc

    def imports_for(self, prompt: Prompt | str) -> list[str]:
        """Return ordered unique fixed-preset references."""

        try:
            return extract_imports(prompt.content if isinstance(prompt, Prompt) else prompt)
        except PlaceholderError as exc:
            raise ValidationError(str(exc)) from exc

    def remembered_values(self, prompt_id: int) -> dict[str, str]:
        """Return values previously entered for a prompt."""

        return self.repository.get_placeholder_values(prompt_id)

    def save_values(self, prompt_id: int, values: Mapping[str, str]) -> None:
        """Persist current input values for future use."""

        self.repository.save_placeholder_values(prompt_id, values.items())

    def render(self, prompt: Prompt, values: Mapping[str, str]) -> str:
        """Expand imports recursively, then replace user-input markers."""

        def expand(content: str, stack: tuple[str, ...]) -> str:
            def replace(match: re.Match[str]) -> str:
                title = match.group(1).strip()
                imported = self.find_prompt_by_name(title, "fixed")
                if imported is None:
                    return match.group(0)
                if imported.name.casefold() in {item.casefold() for item in stack}:
                    return f"[循环导入: {title}]"
                return expand(imported.content, (*stack, imported.name))

            return IMPORT_PATTERN.sub(replace, content)

        return render_replacements(expand(prompt.content, (prompt.name,)), values)

    def settings(self) -> dict[str, str]:
        """Return persisted UI settings."""

        return self.repository.get_settings()

    def save_settings(self, settings: Mapping[str, str]) -> None:
        """Persist UI settings."""

        self.repository.save_settings(settings)

    def _validate_prompt(self, name: str, content: str, kind: str) -> tuple[str, str, str]:
        clean_name = name.strip()
        if not clean_name:
            raise ValidationError("提示词名称不能为空")
        if len(clean_name) > self.MAX_NAME_LENGTH:
            raise ValidationError(f"提示词名称不能超过 {self.MAX_NAME_LENGTH} 个字符")
        if kind not in self.VALID_KINDS:
            raise ValidationError("未知提示词类别")
        if not isinstance(content, str) or not content.strip():
            raise ValidationError("提示词内容不能为空")
        if len(content) > self.MAX_CONTENT_LENGTH:
            raise ValidationError("提示词内容过长，不能超过 2,000,000 个字符")
        try:
            extract_placeholders(content)
            extract_imports(content)
        except PlaceholderError as exc:
            raise ValidationError(str(exc)) from exc
        return clean_name, content, kind


def default_data_directory() -> Path:
    """Return the platform-appropriate persistent application data directory."""

    override = os.environ.get("PROMPT_MANAGER_DATA_DIR")
    if override:
        return Path(override).expanduser()
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
        return base / "PromptManager"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "PromptManager"
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "prompt-manager"
