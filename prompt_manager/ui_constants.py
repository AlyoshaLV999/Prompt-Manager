"""Shared constants for the desktop interface."""

from __future__ import annotations

from PySide6.QtCore import Qt

APP_STYLESHEET = """
QMainWindow, QDialog { background: #f5f6fa; color: #1f2430; }
QFrame#Sidebar, QFrame#EditorCard, QFrame#ToolbarCard, QFrame#FillCard, QFrame#TemporaryCard {
    background: #ffffff; border: 1px solid #e6e8ef; border-radius: 16px;
}
QWidget#AgentConversationCard {
    background: #ffffff; border: 1px solid #e6e8ef; border-radius: 12px;
}
QLabel#AppTitle { font-size: 20px; font-weight: 700; color: #151923; }
QLabel#Subtitle, QLabel#Hint, QLabel#Meta { color: #596273; }
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
QPushButton#RenderButton:checked { background: #6d5ce7; color: white; }
QPushButton#RenderButton:checked:hover { background: #5e4ed3; }
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
QFrame#TranscriptEntry {
    background: #ffffff; border: none; border-left: 2px solid #c5cad5;
}
QFrame#TranscriptEntry[entryRole="user"] { background: #faf8ff; border-left-color: #8c79e7; }
QFrame#TranscriptEntry[entryRole="tool"] { background: #f7f8fb; border-left-color: #687891; }
QFrame#TranscriptEntry[entryRole="system"] { background: #fffaf1; border-left-color: #9b7440; }
QToolButton#TranscriptToggle {
    background: transparent; color: #46546b;
    border: 1px solid transparent; border-radius: 6px; padding: 0;
}
QToolButton#TranscriptToggle:hover { background: #e9ebf4; color: #28354b; }
QToolButton#TranscriptToggle:pressed { background: #dedff0; }
QToolButton#TranscriptToggle:focus { border-color: #6558cb; }
QLabel#TranscriptSpeaker { color: #313d53; font-size: 12px; font-weight: 700; }
QFrame#TranscriptEntry[entryRole="user"] QLabel#TranscriptSpeaker { color: #5141a3; }
QFrame#TranscriptEntry[entryRole="system"] QLabel#TranscriptSpeaker { color: #75552b; }
QLabel#TranscriptSummary { color: #526077; font-size: 12px; padding: 0; }
QTextBrowser#TranscriptContent {
    background: transparent; color: #1f2937; border: none; padding: 0;
    selection-background-color: #8b7cf6;
}
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
    "rename_row_item": "F2",
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
    "rename_row_item": "重命名条目",
}
DEFAULT_ITEM_NAME_MAX_LENGTH = 10
DEFAULT_NEW_PROMPT_NAME = "新建提示词"
DEFAULT_NEW_PROMPT_CONTENT = "# 新建提示词\n"

PROMPT_ID_ROLE = Qt.ItemDataRole.UserRole
ITEM_TYPE_ROLE = Qt.ItemDataRole.UserRole + 1
ITEM_PROMPT = "prompt"
ITEM_GROUP = "group"
ITEM_SECTION = "section"
