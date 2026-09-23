"""Application use cases and validation around the storage layer."""

from __future__ import annotations

import os
import re
import sys
from collections.abc import Mapping
from pathlib import Path

from .models import Prompt, PromptGroup
from .placeholders import IMPORT_PATTERN, PlaceholderError, extract_imports, extract_placeholders, render_replacements
from .storage import PromptRepository, StorageError


class ValidationError(ValueError):
    """Raised when user input violates a prompt contract."""


class PromptService:
    """Coordinate validation, persistence, and recursive prompt rendering."""

    MAX_NAME_LENGTH = 200
    MAX_CONTENT_LENGTH = 2_000_000
    MAX_GROUP_NAME_LENGTH = 100
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

    def list_groups(self, kind: str) -> list[PromptGroup]:
        """Return the first-level groups for one prompt category."""

        self._validate_kind(kind)
        return self.repository.list_groups(kind)

    def create_group(self, name: str, kind: str) -> PromptGroup:
        """Validate and create a named first-level group."""

        clean_name = self._validate_group_name(name)
        self._validate_kind(kind)
        try:
            return self.repository.create_group(clean_name, kind)
        except StorageError as exc:
            raise ValidationError(str(exc)) from exc

    def rename_group(self, group_id: int, name: str) -> PromptGroup:
        """Validate and rename an existing group."""

        clean_name = self._validate_group_name(name)
        try:
            return self.repository.update_group(group_id, clean_name)
        except StorageError as exc:
            raise ValidationError(str(exc)) from exc

    def delete_group(self, group_id: int) -> None:
        """Delete a group while retaining its prompts as ungrouped entries."""

        try:
            self.repository.delete_group(group_id)
        except StorageError as exc:
            raise ValidationError(str(exc)) from exc

    def set_prompt_group(self, prompt_id: int, group_id: int | None) -> None:
        """Assign or unassign a prompt from a first-level group."""

        prompt = self.repository.get_prompt(prompt_id)
        if prompt is None:
            raise ValidationError("要设置分组的提示词不存在")
        if group_id is not None:
            group = self.repository.get_group(group_id)
            if group is None:
                raise ValidationError("目标分组不存在")
            if group.kind != prompt.kind:
                raise ValidationError("提示词只能加入同类别分组")
        try:
            self.repository.set_prompt_group(prompt_id, group_id)
        except StorageError as exc:
            raise ValidationError(str(exc)) from exc

    def set_prompt_pinned(self, prompt_id: int, pinned: bool) -> None:
        """Set or clear the prompt's pinned state."""

        try:
            self.repository.set_prompt_pinned(prompt_id, pinned)
        except StorageError as exc:
            raise ValidationError(str(exc)) from exc

    def reorder_prompts(self, prompt_ids: list[int]) -> None:
        """Persist a drag-and-drop order for a single list bucket."""

        if len(prompt_ids) != len(set(prompt_ids)):
            raise ValidationError("提示词排列中存在重复条目")
        prompts = [self.repository.get_prompt(prompt_id) for prompt_id in prompt_ids]
        if any(prompt is None for prompt in prompts):
            raise ValidationError("要排序的提示词不存在")
        buckets = {
            (prompt.kind, prompt.is_pinned, None if prompt.is_pinned else prompt.group_id)
            for prompt in prompts
            if prompt is not None
        }
        if len(buckets) > 1:
            raise ValidationError("只能在同一分组或同一置顶区域内排序")
        try:
            self.repository.reorder_prompts(prompt_ids)
        except StorageError as exc:
            raise ValidationError(str(exc)) from exc

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
        self._validate_kind(kind)
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

    def _validate_group_name(self, name: str) -> str:
        clean_name = name.strip()
        if not clean_name:
            raise ValidationError("分组名称不能为空")
        if len(clean_name) > self.MAX_GROUP_NAME_LENGTH:
            raise ValidationError(f"分组名称不能超过 {self.MAX_GROUP_NAME_LENGTH} 个字符")
        return clean_name

    def _validate_kind(self, kind: str) -> None:
        if kind not in self.VALID_KINDS:
            raise ValidationError("未知提示词类别")


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


LEGACY_DATABASE_NAMES = (
    "prompts.sqlite3",
    "prompts.db",
    "prompt_manager.sqlite3",
    "prompt_manager.db",
    "PromptManager.sqlite3",
    "PromptManager.db",
    "prompt.db",
)


def legacy_database_candidates(explicit_path: Path | None = None) -> tuple[Path, ...]:
    """Return likely database locations used by older source or exe builds.

    New releases always write to :func:`default_data_directory`.  These
    candidates exist only to provide a one-time bridge for releases that wrote
    the database beside the executable, in the working directory, or into a
    PyInstaller extraction directory.

    :param explicit_path: Optional user-selected legacy database path.  It is
        checked first and is useful when the old database was stored elsewhere.
    :return: Deduplicated candidate paths in migration priority order.
    """

    roots: list[Path] = []
    if explicit_path is not None:
        roots.append(explicit_path.expanduser())
    configured_path = os.environ.get("PROMPT_MANAGER_LEGACY_DATABASE")
    if configured_path:
        roots.append(Path(configured_path).expanduser())

    executable_dir = Path(sys.executable).resolve().parent
    roots.extend((executable_dir, Path.cwd()))
    package_root = Path(__file__).resolve().parent.parent
    if package_root not in roots:
        roots.append(package_root)
    extraction_dir = getattr(sys, "_MEIPASS", None)
    if extraction_dir:
        roots.append(Path(extraction_dir))

    candidates: list[Path] = []
    seen: set[Path] = set()
    for root in roots:
        if root.suffix.lower() in {".db", ".sqlite", ".sqlite3"}:
            candidate_paths = (root,)
        else:
            candidate_paths = tuple(root / name for name in LEGACY_DATABASE_NAMES)
            candidate_paths += tuple(root / "data" / name for name in LEGACY_DATABASE_NAMES)
        for candidate in candidate_paths:
            resolved = candidate.resolve()
            if resolved not in seen:
                seen.add(resolved)
                candidates.append(candidate)
    return tuple(candidates)
