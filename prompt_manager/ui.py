"""PySide6 desktop user interface for Prompt Manager."""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QCloseEvent, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication, QDialog, QDialogButtonBox, QFormLayout, QFrame, QHBoxLayout,
    QLabel, QKeySequenceEdit, QLineEdit, QListWidget, QListWidgetItem, QMainWindow,
    QMenu, QMessageBox, QPushButton, QSizePolicy, QSplitter, QTextEdit, QToolButton,
    QVBoxLayout, QWidget,
)

from .editor import MarkdownEditor
from .models import Prompt
from .service import PromptService, ValidationError
from .storage import StorageError


APP_STYLESHEET = """
QMainWindow, QDialog { background: #f5f6fa; color: #1f2430; }
QFrame#Sidebar, QFrame#EditorCard, QFrame#ToolbarCard, QFrame#FillCard, QFrame#TemporaryCard {
    background: #ffffff; border: 1px solid #e6e8ef; border-radius: 16px;
}
QLabel#AppTitle { font-size: 26px; font-weight: 700; color: #151923; }
QLabel#Subtitle, QLabel#Hint, QLabel#Meta { color: #737a8c; }
QLineEdit, QTextEdit, QPlainTextEdit {
    background: #fbfbfd; border: 1px solid #dfe3eb; border-radius: 10px;
    padding: 8px 10px; selection-background-color: #8b7cf6;
}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus { border: 1px solid #8b7cf6; }
QPushButton, QToolButton {
    border: none; border-radius: 9px; padding: 8px 12px;
    background: #eef0f6; color: #353b4b; font-weight: 600;
}
QPushButton:hover, QToolButton:hover { background: #e2e4ef; }
QPushButton#PrimaryButton, QToolButton#PrimaryButton { background: #6d5ce7; color: white; }
QPushButton#PrimaryButton:hover { background: #5e4ed3; }
QPushButton#DangerButton { color: #c33850; background: #fff0f2; }
QPushButton#MiniButton { padding: 5px 10px; border-radius: 8px; }
QPushButton#CategoryButton:checked, QPushButton#TemporaryButton:checked { background: #6d5ce7; color: white; }
QListWidget { background: transparent; border: none; outline: none; }
QListWidget::item { margin: 3px 0; border-radius: 10px; }
QListWidget::item:selected { background: #eeecff; }
QScrollBar:vertical { width: 8px; background: transparent; }
QScrollBar::handle:vertical { background: #d5d8e2; border-radius: 4px; min-height: 28px; }
"""

DEFAULT_SHORTCUTS = {
    "insert_replace": "Ctrl+Alt+R",
    "insert_import": "Ctrl+Alt+I",
    "settings": "Ctrl+,",
}


class PromptListRow(QWidget):
    """Compact prompt title row with a quick-copy action."""

    quick_copy_requested = Signal(int)

    def __init__(self, prompt: Prompt) -> None:
        super().__init__()
        self.prompt_id = prompt.id
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 8, 8)
        title = QLabel(prompt.name)
        title.setToolTip(prompt.name)
        title.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        badge = QLabel("固定" if prompt.is_fixed else "预设")
        badge.setObjectName("Meta")
        copy_button = QPushButton("复制")
        copy_button.setObjectName("MiniButton")
        copy_button.setToolTip("使用上次保存的占位符值复制")
        copy_button.clicked.connect(lambda: self.quick_copy_requested.emit(self.prompt_id))
        layout.addWidget(title)
        layout.addWidget(badge)
        layout.addWidget(copy_button)


class FillPromptDialog(QDialog):
    """Collect replacement values and copy a rendered prompt."""

    def __init__(self, service: PromptService, prompt: Prompt, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.service = service
        self.prompt = prompt
        self.fields: dict[str, QTextEdit] = {}
        self.setWindowTitle(f"使用提示词 · {prompt.name}")
        self.setMinimumSize(560, 420)
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 22, 24, 20)
        title = QLabel(self.prompt.name)
        title.setObjectName("AppTitle")
        root.addWidget(title)
        hint = QLabel("填写以下内容后复制，输入会自动记忆到下次使用。")
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
        copy_button = buttons.addButton("复制到剪贴板", QDialogButtonBox.ButtonRole.AcceptRole)
        copy_button.setObjectName("PrimaryButton")
        cancel_button = buttons.addButton("取消", QDialogButtonBox.ButtonRole.RejectRole)
        copy_button.clicked.connect(self._copy)
        cancel_button.clicked.connect(self.reject)
        root.addWidget(buttons)

    def _copy(self) -> None:
        values = {title: field.toPlainText() for title, field in self.fields.items()}
        try:
            self.service.save_values(self.prompt.id, values)
            QApplication.clipboard().setText(self.service.render(self.prompt, values))
            self.accept()
        except StorageError as exc:
            QMessageBox.critical(self, "无法保存输入", str(exc))


class SettingsDialog(QDialog):
    """Edit configurable application shortcuts."""

    def __init__(self, service: PromptService, shortcuts: dict[str, str], parent=None) -> None:
        super().__init__(parent)
        self.service = service
        self.shortcut_edits: dict[str, QKeySequenceEdit] = {}
        self.setWindowTitle("设置")
        self.setMinimumWidth(460)
        root = QVBoxLayout(self)
        form = QFormLayout()
        labels = {"insert_replace": "插入替换占位符", "insert_import": "插入导入占位符", "settings": "打开设置"}
        for key, label in labels.items():
            edit = QKeySequenceEdit(QKeySequence(shortcuts.get(key, DEFAULT_SHORTCUTS[key])))
            form.addRow(label, edit)
            self.shortcut_edits[key] = edit
        root.addLayout(form)
        tip = QLabel("快捷键会自动保存到本地设置；编辑器折叠快捷键遵循 Ctrl + / Ctrl -。\n"
                     "Ctrl W 扩选，Ctrl C/X 复制或剪切整行，Alt Shift ↑/↓ 交换相邻行。")
        tip.setObjectName("Hint")
        tip.setWordWrap(True)
        root.addWidget(tip)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _save(self) -> None:
        values = {key: edit.keySequence().toString() for key, edit in self.shortcut_edits.items()}
        try:
            self.service.save_settings(values)
        except StorageError as exc:
            QMessageBox.critical(self, "保存设置失败", str(exc))
            return
        self.accept()


class MainWindow(QMainWindow):
    """Main window for browsing, editing, and using stored prompts."""

    def __init__(self, service: PromptService) -> None:
        super().__init__()
        self.service = service
        self.current_prompt_id: int | None = None
        self.current_kind = "prompt"
        self._loading_editor = False
        self._loading_temporary = False
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
        self._install_shortcuts()
        self.refresh_prompt_list()

    def _build_ui(self) -> None:
        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(26, 22, 26, 18)
        root.setSpacing(14)
        toolbar = QFrame()
        toolbar.setObjectName("ToolbarCard")
        toolbar_layout = QHBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(18, 14, 18, 14)
        title_box = QVBoxLayout()
        app_title = QLabel("Prompt Manager")
        app_title.setObjectName("AppTitle")
        subtitle = QLabel("把常用提示词和固定预设放在一个清晰、可靠的地方")
        subtitle.setObjectName("Subtitle")
        title_box.addWidget(app_title)
        title_box.addWidget(subtitle)
        toolbar_layout.addLayout(title_box, 1)
        settings_button = QPushButton("设置")
        settings_button.clicked.connect(self.open_settings)
        use_button = QPushButton("使用提示词")
        use_button.clicked.connect(self.use_current_prompt)
        new_button = QPushButton("新建")
        new_button.setObjectName("PrimaryButton")
        new_button.clicked.connect(self.new_prompt)
        toolbar_layout.addWidget(settings_button)
        toolbar_layout.addWidget(use_button)
        toolbar_layout.addWidget(new_button)
        root.addWidget(toolbar)

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
        category_bar.addStretch()
        root.addLayout(category_bar)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        sidebar = QFrame()
        sidebar.setObjectName("Sidebar")
        side_layout = QVBoxLayout(sidebar)
        side_layout.setContentsMargins(14, 14, 14, 14)
        side_header = QHBoxLayout()
        side_label = QLabel("我的条目")
        side_label.setStyleSheet("font-size: 16px; font-weight: 700;")
        self.count_label = QLabel()
        self.count_label.setObjectName("Meta")
        side_header.addWidget(side_label)
        side_header.addStretch()
        side_header.addWidget(self.count_label)
        side_layout.addLayout(side_header)
        self.prompt_list = QListWidget()
        self.prompt_list.currentItemChanged.connect(self._select_prompt)
        self.prompt_list.itemDoubleClicked.connect(lambda _item: self.use_current_prompt())
        side_layout.addWidget(self.prompt_list, 1)
        self.temporary_text_button = QPushButton("临时文本")
        self.temporary_text_button.setObjectName("TemporaryButton")
        self.temporary_text_button.setCheckable(True)
        self.temporary_text_button.setToolTip("打开或关闭持久保存的临时文本面板")
        self.temporary_text_button.clicked.connect(self.toggle_temporary_text)
        side_layout.addWidget(self.temporary_text_button)
        splitter.addWidget(sidebar)

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

        form = QFormLayout()
        form.setVerticalSpacing(10)
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("例如：产品需求分析")
        form.addRow("名称", self.name_edit)
        editor_layout.addLayout(form)

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
        self.editing_splitter.setSizes([900, 900])
        editor_layout.addWidget(self.editing_splitter, 1)
        editor_layout.addLayout(self._build_format_toolbar())
        hint = QLabel("修改会自动保存。Ctrl W 扩选；Ctrl C/X 复制或剪切整行；Alt Shift ↑/↓ 移动行；Ctrl + / Ctrl - 折叠。")
        hint.setObjectName("Hint")
        hint.setWordWrap(True)
        editor_layout.addWidget(hint)
        actions = QHBoxLayout()
        self.delete_button = QPushButton("删除")
        self.delete_button.setObjectName("DangerButton")
        self.delete_button.clicked.connect(self.delete_current_prompt)
        actions.addWidget(self.delete_button)
        actions.addStretch()
        self.autosave_label = QLabel("自动保存已开启")
        self.autosave_label.setObjectName("Meta")
        actions.addWidget(self.autosave_label)
        editor_layout.addLayout(actions)
        splitter.addWidget(editor)
        splitter.setSizes([350, 900])
        root.addWidget(splitter, 1)
        self.setCentralWidget(central)

        self.name_edit.textChanged.connect(self._schedule_autosave)
        self.content_edit.textChanged.connect(self._on_content_changed)
        self.temporary_text_edit.textChanged.connect(self._schedule_temporary_autosave)
        self.statusBar().showMessage("准备就绪")

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
            shortcut.deleteLater()
        self._shortcuts = []
        for key, callback in (
            ("insert_replace", lambda: self.insert_marker("replace")),
            ("insert_import", lambda: self.insert_marker("import")),
            ("settings", self.open_settings),
        ):
            shortcut = QShortcut(QKeySequence(settings[key]), self)
            shortcut.setContext(Qt.ShortcutContext.WindowShortcut)
            shortcut.activated.connect(callback)
            self._shortcuts.append(shortcut)

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
        self.prompt_list.blockSignals(True)
        self.prompt_list.clear()
        for prompt in prompts:
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, prompt.id)
            row = PromptListRow(prompt)
            row.quick_copy_requested.connect(self.quick_copy)
            item.setSizeHint(row.sizeHint())
            self.prompt_list.addItem(item)
            self.prompt_list.setItemWidget(item, row)
        self.prompt_list.blockSignals(False)
        self.count_label.setText(f"{len(prompts)} 条")
        if select_id is not None:
            for index in range(self.prompt_list.count()):
                item = self.prompt_list.item(index)
                if item.data(Qt.ItemDataRole.UserRole) == select_id:
                    self.prompt_list.setCurrentItem(item)
                    return
        if prompts:
            self.prompt_list.setCurrentRow(0)
        else:
            self.new_prompt()

    def _select_prompt(self, current: QListWidgetItem | None, _previous: QListWidgetItem | None) -> None:
        if current is None:
            return
        prompt = self.service.get_prompt(int(current.data(Qt.ItemDataRole.UserRole)))
        if prompt is not None:
            self._load_prompt_into_editor(prompt)

    def _load_prompt_into_editor(self, prompt: Prompt) -> None:
        self._loading_editor = True
        self.current_prompt_id = prompt.id
        self.name_edit.setText(prompt.name)
        self.content_edit.setPlainText(prompt.content)
        self.content_edit.set_import_candidates(item.name for item in self.service.list_prompts("fixed") if item.id != prompt.id)
        self._update_meta(prompt)
        self.delete_button.setEnabled(True)
        self._loading_editor = False

    def _update_meta(self, prompt: Prompt) -> None:
        try:
            placeholders = len(self.service.placeholders_for(prompt))
            imports = len(self.service.imports_for(prompt))
        except ValidationError:
            placeholders = imports = 0
        self.meta_label.setText(f"{placeholders} 个输入 · {imports} 个导入")

    def new_prompt(self) -> None:
        self._autosave_timer.stop()
        self._loading_editor = True
        self.current_prompt_id = None
        self.prompt_list.clearSelection()
        self.name_edit.clear()
        self.content_edit.clear()
        self.content_edit.set_import_candidates(item.name for item in self.service.list_prompts("fixed"))
        self.meta_label.setText("新建")
        self.delete_button.setEnabled(False)
        self._loading_editor = False
        self.name_edit.setFocus()
        self.statusBar().showMessage("正在新建提示词，输入完成后会自动保存")

    def _on_content_changed(self) -> None:
        if not self._loading_editor:
            self._schedule_autosave()

    def _schedule_autosave(self) -> None:
        if not self._loading_editor:
            self.autosave_label.setText("正在等待自动保存…")
            self._autosave_timer.start()

    def _auto_save(self) -> None:
        name = self.name_edit.text()
        content = self.content_edit.toPlainText()
        if not name.strip() or not content.strip():
            self.autosave_label.setText("自动保存已开启（名称和内容不能为空）")
            return
        try:
            if self.current_prompt_id is None:
                prompt = self.service.create_prompt(name, content, self.current_kind)
                self.current_prompt_id = prompt.id
                self.delete_button.setEnabled(True)
                self.refresh_prompt_list(prompt.id)
                self.statusBar().showMessage("已自动创建", 2200)
            else:
                prompt = self.service.update_prompt(self.current_prompt_id, name, content, self.current_kind)
                self._update_meta(prompt)
                self.statusBar().showMessage("已自动保存", 1800)
            self.autosave_label.setText("已自动保存")
        except (ValidationError, StorageError) as exc:
            self.autosave_label.setText("自动保存失败")
            self.statusBar().showMessage(str(exc), 3500)

    def insert_marker(self, kind: str) -> None:
        """Insert a marker at the cursor without blocking the editing flow."""

        marker = "=====REPLACE: 标题=====" if kind == "replace" else "=====IMPORT: 固定预设====="
        cursor = self.content_edit.textCursor()
        cursor.insertText(marker)
        self.content_edit.setTextCursor(cursor)
        self.content_edit.setFocus()

    def insert_link(self) -> None:
        self.content_edit.wrap_selection("[", "](链接地址)")

    def insert_code_block(self) -> None:
        cursor = self.content_edit.textCursor()
        selected = cursor.selectedText()
        cursor.insertText(f"```\n{selected or '代码'}\n```")
        self.content_edit.setTextCursor(cursor)

    def open_settings(self) -> None:
        dialog = SettingsDialog(self.service, DEFAULT_SHORTCUTS | self.service.settings(), self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._install_shortcuts()
            self.statusBar().showMessage("设置已保存", 2500)

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

    def use_current_prompt(self) -> None:
        if self.current_prompt_id is None:
            self._show_error("请先选择或输入一个提示词")
            return
        self._autosave_timer.stop()
        self._auto_save()
        prompt = self.service.get_prompt(self.current_prompt_id)
        if prompt is None:
            self._show_error("提示词已不存在，请刷新后重试")
            return
        try:
            if not self.service.placeholders_for(prompt):
                self._copy_to_clipboard(self.service.render(prompt, {}), "提示词已复制")
                return
            if FillPromptDialog(self.service, prompt, self).exec() == QDialog.DialogCode.Accepted:
                self.statusBar().showMessage("提示词已复制到剪贴板", 3500)
        except (ValidationError, StorageError) as exc:
            self._show_error(str(exc))

    def quick_copy(self, prompt_id: int) -> None:
        prompt = self.service.get_prompt(prompt_id)
        if prompt is None:
            self._show_error("提示词已不存在")
            return
        try:
            values = self.service.remembered_values(prompt.id)
            self._copy_to_clipboard(self.service.render(prompt, values), "已使用上次输入复制")
        except (ValidationError, StorageError) as exc:
            self._show_error(str(exc))

    def _copy_to_clipboard(self, text: str, message: str) -> None:
        QApplication.clipboard().setText(text)
        self.statusBar().showMessage(message, 3500)

    def _show_error(self, message: str) -> None:
        QMessageBox.critical(self, "无法完成操作", message)

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 - Qt override
        """Flush debounced edits before the repository is closed by the app."""

        self._autosave_timer.stop()
        self._temporary_autosave_timer.stop()
        self._auto_save()
        self._save_temporary_text()
        event.accept()
