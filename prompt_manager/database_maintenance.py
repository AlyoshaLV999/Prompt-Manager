"""Database snapshot maintenance: the background worker, the restore dialog,
and the per-run safety copies taken for the Agent."""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from .service import PromptService
from .storage import AGENT_BACKUP_STAMP_FORMAT, StorageError, agent_backup_sequence, is_agent_backup

logger = logging.getLogger(__name__)


class AgentBackupSession:
    """Track the Agent safety copies of one program run.

    An Agent reply may call tools that rewrite stored prompts, so one snapshot
    is taken before each generated reply.  The snapshots are tagged with the
    Agent marker and the moment this run started, and they are deleted again
    when the run ends: they are meant to undo an Agent mistake inside the same
    session, not to accumulate on disk as long-term backups.
    """

    def __init__(self, service: PromptService) -> None:
        self._service = service
        self._stamp = datetime.now().strftime(AGENT_BACKUP_STAMP_FORMAT)
        self._paths: list[Path] = []

    @property
    def count(self) -> int:
        """Return how many snapshots this session has taken."""

        return len(self._paths)

    def capture(self) -> Path:
        """Take one tagged snapshot and remember it for the session cleanup.

        :return: Path to the completed snapshot.
        :raises StorageError: If the snapshot cannot be created or verified.
        """

        sequence = len(self._paths) + 1
        path = self._service.backup_agent_database(self._stamp, sequence)
        self._paths.append(path)
        return path

    def discard(self) -> None:
        """Delete every snapshot this session created and forget them."""

        paths, self._paths = self._paths, []
        remaining = self._service.remove_database_backups(paths)
        if remaining:
            logger.warning(
                "Failed to remove %d Agent snapshot(s), for example %s",
                len(remaining), remaining[0],
            )


class DatabaseTaskThread(QThread):
    """Run one repository maintenance call away from the GUI thread.

    The callable performs the blocking work and returns the value reported to
    the GUI.  :attr:`completed` is emitted from the worker thread, so it is
    always delivered to the receiver on the GUI thread.
    """

    completed = Signal(object, str)

    def __init__(self, task: Callable[[], object]) -> None:
        super().__init__()
        self._task = task

    def run(self) -> None:
        try:
            result = self._task()
        except StorageError as exc:
            self.completed.emit(None, str(exc))
        else:
            self.completed.emit(result, "")


def format_byte_size(size: int) -> str:
    """Return a compact human-readable size for a byte count."""

    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size / (1024 * 1024):.1f} MB"


def format_backup_label(path: Path) -> str:
    """Return a user-readable label for one snapshot database.

    :param path: Snapshot file inside its date-named backup folder.
    :return: Creation time, file size, and for an Agent snapshot the number it
        was given inside its session, falling back to the folder and file name
        when the file metadata cannot be read.
    """

    marker = ""
    if is_agent_backup(path):
        sequence = agent_backup_sequence(path)
        marker = "，Agent 自动备份" if sequence is None else f"，Agent 自动备份 #{sequence}"
    try:
        stat = path.stat()
    except OSError:
        return f"{path.parent.name} / {path.name}{marker}"
    created = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M")
    return f"{created}（{format_byte_size(stat.st_size)}{marker}）"


class RestoreDatabaseDialog(QDialog):
    """Choose one database snapshot to restore over the live database."""

    def __init__(self, backups: Sequence[Path], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("恢复数据库")
        self.setMinimumWidth(460)
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 22, 24, 20)
        root.setSpacing(12)

        title = QLabel("恢复数据库")
        title.setObjectName("AppTitle")
        root.addWidget(title)

        hint = QLabel("选择要恢复的备份，点击“确定”后用它替换当前数据库，界面会立即刷新。")
        hint.setObjectName("Subtitle")
        hint.setWordWrap(True)
        root.addWidget(hint)

        warning = QLabel("恢复会用备份内容覆盖当前的提示词、分组、设置与临时文本，且无法撤销。")
        warning.setObjectName("Hint")
        warning.setWordWrap(True)
        root.addWidget(warning)

        form = QFormLayout()
        self.backup_combo = QComboBox()
        self.backup_combo.setToolTip("数据目录中按日期保存的数据库快照，最新的排在最前面")
        for path in backups:
            self.backup_combo.addItem(format_backup_label(path), str(path))
        form.addRow("备份", self.backup_combo)
        root.addLayout(form)
        root.addStretch(1)

        buttons = QDialogButtonBox()
        accept_button = buttons.addButton("确定", QDialogButtonBox.ButtonRole.AcceptRole)
        accept_button.setObjectName("PrimaryButton")
        cancel_button = buttons.addButton("取消", QDialogButtonBox.ButtonRole.RejectRole)
        accept_button.clicked.connect(self.accept)
        cancel_button.clicked.connect(self.reject)
        root.addWidget(buttons)

    def selected_backup(self) -> Path | None:
        """Return the chosen snapshot, or ``None`` when nothing is selected."""

        data = self.backup_combo.currentData()
        return Path(str(data)) if data else None
