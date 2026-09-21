"""SQLite persistence for prompts, settings, and remembered input values."""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from pathlib import Path

from .models import Prompt


def utc_now() -> str:
    """Return a sortable UTC timestamp in ISO-8601 format."""

    return datetime.now(UTC).isoformat(timespec="seconds")


class StorageError(RuntimeError):
    """Raised when the local database cannot complete an operation."""


class PromptRepository:
    """Thread-safe repository backed by a local SQLite database."""

    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._connection: sqlite3.Connection | None = None
        try:
            self._connection = sqlite3.connect(self.database_path)
            self._connection.row_factory = sqlite3.Row
            self._connection.execute("PRAGMA foreign_keys = ON")
            self._connection.execute("PRAGMA journal_mode = WAL")
            self._initialize_schema()
        except sqlite3.Error as exc:
            self.close()
            raise StorageError(f"无法打开提示词数据库: {self.database_path}") from exc

    @property
    def connection(self) -> sqlite3.Connection:
        """Return the active connection or fail with a useful error."""

        if self._connection is None:
            raise StorageError("提示词数据库已关闭")
        return self._connection

    def _initialize_schema(self) -> None:
        with self.connection:
            self.connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS prompts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL COLLATE NOCASE UNIQUE,
                    content TEXT NOT NULL,
                    kind TEXT NOT NULL DEFAULT 'prompt',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS placeholder_values (
                    prompt_id INTEGER NOT NULL,
                    placeholder_title TEXT NOT NULL,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (prompt_id, placeholder_title),
                    FOREIGN KEY (prompt_id) REFERENCES prompts(id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS app_settings (
                    setting_key TEXT PRIMARY KEY,
                    setting_value TEXT NOT NULL
                );
                """
            )
            columns = {str(row["name"]) for row in self.connection.execute("PRAGMA table_info(prompts)")}
            if "kind" not in columns:
                self.connection.execute("ALTER TABLE prompts ADD COLUMN kind TEXT NOT NULL DEFAULT 'prompt'")
            self.connection.execute("CREATE INDEX IF NOT EXISTS idx_prompts_kind_updated ON prompts(kind, updated_at DESC)")

    def list_prompts(self, kind: str | None = None) -> list[Prompt]:
        """Return prompts, optionally restricted to ``prompt`` or ``fixed``."""

        with self._lock:
            if kind is None:
                rows = self.connection.execute(
                    "SELECT id, name, content, kind, created_at, updated_at FROM prompts "
                    "ORDER BY kind, updated_at DESC, name COLLATE NOCASE"
                ).fetchall()
            else:
                rows = self.connection.execute(
                    "SELECT id, name, content, kind, created_at, updated_at FROM prompts "
                    "WHERE kind = ? ORDER BY updated_at DESC, name COLLATE NOCASE", (kind,)
                ).fetchall()
        return [self._row_to_prompt(row) for row in rows]

    def get_prompt(self, prompt_id: int) -> Prompt | None:
        """Return one prompt or ``None`` when its id no longer exists."""

        with self._lock:
            row = self.connection.execute(
                "SELECT id, name, content, kind, created_at, updated_at FROM prompts WHERE id = ?",
                (prompt_id,),
            ).fetchone()
        return self._row_to_prompt(row) if row else None

    def find_prompt_by_name(self, name: str, kind: str | None = None) -> Prompt | None:
        """Find a prompt by case-insensitive name."""

        with self._lock:
            query = "SELECT id, name, content, kind, created_at, updated_at FROM prompts WHERE name = ? COLLATE NOCASE"
            params: tuple[object, ...] = (name,)
            if kind is not None:
                query += " AND kind = ?"
                params += (kind,)
            row = self.connection.execute(query, params).fetchone()
        return self._row_to_prompt(row) if row else None

    def create_prompt(self, name: str, content: str, kind: str = "prompt") -> Prompt:
        """Create and return a prompt."""

        now = utc_now()
        try:
            with self._lock, self.connection:
                cursor = self.connection.execute(
                    "INSERT INTO prompts(name, content, kind, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                    (name, content, kind, now, now),
                )
                prompt_id = int(cursor.lastrowid)
        except sqlite3.IntegrityError as exc:
            raise StorageError("提示词名称已存在") from exc
        except sqlite3.Error as exc:
            raise StorageError("创建提示词失败") from exc
        prompt = self.get_prompt(prompt_id)
        if prompt is None:
            raise StorageError("创建提示词后无法读取记录")
        return prompt

    def update_prompt(self, prompt_id: int, name: str, content: str, kind: str) -> Prompt:
        """Update a prompt and return its new state."""

        try:
            with self._lock, self.connection:
                cursor = self.connection.execute(
                    "UPDATE prompts SET name = ?, content = ?, kind = ?, updated_at = ? WHERE id = ?",
                    (name, content, kind, utc_now(), prompt_id),
                )
                if cursor.rowcount == 0:
                    raise StorageError("要修改的提示词不存在")
        except StorageError:
            raise
        except sqlite3.IntegrityError as exc:
            raise StorageError("提示词名称已存在") from exc
        except sqlite3.Error as exc:
            raise StorageError("修改提示词失败") from exc
        prompt = self.get_prompt(prompt_id)
        if prompt is None:
            raise StorageError("修改提示词后无法读取记录")
        return prompt

    def delete_prompt(self, prompt_id: int) -> None:
        """Delete a prompt and its remembered values."""

        try:
            with self._lock, self.connection:
                self.connection.execute("DELETE FROM prompts WHERE id = ?", (prompt_id,))
        except sqlite3.Error as exc:
            raise StorageError("删除提示词失败") from exc

    def get_placeholder_values(self, prompt_id: int) -> dict[str, str]:
        """Return all remembered placeholder values for one prompt."""

        with self._lock:
            rows = self.connection.execute(
                "SELECT placeholder_title, value FROM placeholder_values WHERE prompt_id = ?", (prompt_id,)
            ).fetchall()
        return {str(row["placeholder_title"]): str(row["value"]) for row in rows}

    def save_placeholder_values(self, prompt_id: int, values: Iterable[tuple[str, str]]) -> None:
        """Upsert supplied values without deleting older titles."""

        rows = [(prompt_id, title, value, utc_now()) for title, value in values]
        try:
            with self._lock, self.connection:
                self.connection.executemany(
                    "INSERT INTO placeholder_values(prompt_id, placeholder_title, value, updated_at) VALUES (?, ?, ?, ?) "
                    "ON CONFLICT(prompt_id, placeholder_title) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
                    rows,
                )
        except sqlite3.Error as exc:
            raise StorageError("保存占位符输入失败") from exc

    def get_settings(self) -> dict[str, str]:
        """Return all persisted application settings."""

        with self._lock:
            rows = self.connection.execute("SELECT setting_key, setting_value FROM app_settings").fetchall()
        return {str(row["setting_key"]): str(row["setting_value"]) for row in rows}

    def save_settings(self, settings: Mapping[str, str]) -> None:
        """Persist application settings atomically."""

        try:
            with self._lock, self.connection:
                self.connection.executemany(
                    "INSERT INTO app_settings(setting_key, setting_value) VALUES (?, ?) "
                    "ON CONFLICT(setting_key) DO UPDATE SET setting_value = excluded.setting_value",
                    list(settings.items()),
                )
        except sqlite3.Error as exc:
            raise StorageError("保存应用设置失败") from exc

    def close(self) -> None:
        """Close the SQLite connection; safe to call more than once."""

        with self._lock:
            if self._connection is not None:
                self._connection.close()
                self._connection = None

    @staticmethod
    def _row_to_prompt(row: sqlite3.Row) -> Prompt:
        return Prompt(
            id=int(row["id"]), name=str(row["name"]), content=str(row["content"]),
            kind=str(row["kind"] or "prompt"), created_at=str(row["created_at"]), updated_at=str(row["updated_at"]),
        )
