"""Markdown syntax palette, parsing helpers, and presentation highlighter."""

from __future__ import annotations

import re
from collections.abc import Iterable

from PySide6.QtGui import QColor, QFont, QSyntaxHighlighter, QTextCharFormat



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
