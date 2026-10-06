"""PySide6 desktop user interface for Prompt Manager."""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import cast

from PySide6.QtCore import QEvent, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QCloseEvent, QKeyEvent, QKeySequence, QPainter, QPen, QShortcut, QTextCursor
from PySide6.QtWidgets import (
    QApplication, QAbstractItemView, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QFrame,
    QHBoxLayout, QLabel, QKeySequenceEdit, QLineEdit, QListWidget, QListWidgetItem,
    QInputDialog, QMainWindow, QMenu, QMessageBox, QPushButton, QSizePolicy, QSplitter,
    QSpinBox, QStackedWidget, QTextEdit, QToolButton, QVBoxLayout, QWidget,
)

from .editor import MarkdownEditor
from .agent import PROVIDER_DEFAULTS, AgentRequestError, fetch_ollama_models
from .agent_panel import AgentPanel
from .models import Prompt
from .service import PromptService, ValidationError
from .storage import StorageError


APP_STYLESHEET = """
QMainWindow, QDialog { background: #f5f6fa; color: #1f2430; }
QFrame#Sidebar, QFrame#EditorCard, QFrame#ToolbarCard, QFrame#FillCard, QFrame#TemporaryCard,
QWidget#AgentConversationCard {
    background: #ffffff; border: 1px solid #e6e8ef; border-radius: 16px;
}
QLabel#AppTitle { font-size: 20px; font-weight: 700; color: #151923; }
QLabel#Subtitle, QLabel#Hint, QLabel#Meta { color: #737a8c; }
QLineEdit, QTextEdit, QPlainTextEdit {
    background: #fbfbfd; border: 1px solid #dfe3eb; border-radius: 10px;
    padding: 8px 10px; selection-background-color: #8b7cf6;
}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus { border: 1px solid #8b7cf6; }
QLineEdit#InlineTitleEdit {
    background: #ffffff;
    border: none;
    border-radius: 0;
    padding: 0px 2px;
}
QLineEdit#InlineTitleEdit:focus { border: none; }
QPushButton, QToolButton {
    border: none; border-radius: 9px; padding: 8px 12px;
    background: #eef0f6; color: #353b4b; font-weight: 600;
}
QFrame#SearchReplaceBar {
    background: #ffffff;
    border: 1px solid #dfe3eb;
    border-radius: 10px;
}
QPushButton:hover, QToolButton:hover { background: #e2e4ef; }
QPushButton#PrimaryButton, QToolButton#PrimaryButton { background: #6d5ce7; color: white; }
QPushButton#PrimaryButton:hover { background: #5e4ed3; }
QPushButton#DangerButton { color: #c33850; background: #fff0f2; }
QPushButton#MiniButton { padding: 3px 6px; border-radius: 7px; }
QPushButton#CategoryButton:checked, QPushButton#TemporaryButton:checked { background: #6d5ce7; color: white; }
QListWidget { background: transparent; border: none; outline: none; }
QListWidget::item { margin: 3px 0; border-radius: 10px; }
QListWidget::item:selected { background: #eeecff; }
QFrame#GroupRow { background: #eef0ff; border: 1px solid #d6d2ff; border-radius: 10px; }
QToolButton#GroupToggleButton { padding: 0; color: #5146a6; font-weight: 700; }
QFrame#SectionDivider { background: #dfe2e9; border: none; }
QPushButton#PinButton { padding: 2px 5px; border-radius: 7px; }
QPushButton#PinButton:checked { background: #ffe49b; color: #795700; }
QPushButton#GroupActionButton { padding: 2px 5px; border-radius: 7px; }
QScrollBar:vertical { width: 8px; background: transparent; }
QScrollBar::handle:vertical { background: #d5d8e2; border-radius: 4px; min-height: 28px; }
"""

DEFAULT_SHORTCUTS = {
    "insert_replace": "Ctrl+Alt+R",
    "insert_import": "Ctrl+Alt+I",
    "settings": "Ctrl+,",
    "find": "Ctrl+F",
    "replace": "Ctrl+R",
    "expand_selection": "Ctrl+W",
    "copy_line": "Ctrl+C",
    "cut_line": "Ctrl+X",
    "move_line_up": "Alt+Shift+Up",
    "move_line_down": "Alt+Shift+Down",
    "fold_section": "Ctrl+-",
    "unfold_section": "Ctrl++",
    "unfold_section_recursive": "Ctrl+Alt++",
    "expand_all": "Ctrl+Shift++",
    "collapse_all": "Ctrl+Shift+-",
}
SHORTCUT_LABELS = {
    "insert_replace": "插入替换占位符",
    "insert_import": "插入导入占位符",
    "settings": "打开设置",
    "find": "查找",
    "replace": "查找和替换",
    "expand_selection": "扩展选区",
    "copy_line": "复制整行（无选区时）",
    "cut_line": "剪切整行（无选区时）",
    "move_line_up": "上移当前行",
    "move_line_down": "下移当前行",
    "fold_section": "折叠当前段落",
    "unfold_section": "展开当前段落",
    "unfold_section_recursive": "递归展开当前段落",
    "expand_all": "展开全部段落",
    "collapse_all": "折叠全部段落",
}
DEFAULT_ITEM_NAME_MAX_LENGTH = 10
DEFAULT_NEW_PROMPT_NAME = "新建提示词"
DEFAULT_NEW_PROMPT_CONTENT = "# 新建提示词\n"

PROMPT_ID_ROLE = Qt.ItemDataRole.UserRole
ITEM_TYPE_ROLE = Qt.ItemDataRole.UserRole + 1
ITEM_PROMPT = "prompt"
ITEM_GROUP = "group"
ITEM_SECTION = "section"
logger = logging.getLogger(__name__)


class _DatabaseBackupThread(QThread):
    """Create an SQLite snapshot away from the GUI thread."""

    completed = Signal(object, str)

    def __init__(self, service: PromptService) -> None:
        super().__init__()
        self.service = service

    def run(self) -> None:
        try:
            destination = self.service.backup_database()
        except StorageError as exc:
            self.completed.emit(None, str(exc))
        else:
            self.completed.emit(destination, "")


class _ModelFetchThread(QThread):
    """Query a local Ollama server for its installed models."""

    completed = Signal(object, str)

    def __init__(self, base_url: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.base_url = base_url

    def run(self) -> None:
        try:
            models = fetch_ollama_models(self.base_url)
        except AgentRequestError as exc:
            self.completed.emit(None, str(exc))
        else:
            self.completed.emit(models, "")


class _ModelComboBox(QComboBox):
    """Editable model picker that asks for a refresh whenever its popup opens."""

    refresh_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setEditable(True)
        self.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.setMinimumContentsLength(24)

    def showPopup(self) -> None:  # noqa: N802 - Qt override
        """Notify listeners before the popup becomes visible."""

        self.refresh_requested.emit()
        super().showPopup()


def truncate_display_name(name: str, max_length: int) -> str:
    """Return a compact, loss-aware name for the narrow navigation column."""

    if max_length < 1 or len(name) <= max_length:
        return name
    return f"{name[:max_length]}..."


class PromptListWidget(QListWidget):
    """List that turns prompt drags into explicit persistence actions."""

    prompt_dropped = Signal(int, int)
    prompt_dropped_on_group = Signal(int, int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)

    def dropEvent(self, event) -> None:  # noqa: N802 - Qt override
        """Translate a drop into group assignment or same-bucket reordering."""

        source = self.currentItem()
        target = self.itemAt(event.position().toPoint())
        if source is None or target is None or source is target:
            event.ignore()
            return
        if source.data(ITEM_TYPE_ROLE) != ITEM_PROMPT:
            event.ignore()
            return
        source_id = int(source.data(PROMPT_ID_ROLE))
        target_type = target.data(ITEM_TYPE_ROLE)
        if target_type == ITEM_GROUP:
            self.prompt_dropped_on_group.emit(source_id, int(target.data(PROMPT_ID_ROLE)))
        elif target_type == ITEM_PROMPT:
            self.prompt_dropped.emit(source_id, int(target.data(PROMPT_ID_ROLE)))
        else:
            event.ignore()
            return
        event.acceptProposedAction()


class PromptListRow(QWidget):
    """Compact prompt row with pinning, grouping, inline rename, and quick use.

    The row owns an inline rename affordance: double-clicking the title swaps
    the label for a text field and emits :attr:`rename_requested` once editing
    finishes.  The copy button reuses the full "use prompt" workflow instead of
    silently copying remembered placeholder values.
    """

    use_requested = Signal(int)
    rename_requested = Signal(int, str)
    group_requested = Signal(int, object)
    pin_requested = Signal(int, bool)

    def __init__(self, prompt: Prompt, max_name_length: int) -> None:
        super().__init__()
        self.prompt_id = prompt.id
        self._full_name = prompt.name
        self._max_name_length = max_name_length
        self._editing = False
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 5, 4)
        layout.setSpacing(2)
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        self._title_label = QLabel()
        self._title_label.setToolTip(prompt.name)
        self._title_label.setMinimumWidth(0)
        self._title_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self._title_label.installEventFilter(self)

        self._title_edit = QLineEdit()
        # A dedicated object name lets the stylesheet drop the global
        # rounded frame and keep only a white background while editing,
        # so the inline editor no longer overlaps the row's text.
        self._title_edit.setObjectName("InlineTitleEdit")
        self._title_edit.setVisible(False)
        self._title_edit.editingFinished.connect(self._commit_rename)

        self._title_stack = QStackedWidget()
        self._title_stack.setMinimumWidth(0)
        self._title_stack.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self._title_stack.addWidget(self._title_label)
        self._title_stack.addWidget(self._title_edit)

        pin_button = QPushButton("📌" if not prompt.is_pinned else "📍")
        pin_button.setObjectName("PinButton")
        pin_button.setFixedWidth(26)
        pin_button.setCheckable(True)
        pin_button.setChecked(prompt.is_pinned)
        pin_button.setToolTip("置顶条目")
        pin_button.clicked.connect(lambda checked: self.pin_requested.emit(self.prompt_id, checked))
        group_button = QPushButton("☰")
        group_button.setObjectName("GroupActionButton")
        group_button.setFixedWidth(26)
        group_button.setToolTip("设置条目所属分组")
        group_button.clicked.connect(lambda: self.group_requested.emit(self.prompt_id, group_button))
        copy_button = CopyButton()
        copy_button.setFixedWidth(26)
        copy_button.setToolTip("使用提示词")
        copy_button.clicked.connect(lambda: self.use_requested.emit(self.prompt_id))
        layout.addWidget(self._title_stack, 1)
        layout.addWidget(pin_button)
        layout.addWidget(group_button)
        layout.addWidget(copy_button)
        self._update_title()

    def eventFilter(self, obj, event) -> bool:  # noqa: N802 - Qt override
        """Enter inline rename mode when the title label is double-clicked."""

        if obj is self._title_label and event.type() == QEvent.Type.MouseButtonDblClick:
            self._begin_rename()
            return True
        return super().eventFilter(obj, event)

    def _begin_rename(self) -> None:
        """Swap the title label for an editable field seeded with the old name."""

        if self._editing:
            return
        self._editing = True
        self._title_edit.setText(self._full_name)
        self._title_stack.setCurrentWidget(self._title_edit)
        self._title_edit.selectAll()
        self._title_edit.setFocus()

    def _commit_rename(self) -> None:
        """Finish inline editing and request a rename when the name changed."""

        if not self._editing:
            return
        self._editing = False
        self._title_stack.setCurrentWidget(self._title_label)
        new_name = self._title_edit.text().strip()
        if not new_name or new_name == self._full_name:
            return
        self._full_name = new_name
        self._title_label.setToolTip(new_name)
        self._update_title()
        self.rename_requested.emit(self.prompt_id, new_name)

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt override
        """Keep the title visibly elided as the row receives its list width."""

        super().resizeEvent(event)
        self._update_title()

    def _update_title(self) -> None:
        compact_name = truncate_display_name(self._full_name, self._max_name_length)
        width = self._title_label.width()
        self._title_label.setText(
            compact_name
            if width <= 0
            else self._title_label.fontMetrics().elidedText(compact_name, Qt.TextElideMode.ElideRight, width)
        )


class CopyButton(QPushButton):
    """Button showing the standard two-overlapping-squares copy glyph."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("MiniButton")
        self.setAccessibleName("使用提示词")

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt override
        """Paint two offset outlines so the icon is independent of system fonts."""

        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(self.palette().buttonText().color())
        pen.setWidthF(1.4)
        painter.setPen(pen)
        painter.drawRect(10, 4, 10, 10)
        painter.drawRect(5, 9, 10, 10)


class GroupListRow(QFrame):
    """Distinct first-level group header with collapse and management actions."""

    toggle_requested = Signal(int)
    rename_requested = Signal(int)
    delete_requested = Signal(int)

    def __init__(self, group_id: int, name: str, count: int, collapsed: bool, max_name_length: int) -> None:
        super().__init__()
        self._full_name = name
        self._max_name_length = max_name_length
        self.setObjectName("GroupRow")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 5, 4)
        layout.setSpacing(2)
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        toggle = QToolButton()
        toggle.setObjectName("GroupToggleButton")
        toggle.setText("▶" if collapsed else "▼")
        toggle.setFixedWidth(24)
        toggle.setToolTip("展开或收起分组")
        toggle.clicked.connect(lambda: self.toggle_requested.emit(group_id))
        name_label = QLabel()
        self._name_label = name_label
        name_label.setToolTip(name)
        name_label.setMinimumWidth(0)
        name_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        name_label.setStyleSheet("font-weight: 700; color: #5146a6;")
        count_label = QLabel(f"{count} 条")
        count_label.setObjectName("Meta")
        rename = QPushButton("✎")
        rename.setObjectName("MiniButton")
        rename.setFixedWidth(26)
        rename.clicked.connect(lambda: self.rename_requested.emit(group_id))
        delete = QPushButton("🗑")
        delete.setObjectName("MiniButton")
        delete.setFixedWidth(26)
        delete.clicked.connect(lambda: self.delete_requested.emit(group_id))
        layout.addWidget(toggle)
        layout.addWidget(name_label, 1)
        layout.addWidget(count_label)
        layout.addWidget(rename)
        layout.addWidget(delete)
        self._update_name()

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt override
        """Keep the group title inside the fixed-width navigation column."""

        super().resizeEvent(event)
        self._update_name()

    def _update_name(self) -> None:
        compact_name = truncate_display_name(self._full_name, self._max_name_length)
        width = self._name_label.width()
        self._name_label.setText(
            compact_name
            if width <= 0
            else self._name_label.fontMetrics().elidedText(compact_name, Qt.TextElideMode.ElideRight, width)
        )


class SectionListRow(QFrame):
    """A non-interactive divider between groups and the remaining prompts."""

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("SectionDivider")
        self.setFixedHeight(1)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)


class FillPromptDialog(QDialog):
    """Collect replacement values and render a prompt for copying or reuse."""

    def __init__(
        self,
        service: PromptService,
        prompt: Prompt,
        parent: QWidget | None = None,
        *,
        accept_text: str = "复制到剪贴板",
        copy_on_accept: bool = True,
    ) -> None:
        super().__init__(parent)
        self.service = service
        self.prompt = prompt
        self._accept_text = accept_text
        self._copy_on_accept = copy_on_accept
        self._rendered: str | None = None
        self.fields: dict[str, QTextEdit] = {}
        self.setWindowTitle(f"使用提示词 · {prompt.name}")
        self.setMinimumSize(560, 420)
        self._build_ui()

    def rendered_content(self) -> str | None:
        """Return the rendered prompt once the dialog has been accepted."""

        return self._rendered

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 22, 24, 20)
        title = QLabel(self.prompt.name)
        title.setObjectName("AppTitle")
        root.addWidget(title)
        hint = QLabel("填写以下内容，输入会自动记忆到下次使用。")
        hint.setObjectName("Subtitle")
        root.addWidget(hint)
        card = QFrame()
        card.setObjectName("FillCard")
        form = QFormLayout(card)
        form.setContentsMargins(16, 16, 16, 16)
        form.setVerticalSpacing(14)
        values = self.service.remembered_values(self.prompt.id)
        for placeholder in self.service.placeholders_for(self.prompt):
            field = QTextEdit()
            field.setPlaceholderText(f"输入 {placeholder}")
            field.setPlainText(values.get(placeholder, ""))
            field.setMinimumHeight(70)
            field.setMaximumHeight(130)
            field.setAcceptRichText(False)
            form.addRow(QLabel(placeholder), field)
            self.fields[placeholder] = field
        root.addWidget(card, 1)
        buttons = QDialogButtonBox()
        accept_button = buttons.addButton(self._accept_text, QDialogButtonBox.ButtonRole.AcceptRole)
        accept_button.setObjectName("PrimaryButton")
        cancel_button = buttons.addButton("取消", QDialogButtonBox.ButtonRole.RejectRole)
        accept_button.clicked.connect(self._accept)
        cancel_button.clicked.connect(self.reject)
        root.addWidget(buttons)

    def _accept(self) -> None:
        """Save values, render the prompt, and optionally copy it to the clipboard."""

        values = {title: field.toPlainText() for title, field in self.fields.items()}
        try:
            self.service.save_values(self.prompt.id, values)
            self._rendered = self.service.render(self.prompt, values)
        except StorageError as exc:
            QMessageBox.critical(self, "无法保存输入", str(exc))
            return
        if self._copy_on_accept:
            QApplication.clipboard().setText(self._rendered)
        self.accept()


class SettingsDialog(QDialog):
    """Edit application shortcuts and OpenAI-compatible Agent settings."""

    def __init__(self, service: PromptService, shortcuts: dict[str, str], parent=None) -> None:
        super().__init__(parent)
        self.service = service
        self.shortcut_edits: dict[str, QKeySequenceEdit] = {}
        self.api_key_value = ""
        self._model_thread: _ModelFetchThread | None = None
        settings = service.settings()
        try:
            item_name_max_length = int(settings.get("item_name_max_length", DEFAULT_ITEM_NAME_MAX_LENGTH))
        except (TypeError, ValueError):
            item_name_max_length = DEFAULT_ITEM_NAME_MAX_LENGTH
        self.setWindowTitle("设置")
        self.setMinimumSize(720, 640)
        root = QVBoxLayout(self)
        body = QHBoxLayout()
        self.settings_navigation = QListWidget()
        self.settings_navigation.setFixedWidth(130)
        self.settings_navigation.addItems(["快捷键", "Agent 设置"])
        self.settings_pages = QStackedWidget()
        body.addWidget(self.settings_navigation)
        body.addWidget(self.settings_pages, 1)
        root.addLayout(body, 1)

        shortcuts_page = QWidget()
        form = QFormLayout(shortcuts_page)
        for key, label in SHORTCUT_LABELS.items():
            edit = QKeySequenceEdit(QKeySequence(shortcuts.get(key, DEFAULT_SHORTCUTS[key])))
            form.addRow(label, edit)
            self.shortcut_edits[key] = edit
        self.item_name_length_edit = QSpinBox()
        self.item_name_length_edit.setRange(1, 100)
        self.item_name_length_edit.setValue(max(1, min(100, item_name_max_length)))
        self.item_name_length_edit.setSuffix(" 个字符")
        self.item_name_length_edit.setToolTip("导航栏中条目和分组名称超过此长度时显示省略号")
        form.addRow("名称显示长度", self.item_name_length_edit)
        shortcuts_tip = QLabel("编辑器快捷键仅在编辑内容区域获得焦点时生效。")
        shortcuts_tip.setObjectName("Hint")
        shortcuts_tip.setWordWrap(True)
        form.addRow(shortcuts_tip)
        self.settings_pages.addWidget(shortcuts_page)

        agent_page = QWidget()
        agent_form = QFormLayout(agent_page)
        self.agent_provider_edit = QComboBox()
        self.agent_provider_edit.addItem("OpenAI", "openai")
        self.agent_provider_edit.addItem("Ollama", "ollama")
        self.agent_provider_edit.addItem("Gemini", "gemini")
        provider = settings.get("agent_provider", "openai")
        if provider not in PROVIDER_DEFAULTS:
            provider = "openai"
        provider_index = self.agent_provider_edit.findData(provider)
        self.agent_provider_edit.setCurrentIndex(max(0, provider_index))
        agent_form.addRow("服务商", self.agent_provider_edit)
        self.agent_base_url_edit = QLineEdit(settings.get("agent_base_url", PROVIDER_DEFAULTS[provider][0]))
        self.agent_base_url_edit.setPlaceholderText("OpenAI 兼容 API 基础地址")
        agent_form.addRow("API 地址", self.agent_base_url_edit)
        self.agent_model_edit = _ModelComboBox()
        self.agent_model_edit.setCurrentText(settings.get("agent_model", PROVIDER_DEFAULTS[provider][1]))
        line_edit = self.agent_model_edit.lineEdit()
        if line_edit is not None:
            line_edit.setPlaceholderText("模型名称（可直接输入或从下拉列表选择）")
        self.agent_model_edit.setToolTip(
            "选择 Ollama 服务商时，展开下拉框会自动获取本地已安装的模型列表；"
            "其他服务商仍可直接输入模型名称。"
        )
        self.agent_model_edit.refresh_requested.connect(self._refresh_agent_models)
        agent_form.addRow("模型", self.agent_model_edit)
        self._agent_provider = provider
        self.agent_provider_edit.currentIndexChanged.connect(self._update_agent_provider_defaults)
        self.agent_api_key_edit = QLineEdit()
        self.agent_api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.agent_api_key_edit.setPlaceholderText("留空时读取 OPENAI_API_KEY 或 GEMINI_API_KEY")
        agent_form.addRow("API Key（本次运行）", self.agent_api_key_edit)
        tip = QLabel(
            "API Key 只保存在本次运行内，不写入本地数据库。Gemini 使用 OpenAI 兼容接口。"
            "Ollama 模型列表通过本机 /api/tags 获取，需要本地服务已启动。"
        )
        tip.setObjectName("Hint")
        tip.setWordWrap(True)
        agent_form.addRow(tip)
        self.settings_pages.addWidget(agent_page)
        self.settings_navigation.currentRowChanged.connect(self.settings_pages.setCurrentIndex)
        self.settings_navigation.setCurrentRow(0)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _update_agent_provider_defaults(self) -> None:
        """Keep default endpoint and model aligned with a provider change."""

        provider = str(self.agent_provider_edit.currentData())
        old_url, old_model = PROVIDER_DEFAULTS[self._agent_provider]
        new_url, new_model = PROVIDER_DEFAULTS[provider]
        if self.agent_base_url_edit.text().strip() == old_url:
            self.agent_base_url_edit.setText(new_url)
        if self.agent_model_edit.currentText().strip() == old_model:
            self.agent_model_edit.setCurrentText(new_model)
        self._agent_provider = provider
        if provider == "ollama":
            self._refresh_agent_models()

    def _refresh_agent_models(self) -> None:
        """Fetch Ollama model names in the background when that provider is active."""

        if str(self.agent_provider_edit.currentData()) != "ollama":
            return
        if self._model_thread is not None and self._model_thread.isRunning():
            return
        base_url = self.agent_base_url_edit.text().strip()
        thread = _ModelFetchThread(base_url, self)
        thread.completed.connect(self._on_agent_models_fetched)
        thread.finished.connect(self._on_model_thread_finished)
        self._model_thread = thread
        thread.start()

    def _on_agent_models_fetched(self, models: object, error: str) -> None:
        """Replace the combo box entries with detected models, preserving user input."""

        if error:
            logger.warning("Ollama 模型列表获取失败: %s", error)
            return
        if not isinstance(models, list) or not models:
            return
        combo = self.agent_model_edit
        current_text = combo.currentText().strip()
        names = [str(model) for model in models]
        combo.blockSignals(True)
        try:
            combo.clear()
            combo.addItems(names)
            combo.setCurrentText(current_text or names[0])
        finally:
            combo.blockSignals(False)

    def _on_model_thread_finished(self) -> None:
        thread = self.sender()
        if thread is self._model_thread:
            self._model_thread = None
        if thread is not None:
            thread.deleteLater()

    def _save(self) -> None:
        values = {key: edit.keySequence().toString() for key, edit in self.shortcut_edits.items()}
        configured: dict[str, str] = {}
        for key, sequence in values.items():
            normalized = QKeySequence(sequence).toString()
            if not normalized:
                continue
            previous = configured.get(normalized)
            if previous is not None:
                QMessageBox.warning(
                    self,
                    "快捷键重复",
                    f"“{SHORTCUT_LABELS[previous]}”和“{SHORTCUT_LABELS[key]}”使用了相同快捷键。",
                )
                return
            configured[normalized] = key
        values["item_name_max_length"] = str(self.item_name_length_edit.value())
        values["agent_provider"] = str(self.agent_provider_edit.currentData())
        values["agent_base_url"] = self.agent_base_url_edit.text().strip()
        values["agent_model"] = self.agent_model_edit.currentText().strip()
        try:
            self.service.save_settings(values)
        except StorageError as exc:
            QMessageBox.critical(self, "保存设置失败", str(exc))
            return
        self.api_key_value = self.agent_api_key_edit.text().strip()
        self.accept()


class MainWindow(QMainWindow):
    """Main window for browsing, editing, and using stored prompts."""

    # Maximum interval between the two Shift presses that open the
    # currently selected prompt.  Chosen to match the OS double-click
    # interval so the gesture feels like a standard double click.
    # _DOUBLE_SHIFT_MAX_INTERVAL_MS = QApplication.doubleClickInterval() if QApplication.instance() else 400

    def __init__(self, service: PromptService) -> None:
        super().__init__()
        self.service = service
        self.current_prompt_id: int | None = None
        self.current_kind = "prompt"
        self._collapsed_group_ids: dict[int, bool] = {}
        self.item_name_max_length = self._read_item_name_max_length(self.service.settings())
        self._loading_editor = False
        self._loading_temporary = False
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
        self._backup_thread: _DatabaseBackupThread | None = None
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

        self.prompt_list = PromptListWidget()
        self.prompt_list.currentItemChanged.connect(self._select_prompt)
        self.prompt_list.prompt_dropped.connect(self._reorder_prompt_by_drag)
        self.prompt_list.prompt_dropped_on_group.connect(self._assign_prompt_by_drag)
        side_layout.addWidget(self.prompt_list, 1)

        self.temporary_text_button = QPushButton("临时文本")
        self.temporary_text_button.setObjectName("TemporaryButton")
        self.temporary_text_button.setCheckable(True)
        self.temporary_text_button.setToolTip("打开或关闭持久保存的临时文本面板")
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
        content_layout.addWidget(content_label)
        content_layout.addWidget(self.content_edit, 1)
        self.editing_splitter.addWidget(content_panel)

        self.temporary_panel = QFrame()
        self.temporary_panel.setObjectName("TemporaryCard")
        temporary_layout = QVBoxLayout(self.temporary_panel)
        temporary_layout.setContentsMargins(12, 12, 12, 12)
        temporary_label = QLabel("临时文本")
        temporary_label.setStyleSheet("font-size: 16px; font-weight: 700;")
        self.temporary_text_edit = QTextEdit()
        self.temporary_text_edit.setAcceptRichText(False)
        self.temporary_text_edit.setPlaceholderText("这里的内容会自动保存，可作为临时记录区使用。")
        self.temporary_text_edit.setPlainText(self.service.settings().get("temporary_text", ""))
        temporary_layout.addWidget(temporary_label)
        temporary_layout.addWidget(self.temporary_text_edit, 1)
        self.editing_splitter.addWidget(self.temporary_panel)
        self.temporary_panel.setVisible(False)
        self.editing_splitter.setSizes([1080, 900])
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

    def _build_format_toolbar(self) -> QHBoxLayout:
        """Build common Markdown actions and put less-used actions in a menu."""

        layout = QHBoxLayout()
        actions = (
            ("H1", "在当前行添加一级标题", lambda: self.content_edit.prefix_current_line("# ")),
            ("H2", "在当前行添加二级标题", lambda: self.content_edit.prefix_current_line("## ")),
            ("粗体", "将选中文本包裹为 **文本**", lambda: self.content_edit.wrap_selection("**")),
            ("斜体", "将选中文本包裹为 *文本*", lambda: self.content_edit.wrap_selection("*")),
            ("代码", "将选中文本包裹为 `代码`", lambda: self.content_edit.wrap_selection("`")),
            ("引用", "在当前行添加 > 引用符号", lambda: self.content_edit.prefix_current_line("> ")),
            ("列表", "在当前行添加 - 列表符号", lambda: self.content_edit.prefix_current_line("- ")),
        )
        for text, tip, callback in actions:
            button = QPushButton(text)
            button.setToolTip(tip)
            button.clicked.connect(callback)
            layout.addWidget(button)
        more = QToolButton()
        more.setText("杂项 ▾")
        more.setToolTip("更多 Markdown 格式与占位符操作")
        menu = QMenu(more)
        for text, callback in (
            ("H3 标题", lambda: self.content_edit.prefix_current_line("### ")),
            ("链接 [文字](地址)", self.insert_link),
            ("代码块 ```", self.insert_code_block),
            ("插入替换占位符", lambda: self.insert_marker("replace")),
            ("插入导入占位符", lambda: self.insert_marker("import")),
        ):
            action = menu.addAction(text)
            action.triggered.connect(callback)
        more.setMenu(menu)
        more.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        layout.addWidget(more)
        layout.addStretch()
        return layout

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
        }
        editor_actions = {
            "find": self.content_edit.open_find_bar,
            "replace": self.content_edit.open_replace_bar,
            "expand_selection": self.content_edit.expand_selection,
            "copy_line": lambda: self._copy_or_cut_editor_line(False),
            "cut_line": lambda: self._copy_or_cut_editor_line(True),
            "move_line_up": lambda: self.content_edit.move_current_line(-1),
            "move_line_down": lambda: self.content_edit.move_current_line(1),
            "fold_section": self.content_edit.collapse_section,
            "unfold_section": lambda: self.content_edit.expand_section(recursive=False),
            "unfold_section_recursive": lambda: self.content_edit.expand_section(recursive=True),
            "expand_all": self.content_edit.expand_all,
            "collapse_all": self.content_edit.collapse_all,
        }
        for key, callback in (global_actions | editor_actions).items():
            sequence_text = settings.get(key, DEFAULT_SHORTCUTS[key])
            if not sequence_text.strip():
                continue
            parent = self if key in global_actions else self.content_edit
            shortcut = QShortcut(QKeySequence(sequence_text), parent)
            shortcut.setContext(
                Qt.ShortcutContext.WindowShortcut
                if key in global_actions
                else Qt.ShortcutContext.WidgetWithChildrenShortcut
            )
            shortcut.activated.connect(callback)
            self._shortcuts.append(shortcut)

    def _copy_or_cut_editor_line(self, cut: bool) -> None:
        """Keep normal selected-text copy behavior and edit whole lines otherwise."""

        if self.content_edit.textCursor().hasSelection():
            (self.content_edit.cut if cut else self.content_edit.copy)()
            return
        self.content_edit._copy_or_cut_current_line(cut)

    def toggle_temporary_text(self) -> None:
        """Show or hide the persistent temporary-text editor."""

        visible = not self.temporary_panel.isVisible()
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
            self.service.save_settings({"temporary_text": self.temporary_text_edit.toPlainText()})
        except StorageError as exc:
            self.statusBar().showMessage(f"临时文本保存失败：{exc}", 3500)

    def switch_category(self, kind: str) -> None:
        """Switch the visible category and start a new entry if necessary."""

        if kind == self.current_kind:
            return
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
        self.refresh_prompt_list(select_id=self.current_prompt_id, load_selection=False)

    def create_group(self) -> None:
        """Create a first-level group for the currently selected category."""

        name, accepted = QInputDialog.getText(self, "新建分组", "分组名称：")
        if not accepted:
            return
        try:
            group = self.service.create_group(name, self.current_kind)
            self._collapsed_group_ids[group.id] = True
            self.refresh_prompt_list()
            self.statusBar().showMessage("分组已创建", 2500)
        except ValidationError as exc:
            self._show_error(str(exc))

    def rename_group(self, group_id: int) -> None:
        """Rename a group without changing any member prompt."""

        group = next((item for item in self.service.list_groups(self.current_kind) if item.id == group_id), None)
        if group is None:
            return
        name, accepted = QInputDialog.getText(self, "重命名分组", "分组名称：", text=group.name)
        if not accepted:
            return
        try:
            self.service.rename_group(group_id, name)
            self.refresh_prompt_list(select_id=self.current_prompt_id, load_selection=False)
            self.statusBar().showMessage("分组已重命名", 2500)
        except ValidationError as exc:
            self._show_error(str(exc))

    def delete_group(self, group_id: int) -> None:
        """Delete a group while keeping its prompts in the ungrouped section."""

        answer = QMessageBox.question(
            self, "删除分组", "删除分组后，其中的条目会保留并移到未分组区域，确定继续吗？",
            QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Yes,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            self.service.delete_group(group_id)
            self._collapsed_group_ids.pop(group_id, None)
            self.refresh_prompt_list(select_id=self.current_prompt_id, load_selection=False)
            self.statusBar().showMessage("分组已删除，条目已保留", 3000)
        except ValidationError as exc:
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
            self._show_error(str(exc))

    def _set_prompt_pinned(self, prompt_id: int, pinned: bool) -> None:
        """Set a prompt's pinned state and keep the current editor selected."""

        try:
            self.service.set_prompt_pinned(prompt_id, pinned)
            self.refresh_prompt_list(select_id=prompt_id, load_selection=False)
            self.statusBar().showMessage("已置顶" if pinned else "已取消置顶", 2200)
        except ValidationError as exc:
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
            self.statusBar().showMessage("条目只能在同一分组或同一置顶区域内排序", 3000)
            return
        bucket = [prompt.id for prompt in prompts if self._prompt_bucket(prompt) == self._prompt_bucket(source)]
        bucket.remove(source_id)
        bucket.insert(bucket.index(target_id), source_id)
        try:
            self.service.reorder_prompts(bucket)
            self.refresh_prompt_list(select_id=source_id, load_selection=False)
        except ValidationError as exc:
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
            self._show_error(str(exc))

    def optimize_current_prompt(self, with_file: bool) -> None:
        """Render the current prompt through the fill dialog, then copy an optimization request.

        The optimization instruction is prepended to the *rendered* prompt, so
        placeholders and imports are resolved before the text is sent to an
        external model.  Without this step the clipboard would contain raw
        ``=====REPLACE: ...=====`` / ``=====IMPORT: ...=====`` markers.
        """

        if self.current_prompt_id is None:
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
            self._show_error(str(exc))
            return
        self._copy_to_clipboard(f"{instruction}\n{content}", "优化提示词已复制到剪贴板")

    def _select_prompt(self, current: QListWidgetItem | None, _previous: QListWidgetItem | None) -> None:
        if current is None or current.data(ITEM_TYPE_ROLE) != ITEM_PROMPT:
            return
        prompt = self.service.get_prompt(int(current.data(PROMPT_ID_ROLE)))
        if prompt is not None:
            self._load_prompt_into_editor(prompt)

    def _load_prompt_into_editor(self, prompt: Prompt) -> None:
        self._loading_editor = True
        self.current_prompt_id = prompt.id
        self.content_edit.setPlainText(prompt.content)
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
            self._show_error(str(exc))
            return
        self.refresh_prompt_list(select_id=prompt.id)
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
            self.statusBar().showMessage(str(exc), 3500)
            self.refresh_prompt_list(select_id=self.current_prompt_id, load_selection=False)
            return
        self.refresh_prompt_list(select_id=prompt_id, load_selection=False)
        self.statusBar().showMessage("条目已重命名", 2200)

    def _on_content_changed(self) -> None:
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
            self.autosave_label.setText("自动保存失败")
            self.statusBar().showMessage(str(exc), 3500)

    def insert_marker(self, kind: str) -> None:
        """Insert a marker at the cursor without blocking the editing flow."""

        marker = "=====REPLACE: 标题=====" if kind == "replace" else "=====IMPORT: ====="
        cursor = self.content_edit.textCursor()
        marker_start = cursor.selectionStart() if cursor.hasSelection() else cursor.position()
        cursor.insertText(marker)
        # Leave the caret inside the marker, immediately before its closing
        # delimiter, so the suggested label can be edited in place.
        cursor.setPosition(marker_start + len(marker) - len("====="))
        self.content_edit.setTextCursor(cursor)
        self.content_edit.setFocus()
        if kind != "replace":
            self.content_edit._update_import_completion()

    def insert_link(self) -> None:
        self.content_edit.wrap_selection("[", "](链接地址)")

    def insert_code_block(self) -> None:
        cursor = self.content_edit.textCursor()
        selected = cursor.selectedText()
        cursor.insertText(f"```\n{selected or '代码'}\n```")
        self.content_edit.setTextCursor(cursor)

    def open_settings(self) -> None:
        dialog = SettingsDialog(self.service, DEFAULT_SHORTCUTS | self.service.settings(), self)
        dialog.agent_api_key_edit.setText(getattr(self, "_agent_api_key", ""))
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._agent_api_key = dialog.api_key_value
            self.item_name_max_length = self._read_item_name_max_length(self.service.settings())
            self._install_shortcuts()
            self.refresh_prompt_list(select_id=self.current_prompt_id, load_selection=False)
            self.statusBar().showMessage("设置已保存", 2500)

    def open_agent(self) -> None:
        """Toggle the embedded Agent panel beside the editor."""

        visible = self.agent_button.isChecked()
        self.agent_panel.setVisible(visible)
        self.agent_button.setChecked(visible)
        if visible:
            self.agent_panel.input_edit.setFocus()

    def start_database_backup(self) -> None:
        """Back up the live database without blocking the interface."""

        if self._backup_thread is not None:
            return
        self.agent_panel.backup_button.setEnabled(False)
        self.agent_panel.status_label.setText("正在备份数据库…")
        self._backup_thread = _DatabaseBackupThread(self.service)
        self._backup_thread.completed.connect(self._on_database_backup_completed)
        self._backup_thread.finished.connect(self._on_database_backup_thread_finished)
        self._backup_thread.start()

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
        message = f"备份完成：{backup_path.parent.name}/{backup_path.name}"
        self.agent_panel.status_label.setText(message)
        self.statusBar().showMessage(f"数据库已备份到：{backup_path}", 6000)

    def _on_database_backup_thread_finished(self) -> None:
        thread = self.sender()
        self._backup_thread = None
        self.agent_panel.backup_button.setEnabled(True)
        if thread is not None:
            thread.deleteLater()

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
            self._show_error("提示词已不存在")
            return
        try:
            if not self.service.placeholders_for(prompt):
                self._copy_to_clipboard(self.service.render(prompt, {}), "提示词已复制")
                return
            if FillPromptDialog(self.service, prompt, self).exec() == QDialog.DialogCode.Accepted:
                self.statusBar().showMessage("提示词已复制到剪贴板", 3500)
        except (ValidationError, StorageError) as exc:
            self._show_error(str(exc))

    def _copy_to_clipboard(self, text: str, message: str) -> None:
        QApplication.clipboard().setText(text)
        self.statusBar().showMessage(message, 3500)

    def _show_error(self, message: str) -> None:
        QMessageBox.critical(self, "无法完成操作", message)

    def eventFilter(self, obj: object, event: QEvent) -> bool:  # noqa: N802 - Qt override
        """Open the fill dialog when Shift is pressed twice in quick succession.

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

        application = QApplication.instance()
        if application is not None:
            application.removeEventFilter(self)
        if self._backup_thread is not None and self._backup_thread.isRunning():
            self._backup_thread.wait()
        self._autosave_timer.stop()
        self._temporary_autosave_timer.stop()
        self._auto_save()
        self._save_temporary_text()
        event.accept()
