"""Prompt list rows and the prompt fill dialog."""

from __future__ import annotations

import logging
from collections.abc import Callable

from pathlib import Path

from PySide6.QtCore import QEvent, QMimeData, Qt, Signal, QUrl
from PySide6.QtGui import QDrag, QPainter, QPen
from PySide6.QtWidgets import (
    QApplication, QAbstractItemView, QDialog, QDialogButtonBox, QFormLayout,
    QFrame, QHBoxLayout, QLabel, QLineEdit, QListWidget, QMessageBox,
    QPushButton, QSizePolicy, QStackedWidget, QTextEdit, QToolButton,
    QVBoxLayout, QWidget,
)

from .models import Prompt
from .service import PromptService
from .storage import StorageError
from .ui_constants import ITEM_GROUP, ITEM_PROMPT, ITEM_TYPE_ROLE, PROMPT_ID_ROLE

logger = logging.getLogger(__name__)


def truncate_display_name(name: str, max_length: int) -> str:
    """Return a compact, loss-aware name for the narrow navigation column."""

    if max_length < 1 or len(name) <= max_length:
        return name
    return f"{name[:max_length]}..."


class PromptListWidget(QListWidget):
    """List that turns prompt drags into explicit persistence actions."""

    prompt_dropped = Signal(int, int)
    prompt_dropped_on_group = Signal(int, int)
    export_failed = Signal(str)

    INTERNAL_PROMPT_MIME = "application/x-prompt-manager-prompt-id"

    def __init__(self, export_prompt: Callable[[int], Path], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._export_prompt = export_prompt
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        # Drop recorded by :meth:`dropEvent` and emitted by :meth:`startDrag`
        # once the drag has finished; see :meth:`startDrag` for the reason.
        self._pending_drop: tuple[str, int, int] | None = None

    def dropEvent(self, event) -> None:  # noqa: N802 - Qt override
        """Translate a drop into group assignment or same-bucket reordering."""

        mime_data = event.mimeData()
        if event.source() is not self or not mime_data.hasFormat(self.INTERNAL_PROMPT_MIME):
            event.ignore()
            return
        source = self.currentItem()
        target = self.itemAt(event.position().toPoint())
        if source is None or target is None or source is target:
            event.ignore()
            return
        if source.data(ITEM_TYPE_ROLE) != ITEM_PROMPT:
            event.ignore()
            return
        target_type = target.data(ITEM_TYPE_ROLE)
        if target_type not in (ITEM_GROUP, ITEM_PROMPT):
            event.ignore()
            return
        try:
            source_id = int(bytes(mime_data.data(self.INTERNAL_PROMPT_MIME)).decode("ascii"))
        except (UnicodeDecodeError, ValueError):
            event.ignore()
            return
        if source_id != int(source.data(PROMPT_ID_ROLE)):
            event.ignore()
            return
        self._pending_drop = (target_type, source_id, int(target.data(PROMPT_ID_ROLE)))
        event.setDropAction(Qt.DropAction.MoveAction)
        event.accept()

    def dragEnterEvent(self, event) -> None:  # noqa: N802 - Qt override
        """Accept only prompt drags originating in this list."""

        if event.source() is self and event.mimeData().hasFormat(self.INTERNAL_PROMPT_MIME):
            event.setDropAction(Qt.DropAction.MoveAction)
            event.accept()
        else:
            event.ignore()

    def dragMoveEvent(self, event) -> None:  # noqa: N802 - Qt override
        """Keep external file drags from being interpreted as list reorders."""

        if event.source() is self and event.mimeData().hasFormat(self.INTERNAL_PROMPT_MIME):
            event.setDropAction(Qt.DropAction.MoveAction)
            event.accept()
        else:
            event.ignore()

    def startDrag(self, supported_actions: Qt.DropActions) -> None:  # noqa: N802 - Qt override
        """Drag a file URL externally and retain internal reorder semantics.

        The custom MIME field identifies an in-list move; the URL is what makes
        the same gesture import the generated Markdown file in other apps.
        """

        self._pending_drop = None
        item = self.currentItem()
        if item is None or item.data(ITEM_TYPE_ROLE) != ITEM_PROMPT:
            return
        prompt_id = int(item.data(PROMPT_ID_ROLE))
        try:
            path: Path = self._export_prompt(prompt_id)
        except (OSError, StorageError) as exc:
            logger.warning("Prompt drag export failed prompt_id=%d error=%s", prompt_id, type(exc).__name__)
            self.export_failed.emit(str(exc))
            return

        mime_data = QMimeData()
        mime_data.setUrls([QUrl.fromLocalFile(str(path))])
        mime_data.setData(self.INTERNAL_PROMPT_MIME, str(prompt_id).encode("ascii"))
        drag = QDrag(self)
        drag.setMimeData(mime_data)
        drag.exec(supported_actions, Qt.DropAction.CopyAction)
        pending_drop, self._pending_drop = self._pending_drop, None
        if pending_drop is None:
            return
        target_type, source_id, target_id = pending_drop
        if target_type == ITEM_GROUP:
            self.prompt_dropped_on_group.emit(source_id, target_id)
        else:
            self.prompt_dropped.emit(source_id, target_id)


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
            logger.warning("Prompt fill failed id=%d error=%s", self.prompt.id, type(exc).__name__)
            QMessageBox.critical(self, "无法保存输入", str(exc))
            return
        logger.info("User filled prompt id=%d field_count=%d output_chars=%d copied=%s", self.prompt.id, len(values), len(self._rendered), self._copy_on_accept)
        if self._copy_on_accept:
            QApplication.clipboard().setText(self._rendered)
        self.accept()
