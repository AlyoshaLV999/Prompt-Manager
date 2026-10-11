"""Settings dialog and provider model list refresh controls."""

from __future__ import annotations

import logging
import os

from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (
    QApplication, QComboBox, QDialog, QDialogButtonBox, QFormLayout,
    QHBoxLayout, QLabel, QKeySequenceEdit, QLineEdit, QListWidget,
    QMessageBox, QSpinBox, QStackedWidget, QVBoxLayout, QWidget,
)

from .agent import (
    GLM_KNOWN_MODELS, PROVIDER_DEFAULTS, AgentRequestError,
    fetch_glm_models, fetch_ollama_models, provider_api_key, provider_config,
)
from .drag_exports import DEFAULT_RETENTION_MINUTES, MAX_RETENTION_MINUTES, MIN_RETENTION_MINUTES
from .service import PromptService
from .storage import StorageError
from .ui_constants import DEFAULT_ITEM_NAME_MAX_LENGTH, DEFAULT_SHORTCUTS, SHORTCUT_LABELS

logger = logging.getLogger(f"{__package__}.ui")


class _ModelFetchThread(QThread):
    """Query a model provider (Ollama or GLM) for available models."""

    completed = Signal(object, str)

    def __init__(self, base_url: str, api_key: str = "", provider: str = "ollama", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.base_url = base_url
        self.api_key = api_key
        self.provider = provider

    def run(self) -> None:
        try:
            if self.provider == "ollama":
                models = fetch_ollama_models(self.base_url)
            elif self.provider == "glm":
                models = fetch_glm_models(self.base_url, self.api_key)
            else:
                raise AgentRequestError(f"不支持的模型服务商: {self.provider}")
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


class SettingsDialog(QDialog):
    """Edit application shortcuts and OpenAI-compatible Agent settings."""

    def __init__(self, service: PromptService, shortcuts: dict[str, str], parent=None,
                 api_keys: dict[str, str] | None = None) -> None:
        super().__init__(parent)
        self.service = service
        self.shortcut_edits: dict[str, QKeySequenceEdit] = {}
        self.api_key_value = ""
        self._model_thread: _ModelFetchThread | None = None
        self._model_refresh_pending = False
        self._provider_config: dict[str, dict[str, str]] = {}
        settings = service.settings()
        for name in PROVIDER_DEFAULTS:
            url, model = provider_config(settings, name)
            persisted_key = provider_api_key(settings, name)
            has_saved_key = f"agent_{name}_api_key" in settings or (
                settings.get("agent_provider", "openai") == name and "agent_api_key" in settings
            )
            self._provider_config[name] = {
                "base_url": url,
                "model": model,
                "api_key": persisted_key if has_saved_key else (api_keys or {}).get(name, ""),
            }
        try:
            item_name_max_length = int(settings.get("item_name_max_length", DEFAULT_ITEM_NAME_MAX_LENGTH))
        except (TypeError, ValueError):
            item_name_max_length = DEFAULT_ITEM_NAME_MAX_LENGTH
        try:
            drag_retention_minutes = int(settings.get("drag_export_retention_minutes", DEFAULT_RETENTION_MINUTES))
        except (TypeError, ValueError):
            drag_retention_minutes = DEFAULT_RETENTION_MINUTES
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
        self.drag_retention_edit = QSpinBox()
        self.drag_retention_edit.setRange(MIN_RETENTION_MINUTES, MAX_RETENTION_MINUTES)
        self.drag_retention_edit.setValue(max(MIN_RETENTION_MINUTES, min(MAX_RETENTION_MINUTES, drag_retention_minutes)))
        self.drag_retention_edit.setSuffix(" 分钟")
        self.drag_retention_edit.setToolTip("拖拽生成的临时 Markdown 文件超过此时长后自动删除")
        form.addRow("拖拽文件保留时间", self.drag_retention_edit)
        shortcuts_tip = QLabel("编辑器快捷键在内容编辑区或临时文本区获得焦点时生效。")
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
        self.agent_provider_edit.addItem("GLM", "glm")
        provider = settings.get("agent_provider", "openai")
        if provider not in PROVIDER_DEFAULTS:
            provider = "openai"
        provider_index = self.agent_provider_edit.findData(provider)
        self.agent_provider_edit.setCurrentIndex(max(0, provider_index))
        agent_form.addRow("服务商", self.agent_provider_edit)
        self.agent_base_url_edit = QLineEdit(self._provider_config[provider]["base_url"])
        self.agent_base_url_edit.setPlaceholderText("OpenAI 兼容 API 基础地址")
        agent_form.addRow("API 地址", self.agent_base_url_edit)
        self.agent_model_edit = _ModelComboBox()
        self.agent_model_edit.setCurrentText(self._provider_config[provider]["model"])
        line_edit = self.agent_model_edit.lineEdit()
        if line_edit is not None:
            line_edit.setPlaceholderText("模型名称（可直接输入或从下拉列表选择）")
        self.agent_model_edit.setToolTip(
            "Ollama 和 GLM 可从下拉列表选择模型；也可以直接输入模型名称。"
        )
        self.agent_model_edit.refresh_requested.connect(self._refresh_agent_models)
        agent_form.addRow("模型", self.agent_model_edit)
        self.model_status_label = QLabel()
        self.model_status_label.setObjectName("Meta")
        agent_form.addRow("", self.model_status_label)

        self.agent_api_key_edit = QLineEdit()
        self.agent_api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.agent_api_key_edit.setPlaceholderText("留空时读取 OPENAI_API_KEY / GEMINI_API_KEY / GLM_API_KEY")
        api_key = self._provider_config[provider]["api_key"]
        self.agent_api_key_edit.setText(api_key)
        agent_form.addRow("API Key（持久化保存）", self.agent_api_key_edit)
        self._agent_provider = provider
        self.agent_provider_edit.currentIndexChanged.connect(self._update_agent_provider_defaults)
        self._set_model_options(GLM_KNOWN_MODELS if provider == "glm" else [])
        self.model_status_label.setText("可选择建议模型，或输入自己的模型名称" if provider == "glm" else "")
        if provider in ("ollama", "glm"):
            self._refresh_agent_models()
        tip = QLabel(
            "API Key 会持久化保存到本地数据库，关闭程序后仍然可用。"
            "如果您有多个服务商的 Key，请分别保存。"
            "Gemini 使用 OpenAI 兼容接口。GLM 使用智谱 AI 平台 OpenAI 兼容接口。"
            "Ollama 模型列表通过本机 /api/tags 获取；GLM 提供模型建议，填写 Key 后可获取服务端列表。"
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

    def _save_provider_config(self, provider: str) -> None:
        """Save the current values for the given provider to the per-provider cache.

        This cache persists across provider switches so that users can switch
        back to OpenAI and see their previous OpenAI settings (URL, model,
        API key) instead of OpenAI's default values.
        """

        config = {
            "base_url": self.agent_base_url_edit.text().strip(),
            "model": self.agent_model_edit.currentText().strip(),
            "api_key": self.agent_api_key_edit.text().strip(),
        }
        self._provider_config[provider] = config

    def _load_provider_config(self, provider: str) -> None:
        """Restore this provider's persisted or newly edited session values."""

        config = self._provider_config[provider]
        self.agent_base_url_edit.setText(config["base_url"])
        self.agent_model_edit.setCurrentText(config["model"])
        # Always load from persisted config (session or disk)
        self.agent_api_key_edit.setText(config.get("api_key", ""))

    def _update_agent_provider_defaults(self) -> None:
        """Save current provider config, restore target provider config, and fetch models if needed."""

        target_provider = str(self.agent_provider_edit.currentData())
        if target_provider == self._agent_provider:
            return
        logger.info("User changed Agent provider from %s to %s", self._agent_provider, target_provider)
        self._save_provider_config(self._agent_provider)
        self._load_provider_config(target_provider)
        self._agent_provider = target_provider
        self._set_model_options(GLM_KNOWN_MODELS if target_provider == "glm" else [])
        self.model_status_label.setText("可选择建议模型，或输入自己的模型名称" if target_provider == "glm" else "")

        # Fetch models if Ollama or GLM is selected.
        if target_provider in ("ollama", "glm"):
            self._refresh_agent_models()

    def _refresh_agent_models(self) -> None:
        """Fetch the selected provider's models without blocking the dialog."""

        provider = str(self.agent_provider_edit.currentData())
        if provider not in ("ollama", "glm"):
            return
        if self._model_thread is not None and self._model_thread.isRunning():
            self._model_refresh_pending = True
            return
        base_url = self.agent_base_url_edit.text().strip()
        key = self.agent_api_key_edit.text().strip()
        if provider == "glm":
            key = key or os.environ.get("GLM_API_KEY", "")
        if provider == "glm" and not key:
            logger.debug("GLM model suggestions used because no API key is configured")
            self._set_model_options(GLM_KNOWN_MODELS)
            return
        logger.info("User requested Agent model list provider=%s", provider)
        self.model_status_label.setText("正在获取模型列表…")
        thread = _ModelFetchThread(base_url, key, provider, QApplication.instance())
        thread.completed.connect(self._on_agent_models_fetched)
        thread.finished.connect(self._on_model_thread_finished)
        thread.finished.connect(thread.deleteLater)
        self._model_thread = thread
        thread.start()

    def _on_agent_models_fetched(self, models: object, error: str) -> None:
        """Replace the combo box entries with detected models, preserving user input."""

        thread = self.sender()
        if (thread is not self._model_thread or
            thread.provider != str(self.agent_provider_edit.currentData()) or
            thread.base_url != self.agent_base_url_edit.text().strip() or
            thread.api_key != (self.agent_api_key_edit.text().strip() or
                               (os.environ.get("GLM_API_KEY", "") if thread.provider == "glm" else ""))):
            return
        if error:
            logger.warning("Agent model list failed provider=%s response_chars=%d", thread.provider, len(error))
            self.model_status_label.setText("无法获取模型列表；可直接输入模型名称")
            return
        if not isinstance(models, list) or not models:
            logger.warning("Agent model list empty provider=%s", thread.provider)
            self.model_status_label.setText("服务端未返回模型；可直接输入模型名称")
            return
        logger.info("Agent model list loaded provider=%s count=%d", thread.provider, len(models))
        self._set_model_options([str(model) for model in models])
        self.model_status_label.setText(f"已获取 {len(models)} 个模型")

    def _set_model_options(self, names: list[str]) -> None:
        """Update suggestions without replacing a custom model name."""

        combo = self.agent_model_edit
        current_text = combo.currentText().strip()
        combo.blockSignals(True)
        try:
            combo.clear()
            combo.addItems(names)
            combo.setCurrentText(current_text)
        finally:
            combo.blockSignals(False)

    def _on_model_thread_finished(self) -> None:
        thread = self.sender()
        if thread is self._model_thread:
            self._model_thread = None
            if self._model_refresh_pending:
                self._model_refresh_pending = False
                self._refresh_agent_models()

    def _save(self) -> None:
        values = {key: edit.keySequence().toString() for key, edit in self.shortcut_edits.items()}
        configured: dict[str, str] = {}
        for key, sequence in values.items():
            normalized = QKeySequence(sequence).toString()
            if not normalized:
                continue
            previous = configured.get(normalized)
            if previous is not None:
                logger.warning("Settings save rejected duplicate shortcuts first=%s second=%s", previous, key)
                QMessageBox.warning(
                    self,
                    "快捷键重复",
                    f"“{SHORTCUT_LABELS[previous]}”和“{SHORTCUT_LABELS[key]}”使用了相同快捷键。",
                )
                return
            configured[normalized] = key
        values["item_name_max_length"] = str(self.item_name_length_edit.value())
        values["drag_export_retention_minutes"] = str(self.drag_retention_edit.value())
        self._save_provider_config(self._agent_provider)
        values["agent_provider"] = str(self.agent_provider_edit.currentData())
        for provider, config in self._provider_config.items():
            values[f"agent_{provider}_base_url"] = config["base_url"]
            values[f"agent_{provider}_model"] = config["model"]
            values[f"agent_{provider}_api_key"] = config["api_key"]
        current = self._provider_config[self._agent_provider]
        values["agent_base_url"] = current["base_url"]
        values["agent_model"] = current["model"]
        values["agent_api_key"] = current["api_key"]
        try:
            self.service.save_settings(values)
        except StorageError as exc:
            logger.warning("Settings save failed error=%s", type(exc).__name__)
            QMessageBox.critical(self, "保存设置失败", str(exc))
            return
        logger.info("User saved settings provider=%s shortcut_count=%d", self._agent_provider, len(configured))
        self.api_key_values = {name: config["api_key"] for name, config in self._provider_config.items()}
        self.api_key_value = current["api_key"]
        self.accept()
