"""Domain models used by the prompt manager."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Prompt:
    """A named Markdown prompt or reusable fixed preset."""

    id: int
    name: str
    content: str
    kind: str
    created_at: str
    updated_at: str

    @property
    def is_fixed(self) -> bool:
        """Return whether this item is a reusable fixed preset."""

        return self.kind == "fixed"
