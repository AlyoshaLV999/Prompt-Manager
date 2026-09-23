"""SQLite persistence for prompts, settings, and remembered input values."""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from .models import Prompt, PromptGroup


def utc_now() -> str:
    """Return a sortable UTC timestamp in ISO-8601 format."""

    return datetime.now(UTC).isoformat(timespec="seconds")


class StorageError(RuntimeError):
    """Raised when the local database cannot complete an operation."""


def migrate_legacy_database(database_path: Path, legacy_paths: Iterable[Path]) -> Path | None:
    """Migrate the first recognized legacy database into ``database_path``.

    The migration only runs when the new database does not exist.  SQLite's
    backup API is used instead of copying bytes so an active WAL journal is
    included consistently.  The result is written to a temporary file in the
    target directory and published only after the backup passes an integrity
    check, leaving the original database untouched.

    :param database_path: Destination of the persistent application database.
    :param legacy_paths: Candidate database files from older releases.
    :return: The source path when a migration occurred, otherwise ``None``.
    :raises StorageError: If a candidate exists but is corrupt or cannot be
        copied safely.
    """

    database_path = database_path.expanduser()
    if database_path.exists():
        return None

    try:
        database_path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise StorageError(f"无法创建提示词数据目录: {database_path.parent}") from exc
    destination_resolved = database_path.resolve()
    seen: set[Path] = set()
    for candidate in legacy_paths:
        source_path = candidate.expanduser()
        resolved_source = source_path.resolve()
        if resolved_source in seen:
            continue
        seen.add(resolved_source)
        if resolved_source == destination_resolved or not source_path.is_file():
            continue
        if not _contains_prompt_schema(source_path):
            continue
        try:
            _backup_sqlite_database(source_path, database_path)
        except (OSError, sqlite3.DatabaseError) as exc:
            raise StorageError(f"无法迁移旧提示词数据库: {source_path}") from exc
        return source_path
    return None


def _readonly_connection(database_path: Path) -> sqlite3.Connection:
    """Open a SQLite file read-only, including its sidecar WAL when present."""

    uri = f"{database_path.resolve().as_uri()}?mode=ro"
    return sqlite3.connect(uri, uri=True)


def _contains_prompt_schema(database_path: Path) -> bool:
    """Return whether a candidate is a readable Prompt Manager database."""

    connection: sqlite3.Connection | None = None
    try:
        connection = _readonly_connection(database_path)
        row = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'prompts'"
        ).fetchone()
        if row is None:
            return False
        check = connection.execute("PRAGMA quick_check").fetchone()
        return bool(check and str(check[0]).lower() == "ok")
    except sqlite3.DatabaseError as exc:
        raise StorageError(f"旧提示词数据库无法读取: {database_path}") from exc
    finally:
        if connection is not None:
            connection.close()


def _backup_sqlite_database(source_path: Path, database_path: Path) -> None:
    """Create an atomic SQLite backup without modifying the source file."""

    temporary_path = database_path.with_name(f".{database_path.name}.migration-{uuid4().hex}.tmp")
    source_connection: sqlite3.Connection | None = None
    target_connection: sqlite3.Connection | None = None
    try:
        source_connection = _readonly_connection(source_path)
        target_connection = sqlite3.connect(temporary_path)
        source_connection.backup(target_connection, pages=1_000)
        integrity = target_connection.execute("PRAGMA integrity_check").fetchone()
        if not integrity or str(integrity[0]).lower() != "ok":
            raise sqlite3.DatabaseError("迁移后的数据库完整性检查失败")
        target_connection.close()
        target_connection = None
        source_connection.close()
        source_connection = None
        if database_path.exists():
            temporary_path.unlink(missing_ok=True)
            return
        temporary_path.replace(database_path)
    finally:
        if target_connection is not None:
            target_connection.close()
        if source_connection is not None:
            source_connection.close()
        temporary_path.unlink(missing_ok=True)


class PromptRepository:
    """Thread-safe repository backed by a local SQLite database."""

    SCHEMA_VERSION = 3

    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path.expanduser()
        self._lock = threading.RLock()
        self._connection: sqlite3.Connection | None = None
        try:
            self.database_path.parent.mkdir(parents=True, exist_ok=True)
            self._connection = sqlite3.connect(self.database_path)
            self._connection.row_factory = sqlite3.Row
            self._connection.execute("PRAGMA foreign_keys = ON")
            self._connection.execute("PRAGMA journal_mode = WAL")
            self._initialize_schema()
        except (OSError, sqlite3.Error) as exc:
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
                    updated_at TEXT NOT NULL,
                    group_id INTEGER REFERENCES prompt_groups(id) ON DELETE SET NULL,
                    sort_order INTEGER NOT NULL DEFAULT 0,
                    is_pinned INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS prompt_groups (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    sort_order INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(kind, name COLLATE NOCASE)
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
            if "group_id" not in columns:
                self.connection.execute("ALTER TABLE prompts ADD COLUMN group_id INTEGER REFERENCES prompt_groups(id) ON DELETE SET NULL")
            if "sort_order" not in columns:
                self.connection.execute("ALTER TABLE prompts ADD COLUMN sort_order INTEGER NOT NULL DEFAULT 0")
            if "is_pinned" not in columns:
                self.connection.execute("ALTER TABLE prompts ADD COLUMN is_pinned INTEGER NOT NULL DEFAULT 0")
            self.connection.execute("CREATE INDEX IF NOT EXISTS idx_prompts_kind_order ON prompts(kind, is_pinned, group_id, sort_order)")
            self.connection.execute("CREATE INDEX IF NOT EXISTS idx_prompt_groups_kind_order ON prompt_groups(kind, sort_order)")
            self.connection.execute(f"PRAGMA user_version = {self.SCHEMA_VERSION}")

    def list_prompts(self, kind: str | None = None) -> list[Prompt]:
        """Return prompts, optionally restricted to ``prompt`` or ``fixed``."""

        with self._lock:
            if kind is None:
                rows = self.connection.execute(
                    "SELECT id, name, content, kind, created_at, updated_at, group_id, sort_order, is_pinned FROM prompts "
                    "ORDER BY kind, is_pinned DESC, CASE WHEN is_pinned = 1 THEN 0 ELSE COALESCE(group_id, -1) END, "
                    "sort_order, updated_at DESC, name COLLATE NOCASE"
                ).fetchall()
            else:
                rows = self.connection.execute(
                    "SELECT id, name, content, kind, created_at, updated_at, group_id, sort_order, is_pinned FROM prompts "
                    "WHERE kind = ? ORDER BY is_pinned DESC, CASE WHEN is_pinned = 1 THEN 0 ELSE COALESCE(group_id, -1) END, "
                    "sort_order, updated_at DESC, name COLLATE NOCASE", (kind,)
                ).fetchall()
        return [self._row_to_prompt(row) for row in rows]

    def get_prompt(self, prompt_id: int) -> Prompt | None:
        """Return one prompt or ``None`` when its id no longer exists."""

        with self._lock:
            row = self.connection.execute(
                "SELECT id, name, content, kind, created_at, updated_at, group_id, sort_order, is_pinned FROM prompts WHERE id = ?",
                (prompt_id,),
            ).fetchone()
        return self._row_to_prompt(row) if row else None

    def find_prompt_by_name(self, name: str, kind: str | None = None) -> Prompt | None:
        """Find a prompt by case-insensitive name."""

        with self._lock:
            query = "SELECT id, name, content, kind, created_at, updated_at, group_id, sort_order, is_pinned FROM prompts WHERE name = ? COLLATE NOCASE"
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
                    "INSERT INTO prompts(name, content, kind, created_at, updated_at, sort_order) VALUES (?, ?, ?, ?, ?, ?)",
                    (name, content, kind, now, now, self._next_prompt_order(kind, None, False)),
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

    def list_groups(self, kind: str) -> list[PromptGroup]:
        """Return first-level groups in their user-defined order."""

        with self._lock:
            rows = self.connection.execute(
                "SELECT id, name, kind, sort_order FROM prompt_groups WHERE kind = ? "
                "ORDER BY sort_order, name COLLATE NOCASE", (kind,)
            ).fetchall()
        return [self._row_to_group(row) for row in rows]

    def create_group(self, name: str, kind: str) -> PromptGroup:
        """Create a group at the end of its category."""

        try:
            with self._lock, self.connection:
                cursor = self.connection.execute(
                    "INSERT INTO prompt_groups(name, kind, sort_order, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                    (name, kind, self._next_group_order(kind), utc_now(), utc_now()),
                )
                group_id = int(cursor.lastrowid)
        except sqlite3.IntegrityError as exc:
            raise StorageError("分组名称已存在") from exc
        except sqlite3.Error as exc:
            raise StorageError("创建分组失败") from exc
        group = self.get_group(group_id)
        if group is None:
            raise StorageError("创建分组后无法读取记录")
        return group

    def get_group(self, group_id: int) -> PromptGroup | None:
        """Return one group or ``None`` when it no longer exists."""

        with self._lock:
            row = self.connection.execute(
                "SELECT id, name, kind, sort_order FROM prompt_groups WHERE id = ?", (group_id,)
            ).fetchone()
        return self._row_to_group(row) if row else None

    def update_group(self, group_id: int, name: str) -> PromptGroup:
        """Rename a group without changing its category or members."""

        try:
            with self._lock, self.connection:
                cursor = self.connection.execute(
                    "UPDATE prompt_groups SET name = ?, updated_at = ? WHERE id = ?",
                    (name, utc_now(), group_id),
                )
                if cursor.rowcount == 0:
                    raise StorageError("要修改的分组不存在")
        except StorageError:
            raise
        except sqlite3.IntegrityError as exc:
            raise StorageError("分组名称已存在") from exc
        except sqlite3.Error as exc:
            raise StorageError("重命名分组失败") from exc
        group = self.get_group(group_id)
        if group is None:
            raise StorageError("重命名分组后无法读取记录")
        return group

    def delete_group(self, group_id: int) -> None:
        """Delete a group and leave its prompts as ungrouped entries."""

        try:
            with self._lock, self.connection:
                self.connection.execute("DELETE FROM prompt_groups WHERE id = ?", (group_id,))
        except sqlite3.Error as exc:
            raise StorageError("删除分组失败") from exc

    def set_prompt_group(self, prompt_id: int, group_id: int | None) -> None:
        """Assign a prompt to a group or clear its group assignment."""

        try:
            with self._lock, self.connection:
                self.connection.execute("UPDATE prompts SET group_id = ? WHERE id = ?", (group_id, prompt_id))
        except sqlite3.Error as exc:
            raise StorageError("设置提示词分组失败") from exc

    def set_prompt_pinned(self, prompt_id: int, pinned: bool) -> None:
        """Set or clear a prompt's pinned state."""

        try:
            with self._lock, self.connection:
                row = self.connection.execute(
                    "SELECT kind, group_id FROM prompts WHERE id = ?", (prompt_id,)
                ).fetchone()
                if row is None:
                    raise StorageError("要设置置顶状态的提示词不存在")
                if pinned:
                    next_order = int(self.connection.execute(
                        "SELECT COALESCE(MAX(sort_order), -1) + 1 FROM prompts WHERE kind = ? AND is_pinned = 1",
                        (str(row["kind"]),),
                    ).fetchone()[0])
                else:
                    next_order = self._next_prompt_order(str(row["kind"]), row["group_id"], False)
                self.connection.execute(
                    "UPDATE prompts SET is_pinned = ?, sort_order = ? WHERE id = ?",
                    (int(pinned), next_order, prompt_id),
                )
        except sqlite3.Error as exc:
            raise StorageError("设置置顶状态失败") from exc
        except StorageError:
            raise

    def reorder_prompts(self, prompt_ids: Iterable[int]) -> None:
        """Persist the order of prompts within one visible list bucket."""

        try:
            with self._lock, self.connection:
                self.connection.executemany(
                    "UPDATE prompts SET sort_order = ? WHERE id = ?",
                    [(index, prompt_id) for index, prompt_id in enumerate(prompt_ids)],
                )
        except sqlite3.Error as exc:
            raise StorageError("保存提示词排列顺序失败") from exc

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
            group_id=int(row["group_id"]) if row["group_id"] is not None else None,
            sort_order=int(row["sort_order"] or 0), is_pinned=bool(row["is_pinned"]),
        )

    @staticmethod
    def _row_to_group(row: sqlite3.Row) -> PromptGroup:
        return PromptGroup(id=int(row["id"]), name=str(row["name"]), kind=str(row["kind"]), sort_order=int(row["sort_order"] or 0))

    def _next_prompt_order(self, kind: str, group_id: int | None, pinned: bool) -> int:
        row = self.connection.execute(
            "SELECT COALESCE(MAX(sort_order), -1) + 1 FROM prompts "
            "WHERE kind = ? AND group_id IS ? AND is_pinned = ?",
            (kind, group_id, int(pinned)),
        ).fetchone()
        return int(row[0])

    def _next_group_order(self, kind: str) -> int:
        row = self.connection.execute(
            "SELECT COALESCE(MAX(sort_order), -1) + 1 FROM prompt_groups WHERE kind = ?", (kind,)
        ).fetchone()
        return int(row[0])
