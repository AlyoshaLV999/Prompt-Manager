"""Markdown editor with folding and PyCharm-like editing conveniences."""

from __future__ import annotations

import re
from collections.abc import Iterable

from PySide6.QtCore import Qt, QStringListModel, Signal
from PySide6.QtGui import QColor, QFont, QSyntaxHighlighter, QTextCharFormat, QTextCursor, QTextFormat
from PySide6.QtWidgets import QApplication, QCompleter, QPlainTextEdit, QTextEdit


HEADING_RE = re.compile(r"^(\s{0,3})(#{1,6})(?:\s+|$)")
IMPORT_INPUT_RE = re.compile(r"=====IMPORT:\s*([^=\n]*)$")


def chinese_initials(value: str) -> str:
    """Return ASCII initials for Chinese and Latin text."""

    initials = ""
    for character in value:
        if "a" <= character.lower() <= "z":
            initials += character.lower()
            continue
        try:
            encoded = character.encode("gb2312")
        except UnicodeEncodeError:
            continue
        if len(encoded) != 2:
            continue
        code = encoded[0] * 256 + encoded[1]
        ranges = (
            (45217, "a"), (45253, "b"), (45761, "c"), (46318, "d"),
            (46826, "e"), (47010, "f"), (47297, "g"), (47614, "h"),
            (48119, "j"), (49062, "k"), (49324, "l"), (49896, "m"),
            (50371, "n"), (50614, "o"), (50622, "p"), (50906, "q"),
            (51387, "r"), (51446, "s"), (52218, "t"), (52698, "w"),
            (52980, "x"), (53689, "y"), (54481, "z"),
        )
        for index, (start, letter) in enumerate(ranges):
            end = ranges[index + 1][0] if index + 1 < len(ranges) else 55290
            if start <= code < end:
                initials += letter
                break
    return initials


class MarkdownHighlighter(QSyntaxHighlighter):
    """Apply lightweight Markdown colors without changing document text."""

    def __init__(self, document) -> None:
        super().__init__(document)
        self.heading = QTextCharFormat()
        self.heading.setForeground(QColor("#5b4bd6"))
        self.heading.setFontWeight(QFont.Weight.Bold)
        self.marker = QTextCharFormat()
        self.marker.setForeground(QColor("#c26a18"))
        self.code = QTextCharFormat()
        self.code.setForeground(QColor("#19745b"))
        self.emphasis = QTextCharFormat()
        self.emphasis.setForeground(QColor("#9c3d6d"))

    def highlightBlock(self, text: str) -> None:
        """Highlight headings, markers, inline code, and emphasis."""

        if HEADING_RE.match(text):
            self.setFormat(0, len(text), self.heading)
        for pattern in (r"=====\w+:.*?=====", r"`[^`\n]+`", r"\*\*[^*\n]+\*\*|_[^_\n]+_"):
            format_ = self.marker if pattern.startswith("=====") else (
                self.code if pattern.startswith("`") else self.emphasis
            )
            for match in re.finditer(pattern, text):
                self.setFormat(match.start(), match.end() - match.start(), format_)


class MarkdownEditor(QPlainTextEdit):
    """Plain-text Markdown editor with folding and IDE-like keyboard actions."""

    import_name_selected = Signal(str)
    completion_visibility_changed = Signal(bool)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setTabStopDistance(4 * self.fontMetrics().horizontalAdvance(" "))
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.highlighter = MarkdownHighlighter(self.document())
        self._completion_model = QStringListModel(self)
        self._completer = QCompleter(self._completion_model, self)
        self._completer.setWidget(self)
        self._completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self._completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        self._completer.activated.connect(self._complete_import)
        self._import_start = -1
        self._import_candidates: list[str] = []
        self.document().contentsChanged.connect(self._update_fold_markers)

    def set_import_candidates(self, names: Iterable[str]) -> None:
        """Replace fixed-preset completion candidates."""

        self._import_candidates = list(dict.fromkeys(names))

    def keyPressEvent(self, event) -> None:  # noqa: N802 - Qt override
        """Handle folding, selection expansion, line editing, and completion."""

        modifiers = event.modifiers()
        key = event.key()
        control = Qt.KeyboardModifier.ControlModifier
        alt_shift = Qt.KeyboardModifier.AltModifier | Qt.KeyboardModifier.ShiftModifier

        if modifiers == control and key == Qt.Key.Key_W:
            self.expand_selection()
            return
        if modifiers == control and key in (Qt.Key.Key_C, Qt.Key.Key_X) and not self.textCursor().hasSelection():
            self._copy_or_cut_current_line(key == Qt.Key.Key_X)
            return
        if modifiers == alt_shift and key in (Qt.Key.Key_Up, Qt.Key.Key_Down):
            self.move_current_line(-1 if key == Qt.Key.Key_Up else 1)
            return
        if modifiers & control:
            if key in (Qt.Key.Key_Plus, Qt.Key.Key_Equal):
                if modifiers & Qt.KeyboardModifier.ShiftModifier:
                    self.expand_all()
                elif modifiers & Qt.KeyboardModifier.AltModifier:
                    self.expand_section(recursive=True)
                else:
                    self.expand_section(recursive=False)
                return
            if key == Qt.Key.Key_Minus:
                if modifiers & Qt.KeyboardModifier.ShiftModifier:
                    self.collapse_all()
                else:
                    self.collapse_section()
                return
        if not modifiers and key in (Qt.Key.Key_QuoteDbl, Qt.Key.Key_Apostrophe):
            self.wrap_selection(event.text(), event.text())
            return
        if not modifiers and key == Qt.Key.Key_QuoteLeft:
            self.wrap_selection("`", "`")
            return
        super().keyPressEvent(event)
        self._update_import_completion()

    def _line_bounds(self, block=None) -> tuple[int, int]:
        """Return Python-text offsets for one document block, including its newline."""

        block = self.textCursor().block() if block is None else block
        text = self.toPlainText()
        start = block.position()
        next_block = block.next()
        end = next_block.position() if next_block.isValid() else len(text)
        return min(start, len(text)), min(end, len(text))

    def _copy_or_cut_current_line(self, cut: bool) -> None:
        """Copy a complete current line, optionally removing it from the document."""

        text = self.toPlainText()
        start, end = self._line_bounds()
        if start == end and not text:
            QApplication.clipboard().setText("")
            return
        line = text[start:end]
        QApplication.clipboard().setText(line)
        if not cut:
            return
        remove_start, remove_end = start, end
        if remove_start == remove_end and remove_start > 0:
            remove_start -= 1
        elif remove_end == len(text) and remove_start > 0 and not line:
            remove_start -= 1
        cursor = QTextCursor(self.document())
        cursor.setPosition(remove_start)
        cursor.setPosition(remove_end, QTextCursor.MoveMode.KeepAnchor)
        cursor.removeSelectedText()
        self.setTextCursor(cursor)

    def move_current_line(self, direction: int) -> None:
        """Swap the current line with its neighbor and keep the caret column."""

        if direction not in (-1, 1):
            return
        cursor = self.textCursor()
        block_number = cursor.block().blockNumber()
        lines = self.toPlainText().split("\n")
        target = block_number + direction
        if target < 0 or target >= len(lines):
            return
        lines[block_number], lines[target] = lines[target], lines[block_number]
        new_text = "\n".join(lines)
        column = cursor.positionInBlock()
        document_cursor = QTextCursor(self.document())
        document_cursor.select(QTextCursor.SelectionType.Document)
        document_cursor.insertText(new_text)
        new_block = self.document().findBlockByNumber(target)
        new_cursor = QTextCursor(self.document())
        new_cursor.setPosition(new_block.position() + min(column, len(new_block.text())))
        self.setTextCursor(new_cursor)

    def wrap_selection(self, prefix: str, suffix: str | None = None) -> None:
        """Wrap selected text, or insert a pair at the cursor."""

        suffix = prefix if suffix is None else suffix
        cursor = self.textCursor()
        selected = cursor.selectedText()
        cursor.insertText(f"{prefix}{selected}{suffix}")
        cursor.setPosition(cursor.position() - len(suffix))
        self.setTextCursor(cursor)

    def prefix_current_line(self, prefix: str) -> None:
        """Add a Markdown prefix at the current line's first non-space column."""

        cursor = self.textCursor()
        block_start = cursor.block().position()
        line_text = cursor.block().text()
        indentation = len(line_text) - len(line_text.lstrip(" "))
        cursor.setPosition(block_start + indentation)
        cursor.insertText(prefix)
        self.setTextCursor(cursor)

    def expand_selection(self) -> None:
        """Expand selection from word to pair, line, paragraph, and document."""

        cursor = self.textCursor()
        text = self.toPlainText()
        if not text:
            return
        if not cursor.hasSelection():
            cursor.select(QTextCursor.SelectionType.WordUnderCursor)
            if cursor.hasSelection():
                self.setTextCursor(cursor)
                return
            block = self.textCursor().block()
            start, end = self._line_bounds(block)
            cursor.setPosition(start)
            cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
            self.setTextCursor(cursor)
            return

        start, end = cursor.selectionStart(), cursor.selectionEnd()
        if start > 0 and end < len(text):
            pairs = {"(": ")", "[": "]", "{": "}", '"': '"', "'": "'", "`": "`"}
            if text[start - 1] in pairs and text[end] == pairs[text[start - 1]]:
                cursor.setPosition(start - 1)
                cursor.setPosition(end + 1, QTextCursor.MoveMode.KeepAnchor)
                self.setTextCursor(cursor)
                return

        block = self.document().findBlock(start)
        line_start, line_end = self._line_bounds(block)
        if start > line_start or end < line_end:
            cursor.setPosition(line_start)
            cursor.setPosition(line_end, QTextCursor.MoveMode.KeepAnchor)
            self.setTextCursor(cursor)
            return

        paragraph_start = line_start
        previous = block.previous()
        while previous.isValid() and previous.text().strip():
            paragraph_start = previous.position()
            previous = previous.previous()
        paragraph_end = line_end
        following = block.next()
        while following.isValid() and following.text().strip():
            paragraph_end = self._line_bounds(following)[1]
            following = following.next()
        if start != paragraph_start or end != paragraph_end:
            cursor.setPosition(paragraph_start)
            cursor.setPosition(paragraph_end, QTextCursor.MoveMode.KeepAnchor)
            self.setTextCursor(cursor)
            return

        cursor.setPosition(0)
        cursor.setPosition(len(text), QTextCursor.MoveMode.KeepAnchor)
        self.setTextCursor(cursor)

    def _heading_level(self, block) -> int | None:
        match = HEADING_RE.match(block.text())
        return len(match.group(2)) if match else None

    def _fold_target(self, block):
        """Return the heading owning ``block``; this enables folding from body text."""

        current = block
        while current.isValid():
            if self._heading_level(current) is not None:
                return current
            current = current.previous()
        return None

    @staticmethod
    def _set_block_visible(block, visible: bool) -> None:
        block.setVisible(visible)
        block.setLineCount(1 if visible else 0)

    def collapse_section(self) -> None:
        """Hide the owning heading's body, even when the caret is in body text."""

        target = self._fold_target(self.textCursor().block())
        if target is None:
            return
        level = self._heading_level(target)
        block = target.next()
        while block.isValid():
            next_level = self._heading_level(block)
            if next_level is not None and next_level <= level:
                break
            self._set_block_visible(block, False)
            block = block.next()
        if not self.textCursor().block().isVisible():
            cursor = self.textCursor()
            cursor.setPosition(target.position())
            self.setTextCursor(cursor)
        self._refresh_document_layout()

    def expand_section(self, recursive: bool = False) -> None:
        """Show the owning heading's body; recursive controls nested sections."""

        target = self._fold_target(self.textCursor().block())
        if target is None:
            return
        level = self._heading_level(target)
        block = target.next()
        while block.isValid():
            next_level = self._heading_level(block)
            if next_level is not None and next_level <= level:
                break
            self._set_block_visible(block, True)
            block = block.next()
        if recursive:
            block = target.next()
            while block.isValid():
                next_level = self._heading_level(block)
                if next_level is not None and next_level <= level:
                    break
                if next_level is not None:
                    self._expand_from_block(block)
                block = block.next()
        self._refresh_document_layout()

    def _expand_from_block(self, heading) -> None:
        level = self._heading_level(heading)
        if level is None:
            return
        block = heading.next()
        while block.isValid():
            next_level = self._heading_level(block)
            if next_level is not None and next_level <= level:
                break
            self._set_block_visible(block, True)
            block = block.next()

    def expand_all(self) -> None:
        """Show every document block and remove folded-line markers."""

        block = self.document().firstBlock()
        while block.isValid():
            self._set_block_visible(block, True)
            block = block.next()
        self._refresh_document_layout()

    def collapse_all(self) -> None:
        """Collapse every heading section while leaving headings visible."""

        self.expand_all()
        block = self.document().firstBlock()
        while block.isValid():
            if self._heading_level(block) is not None:
                self._collapse_from_block(block)
            block = block.next()
        self._refresh_document_layout()

    def _collapse_from_block(self, heading) -> None:
        level = self._heading_level(heading)
        if level is None:
            return
        block = heading.next()
        while block.isValid():
            next_level = self._heading_level(block)
            if next_level is not None and next_level <= level:
                break
            self._set_block_visible(block, False)
            block = block.next()

    def _update_fold_markers(self) -> None:
        """Shade visible headings whose body currently contains hidden blocks."""

        selections: list[QTextEdit.ExtraSelection] = []
        block = self.document().firstBlock()
        while block.isValid():
            level = self._heading_level(block)
            if level is not None:
                following = block.next()
                folded = False
                while following.isValid():
                    next_level = self._heading_level(following)
                    if next_level is not None and next_level <= level:
                        break
                    if not following.isVisible():
                        folded = True
                        break
                    following = following.next()
                if folded:
                    selection = QTextEdit.ExtraSelection()
                    selection.cursor = QTextCursor(self.document())
                    selection.cursor.setPosition(block.position())
                    selection.cursor.movePosition(QTextCursor.MoveOperation.EndOfBlock, QTextCursor.MoveMode.KeepAnchor)
                    selection.format.setBackground(QColor("#e3e5eb"))
                    selection.format.setForeground(QColor("#6b7280"))
                    selection.format.setProperty(QTextFormat.Property.FullWidthSelection, True)
                    selections.append(selection)
            block = block.next()
        self.setExtraSelections(selections)

    def _refresh_document_layout(self) -> None:
        self.document().markContentsDirty(0, self.document().characterCount())
        self._update_fold_markers()
        self.viewport().update()

    def _update_import_completion(self) -> None:
        cursor = self.textCursor()
        line = cursor.block().text()[: cursor.positionInBlock()]
        match = IMPORT_INPUT_RE.search(line)
        if not match or not self._import_candidates:
            if self._completer.popup().isVisible():
                self._completer.popup().hide()
                self.completion_visibility_changed.emit(False)
            return
        prefix = match.group(1).strip()
        candidates = [
            name for name in self._import_candidates
            if not prefix or prefix.casefold() in name.casefold() or prefix.casefold() in chinese_initials(name)
        ]
        if not candidates:
            self._completer.popup().hide()
            return
        self._import_start = cursor.block().position() + match.start(1)
        self._completion_model.setStringList(candidates)
        self._completer.setCompletionPrefix("")
        rectangle = self.cursorRect(cursor)
        rectangle.setWidth(360)
        self._completer.complete(rectangle)
        self.completion_visibility_changed.emit(True)

    def _complete_import(self, name: str) -> None:
        """Replace the currently typed import name with the selected candidate."""

        if self._import_start < 0:
            return
        cursor = self.textCursor()
        cursor.setPosition(self._import_start)
        cursor.setPosition(self.textCursor().position(), QTextCursor.MoveMode.KeepAnchor)
        cursor.insertText(name)
        self.setTextCursor(cursor)
        self._import_start = -1
        self._completer.popup().hide()
        self.completion_visibility_changed.emit(False)
