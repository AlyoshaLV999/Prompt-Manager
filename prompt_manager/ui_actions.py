"""Database maintenance and allow-listed Agent actions of the main window."""

from __future__ import annotations

import logging
from functools import wraps
from pathlib import Path
from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

from .database_maintenance import DatabaseTaskThread, RestoreDatabaseDialog
from .agent import AGENT_TOOLS
from .models import Prompt
from .service import ValidationError
from .storage import StorageError
from .ui_widgets import FillPromptDialog

logger = logging.getLogger(f"{__package__}.ui")
KNOWN_TOOL_NAMES = frozenset(tool["function"]["name"] for tool in AGENT_TOOLS)


def _log_agent_tool(method: Callable[..., dict[str, object]]) -> Callable[..., dict[str, object]]:
    """Record tool metadata and outcomes without storing its text arguments."""

    @wraps(method)
    def wrapped(self, name: str, arguments: dict[str, object]) -> dict[str, object]:
        safe_name = name if isinstance(name, str) and name in KNOWN_TOOL_NAMES else "<unknown>"
        prompt_id = arguments.get("prompt_id")
        group_id = arguments.get("group_id")
        content = arguments.get("content")
        kind = arguments.get("kind")
        logger.info(
            "Agent tool started name=%s prompt_id=%s group_id=%s kind=%s content_chars=%s",
            safe_name,
            prompt_id if type(prompt_id) is int else "-",
            group_id if type(group_id) is int else "-",
            kind if kind in ("prompt", "fixed") else "-",
            len(content) if isinstance(content, str) else "-",
        )
        try:
            result = method(self, name, arguments)
        except Exception as exc:
            logger.error("Agent tool crashed name=%s error=%s", safe_name, type(exc).__name__)
            raise
        logger.log(
            logging.WARNING if "error" in result else logging.INFO,
            "Agent tool finished name=%s status=%s result_id=%s item_count=%s",
            safe_name, "error" if "error" in result else "ok",
            result.get("id", "-"),
            len(result["prompts"]) if "prompts" in result else (
                len(result["groups"]) if "groups" in result else "-"
            ),
        )
        return result

    return wrapped


class MainWindowActions:
    """Operations shared with the main window without owning Qt state."""

    def start_database_backup(self) -> None:
        """Back up the live database without blocking the interface."""

        if self._database_thread is not None:
            return
        logger.info("User requested database backup")
        self.agent_panel.set_database_actions_enabled(False)
        self.agent_panel.status_label.setText("正在备份数据库…")
        self._database_thread = DatabaseTaskThread(self.service.backup_database)
        self._database_thread.completed.connect(self._on_database_backup_completed)
        self._database_thread.finished.connect(self._on_database_task_finished)
        self._database_thread.start()

    def start_database_restore(self) -> None:
        """Replace the live database with a snapshot chosen by the user.

        The snapshot is applied on the GUI thread because SQLite's online backup
        API runs on the connection this window already owns, and that connection
        may only be used from the thread that created it.  Copying a local
        snapshot is quick, and the wait cursor reports the operation while it
        runs.
        """

        if self._database_thread is not None:
            return
        logger.info("User requested database restore")
        try:
            backups = self.service.list_database_backups()
        except StorageError as exc:
            logger.warning("Database backup list failed error=%s", type(exc).__name__)
            self._show_error(str(exc))
            return
        if not backups:
            message = "没有可用的数据库备份，请先备份数据库"
            self.agent_panel.status_label.setText(message)
            self.statusBar().showMessage(message, 4000)
            return
        dialog = RestoreDatabaseDialog(backups, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            logger.info("User cancelled database restore")
            return
        backup_path = dialog.selected_backup()
        if backup_path is None:
            return
        logger.info("User confirmed database restore from %s", backup_path)
        # Debounced writes still in flight belong to the database being
        # replaced; letting them fire afterwards would undo the restore.
        self._autosave_timer.stop()
        self._temporary_autosave_timer.stop()
        self.agent_panel.set_database_actions_enabled(False)
        self.agent_panel.status_label.setText(f"正在恢复 {backup_path.parent.name} 的备份…")
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            restored = self.service.restore_database(backup_path)
        except StorageError as exc:
            logger.warning("Database restore failed: %s", exc)
            message = f"数据库恢复失败：{exc}"
            self.agent_panel.status_label.setText(message)
            self.statusBar().showMessage(message, 6000)
            return
        finally:
            QApplication.restoreOverrideCursor()
            self.agent_panel.set_database_actions_enabled(True)
        self.agent_panel.status_label.setText(f"已从 {restored.parent.name} 的备份恢复数据库")
        logger.info("Database restore completed from %s", restored)
        self._refresh_after_database_restore()

    def _on_database_backup_completed(self, destination: object, error: str) -> None:
        if error:
            logger.warning("Database backup failed: %s", error)
            message = f"数据库备份失败：{error}"
            self.agent_panel.status_label.setText(message)
            self.statusBar().showMessage(message, 6000)
            return
        if not isinstance(destination, Path):
            logger.error("Database backup worker returned an invalid destination")
            self.agent_panel.status_label.setText("数据库备份失败：未返回备份路径")
            return
        backup_path = Path(destination)
        logger.info("Database backup completed at %s", backup_path)
        message = f"备份完成：{backup_path.parent.name}/{backup_path.name}"
        self.agent_panel.status_label.setText(message)
        self.statusBar().showMessage(f"数据库已备份到：{backup_path}", 6000)

    def _on_database_task_finished(self) -> None:
        thread = self.sender()
        self._database_thread = None
        self.agent_panel.set_database_actions_enabled(True)
        if thread is not None:
            thread.deleteLater()

    def capture_agent_backup(self) -> None:
        """Snapshot the database before the Agent generates a reply.

        The snapshot is the way back from a tool call that damaged stored
        prompts.  It is removed again when the window closes, so it only ever
        covers the run that created it; a failure is reported without stopping
        the generation, which would otherwise make the Agent unusable whenever
        the backup folder is not writable.
        """

        try:
            backup_path = self._agent_backups.capture()
        except StorageError as exc:
            logger.warning("Agent backup failed: %s", exc)
            self.statusBar().showMessage(f"Agent 自动备份失败，本次生成没有可回滚的备份：{exc}", 6000)
            return
        if self._agent_backups.count == 1:
            self.statusBar().showMessage(
                f"本次运行已开启 Agent 自动备份（{backup_path.parent.name}/{backup_path.name}），关闭程序时会清理",
                5000,
            )
        logger.debug("Agent snapshot created: %s", backup_path)

    def _refresh_after_database_restore(self) -> None:
        """Reload every view that reads from the restored database."""

        settings = self.service.settings()
        self.item_name_max_length = self._read_item_name_max_length(settings)
        self._loading_temporary = True
        try:
            self.temporary_text_edit.setPlainText(settings.get("temporary_text", ""))
        finally:
            self._loading_temporary = False
        self._install_shortcuts()
        # The entry that was open may not exist in the restored database, and
        # the editor must never keep showing pre-restore text that autosave
        # could later write back over the restored content.
        selected = self.current_prompt_id
        self._clear_editor()
        self.refresh_prompt_list(select_id=selected)
        self.statusBar().showMessage("数据库已恢复，界面已刷新", 4000)

    @_log_agent_tool
    def execute_agent_tool(self, name: str, arguments: dict[str, object]) -> dict[str, object]:
        """Run one allow-listed Agent action on the GUI thread.

        :param name: Tool name returned by the configured model.
        :param arguments: JSON object validated against the tool's required fields.
        :return: JSON-serializable action result or a user-readable error.
        """

        try:
            if name == "list_prompts":
                kind = arguments.get("kind")
                prompts = self.service.list_prompts(str(kind) if kind is not None else None)
                return {
                    "prompts": [
                        {
                            "id": prompt.id,
                            "name": prompt.name,
                            "kind": prompt.kind,
                            "group_id": prompt.group_id,
                            "is_pinned": prompt.is_pinned,
                            "updated_at": prompt.updated_at,
                        }
                        for prompt in prompts
                    ]
                }
            if name == "read_prompt":
                prompt = self.service.get_prompt(int(arguments["prompt_id"]))
                if prompt is None:
                    return {"error": "未找到该提示词"}
                return {
                    "id": prompt.id,
                    "name": prompt.name,
                    "content": prompt.content,
                    "kind": prompt.kind,
                    "group_id": prompt.group_id,
                    "is_pinned": prompt.is_pinned,
                }
            if name == "create_prompt":
                prompt = self.service.create_prompt(str(arguments["name"]), str(arguments["content"]),
                                                    str(arguments["kind"]))
                self._focus_agent_prompt(prompt)
                return {
                    "created": True,
                    "id": prompt.id,
                    "name": prompt.name,
                    "kind": prompt.kind,
                    "group_id": prompt.group_id,
                }
            if name == "update_prompt":
                prompt = self.service.update_prompt(int(arguments["prompt_id"]), str(arguments["name"]),
                                                    str(arguments["content"]), str(arguments["kind"]))
                self._focus_agent_prompt(prompt)
                return {
                    "updated": True,
                    "id": prompt.id,
                    "name": prompt.name,
                    "kind": prompt.kind,
                    "group_id": prompt.group_id,
                }
            if name == "delete_prompt":
                prompt_id = int(arguments["prompt_id"])
                if self.service.get_prompt(prompt_id) is None:
                    return {"error": "未找到该提示词"}
                self.service.delete_prompt(prompt_id)
                self.refresh_prompt_list()
                return {"deleted": True, "id": prompt_id}
            if name == "select_prompt":
                prompt = self.service.get_prompt(int(arguments["prompt_id"]))
                if prompt is None:
                    return {"error": "未找到该提示词"}
                self._focus_agent_prompt(prompt)
                return {"selected": True, "id": prompt.id, "name": prompt.name}
            if name == "list_groups":
                kind = str(arguments["kind"])
                groups = self.service.list_groups(kind)
                prompts = self.service.list_prompts(kind)
                counts: dict[int, int] = {}
                for prompt in prompts:
                    if prompt.group_id is not None and not prompt.is_pinned:
                        counts[prompt.group_id] = counts.get(prompt.group_id, 0) + 1
                return {
                    "groups": [
                        {
                            "id": group.id,
                            "name": group.name,
                            "kind": group.kind,
                            "sort_order": group.sort_order,
                            "prompt_count": counts.get(group.id, 0),
                        }
                        for group in groups
                    ]
                }
            if name == "create_group":
                group = self.service.create_group(str(arguments["name"]), str(arguments["kind"]))
                if group.kind == self.current_kind:
                    self.refresh_prompt_list(select_id=self.current_prompt_id, load_selection=False)
                return {
                    "created": True,
                    "id": group.id,
                    "name": group.name,
                    "kind": group.kind,
                }
            if name == "set_prompt_group":
                prompt_id = int(arguments["prompt_id"])
                group_id = int(arguments["group_id"])
                self.service.set_prompt_group(prompt_id, group_id)
                prompt = self.service.get_prompt(prompt_id)
                if prompt is None:
                    return {"error": "未找到该提示词"}
                self._focus_agent_prompt(prompt)
                return {
                    "updated": True,
                    "id": prompt.id,
                    "name": prompt.name,
                    "kind": prompt.kind,
                    "group_id": prompt.group_id,
                }
            if name == "clear_prompt_group":
                prompt_id = int(arguments["prompt_id"])
                prompt = self.service.get_prompt(prompt_id)
                if prompt is None:
                    return {"error": "未找到该提示词"}
                self.service.set_prompt_group(prompt_id, None)
                prompt = self.service.get_prompt(prompt_id)
                if prompt is None:
                    return {"error": "未找到该提示词"}
                self._focus_agent_prompt(prompt)
                return {
                    "updated": True,
                    "id": prompt.id,
                    "name": prompt.name,
                    "kind": prompt.kind,
                    "group_id": None,
                }
            return {"error": f"未知工具: {name}"}
        except (KeyError, TypeError, ValueError, ValidationError, StorageError) as exc:
            return {"error": str(exc)}

    def _focus_agent_prompt(self, prompt: Prompt) -> None:
        """Switch to an Agent-selected prompt and expand its group if needed."""

        if prompt.kind != self.current_kind:
            self.switch_category(prompt.kind)
        if prompt.group_id is not None:
            self._collapsed_group_ids[prompt.group_id] = False
        self.refresh_prompt_list(select_id=prompt.id)

    def delete_current_prompt(self) -> None:
        if self.current_prompt_id is None:
            return
        answer = QMessageBox.question(
            self, "删除提示词", "确定删除当前条目吗？已记忆的占位符输入也会一并删除。",
            QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Yes,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            logger.info("User cancelled prompt deletion id=%d", self.current_prompt_id)
            return
        self.service.delete_prompt(self.current_prompt_id)
        self.refresh_prompt_list()
        self.statusBar().showMessage("已删除", 3000)

    def use_prompt(self, prompt_id: int) -> None:
        """Render and copy one prompt, asking for placeholder values when needed.

        The list-row copy button delegates here so every entry exposes the full
        "use prompt" workflow rather than a silent remembered-value copy.
        """

        if prompt_id == self.current_prompt_id:
            # Flush pending edits so the copy reflects exactly what is on screen.
            self._autosave_timer.stop()
            self._auto_save()
        prompt = self.service.get_prompt(prompt_id)
        if prompt is None:
            logger.warning("User requested missing prompt id=%d", prompt_id)
            self._show_error("提示词已不存在")
            return
        logger.info("User invoked prompt id=%d kind=%s", prompt.id, prompt.kind)
        try:
            if not self.service.placeholders_for(prompt):
                self._copy_to_clipboard(self.service.render(prompt, {}), "提示词已复制")
                return
            if FillPromptDialog(self.service, prompt, self).exec() == QDialog.DialogCode.Accepted:
                self.statusBar().showMessage("提示词已复制到剪贴板", 3500)
        except (ValidationError, StorageError) as exc:
            logger.warning("Prompt use failed id=%d error=%s", prompt_id, type(exc).__name__)
            self._show_error(str(exc))
