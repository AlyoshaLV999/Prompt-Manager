"""Markdown editor with folding and PyCharm-like editing conveniences."""

from __future__ import annotations

import re
from collections.abc import Iterable

from PySide6.QtCore import QEvent, Qt, QStringListModel, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QSyntaxHighlighter,
    QTextCharFormat,
    QTextCursor,
    QTextFormat,
)
from PySide6.QtWidgets import (
    QApplication,
    QCompleter,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QTextEdit,
    QToolButton,
)


HEADING_RE = re.compile(r"^(\s{0,3})(#{1,6})(?:\s+|$)")
IMPORT_INPUT_RE = re.compile(r"=====IMPORT:\s*([^=\n]*)$")

SEARCH_MATCH_COLOR = "#fff3b0"
SEARCH_CURRENT_COLOR = "#ffb86b"
SEARCH_CURRENT_TEXT_COLOR = "#1f2430"

# Markdown palette.  The colours follow the IntelliJ/PyCharm light scheme
# closely enough to feel familiar while staying in the pastel family the rest of
# the window already uses.  Keeping every entry here makes the whole scheme
# adjustable in one place.
HEADING_COLOR = "#5b4bd6"
HEADING_MARKER_COLOR = "#a49ce8"
STRONG_COLOR = "#8e3560"
EMPHASIS_COLOR = "#9c3d6d"
STRIKETHROUGH_COLOR = "#8a8f9c"
CODE_COLOR = "#19745b"
CODE_BACKGROUND_COLOR = "#eef6f1"
FENCE_COLOR = "#7fa79a"
MARKER_COLOR = "#c26a18"
QUOTE_COLOR = "#4f7a68"
LINK_COLOR = "#1a63c9"
LINK_DESTINATION_COLOR = "#7b8aa3"
HTML_TAG_COLOR = "#0f7b9c"
ESCAPE_COLOR = "#b07d3a"
RULE_COLOR = "#c3c8d4"
TABLE_COLOR = "#a3adc2"

# Block-level constructs.  A fenced code block is the only construct that spans
# lines, so it is tracked through the block state: the state encodes the fence
# character together with the length of its opening run, which is what decides
# whether a later run of the same character closes the block.
RULE_RE = re.compile(r"^\s{0,3}(?:(?:\*\s*){3,}|(?:-\s*){3,}|(?:_\s*){3,})$")
QUOTE_RE = re.compile(r"^\s*(?:>\s?)+")
LIST_MARKER_RE = re.compile(r"^(\s*(?:>\s?)*)([-*+]|\d{1,9}[.)])(?=\s|$)")
TASK_MARKER_RE = re.compile(r"^\s*(?:>\s?)*[-*+]\s+(\[[ xX]\])(?=\s|$)")
FENCE_MINIMUM_LENGTH = 3
FENCE_TICK_STATE = 100
FENCE_TILDE_STATE = 200
FENCE_LENGTH_LIMIT = 63

# Inline constructs.  Every pattern is matched against a masked copy of the line
# in which code spans, escapes, and block markers are replaced by NUL
# characters, so markers that belong to another construct cannot be paired
# across them.
INLINE_CODE_RE = re.compile(r"(`+)(.+?)\1")
ESCAPE_RE = re.compile(r"\\[!-/:-@\[-`{-~]")
INTRAWORD_UNDERSCORE_RE = re.compile(r"(?<=\w)_(?=\w)")
BARE_URL_RE = re.compile(r"(?<![\w/])(?:https?://|ftp://|www\.)[^\s<>()\[\]`\"'*_~]+")
AUTOLINK_RE = re.compile(r"<(?:[a-zA-Z][a-zA-Z0-9+.-]*:[^<>\s]+|[^<>\s@]+@[^<>\s@]+\.[^<>\s@]+)>")
HTML_TAG_RE = re.compile(r"</?[A-Za-z][A-Za-z0-9-]*(?:\s[^<>]*?)?/?>")
IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(([^)\n]*)\)")
LINK_RE = re.compile(r"\[([^\]]*)\]\(([^)\n]*)\)")
LINK_REFERENCE_RE = re.compile(r"\[([^\]]*)\]\[([^\]]*)\]")
LINK_DEFINITION_RE = re.compile(r"^(\s{0,3}\[[^\]]+\]:)[ \t]*(\S+)")
# Emphasis is a single ordered alternation, longest marker first, so that
# ``***bold italic***`` is not re-matched as strong-only by a later pattern; the
# format is then chosen from the length of the marker that matched.
EMPHASIS_RE = re.compile(r"(\*\*\*|___|\*\*|__|\*|_)(?=\S)([^*_]+?)(?<=\S)\1")
STRIKETHROUGH_RE = re.compile(r"(~~)(?=\S)(.+?)(?<=\S)\1")
APP_MARKER_RE = re.compile(r"=====\w+:.*?=====")
PIPE_RE = re.compile(r"\|")
TABLE_CELL_RE = re.compile(r":?-+:?")


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


def _text_format(
    color: str,
    *,
    bold: bool = False,
    italic: bool = False,
    underline: bool = False,
    strikeout: bool = False,
    background: str | None = None,
) -> QTextCharFormat:
    """Build one character format of the Markdown palette.

    :param color: Foreground colour as a hex string.
    :param bold: Whether the text renders bold.
    :param italic: Whether the text renders italic.
    :param underline: Whether the text renders underlined.
    :param strikeout: Whether the text renders struck through.
    :param background: Optional background colour as a hex string.
    :return: A new format, so no two constructs ever share one instance.
    """

    format_ = QTextCharFormat()
    format_.setForeground(QColor(color))
    if bold:
        format_.setFontWeight(QFont.Weight.Bold)
    if italic:
        format_.setFontItalic(True)
    if underline:
        format_.setFontUnderline(True)
    if strikeout:
        format_.setFontStrikeOut(True)
    if background is not None:
        format_.setBackground(QColor(background))
    return format_


def _mask(text: str, ranges: Iterable[tuple[int, int]]) -> str:
    """Return ``text`` with ``ranges`` replaced by NUL characters.

    Replacing characters one for one keeps every index in place, so a pattern
    matched against the result still reports its original position, while the
    NUL characters stop it from spanning a range it must ignore.
    """

    if not ranges:
        return text
    characters = list(text)
    for start, end in ranges:
        for index in range(max(start, 0), min(end, len(characters))):
            characters[index] = "\x00"
    return "".join(characters)


def _trim_url_end(text: str, end: int) -> int:
    """Drop the sentence punctuation a bare URL only picks up in prose."""

    while end > 0 and text[end - 1] in ".,;:!?":
        end -= 1
    return end


def _fence_state(character: str, length: int) -> int:
    """Encode a fence that is now open as a block state value."""

    base = FENCE_TICK_STATE if character == "`" else FENCE_TILDE_STATE
    return base + min(length, FENCE_LENGTH_LIMIT)


def _fence_from_state(state: int) -> tuple[str, int] | None:
    """Return the fence character and run length remembered in ``state``."""

    for character, base in (("`", FENCE_TICK_STATE), ("~", FENCE_TILDE_STATE)):
        if base < state <= base + FENCE_LENGTH_LIMIT:
            return character, state - base
    return None


def _opening_fence(text: str) -> tuple[str, int, int] | None:
    """Return ``(character, length, run end)`` when ``text`` opens a fence."""

    body = text.lstrip(" ")
    if not body or len(text) - len(body) > 3:
        return None
    character = body[0]
    if character not in ("`", "~"):
        return None
    length = len(body) - len(body.lstrip(character))
    if length < FENCE_MINIMUM_LENGTH:
        return None
    # A backtick fence may not carry backticks in its info string, which is what
    # keeps a line that is only inline code from being read as a fence.
    if character == "`" and "`" in body[length:]:
        return None
    return character, length, len(text) - len(body) + length


def _closes_fence(text: str, character: str, length: int) -> bool:
    """Return whether ``text`` closes the fence opened by ``character``."""

    body = text.lstrip(" ")
    if len(text) - len(body) > 3:
        return False
    run = body.rstrip(" \t")
    return len(run) >= length and set(run) == {character}


def _is_table_delimiter(text: str) -> bool:
    """Return whether ``text`` is a pipe table's ``|---|:--:|`` separator row."""

    stripped = text.strip()
    if "|" not in stripped or "-" not in stripped or not set(stripped) <= set("|:- \t"):
        return False
    for cell in stripped.strip("|").split("|"):
        cell = cell.strip()
        if cell and not TABLE_CELL_RE.fullmatch(cell):
            return False
    return True


class MarkdownHighlighter(QSyntaxHighlighter):
    """Colour Markdown the way an IDE colours a Markdown file.

    Only presentation is produced: the document text is never modified, and
    folding keeps working on the plain text through :data:`HEADING_RE`.  Fenced
    code blocks are tracked across lines through the block state so that
    everything between the fences is shown as code; every other construct is
    decided from its own line.
    """

    def __init__(self, document) -> None:
        super().__init__(document)
        self.heading = _text_format(HEADING_COLOR, bold=True)
        self.heading_marker = _text_format(HEADING_MARKER_COLOR, bold=True)
        self.strong = _text_format(STRONG_COLOR, bold=True)
        self.strong_emphasis = _text_format(STRONG_COLOR, bold=True, italic=True)
        self.emphasis = _text_format(EMPHASIS_COLOR, italic=True)
        self.strikethrough = _text_format(STRIKETHROUGH_COLOR, strikeout=True)
        self.code = _text_format(CODE_COLOR, background=CODE_BACKGROUND_COLOR)
        self.fence = _text_format(FENCE_COLOR)
        self.marker = _text_format(MARKER_COLOR)
        self.list_marker = _text_format(MARKER_COLOR, bold=True)
        self.quote = _text_format(QUOTE_COLOR, italic=True)
        self.link = _text_format(LINK_COLOR, underline=True)
        self.link_destination = _text_format(LINK_DESTINATION_COLOR)
        self.html_tag = _text_format(HTML_TAG_COLOR)
        self.escape = _text_format(ESCAPE_COLOR)
        self.rule = _text_format(RULE_COLOR)
        self.table = _text_format(TABLE_COLOR)

    def highlightBlock(self, text: str) -> None:  # noqa: N802 - Qt override
        """Colour one document line.

        Later calls win wherever ranges overlap, so the statements below are the
        precedence order as well: line-wide styles first, inline constructs
        next, then the code spans and escapes they may not cross, and finally
        the block markers, which stay visible whatever else the line holds.
        """

        self.setCurrentBlockState(0)
        if self._highlight_fence_line(text):
            return

        heading = HEADING_RE.match(text)
        if heading is not None:
            self.setFormat(0, len(text), self.heading)
        if RULE_RE.match(text):
            self.setFormat(0, len(text), self.rule)
            return
        if QUOTE_RE.match(text):
            self.setFormat(0, len(text), self.quote)

        markers: list[tuple[int, int, QTextCharFormat]] = []
        for match in LIST_MARKER_RE.finditer(text):
            markers.append((match.start(2), match.end(2), self.list_marker))
        for match in TASK_MARKER_RE.finditer(text):
            markers.append((match.start(1), match.end(1), self.list_marker))
        if _is_table_delimiter(text):
            markers.append((0, len(text), self.table))
        elif text.count("|") >= 2:
            for match in PIPE_RE.finditer(text):
                markers.append((match.start(), match.end(), self.table))

        self._highlight_inline(text, [(start, end) for start, end, _ in markers])

        if heading is not None:
            self.setFormat(heading.start(2), heading.end(2) - heading.start(2), self.heading_marker)
        for start, end, format_ in markers:
            self.setFormat(start, end - start, format_)

    def _highlight_inline(self, text: str, markers: list[tuple[int, int]]) -> None:
        """Colour the inline constructs of one line.

        :param text: The line as written.
        :param markers: Ranges the caller styles afterwards; they are masked out
            here so that, for one example, the ``*`` of a bullet cannot be paired
            with the ``*`` of an emphasis further along the line.
        """

        code_spans = [(match.start(), match.end()) for match in INLINE_CODE_RE.finditer(text)]
        escape_spans = [(match.start(), match.end()) for match in ESCAPE_RE.finditer(text)]
        # An underscore between two word characters belongs to a name such as
        # ``prompt_id``, not to an emphasised word.
        underscore_spans = [
            (match.start(), match.end()) for match in INTRAWORD_UNDERSCORE_RE.finditer(text)
        ]
        masked = _mask(text, [*markers, *code_spans, *escape_spans, *underscore_spans])

        for match in EMPHASIS_RE.finditer(masked):
            self.setFormat(
                match.start(),
                match.end() - match.start(),
                self._emphasis_format(len(match.group(1))),
            )
        for match in STRIKETHROUGH_RE.finditer(masked):
            self.setFormat(match.start(), match.end() - match.start(), self.strikethrough)
        for match in BARE_URL_RE.finditer(masked):
            end = _trim_url_end(masked, match.end())
            self.setFormat(match.start(), end - match.start(), self.link)
        for match in AUTOLINK_RE.finditer(masked):
            self.setFormat(match.start(), match.end() - match.start(), self.link)
        for match in HTML_TAG_RE.finditer(masked):
            self.setFormat(match.start(), match.end() - match.start(), self.html_tag)
        for match in IMAGE_RE.finditer(masked):
            self._format_link(match)
        for match in LINK_RE.finditer(masked):
            if match.start() == 0 or masked[match.start() - 1] != "!":
                self._format_link(match)
        for match in LINK_REFERENCE_RE.finditer(masked):
            self.setFormat(match.start(), match.end() - match.start(), self.link)
        definition = LINK_DEFINITION_RE.match(masked)
        if definition is not None:
            self.setFormat(definition.start(1), definition.end(1) - definition.start(1), self.link)
            self.setFormat(
                definition.start(2), definition.end(2) - definition.start(2), self.link_destination,
            )
        for match in APP_MARKER_RE.finditer(text):
            self.setFormat(match.start(), match.end() - match.start(), self.marker)
        for start, end in escape_spans:
            self.setFormat(start, end - start, self.escape)
        for start, end in code_spans:
            self.setFormat(start, end - start, self.code)

    def _format_link(self, match: re.Match[str]) -> None:
        """Colour ``[text](target)``: the label as a link, the target dimmed."""

        label_end = match.end(1) + 1
        self.setFormat(match.start(), label_end - match.start(), self.link)
        self.setFormat(label_end, match.end() - label_end, self.link_destination)

    def _emphasis_format(self, marker_length: int) -> QTextCharFormat:
        """Return the format for ``*``, ``**``, or ``***`` emphasis."""

        if marker_length >= 3:
            return self.strong_emphasis
        return self.strong if marker_length == 2 else self.emphasis

    def _highlight_fence_line(self, text: str) -> bool:
        """Colour a line that opens, closes, or sits inside a fenced code block.

        :param text: The line as written.
        :return: ``True`` when the line belongs to a fence and was handled here.
        """

        open_fence = _fence_from_state(self.previousBlockState())
        if open_fence is not None:
            character, length = open_fence
            self.setFormat(0, len(text), self.code)
            if _closes_fence(text, character, length):
                run_start = len(text) - len(text.lstrip(" "))
                self.setFormat(run_start, len(text) - run_start, self.fence)
            else:
                self.setCurrentBlockState(_fence_state(character, length))
            return True
        opening = _opening_fence(text)
        if opening is None:
            return False
        character, length, run_end = opening
        self.setCurrentBlockState(_fence_state(character, length))
        self.setFormat(0, len(text), self.code)
        self.setFormat(run_end - length, length, self.fence)
        return True


class SearchReplaceBar(QFrame):
    """Inline find/replace panel attached to a :class:`MarkdownEditor`."""

    def __init__(self, editor: "MarkdownEditor") -> None:
        super().__init__(editor)
        self._editor = editor
        self._matches: list[QTextCursor] = []
        self._current_index = -1
        self.setObjectName("SearchReplaceBar")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setVisible(False)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 5, 8, 5)
        layout.setSpacing(4)

        self.search_field = QLineEdit()
        self.search_field.setPlaceholderText("查找")
        self.search_field.setClearButtonEnabled(True)
        self.search_field.setMinimumWidth(140)
        self.search_field.textChanged.connect(self._refresh_matches)
        self.search_field.installEventFilter(self)

        self.counter_label = QLabel("")
        self.counter_label.setObjectName("Meta")
        self.counter_label.setMinimumWidth(48)
        self.counter_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.previous_button = QToolButton()
        self.previous_button.setText("↑")
        self.previous_button.setToolTip("上一个匹配 (Shift+Enter)")
        self.previous_button.clicked.connect(self.find_previous)

        self.next_button = QToolButton()
        self.next_button.setText("↓")
        self.next_button.setToolTip("下一个匹配 (Enter)")
        self.next_button.clicked.connect(self.find_next)

        self.replace_field = QLineEdit()
        self.replace_field.setPlaceholderText("替换为")
        self.replace_field.setClearButtonEnabled(True)
        self.replace_field.setMinimumWidth(140)

        self.replace_button = QToolButton()
        self.replace_button.setText("替换")
        self.replace_button.setToolTip("替换当前匹配")
        self.replace_button.clicked.connect(self.replace_current)

        self.replace_all_button = QToolButton()
        self.replace_all_button.setText("全部替换")
        self.replace_all_button.setToolTip("替换所有匹配")
        self.replace_all_button.clicked.connect(self.replace_all)

        self.close_button = QToolButton()
        self.close_button.setText("✕")
        self.close_button.setToolTip("关闭 (Esc)")
        self.close_button.clicked.connect(self.close_bar)

        layout.addWidget(self.search_field)
        layout.addWidget(self.counter_label)
        layout.addWidget(self.previous_button)
        layout.addWidget(self.next_button)
        layout.addWidget(self.replace_field)
        layout.addWidget(self.replace_button)
        layout.addWidget(self.replace_all_button)
        layout.addWidget(self.close_button)

        self._replace_widgets = (
            self.replace_field,
            self.replace_button,
            self.replace_all_button,
        )
        self._set_replace_visible(False)

    def open_for(self, *, replace: bool) -> None:
        """Show the bar, optionally revealing the replacement controls."""

        self._set_replace_visible(replace)
        self.adjustSize()
        self.show()
        self.reposition()
        cursor = self._editor.textCursor()
        if cursor.hasSelection() and "\u2029" not in cursor.selectedText():
            self.search_field.setText(cursor.selectedText())
        self.search_field.setFocus()
        self.search_field.selectAll()
        self._refresh_matches()

    def close_bar(self) -> None:
        """Hide the bar and drop search highlights."""

        self.hide()
        self._matches = []
        self._current_index = -1
        self._editor.set_search_highlights([], -1)
        self._editor.setFocus()

    def refresh_matches(self) -> None:
        """Recompute matches after the document changed."""

        self._refresh_matches(preserve_index=True)

    def reposition(self) -> None:
        """Place the bar in the editor's top-right corner."""

        editor_width = self._editor.width()
        if editor_width <= 0:
            return
        hint = self.sizeHint()
        max_width = max(320, editor_width - 24)
        width = min(hint.width(), max_width)
        self.resize(width, hint.height())
        self.move(max(12, editor_width - width - 12), 8)

    def eventFilter(self, obj, event) -> bool:  # noqa: N802 - Qt override
        """Route Escape / Enter / Shift+Enter while the search field has focus."""

        if obj is self.search_field and event.type() == QEvent.Type.KeyPress:
            if event.key() == Qt.Key.Key_Escape:
                self.close_bar()
                return True
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                    self.find_previous()
                else:
                    self.find_next()
                return True
        return super().eventFilter(obj, event)

    def find_next(self) -> None:
        """Select the next match, wrapping around the document end."""

        if not self._matches:
            self._refresh_matches()
            if not self._matches:
                return
        if self._current_index < 0:
            self._current_index = 0
        else:
            self._current_index = (self._current_index + 1) % len(self._matches)
        self._apply_current_match()

    def find_previous(self) -> None:
        """Select the previous match, wrapping around the document start."""

        if not self._matches:
            self._refresh_matches()
            if not self._matches:
                return
        if self._current_index < 0:
            self._current_index = len(self._matches) - 1
        else:
            self._current_index = (self._current_index - 1) % len(self._matches)
        self._apply_current_match()

    def replace_current(self) -> None:
        """Replace the selected match and select the following one."""

        if not self._matches or not (0 <= self._current_index < len(self._matches)):
            return
        replacement = self.replace_field.text()
        match = self._matches[self._current_index]
        replacement_end = match.selectionStart() + len(replacement)
        cursor = QTextCursor(self._editor.document())
        cursor.setPosition(match.selectionStart())
        cursor.setPosition(match.selectionEnd(), QTextCursor.MoveMode.KeepAnchor)
        cursor.insertText(replacement)
        self._refresh_matches()
        if not self._matches:
            return
        self._current_index = 0
        for index, candidate in enumerate(self._matches):
            if candidate.selectionStart() >= replacement_end:
                self._current_index = index
                break
        self._apply_current_match()

    def replace_all(self) -> None:
        """Replace every match in one undoable edit block."""

        text = self.search_field.text()
        if not text:
            return
        matches = self._editor.find_all(text)
        if not matches:
            return
        replacement = self.replace_field.text()
        cursor = QTextCursor(self._editor.document())
        cursor.beginEditBlock()
        try:
            # Replace back-to-front so earlier matches keep their positions.
            for match in reversed(matches):
                replace_cursor = QTextCursor(self._editor.document())
                replace_cursor.setPosition(match.selectionStart())
                replace_cursor.setPosition(match.selectionEnd(), QTextCursor.MoveMode.KeepAnchor)
                replace_cursor.insertText(replacement)
        finally:
            cursor.endEditBlock()
        self._refresh_matches()

    def _set_replace_visible(self, visible: bool) -> None:
        for widget in self._replace_widgets:
            widget.setVisible(visible)

    def _refresh_matches(self, preserve_index: bool = False) -> None:
        text = self.search_field.text()
        previous = self._current_index
        self._matches = self._editor.find_all(text) if text else []
        if not self._matches:
            self._current_index = -1
        elif preserve_index and 0 <= previous < len(self._matches):
            self._current_index = previous
        else:
            self._current_index = 0
        self._editor.set_search_highlights(self._matches, self._current_index)
        self._update_counter()

    def _apply_current_match(self) -> None:
        if not self._matches:
            self._editor.set_search_highlights([], -1)
            self._update_counter()
            return
        if not (0 <= self._current_index < len(self._matches)):
            self._current_index = 0
        match = self._matches[self._current_index]
        cursor = QTextCursor(self._editor.document())
        cursor.setPosition(match.selectionStart())
        self._editor.setTextCursor(cursor)
        self._editor.ensureCursorVisible()
        self._editor.set_search_highlights(self._matches, self._current_index)
        self._update_counter()

    def _update_counter(self) -> None:
        if not self._matches:
            self.counter_label.setText("0/0" if self.search_field.text() else "")
            return
        self.counter_label.setText(f"{self._current_index + 1}/{len(self._matches)}")


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
        self._search_matches: list[QTextCursor] = []
        self._current_search_index = -1
        self._search_bar = SearchReplaceBar(self)
        self.document().contentsChanged.connect(self._on_document_changed)

    def open_find_bar(self) -> None:
        """Show the inline find bar and focus its search field."""

        self._search_bar.open_for(replace=False)

    def open_replace_bar(self) -> None:
        """Show the inline replace bar and focus its search field."""

        self._search_bar.open_for(replace=True)

    def find_all(self, text: str) -> list[QTextCursor]:
        """Return cursors for every non-overlapping occurrence of ``text``."""

        if not text:
            return []
        matches: list[QTextCursor] = []
        document = self.document()
        cursor = QTextCursor(document)
        while True:
            match = document.find(text, cursor)
            if match.isNull():
                break
            matches.append(match)
            cursor.setPosition(match.selectionEnd())
        return matches

    def set_search_highlights(self, matches: list[QTextCursor], current_index: int) -> None:
        """Update the highlight overlays used by the find bar."""

        self._search_matches = matches
        self._current_search_index = current_index
        self._update_extra_selections()

    def set_import_candidates(self, names: Iterable[str]) -> None:
        """Replace fixed-preset completion candidates."""

        self._import_candidates = list(dict.fromkeys(names))

    def keyPressEvent(self, event) -> None:  # noqa: N802 - Qt override
        """Handle folding, selection expansion, line editing, and completion."""

        key = event.key()
        modifiers = event.modifiers()
        no_modifier = modifiers == Qt.KeyboardModifier.NoModifier

        # QCompleter normally filters this event, but with a QPlainTextEdit it
        # can occasionally reach the editor as well.  Consume it explicitly
        # so selecting an import with the arrow keys and pressing Enter never
        # inserts an unintended newline.
        #
        # Note: ``QCompleter.currentCompletion()`` is not reliable here.  The
        # import popup intentionally uses an empty completion prefix (the user
        # filters by typing after the marker, not as a completer prefix), and
        # when the prefix is empty the completer's internal current index can
        # stay pinned to the first candidate even after the user navigates the
        # popup with the arrow keys.  That is what caused Enter to always
        # insert the first candidate.  The popup view's ``currentIndex`` is
        # the authoritative source of the row the user actually highlighted,
        # so prefer it and fall back to ``currentCompletion()`` only when the
        # view has no valid selection.
        if self._completer.popup().isVisible() and key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            completion = ""
            popup_index = self._completer.popup().currentIndex()
            if popup_index.isValid():
                completion = str(popup_index.data() or "")
            if not completion:
                completion = self._completer.currentCompletion()
            if completion:
                self._complete_import(completion)
                event.accept()
                return

        if no_modifier and key in (Qt.Key.Key_QuoteDbl, Qt.Key.Key_Apostrophe):
            self.wrap_selection(event.text(), event.text())
            return
        if no_modifier and key == Qt.Key.Key_QuoteLeft:
            self.wrap_selection("`", "`")
            return
        super().keyPressEvent(event)
        self._update_import_completion()

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().resizeEvent(event)
        if self._search_bar.isVisible():
            self._search_bar.reposition()

    def _on_document_changed(self) -> None:
        """Keep fold markers and live search overlays in sync with the text."""

        self._update_fold_markers()
        if self._search_bar.isVisible():
            self._search_bar.refresh_matches()

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

        self._update_extra_selections()

    def _update_extra_selections(self) -> None:
        """Merge fold markers and search highlights into one selection list."""

        selections = self._compute_fold_selections()
        for index, match in enumerate(self._search_matches):
            selection = QTextEdit.ExtraSelection()
            selection.cursor = match
            if index == self._current_search_index:
                selection.format.setBackground(QColor(SEARCH_CURRENT_COLOR))
                selection.format.setForeground(QColor(SEARCH_CURRENT_TEXT_COLOR))
            else:
                selection.format.setBackground(QColor(SEARCH_MATCH_COLOR))
            selections.append(selection)
        self.setExtraSelections(selections)

    def _compute_fold_selections(self) -> list[QTextEdit.ExtraSelection]:
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
                    selection.cursor.movePosition(
                        QTextCursor.MoveOperation.EndOfBlock,
                        QTextCursor.MoveMode.KeepAnchor,
                    )
                    selection.format.setBackground(QColor("#e3e5eb"))
                    selection.format.setForeground(QColor("#6b7280"))
                    selection.format.setProperty(QTextFormat.Property.FullWidthSelection, True)
                    selections.append(selection)
            block = block.next()
        return selections

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
        end = cursor.position()
        if end < self._import_start:
            self._import_start = -1
            return
        cursor.setPosition(self._import_start)
        cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
        cursor.insertText(name)
        self.setTextCursor(cursor)
        self._import_start = -1
        self._completer.popup().hide()
        self.completion_visibility_changed.emit(False)
