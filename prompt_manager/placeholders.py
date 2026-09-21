"""Parsing and rendering of prompt replacement and import markers."""

from __future__ import annotations

import re
from collections.abc import Mapping


REPLACE_PATTERN = re.compile(r"=====REPLACE:\s*([^=\n]+?)\s*=====")
IMPORT_PATTERN = re.compile(r"=====IMPORT:\s*([^=\n]+?)\s*=====")
MAX_PLACEHOLDER_TITLE_LENGTH = 100


class PlaceholderError(ValueError):
    """Raised when a prompt contains an invalid marker definition."""


def _extract(pattern: re.Pattern[str], content: str) -> list[str]:
    titles: list[str] = []
    seen: set[str] = set()
    for match in pattern.finditer(content):
        title = match.group(1).strip()
        if not title:
            raise PlaceholderError("占位符标题不能为空")
        if len(title) > MAX_PLACEHOLDER_TITLE_LENGTH:
            raise PlaceholderError(f"占位符标题不能超过 {MAX_PLACEHOLDER_TITLE_LENGTH} 个字符")
        if title not in seen:
            titles.append(title)
            seen.add(title)
    return titles


def extract_placeholders(content: str) -> list[str]:
    """Return unique replacement titles in first-seen order."""

    return _extract(REPLACE_PATTERN, content)


def extract_imports(content: str) -> list[str]:
    """Return unique fixed-preset names referenced by a prompt."""

    return _extract(IMPORT_PATTERN, content)


def render_replacements(content: str, values: Mapping[str, str]) -> str:
    """Replace known input markers and preserve missing markers."""

    def replace(match: re.Match[str]) -> str:
        title = match.group(1).strip()
        return values[title] if title in values else match.group(0)

    return REPLACE_PATTERN.sub(replace, content)
