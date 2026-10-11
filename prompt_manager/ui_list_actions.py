"""Prompt navigation, grouping, pinning, and drag reorder actions."""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QInputDialog, QListWidgetItem, QMenu, QMessageBox, QPushButton

from .models import Prompt
from .service import ValidationError
from .ui_constants import ITEM_GROUP, ITEM_PROMPT, ITEM_SECTION, ITEM_TYPE_ROLE, PROMPT_ID_ROLE
from .ui_widgets import GroupListRow, PromptListRow, SectionListRow

logger = logging.getLogger(__name__)


class MainWindowListActions:
    """Keep list and group interactions together on the main window."""

    def switch_category(self, kind: str) -> None:
        """Switch the visible category and start a new entry if necessary."""

        if kind == self.current_kind:
            return
        logger.info("User switched category from %s to %s", self.current_kind, kind)
        self._autosave_timer.stop()
        self.current_kind = kind
        self.prompt_category_button.setChecked(kind == "prompt")
        self.fixed_category_button.setChecked(kind == "fixed")
        self.refresh_prompt_list()

    def refresh_prompt_list(self, select_id: int | None = None, load_selection: bool = True) -> None:
        prompts = self.service.list_prompts(self.current_kind)
        groups = self.service.list_groups(self.current_kind)
        group_ids = {group.id for group in groups}
        self._collapsed_group_ids = {
            group_id: collapsed
            for group_id, collapsed in self._collapsed_group_ids.items()
            if group_id in group_ids
        }
        for group_id in group_ids:
            self._collapsed_group_ids.setdefault(group_id, True)
        prompts_by_group: dict[int, list[Prompt]] = {group.id: [] for group in groups}
        pinned: list[Prompt] = []
        ungrouped: list[Prompt] = []
        for prompt in prompts:
            if prompt.is_pinned:
                pinned.append(prompt)
            elif prompt.group_id in prompts_by_group:
                prompts_by_group[prompt.group_id].append(prompt)
            else:
                ungrouped.append(prompt)

        self.prompt_list.blockSignals(True)
        self.prompt_list.clear()
        for group in groups:
            self._add_group_item(group.id, group.name, len(prompts_by_group[group.id]))
            if not self._collapsed_group_ids[group.id]:
                for prompt in prompts_by_group[group.id]:
                    self._add_prompt_item(prompt)
        if pinned or ungrouped:
            self._add_section_item()
            for prompt in pinned:
                self._add_prompt_item(prompt)
            for prompt in ungrouped:
                self._add_prompt_item(prompt)
        self.prompt_list.blockSignals(False)
        self.count_label.setText(f"{len(prompts)} 条 · {len(groups)} 个分组")
        if select_id is not None:
            for index in range(self.prompt_list.count()):
                item = self.prompt_list.item(index)
                if item.data(ITEM_TYPE_ROLE) == ITEM_PROMPT and item.data(PROMPT_ID_ROLE) == select_id:
                    self.prompt_list.setCurrentItem(item)
                    return
        if load_selection and prompts:
            if self.current_prompt_id is not None:
                for index in range(self.prompt_list.count()):
                    item = self.prompt_list.item(index)
                    if item.data(ITEM_TYPE_ROLE) == ITEM_PROMPT and item.data(PROMPT_ID_ROLE) == self.current_prompt_id:
                        self.prompt_list.setCurrentItem(item)
                        return
            self.prompt_list.setCurrentRow(0)
        elif not prompts:
            self._clear_editor()

    def _add_group_item(self, group_id: int, name: str, count: int) -> None:
        item = QListWidgetItem()
        item.setData(PROMPT_ID_ROLE, group_id)
        item.setData(ITEM_TYPE_ROLE, ITEM_GROUP)
        item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsDropEnabled)
        row = GroupListRow(
            group_id, name, count, self._collapsed_group_ids[group_id], self.item_name_max_length,
        )
        row.toggle_requested.connect(self.toggle_group)
        row.rename_requested.connect(self.rename_group)
        row.delete_requested.connect(self.delete_group)
        item.setSizeHint(row.sizeHint())
        self.prompt_list.addItem(item)
        self.prompt_list.setItemWidget(item, row)

    def _add_section_item(self) -> None:
        """Insert the separator before pinned and ungrouped prompts."""

        item = QListWidgetItem()
        item.setData(ITEM_TYPE_ROLE, ITEM_SECTION)
        item.setFlags(Qt.ItemFlag.ItemIsEnabled)
        row = SectionListRow()
        item.setSizeHint(row.sizeHint())
        self.prompt_list.addItem(item)
        self.prompt_list.setItemWidget(item, row)

    def _add_prompt_item(self, prompt: Prompt) -> None:
        item = QListWidgetItem()
        item.setData(PROMPT_ID_ROLE, prompt.id)
        item.setData(ITEM_TYPE_ROLE, ITEM_PROMPT)
        item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsDragEnabled)
        row = PromptListRow(prompt, self.item_name_max_length)
        row.use_requested.connect(self.use_prompt)
        row.rename_requested.connect(self._rename_prompt_from_list)
        row.group_requested.connect(self._show_group_menu)
        row.pin_requested.connect(self._set_prompt_pinned)
        item.setSizeHint(row.sizeHint())
        self.prompt_list.addItem(item)
        self.prompt_list.setItemWidget(item, row)

    def toggle_group(self, group_id: int) -> None:
        """Toggle one group's visibility; groups start collapsed by default."""

        self._collapsed_group_ids[group_id] = not self._collapsed_group_ids.get(group_id, True)
        logger.info("User toggled group id=%d collapsed=%s", group_id, self._collapsed_group_ids[group_id])
        self.refresh_prompt_list(select_id=self.current_prompt_id, load_selection=False)

    def create_group(self) -> None:
        """Create a first-level group for the currently selected category."""

        name, accepted = QInputDialog.getText(self, "新建分组", "分组名称：")
        if not accepted:
            logger.debug("User cancelled group creation")
            return
        try:
            group = self.service.create_group(name, self.current_kind)
            self._collapsed_group_ids[group.id] = True
            self.refresh_prompt_list()
            self.statusBar().showMessage("分组已创建", 2500)
        except ValidationError as exc:
            logger.warning("Group creation failed kind=%s error=%s", self.current_kind, type(exc).__name__)
            self._show_error(str(exc))

    def rename_group(self, group_id: int) -> None:
        """Rename a group without changing any member prompt."""

        group = next((item for item in self.service.list_groups(self.current_kind) if item.id == group_id), None)
        if group is None:
            return
        name, accepted = QInputDialog.getText(self, "重命名分组", "分组名称：", text=group.name)
        if not accepted:
            logger.debug("User cancelled group rename id=%d", group_id)
            return
        try:
            self.service.rename_group(group_id, name)
            self.refresh_prompt_list(select_id=self.current_prompt_id, load_selection=False)
            self.statusBar().showMessage("分组已重命名", 2500)
        except ValidationError as exc:
            logger.warning("Group rename failed id=%d error=%s", group_id, type(exc).__name__)
            self._show_error(str(exc))

    def delete_group(self, group_id: int) -> None:
        """Delete a group while keeping its prompts in the ungrouped section."""

        answer = QMessageBox.question(
            self, "删除分组", "删除分组后，其中的条目会保留并移到未分组区域，确定继续吗？",
            QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Yes,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            logger.info("User cancelled group deletion id=%d", group_id)
            return
        try:
            self.service.delete_group(group_id)
            self._collapsed_group_ids.pop(group_id, None)
            self.refresh_prompt_list(select_id=self.current_prompt_id, load_selection=False)
            self.statusBar().showMessage("分组已删除，条目已保留", 3000)
        except ValidationError as exc:
            logger.warning("Group deletion failed id=%d error=%s", group_id, type(exc).__name__)
            self._show_error(str(exc))

    def _show_group_menu(self, prompt_id: int, button: object) -> None:
        """Show group choices for one prompt row."""

        if not isinstance(button, QPushButton):
            return
        prompt = self.service.get_prompt(prompt_id)
        if prompt is None:
            return
        menu = QMenu(button)
        actions: dict[object, int | None] = {}
        ungrouped = menu.addAction("无分组")
        ungrouped.setCheckable(True)
        ungrouped.setChecked(prompt.group_id is None)
        actions[ungrouped] = None
        menu.addSeparator()
        for group in self.service.list_groups(self.current_kind):
            action = menu.addAction(group.name)
            action.setCheckable(True)
            action.setChecked(prompt.group_id == group.id)
            actions[action] = group.id
        if len(actions) == 1:
            menu.addAction("请先新建分组").setEnabled(False)
        chosen = menu.exec(button.mapToGlobal(button.rect().bottomLeft()))
        if chosen not in actions:
            return
        try:
            self.service.set_prompt_group(prompt_id, actions[chosen])
            self.refresh_prompt_list(select_id=prompt_id, load_selection=False)
            self.statusBar().showMessage("分组已更新", 2200)
        except ValidationError as exc:
            logger.warning("Group assignment failed prompt_id=%d error=%s", prompt_id, type(exc).__name__)
            self._show_error(str(exc))

    def _set_prompt_pinned(self, prompt_id: int, pinned: bool) -> None:
        """Set a prompt's pinned state and keep the current editor selected."""

        try:
            self.service.set_prompt_pinned(prompt_id, pinned)
            self.refresh_prompt_list(select_id=prompt_id, load_selection=False)
            self.statusBar().showMessage("已置顶" if pinned else "已取消置顶", 2200)
        except ValidationError as exc:
            logger.warning("Pin change failed prompt_id=%d error=%s", prompt_id, type(exc).__name__)
            self._show_error(str(exc))

    @staticmethod
    def _prompt_bucket(prompt: Prompt) -> tuple[str, int | None]:
        if prompt.is_pinned:
            return "pinned", None
        return ("group", prompt.group_id) if prompt.group_id is not None else ("ungrouped", None)

    def _reorder_prompt_by_drag(self, source_id: int, target_id: int) -> None:
        """Move a dragged prompt before its target inside the same bucket."""

        prompts = self.service.list_prompts(self.current_kind)
        source = next((prompt for prompt in prompts if prompt.id == source_id), None)
        target = next((prompt for prompt in prompts if prompt.id == target_id), None)
        if source is None or target is None or self._prompt_bucket(source) != self._prompt_bucket(target):
            logger.warning("Invalid drag reorder source_id=%d target_id=%d", source_id, target_id)
            self.statusBar().showMessage("条目只能在同一分组或同一置顶区域内排序", 3000)
            return
        bucket = [prompt.id for prompt in prompts if self._prompt_bucket(prompt) == self._prompt_bucket(source)]
        bucket.remove(source_id)
        bucket.insert(bucket.index(target_id), source_id)
        try:
            self.service.reorder_prompts(bucket)
            self.refresh_prompt_list(select_id=source_id, load_selection=False)
        except ValidationError as exc:
            logger.warning("Reorder failed source_id=%d target_id=%d error=%s", source_id, target_id, type(exc).__name__)
            self._show_error(str(exc))

    def _assign_prompt_by_drag(self, prompt_id: int, group_id: int) -> None:
        """Assign a dragged prompt to a group; dragging a pinned item unpins it."""

        try:
            self.service.set_prompt_group(prompt_id, group_id)
            prompt = self.service.get_prompt(prompt_id)
            if prompt is not None and prompt.is_pinned:
                self.service.set_prompt_pinned(prompt_id, False)
            self.refresh_prompt_list(select_id=prompt_id, load_selection=False)
            self.statusBar().showMessage("条目已移入分组", 2200)
        except ValidationError as exc:
            logger.warning("Drop into group failed prompt_id=%d group_id=%d error=%s", prompt_id, group_id, type(exc).__name__)
            self._show_error(str(exc))
