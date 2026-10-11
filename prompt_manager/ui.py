"""PySide6 desktop user interface for Prompt Manager."""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Callable
from pathlib import Path
from typing import cast

from PySide6.QtCore import QEvent, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QCloseEvent, QKeyEvent, QKeySequence, QPainter, QPen, QShortcut, QTextCursor
from PySide6.QtWidgets import (
    QApplication, QAbstractItemView, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QFrame,
    QHBoxLayout, QLabel, QKeySequenceEdit, QLineEdit, QListWidget, QListWidgetItem,
    QInputDialog, QMainWindow, QMenu, QMessageBox, QPushButton, QSizePolicy, QSplitter,
    QSpinBox, QStackedWidget, QTextBrowser, QTextEdit, QToolButton, QVBoxLayout, QWidget,
)

from .editor import MarkdownEditor
from .agent import (
    GLM_KNOWN_MODELS, PROVIDER_DEFAULTS, AgentRequestError,
    fetch_glm_models, fetch_ollama_models, provider_config,
)
from .agent_panel import AgentPanel
from .database_maintenance import AgentBackupSession, DatabaseTaskThread, RestoreDatabaseDialog
from .drag_exports import DEFAULT_RETENTION_MINUTES, MAX_RETENTION_MINUTES, MIN_RETENTION_MINUTES, PromptDragExportManager
from .models import Prompt
from .service import PromptService, ValidationError
from .storage import StorageError
from .ui_constants import (
    APP_STYLESHEET, DEFAULT_SHORTCUTS, SHORTCUT_LABELS,
    DEFAULT_ITEM_NAME_MAX_LENGTH, DEFAULT_NEW_PROMPT_NAME,
    DEFAULT_NEW_PROMPT_CONTENT, PROMPT_ID_ROLE, ITEM_TYPE_ROLE,
    ITEM_PROMPT, ITEM_GROUP, ITEM_SECTION,
)
from .ui_widgets import (
    truncate_display_name, PromptListWidget, PromptListRow, CopyButton,
    GroupListRow, SectionListRow, FillPromptDialog,
)
from .ui_settings import _ModelFetchThread, _ModelComboBox, SettingsDialog
from .ui_actions import MainWindowActions
from .ui_list_actions import MainWindowListActions

logger = logging.getLogger(__name__)


class MainWindow(MainWindowListActions, MainWindowActions, QMainWindow):
    """Main window for browsing, editing, and using stored prompts."""

    # Maximum interval between the two Shift presses that open the
    # currently selected prompt.  Chosen to match the OS double-click
    # interval so the gesture feels like a standard double click.
    # _DOUBLE_SHIFT_MAX_INTERVAL_MS = QApplication.doubleClickInterval() if QApplication.instance() else 400

    def __init__(self, service: PromptService) -> None:
        super().__init__()
        self.service = service
        self._drag_exports = PromptDragExportManager(
            service,
            service.repository.database_path.parent,
            self._read_drag_export_retention(self.service.settings()),
            self,
        )
        # Safety copies taken before every Agent reply; they live for this run
        # only and are removed again when the window closes.
        self._agent_backups = AgentBackupSession(service)
        self.current_prompt_id: int | None = None
        self.current_kind = "prompt"
        self._collapsed_group_ids: dict[int, bool] = {}
        self.item_name_max_length = self._read_item_name_max_length(self.service.settings())
        self._loading_editor = False
        self._loading_temporary = False
        # Every Markdown pane of the window, and the one the shared formatting
        # actions currently target.  Both are filled in by ``_build_ui``; the
        # empty default keeps event delivery safe before that happens.
        self._markdown_editors: tuple[MarkdownEditor, ...] = ()
        self._last_focused_editor: MarkdownEditor | None = None
        # Double Shift gesture state.
        #
        # ``_last_shift_press_time`` holds the monotonic time of the most
        # recent counted physical Shift press, or ``None`` while no press is
        # pending.  ``_last_shift_press_id`` holds that press's event
        # timestamp so Qt's re-delivery of the very same event along the
        # widget parent chain can be recognised and ignored.
        self._last_shift_press_time: float | None = None
        self._last_shift_press_id: int | None = None
        # Qt's double-click interval defines how quickly the second Shift
        # press must follow the first one.  It is read here rather than at
        # class-definition time because no QApplication instance exists while
        # this module is being imported.
        self._double_shift_interval_seconds = QApplication.doubleClickInterval() / 1000.0
        self._autosave_timer = QTimer(self)
        self._autosave_timer.setSingleShot(True)
        self._autosave_timer.setInterval(650)
        self._autosave_timer.timeout.connect(self._auto_save)
        self._temporary_autosave_timer = QTimer(self)
        self._temporary_autosave_timer.setSingleShot(True)
        self._temporary_autosave_timer.setInterval(450)
        self._temporary_autosave_timer.timeout.connect(self._save_temporary_text)
        self._shortcuts: list[QShortcut] = []
        self.setWindowTitle("Prompt Manager")
        self.setMinimumSize(1080, 720)
        self.resize(1260, 820)
        self.setStyleSheet(APP_STYLESHEET)
        self._build_ui()
        self._database_thread: DatabaseTaskThread | None = None
        self._install_shortcuts()
        self.refresh_prompt_list()
        # Application-level filter is required because the double Shift
        # gesture must fire regardless of which child widget owns focus.
        application = QApplication.instance()
        if application is not None:
            application.installEventFilter(self)

    def _build_ui(self) -> None:
        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(26, 22, 26, 18)
        root.setSpacing(14)

        columns = QHBoxLayout()
        columns.setSpacing(14)

        # Left column: compact title card, the prompt list card, and the
        # settings/Agent actions moved below the list to free vertical space.
        left_panel = QWidget()
        left_panel.setFixedWidth(250)
        left_column = QVBoxLayout(left_panel)
        left_column.setContentsMargins(0, 0, 0, 0)
        left_column.setSpacing(14)

        title_card = QFrame()
        title_card.setObjectName("ToolbarCard")
        title_layout = QVBoxLayout(title_card)
        title_layout.setContentsMargins(18, 14, 18, 14)
        app_title = QLabel("Prompt Manager")
        app_title.setObjectName("AppTitle")
        title_layout.addWidget(app_title)
        left_column.addWidget(title_card)

        sidebar = QFrame()
        sidebar.setObjectName("Sidebar")
        side_layout = QVBoxLayout(sidebar)
        side_layout.setContentsMargins(14, 14, 14, 14)
        side_layout.setSpacing(8)

        category_bar = QHBoxLayout()
        self.prompt_category_button = QPushButton("提示词预设")
        self.fixed_category_button = QPushButton("固定预设")
        for button in (self.prompt_category_button, self.fixed_category_button):
            button.setObjectName("CategoryButton")
            button.setCheckable(True)
            category_bar.addWidget(button)
        self.prompt_category_button.setChecked(True)
        self.prompt_category_button.clicked.connect(lambda: self.switch_category("prompt"))
        self.fixed_category_button.clicked.connect(lambda: self.switch_category("fixed"))
        side_layout.addLayout(category_bar)

        side_header = QHBoxLayout()
        side_label = QLabel("我的条目")
        side_label.setStyleSheet("font-size: 16px; font-weight: 700;")
        self.count_label = QLabel()
        self.count_label.setObjectName("Meta")
        self.new_group_button = QPushButton("新建分组")
        self.new_group_button.setObjectName("MiniButton")
        self.new_group_button.clicked.connect(self.create_group)
        side_header.addWidget(side_label)
        side_header.addStretch()
        side_header.addWidget(self.count_label)
        side_header.addWidget(self.new_group_button)
        side_layout.addLayout(side_header)

        self.prompt_list = PromptListWidget(self._export_prompt_for_drag)
        self.prompt_list.export_failed.connect(self._show_drag_export_error)
        self.prompt_list.currentItemChanged.connect(self._select_prompt)
        self.prompt_list.prompt_dropped.connect(self._reorder_prompt_by_drag)
        self.prompt_list.prompt_dropped_on_group.connect(self._assign_prompt_by_drag)
        side_layout.addWidget(self.prompt_list, 1)

        self.temporary_text_button = QPushButton("临时文本")
        self.temporary_text_button.setObjectName("TemporaryButton")
        self.temporary_text_button.setCheckable(True)
        self.temporary_text_button.setToolTip("打开或关闭支持 Markdown 的临时文本面板")
        self.temporary_text_button.clicked.connect(self.toggle_temporary_text)
        new_button = QPushButton("新建")
        new_button.setObjectName("PrimaryButton")
        new_button.setToolTip("新建当前类别的条目")
        new_button.clicked.connect(self.new_prompt)
        bottom_row = QHBoxLayout()
        bottom_row.setSpacing(8)
        bottom_row.addWidget(self.temporary_text_button, 1)
        bottom_row.addWidget(new_button, 1)
        side_layout.addLayout(bottom_row)
        left_column.addWidget(sidebar, 1)

        actions_row = QHBoxLayout()
        actions_row.setSpacing(8)
        settings_button = QPushButton("设置")
        settings_button.clicked.connect(self.open_settings)
        self.agent_button = QPushButton("Agent")
        self.agent_button.setCheckable(True)
        self.agent_button.clicked.connect(self.open_agent)
        actions_row.addWidget(settings_button, 1)
        actions_row.addWidget(self.agent_button, 1)
        left_column.addLayout(actions_row)

        columns.addWidget(left_panel)

        editor = QFrame()
        editor.setObjectName("EditorCard")
        editor_layout = QVBoxLayout(editor)
        editor_layout.setContentsMargins(22, 20, 22, 20)
        header = QHBoxLayout()
        editor_title = QLabel("编辑内容")
        editor_title.setStyleSheet("font-size: 20px; font-weight: 700;")
        header.addWidget(editor_title)
        header.addStretch()
        self.meta_label = QLabel("")
        self.meta_label.setObjectName("Meta")
        header.addWidget(self.meta_label)
        editor_layout.addLayout(header)

        self.editing_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.editing_splitter.setChildrenCollapsible(False)
        content_panel = QWidget()
        content_layout = QVBoxLayout(content_panel)
        content_layout.setContentsMargins(0, 0, 6, 0)
        content_label = QLabel("内容")
        content_label.setObjectName("Meta")
        self.content_edit = MarkdownEditor()
        self.content_edit.setPlaceholderText("输入 Markdown 提示词。\n\n=====REPLACE: 主题=====\n=====IMPORT: 代码质量要求=====")
        self.content_edit.setMinimumHeight(390)
        self.content_preview = QTextBrowser()
        self.content_preview.setOpenLinks(False)
        self.content_preview.setOpenExternalLinks(False)
        self.content_stack = QStackedWidget()
        self.content_stack.addWidget(self.content_edit)
        self.content_stack.addWidget(self.content_preview)
        content_layout.addWidget(content_label)
        content_layout.addWidget(self.content_stack, 1)
        self.editing_splitter.addWidget(content_panel)

        self.temporary_panel = QFrame()
        self.temporary_panel.setObjectName("TemporaryCard")
        temporary_layout = QVBoxLayout(self.temporary_panel)
        temporary_layout.setContentsMargins(12, 12, 12, 12)
        temporary_label = QLabel("临时文本")
        temporary_label.setStyleSheet("font-size: 16px; font-weight: 700;")
        # The scratch pane is the same Markdown editor as the prompt pane, so
        # highlighting, folding, and the shared editing shortcuts behave the
        # same in both.
        self.temporary_text_edit = MarkdownEditor()
        self.temporary_text_edit.setPlaceholderText(
            "支持 Markdown。这里的内容会自动保存，可作为临时记录区使用。"
        )
        self.temporary_text_edit.setPlainText(self.service.settings().get("temporary_text", ""))
        temporary_layout.addWidget(temporary_label)
        temporary_layout.addWidget(self.temporary_text_edit, 1)
        self.editing_splitter.addWidget(self.temporary_panel)
        self.temporary_panel.setVisible(False)
        self.editing_splitter.setSizes([1080, 900])
        self._markdown_editors = (self.content_edit, self.temporary_text_edit)
        for markdown_editor in self._markdown_editors:
            markdown_editor.installEventFilter(self)
        editor_layout.addWidget(self.editing_splitter, 1)
        editor_layout.addLayout(self._build_format_toolbar())
        hint = QLabel("修改会自动保存。编辑器快捷键可在设置中查看和修改。")
        hint.setObjectName("Hint")
        hint.setWordWrap(True)
        editor_layout.addWidget(hint)
        actions = QHBoxLayout()
        self.delete_button = QPushButton("删除")
        self.delete_button.setObjectName("DangerButton")
        self.delete_button.clicked.connect(self.delete_current_prompt)
        actions.addWidget(self.delete_button)
        optimize_button = QToolButton()
        optimize_button.setText("优化提示词 ▾")
        optimize_button.setToolTip("将当前编辑框中的提示词组装后复制到剪贴板")
        optimize_menu = QMenu(optimize_button)
        no_file_action = optimize_menu.addAction("无文件优化")
        no_file_action.triggered.connect(lambda: self.optimize_current_prompt(False))
        with_file_action = optimize_menu.addAction("有文件优化")
        with_file_action.triggered.connect(lambda: self.optimize_current_prompt(True))
        optimize_button.setMenu(optimize_menu)
        optimize_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        actions.addWidget(optimize_button)
        self.render_button = QPushButton("渲染")
        self.render_button.setObjectName("RenderButton")
        self.render_button.setCheckable(True)
        self.render_button.setToolTip("切换提示词的 Markdown 渲染与编辑模式")
        self.render_button.setAccessibleName("渲染提示词")
        self.render_button.toggled.connect(self._toggle_content_render)
        actions.addWidget(self.render_button)
        actions.addStretch()
        self.autosave_label = QLabel("自动保存已开启")
        self.autosave_label.setObjectName("Meta")
        actions.addWidget(self.autosave_label)
        editor_layout.addLayout(actions)
        columns.addWidget(editor, 1)

        self.agent_panel = AgentPanel(self)
        columns.addWidget(self.agent_panel)
        self.agent_panel.setVisible(False)
        root.addLayout(columns, 1)
        self.setCentralWidget(central)

        self.content_edit.textChanged.connect(self._on_content_changed)
        self.temporary_text_edit.textChanged.connect(self._schedule_temporary_autosave)
        self.statusBar().showMessage("准备就绪")

    @staticmethod
    def _read_item_name_max_length(settings: dict[str, str]) -> int:
        """Read and clamp the user-configurable navigation name length."""

        try:
            return max(1, min(100, int(settings.get("item_name_max_length", DEFAULT_ITEM_NAME_MAX_LENGTH))))
        except (TypeError, ValueError):
            return DEFAULT_ITEM_NAME_MAX_LENGTH

    @staticmethod
    def _read_drag_export_retention(settings: dict[str, str]) -> int:
        """Read the persisted temporary export lifetime with safe defaults."""

        try:
            value = int(settings.get("drag_export_retention_minutes", DEFAULT_RETENTION_MINUTES))
        except (TypeError, ValueError):
            value = DEFAULT_RETENTION_MINUTES
        return max(MIN_RETENTION_MINUTES, min(MAX_RETENTION_MINUTES, value))

    def _show_drag_export_error(self, message: str) -> None:
        """Show a recoverable file export failure without interrupting the user."""

        self.statusBar().showMessage(message, 5000)

    def _export_prompt_for_drag(self, prompt_id: int) -> Path:
        """Save the selected editor before exporting its current database content."""

        if prompt_id == self.current_prompt_id:
            self._autosave_timer.stop()
            self._auto_save()
            prompt = self.service.get_prompt(prompt_id)
            if prompt is not None and prompt.content != self.content_edit.toPlainText():
                raise OSError("当前条目尚未成功保存，无法生成拖拽文件")
        return self._drag_exports.export_prompt(prompt_id)

    def _build_format_toolbar(self) -> QHBoxLayout:
        """Build common Markdown actions and put less-used actions in a menu.

        Every action modifies the Markdown pane that last had focus, so the
        toolbar works for the prompt editor and the temporary editor alike.
        """

        layout = QHBoxLayout()
        actions = (
            ("H1", "在当前行添加一级标题", lambda: self._active_editor().prefix_current_line("# ")),
            ("H2", "在当前行添加二级标题", lambda: self._active_editor().prefix_current_line("## ")),
            ("粗体", "将选中文本包裹为 **文本**", lambda: self._active_editor().wrap_selection("**")),
            ("斜体", "将选中文本包裹为 *文本*", lambda: self._active_editor().wrap_selection("*")),
            ("代码", "将选中文本包裹为 `代码`", lambda: self._active_editor().wrap_selection("`")),
            ("引用", "在当前行添加 > 引用符号", lambda: self._active_editor().prefix_current_line("> ")),
            ("列表", "在当前行添加 - 列表符号", lambda: self._active_editor().prefix_current_line("- ")),
        )
        for text, tip, callback in actions:
            button = QPushButton(text)
            button.setToolTip(tip)
            button.clicked.connect(lambda _checked=False, action=text: logger.info("User selected formatting action=%s", action))
            button.clicked.connect(callback)
            layout.addWidget(button)
        more = QToolButton()
        more.setText("杂项 ▾")
        more.setToolTip("更多 Markdown 格式与占位符操作")
        menu = QMenu(more)
        for text, callback in (
            ("H3 标题", lambda: self._active_editor().prefix_current_line("### ")),
            ("链接 [文字](地址)", self.insert_link),
            ("代码块 ```", self.insert_code_block),
            ("插入替换占位符", lambda: self.insert_marker("replace")),
            ("插入导入占位符", lambda: self.insert_marker("import")),
        ):
            action = menu.addAction(text)
            action.triggered.connect(lambda _checked=False, action_name=text: logger.info("User selected formatting action=%s", action_name))
            action.triggered.connect(callback)
        more.setMenu(menu)
        more.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        layout.addWidget(more)
        layout.addStretch()
        return layout

    def _active_editor(self) -> MarkdownEditor:
        """Return the Markdown pane the shared editing actions must modify.

        The prompt editor is the default so that every action keeps its
        original target while the temporary pane is hidden or has never been
        used.
        """

        editor = self._last_focused_editor
        if editor is not None and editor.isVisible():
            return editor
        if self.render_button.isChecked():
            self.render_button.setChecked(False)
        return self.content_edit

    def _toggle_content_render(self, rendered: bool) -> None:
        """Show the current Markdown without changing the editor document or undo stack."""

        if rendered:
            self.content_preview.setMarkdown(self.content_edit.toPlainText())
            self.content_stack.setCurrentWidget(self.content_preview)
        else:
            self.content_stack.setCurrentWidget(self.content_edit)
            self.content_edit.setFocus()

    def _install_shortcuts(self) -> None:
        settings = DEFAULT_SHORTCUTS | self.service.settings()
        for shortcut in self._shortcuts:
            shortcut.setEnabled(False)
            shortcut.deleteLater()
        self._shortcuts = []
        global_actions = {
            "insert_replace": lambda: self.insert_marker("replace"),
            "insert_import": lambda: self.insert_marker("import"),
            "settings": self.open_settings,
            "rename_row_item": self._trigger_row_rename,
        }
        # Global actions belong to the window; the editor actions are bound once
        # per Markdown pane so that each of them only fires while that pane, or
        # one of its children, holds the focus.
        bindings: list[tuple[str, QWidget, Callable[[], None]]] = [
            (key, self, callback) for key, callback in global_actions.items()
        ]
        for editor in self._markdown_editors:
            bindings.extend(
                (key, editor, callback) for key, callback in self._editor_actions(editor).items()
            )
        for key, parent, callback in bindings:
            sequence_text = settings.get(key, DEFAULT_SHORTCUTS[key])
            if not sequence_text.strip():
                continue
            shortcut = QShortcut(QKeySequence(sequence_text), parent)
            shortcut.setContext(
                Qt.ShortcutContext.WindowShortcut
                if parent is self
                else Qt.ShortcutContext.WidgetWithChildrenShortcut
            )
            shortcut.activated.connect(lambda action=key: logger.info("User activated shortcut=%s", action))
            shortcut.activated.connect(callback)
            self._shortcuts.append(shortcut)

    def _editor_actions(self, editor: MarkdownEditor) -> dict[str, Callable[[], None]]:
        """Return the editor shortcuts bound to one Markdown pane."""

        return {
            "find": editor.open_find_bar,
            "replace": editor.open_replace_bar,
            "expand_selection": editor.expand_selection,
            "copy_line": lambda: self._copy_or_cut_editor_line(editor, False),
            "cut_line": lambda: self._copy_or_cut_editor_line(editor, True),
            "move_line_up": lambda: editor.move_current_line(-1),
            "move_line_down": lambda: editor.move_current_line(1),
            "fold_section": editor.collapse_section,
            "unfold_section": lambda: editor.expand_section(recursive=False),
            "unfold_section_recursive": lambda: editor.expand_section(recursive=True),
            "expand_all": editor.expand_all,
            "collapse_all": editor.collapse_all,
        }

    def _trigger_row_rename(self) -> None:
        """Start inline renaming of the selected navigation entry.

        Bound to a shortcut, F2 by default, and equivalent to double-clicking
        the entry's title.  Group rows and an empty selection are ignored,
        because only prompt entries are renamed in place.
        """

        current_item = self.prompt_list.currentItem()
        if current_item is None or current_item.data(ITEM_TYPE_ROLE) != ITEM_PROMPT:
            return
        row_widget = self.prompt_list.itemWidget(current_item)
        if isinstance(row_widget, PromptListRow):
            row_widget._begin_rename()

    def _copy_or_cut_editor_line(self, editor: MarkdownEditor, cut: bool) -> None:
        """Keep normal selected-text copy behavior and edit whole lines otherwise."""

        if editor.textCursor().hasSelection():
            (editor.cut if cut else editor.copy)()
            return
        editor._copy_or_cut_current_line(cut)

    def toggle_temporary_text(self) -> None:
        """Show or hide the persistent temporary-text Markdown editor."""

        visible = not self.temporary_panel.isVisible()
        logger.info("User toggled temporary editor visible=%s", visible)
        self.temporary_panel.setVisible(visible)
        self.temporary_text_button.setChecked(visible)
        if visible:
            self.editing_splitter.setSizes([1, 1])
            self.temporary_text_edit.setFocus()

    def _schedule_temporary_autosave(self) -> None:
        """Debounce temporary text writes so each keystroke does not hit SQLite."""

        if not self._loading_temporary:
            self._temporary_autosave_timer.start()

    def _save_temporary_text(self) -> None:
        """Persist the global temporary note in the existing settings table."""

        try:
            content = self.temporary_text_edit.toPlainText()
            self.service.save_settings({"temporary_text": content})
            logger.debug("Temporary text saved chars=%d", len(content))
        except StorageError as exc:
            logger.warning("Temporary text save failed error=%s", type(exc).__name__)
            self.statusBar().showMessage(f"临时文本保存失败：{exc}", 3500)


    def optimize_current_prompt(self, with_file: bool) -> None:
        """Render the current prompt through the fill dialog, then copy an optimization request.

        The optimization instruction is prepended to the *rendered* prompt, so
        placeholders and imports are resolved before the text is sent to an
        external model.  Without this step the clipboard would contain raw
        ``=====REPLACE: ...=====`` / ``=====IMPORT: ...=====`` markers.
        """

        if self.current_prompt_id is None:
            logger.warning("Optimization requested without a selected prompt")
            self._show_error("请先选择或输入一个提示词")
            return
        self._autosave_timer.stop()
        self._auto_save()
        prompt = self.service.get_prompt(self.current_prompt_id)
        if prompt is None:
            self._show_error("提示词已不存在，请刷新后重试")
            return
        instruction = (
            "请你根据我发给你的文件内容，帮我优化以下提示词，并以text格式交付我"
            if with_file else "请你帮我优化以下提示词，并以text格式交付我"
        )
        try:
            if self.service.placeholders_for(prompt):
                dialog = FillPromptDialog(
                    self.service,
                    prompt,
                    self,
                    accept_text="生成优化指令",
                    copy_on_accept=False,
                )
                if dialog.exec() != QDialog.DialogCode.Accepted:
                    return
                content = dialog.rendered_content()
                if content is None:
                    return
            else:
                content = self.service.render(prompt, {})
        except (ValidationError, StorageError) as exc:
            logger.warning("Prompt optimization failed id=%d error=%s", prompt.id, type(exc).__name__)
            self._show_error(str(exc))
            return
        logger.info("User copied optimization request prompt_id=%d with_file=%s chars=%d", prompt.id, with_file, len(content))
        self._copy_to_clipboard(f"{instruction}\n{content}", "优化提示词已复制到剪贴板")

    def _select_prompt(self, current: QListWidgetItem | None, _previous: QListWidgetItem | None) -> None:
        if current is None or current.data(ITEM_TYPE_ROLE) != ITEM_PROMPT:
            return
        prompt = self.service.get_prompt(int(current.data(PROMPT_ID_ROLE)))
        if prompt is not None:
            logger.info("User selected prompt id=%d kind=%s", prompt.id, prompt.kind)
            self._load_prompt_into_editor(prompt)

    def _load_prompt_into_editor(self, prompt: Prompt) -> None:
        self._loading_editor = True
        self.current_prompt_id = prompt.id
        self.content_edit.setPlainText(prompt.content)
        if self.render_button.isChecked():
            self.content_preview.setMarkdown(prompt.content)
        self.content_edit.set_import_candidates(
            item.name for item in self.service.list_prompts("fixed") if item.id != prompt.id
        )
        self._update_meta(prompt)
        self.delete_button.setEnabled(True)
        self._loading_editor = False

    def _clear_editor(self) -> None:
        """Reset the editor when the active category has no prompts left."""

        self._loading_editor = True
        self.current_prompt_id = None
        self.prompt_list.clearSelection()
        self.content_edit.clear()
        if self.render_button.isChecked():
            self.content_preview.clear()
        self.meta_label.setText("")
        self.delete_button.setEnabled(False)
        self._loading_editor = False

    def _update_meta(self, prompt: Prompt) -> None:
        try:
            placeholders = len(self.service.placeholders_for(prompt))
            imports = len(self.service.imports_for(prompt))
        except ValidationError:
            placeholders = imports = 0
        self.meta_label.setText(f"{placeholders} 个输入 · {imports} 个导入")

    def _unique_new_prompt_name(self) -> str:
        """Return a free ``新建提示词`` name across all prompt categories.

        The ``prompts`` table enforces a global ``UNIQUE(name)`` constraint,
        so prompts from different categories cannot share the same name.
        The previous implementation restricted the availability check to
        :attr:`current_kind`; when the *other* category already held the
        default name, the pre-flight check reported it as free and the
        subsequent ``INSERT`` failed with the ``提示词名称已存在`` error
        surfaced by the storage layer.  Querying without a category filter
        keeps the check aligned with the actual database constraint.
        """

        candidate = DEFAULT_NEW_PROMPT_NAME
        index = 2
        while self.service.find_prompt_by_name(candidate) is not None:
            candidate = f"{DEFAULT_NEW_PROMPT_NAME} {index}"
            index += 1
        return candidate

    def new_prompt(self) -> None:
        """Create a fresh prompt entry and place the caret in the content editor."""

        self._autosave_timer.stop()
        try:
            name = self._unique_new_prompt_name()
            prompt = self.service.create_prompt(name, DEFAULT_NEW_PROMPT_CONTENT, self.current_kind)
        except (ValidationError, StorageError) as exc:
            logger.warning("Prompt creation failed kind=%s error=%s", self.current_kind, type(exc).__name__)
            self._show_error(str(exc))
            return
        self.refresh_prompt_list(select_id=prompt.id)
        self.render_button.setChecked(False)
        self.content_edit.setFocus()
        self.content_edit.selectAll()
        cursor = self.content_edit.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self.content_edit.setTextCursor(cursor)
        self.statusBar().showMessage("已新建条目，可直接编辑内容", 2500)

    def _rename_prompt_from_list(self, prompt_id: int, new_name: str) -> None:
        """Persist an inline title rename requested from a list row."""

        new_name = new_name.strip()
        prompt = self.service.get_prompt(prompt_id)
        if prompt is None or not new_name or new_name == prompt.name:
            return
        content = prompt.content
        if prompt_id == self.current_prompt_id:
            editor_content = self.content_edit.toPlainText()
            if editor_content.strip():
                content = editor_content
        try:
            self.service.update_prompt(prompt_id, new_name, content, prompt.kind)
        except (ValidationError, StorageError) as exc:
            logger.warning("Prompt rename failed id=%d error=%s", prompt_id, type(exc).__name__)
            self.statusBar().showMessage(str(exc), 3500)
            self.refresh_prompt_list(select_id=self.current_prompt_id, load_selection=False)
            return
        self.refresh_prompt_list(select_id=prompt_id, load_selection=False)
        self.statusBar().showMessage("条目已重命名", 2200)

    def _on_content_changed(self) -> None:
        if self.render_button.isChecked():
            self.content_preview.setMarkdown(self.content_edit.toPlainText())
        if not self._loading_editor:
            self._schedule_autosave()

    def _schedule_autosave(self) -> None:
        if not self._loading_editor:
            self.autosave_label.setText("正在等待自动保存…")
            self._autosave_timer.start()

    def _auto_save(self) -> None:
        """Persist the editor content while keeping the entry name unchanged."""

        if self.current_prompt_id is None:
            return
        content = self.content_edit.toPlainText()
        if not content.strip():
            logger.debug("Autosave skipped empty prompt id=%d", self.current_prompt_id)
            self.autosave_label.setText("自动保存已开启（内容不能为空）")
            return
        try:
            prompt = self.service.get_prompt(self.current_prompt_id)
            if prompt is None:
                return
            updated = self.service.update_prompt(self.current_prompt_id, prompt.name, content, prompt.kind)
            self._update_meta(updated)
            self.autosave_label.setText("已自动保存")
            self.statusBar().showMessage("已自动保存", 1800)
        except (ValidationError, StorageError) as exc:
            logger.warning("Prompt autosave failed id=%d error=%s", self.current_prompt_id, type(exc).__name__)
            self.autosave_label.setText("自动保存失败")
            self.statusBar().showMessage(str(exc), 3500)

    def insert_marker(self, kind: str) -> None:
        """Insert a marker at the cursor without blocking the editing flow."""

        editor = self._active_editor()
        marker = "=====REPLACE: 标题=====" if kind == "replace" else "=====IMPORT: ====="
        cursor = editor.textCursor()
        marker_start = cursor.selectionStart() if cursor.hasSelection() else cursor.position()
        cursor.insertText(marker)
        # Leave the caret inside the marker, immediately before its closing
        # delimiter, so the suggested label can be edited in place.
        cursor.setPosition(marker_start + len(marker) - len("====="))
        editor.setTextCursor(cursor)
        editor.setFocus()
        if kind != "replace":
            editor._update_import_completion()

    def insert_link(self) -> None:
        self._active_editor().wrap_selection("[", "](链接地址)")

    def insert_code_block(self) -> None:
        editor = self._active_editor()
        cursor = editor.textCursor()
        selected = cursor.selectedText()
        cursor.insertText(f"```\n{selected or '代码'}\n```")
        editor.setTextCursor(cursor)

    def open_settings(self) -> None:
        logger.info("User opened settings")
        dialog = SettingsDialog(self.service, DEFAULT_SHORTCUTS | self.service.settings(), self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            settings = self.service.settings()
            self.item_name_max_length = self._read_item_name_max_length(settings)
            self._drag_exports.set_retention_minutes(self._read_drag_export_retention(settings))
            self._install_shortcuts()
            self.refresh_prompt_list(select_id=self.current_prompt_id, load_selection=False)
            self.statusBar().showMessage("设置已保存", 2500)
        else:
            logger.debug("User closed settings without saving")

    def open_agent(self) -> None:
        """Toggle the embedded Agent panel beside the editor."""

        visible = self.agent_button.isChecked()
        logger.info("User toggled Agent panel visible=%s", visible)
        self.agent_panel.setVisible(visible)
        self.agent_button.setChecked(visible)
        if visible:
            self.agent_panel.input_edit.setFocus()

    def _copy_to_clipboard(self, text: str, message: str) -> None:
        logger.info("User copied generated text chars=%d", len(text))
        QApplication.clipboard().setText(text)
        self.statusBar().showMessage(message, 3500)

    def _show_error(self, message: str) -> None:
        logger.warning("UI displayed error dialog message_chars=%d", len(message))
        QMessageBox.critical(self, "无法完成操作", message)

    def eventFilter(self, obj: object, event: QEvent) -> bool:  # noqa: N802 - Qt override
        """Track the focused Markdown pane and open the fill dialog on double Shift.

        The filter is installed on :class:`QApplication` so the gesture fires
        no matter which child widget owns the keyboard focus, as long as the
        event belongs to this main window.  Events aimed at modal dialogs,
        popup menus, or other top-level windows are ignored, and a prompt must
        be selected in the navigation list for the gesture to do anything.

        Qt re-delivers an unaccepted key event to every ancestor widget, so a
        single physical Shift press reaches this filter several times.  Every
        re-delivery carries the same :meth:`QKeyEvent.timestamp`, which is used
        here to collapse them into one logical press.  Counting each
        re-delivery separately made one tap satisfy the double-press condition
        and queued one fill dialog per propagation step.

        :param obj: Object the event is being delivered to.
        :param event: Event being delivered.
        :return: Always ``False``; the event is never consumed so normal Shift
            behaviour in the focused widget is preserved.
        """

        if event.type() == QEvent.Type.FocusIn and any(
                obj is editor for editor in self._markdown_editors
        ):
            # Remember which Markdown pane the user is working in.  The filter
            # is installed on both panes so the shared formatting actions follow
            # the focused pane even when it is the temporary one.
            self._last_focused_editor = cast(MarkdownEditor, obj)
        if (
                event.type() == QEvent.Type.KeyPress
                and isinstance(obj, QWidget)
                and obj.window() is self
        ):
            key_event = cast(QKeyEvent, event)
            if key_event.key() == Qt.Key.Key_Shift and not key_event.isAutoRepeat():
                press_id = key_event.timestamp()
                if press_id != self._last_shift_press_id:
                    self._last_shift_press_id = press_id
                    now = time.monotonic()
                    if (
                            self._last_shift_press_time is not None
                            and now - self._last_shift_press_time <= self._double_shift_interval_seconds
                    ):
                        # Reset the pending state before invoking the action so
                        # the modal fill dialog cannot observe a stale press.
                        self._last_shift_press_time = None
                        self._use_current_prompt_shortcut()
                    else:
                        self._last_shift_press_time = now
            elif key_event.key() != Qt.Key.Key_Shift:
                self._last_shift_press_time = None
                self._last_shift_press_id = None
        return super().eventFilter(obj, event)

    def _use_current_prompt_shortcut(self) -> None:
        """Copy the prompt currently selected in the navigation list."""

        if self.current_prompt_id is None:
            return
        self.use_prompt(self.current_prompt_id)

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 - Qt override
        """Flush debounced edits before the repository is closed by the app."""

        logger.info("Main window closing")
        application = QApplication.instance()
        if application is not None:
            application.removeEventFilter(self)
        if self._database_thread is not None and self._database_thread.isRunning():
            self._database_thread.wait()
        self.agent_panel.shutdown()
        self._agent_backups.discard()
        self._autosave_timer.stop()
        self._temporary_autosave_timer.stop()
        self._drag_exports.shutdown()
        self._auto_save()
        self._save_temporary_text()
        logger.info("Main window closed")
        event.accept()
