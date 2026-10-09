"""OpenAI-compatible chat transport and bounded tool definitions for the Agent."""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from dataclasses import dataclass
from collections.abc import Callable, Mapping
from typing import Any

logger = logging.getLogger(__name__)

PROVIDER_DEFAULTS: dict[str, tuple[str, str]] = {
    "openai": ("https://api.openai.com/v1", "gpt-4o-mini"),
    "ollama": ("http://localhost:11434/v1", "qwen2.5:7b"),
    "gemini": ("https://generativelanguage.googleapis.com/v1beta/openai/", "gemini-2.0-flash"),
    "glm": ("https://open.bigmodel.cn/api/paas/v4", "glm-4-flash"),
}
MAX_RESPONSE_BYTES = 4 * 1024 * 1024
OLLAMA_MODEL_LIST_TIMEOUT = 10.0
GLM_MODEL_LIST_TIMEOUT = 10.0

GLM_KNOWN_MODELS: list[str] = [
    # Text/chat suggestions from the platform model overview; availability
    # depends on the account and can be overridden by typing a model ID.
    "glm-5.3",
    "glm-5.3-flash",
    "glm-5.2",
    "glm-5.1",
    "glm-5",
    "glm-4.7",
    "glm-4.7-flash",
    "glm-4.6",
    "glm-4.5-air",
    "glm-4.5-flash",
    # Keep the old default selectable for existing installations.
    "glm-4-flash",
]


def provider_config(settings: Mapping[str, str], provider: str) -> tuple[str, str]:
    """Read one provider's URL and model, including legacy active settings.

    Provider-specific values take precedence. Existing installations only
    have the shared keys, which belong to the previously selected provider.
    """

    default_url, default_model = PROVIDER_DEFAULTS[provider]
    legacy = settings.get("agent_provider", "openai") == provider
    return (
        settings.get(f"agent_{provider}_base_url", settings.get("agent_base_url", default_url) if legacy else default_url),
        settings.get(f"agent_{provider}_model", settings.get("agent_model", default_model) if legacy else default_model),
    )

AGENT_TOOLS: list[dict[str, Any]] = [
    {"type": "function", "function": {"name": "list_prompts", "description": "List saved prompts, optionally filtered by kind.", "parameters": {"type": "object", "properties": {"kind": {"type": "string", "enum": ["prompt", "fixed"]}}, "additionalProperties": False}}},
    {"type": "function", "function": {"name": "read_prompt", "description": "Read one saved prompt by its numeric ID.", "parameters": {"type": "object", "properties": {"prompt_id": {"type": "integer"}}, "required": ["prompt_id"], "additionalProperties": False}}},
    {"type": "function", "function": {"name": "create_prompt", "description": "Create a prompt or fixed preset.", "parameters": {"type": "object", "properties": {"name": {"type": "string"}, "content": {"type": "string"}, "kind": {"type": "string", "enum": ["prompt", "fixed"]}}, "required": ["name", "content", "kind"], "additionalProperties": False}}},
    {"type": "function", "function": {"name": "update_prompt", "description": "Update a saved prompt by its numeric ID.", "parameters": {"type": "object", "properties": {"prompt_id": {"type": "integer"}, "name": {"type": "string"}, "content": {"type": "string"}, "kind": {"type": "string", "enum": ["prompt", "fixed"]}}, "required": ["prompt_id", "name", "content", "kind"], "additionalProperties": False}}},
    {"type": "function", "function": {"name": "delete_prompt", "description": "Permanently delete a prompt by ID and its remembered placeholder values. Only do this when the user explicitly asks for deletion.", "parameters": {"type": "object", "properties": {"prompt_id": {"type": "integer"}}, "required": ["prompt_id"], "additionalProperties": False}}},
    {"type": "function", "function": {"name": "select_prompt", "description": "Show a saved prompt in the main editor by numeric ID.", "parameters": {"type": "object", "properties": {"prompt_id": {"type": "integer"}}, "required": ["prompt_id"], "additionalProperties": False}}},
    {"type": "function", "function": {"name": "list_groups", "description": "List first-level groups for one prompt kind.", "parameters": {"type": "object", "properties": {"kind": {"type": "string", "enum": ["prompt", "fixed"]}}, "required": ["kind"], "additionalProperties": False}}},
    {"type": "function", "function": {"name": "create_group", "description": "Create a first-level group for one prompt kind. Use this before assigning a prompt to a new group.", "parameters": {"type": "object", "properties": {"name": {"type": "string"}, "kind": {"type": "string", "enum": ["prompt", "fixed"]}}, "required": ["name", "kind"], "additionalProperties": False}}},
    {"type": "function", "function": {"name": "set_prompt_group", "description": "Move a saved prompt into an existing first-level group of the same kind.", "parameters": {"type": "object", "properties": {"prompt_id": {"type": "integer"}, "group_id": {"type": "integer"}}, "required": ["prompt_id", "group_id"], "additionalProperties": False}}},
    {"type": "function", "function": {"name": "clear_prompt_group", "description": "Remove a saved prompt from its first-level group.", "parameters": {"type": "object", "properties": {"prompt_id": {"type": "integer"}}, "required": ["prompt_id"], "additionalProperties": False}}},
]


@dataclass(frozen=True, slots=True)
class AgentResponse:
    """One assistant response, either text or tool requests."""

    content: str
    tool_calls: list[dict[str, Any]]


class AgentRequestError(RuntimeError):
    """Raised when an OpenAI-compatible Agent request cannot be completed."""


def request_completion(
    base_url: str,
    model: str,
    api_key: str,
    messages: list[dict[str, Any]],
    *,
    timeout: float = 90,
    on_delta: Callable[[str], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
) -> AgentResponse:
    """Stream a chat completion, returning complete text and tool calls.

    :param base_url: Provider base URL, with or without a trailing ``/v1``.
    :param model: Provider model identifier.
    :param api_key: Session key; may be empty for local Ollama servers.
    :param messages: OpenAI chat messages including any prior tool results.
    :param timeout: Maximum time to wait for the provider response.
    :param on_delta: Optional callback for each text fragment, on the calling thread.
    :param should_cancel: Optional check between stream events to abandon a request.
    :return: Assistant text and validated-shape tool call records.
    :raises AgentRequestError: If the endpoint, response, or HTTP request fails.
    """

    root = base_url.strip().rstrip("/")
    if not root.startswith(("http://", "https://")):
        raise AgentRequestError("服务地址必须以 http:// 或 https:// 开头")
    if not model.strip():
        raise AgentRequestError("请在设置中填写 Agent 模型名称")
    endpoint = root if root.endswith("/chat/completions") else f"{root}/chat/completions"
    payload = json.dumps({"model": model.strip(), "messages": messages, "tools": AGENT_TOOLS,
                          "tool_choice": "auto", "stream": True}).encode("utf-8")
    headers = {"Content-Type": "application/json", "Accept": "text/event-stream, application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    request = urllib.request.Request(endpoint, data=payload, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            content_type = response.headers.get("Content-Type", "").lower()
            if "text/event-stream" in content_type:
                return _read_completion_stream(response, on_delta, should_cancel)
            body = response.read(MAX_RESPONSE_BYTES + 1)
            if len(body) > MAX_RESPONSE_BYTES:
                raise AgentRequestError("Agent 响应超过 4 MiB 限制")
            data = json.loads(body.decode("utf-8"))
            choice = data["choices"][0]["message"]
            calls = choice.get("tool_calls") or []
            if not isinstance(calls, list):
                raise ValueError("tool_calls 格式无效")
            content = choice.get("content") or ""
            if not isinstance(content, str):
                raise ValueError("content 格式无效")
            if content and on_delta and not (should_cancel and should_cancel()):
                on_delta(content)
            return AgentResponse(content, calls)
    except urllib.error.HTTPError as exc:
        detail = exc.read(2048).decode("utf-8", errors="replace")
        raise AgentRequestError(f"模型服务返回 HTTP {exc.code}: {detail}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise AgentRequestError(f"无法连接模型服务: {exc}") from exc
    except (UnicodeDecodeError, json.JSONDecodeError, KeyError, IndexError, TypeError, ValueError) as exc:
        raise AgentRequestError(f"模型服务返回的数据格式无效: {exc}") from exc


def _read_completion_stream(
    response: Any,
    on_delta: Callable[[str], None] | None,
    should_cancel: Callable[[], bool] | None,
) -> AgentResponse:
    """Read bounded SSE frames and assemble indexed tool-call fragments."""

    text_parts: list[str] = []
    calls: dict[int, dict[str, Any]] = {}
    data_lines: list[str] = []
    total_bytes = 0
    done = False

    def consume_frame() -> bool:
        if not data_lines:
            return False
        payload = "\n".join(data_lines)
        data_lines.clear()
        if payload.strip() == "[DONE]":
            return True
        chunk = json.loads(payload)
        if not isinstance(chunk, dict):
            raise ValueError("SSE 事件不是 JSON 对象")
        if "error" in chunk:
            error = chunk["error"]
            detail = error.get("message", "未知错误") if isinstance(error, dict) else str(error)
            raise AgentRequestError(f"模型服务流式请求失败: {detail}")
        choices = chunk.get("choices") or []
        if not isinstance(choices, list):
            raise ValueError("choices 格式无效")
        if not choices:
            return False  # Usage-only final event.
        choice = choices[0]
        if not isinstance(choice, dict):
            raise ValueError("choice 格式无效")
        delta = choice.get("delta") or {}
        if not isinstance(delta, dict):
            raise ValueError("delta 格式无效")
        fragment = delta.get("content")
        if fragment is not None:
            if not isinstance(fragment, str):
                raise ValueError("content 增量格式无效")
            text_parts.append(fragment)
            if fragment and on_delta:
                on_delta(fragment)
        fragments = delta.get("tool_calls") or []
        if not isinstance(fragments, list):
            raise ValueError("tool_calls 增量格式无效")
        for position, part in enumerate(fragments):
            if not isinstance(part, dict):
                raise ValueError("tool_calls 增量格式无效")
            index = part.get("index", position)
            if type(index) is not int or not 0 <= index < 64:
                raise ValueError("tool_calls 索引无效")
            call = calls.setdefault(index, {"id": "", "type": "function", "function": {"name": "", "arguments": ""}})
            for field in ("id", "type"):
                value = part.get(field)
                if value is not None:
                    if not isinstance(value, str):
                        raise ValueError(f"tool_calls.{field} 格式无效")
                    if field == "type":
                        call[field] = value
                    else:
                        call[field] += value
            function = part.get("function") or {}
            if not isinstance(function, dict):
                raise ValueError("tool_calls.function 格式无效")
            for field in ("name", "arguments"):
                value = function.get(field)
                if value is not None:
                    if not isinstance(value, str):
                        raise ValueError(f"tool_calls.function.{field} 格式无效")
                    call["function"][field] += value
        return False

    while True:
        if should_cancel and should_cancel():
            raise AgentRequestError("请求已停止")
        line = response.readline(MAX_RESPONSE_BYTES + 1)
        if not line:
            break
        total_bytes += len(line)
        if total_bytes > MAX_RESPONSE_BYTES:
            raise AgentRequestError("Agent 响应超过 4 MiB 限制")
        decoded = line.decode("utf-8-sig").rstrip("\r\n")
        if not decoded:
            if consume_frame():
                done = True
                break
        elif decoded.startswith("data:"):
            data_lines.append(decoded[5:].lstrip(" "))
    if not done and data_lines:
        done = consume_frame()
    if not done:
        raise AgentRequestError("模型服务流式响应意外中断")
    ordered_calls = [calls[index] for index in sorted(calls)]
    for call in ordered_calls:
        if not call["id"] or call["type"] != "function" or not call["function"]["name"]:
            raise AgentRequestError("模型服务返回了不完整的工具调用")
        call["function"]["arguments"] = call["function"]["arguments"] or "{}"
    return AgentResponse("".join(text_parts), ordered_calls)


def fetch_ollama_models(base_url: str, *, timeout: float = OLLAMA_MODEL_LIST_TIMEOUT) -> list[str]:
    """Return the model names installed on a local Ollama server.

    Ollama exposes ``GET /api/tags`` on the server root, independently of the
    OpenAI-compatible ``/v1`` prefix used for chat completions.  A trailing
    ``/v1`` segment is therefore stripped before the request is issued.

    :param base_url: Ollama server address, with or without a ``/v1`` suffix.
    :param timeout: Maximum number of seconds to wait for the server response.
    :return: Model names in the server's reported order; empty when none exist.
    :raises AgentRequestError: If the address is invalid, the server cannot be
        reached, or the response is too large or not a valid Ollama payload.
    """

    root = base_url.strip().rstrip("/")
    if not root.startswith(("http://", "https://")):
        raise AgentRequestError("服务地址必须以 http:// 或 https:// 开头")
    if root.endswith("/v1"):
        root = root[: -len("/v1")]
    endpoint = f"{root}/api/tags"
    request = urllib.request.Request(endpoint, headers={"Accept": "application/json"}, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read(MAX_RESPONSE_BYTES + 1)
        if len(body) > MAX_RESPONSE_BYTES:
            raise AgentRequestError("Ollama 模型列表响应超过 4 MiB 限制")
        data = json.loads(body.decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read(2048).decode("utf-8", errors="replace")
        raise AgentRequestError(f"Ollama 返回 HTTP {exc.code}: {detail}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise AgentRequestError(f"无法连接 Ollama 服务: {exc}") from exc
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AgentRequestError(f"Ollama 返回的数据格式无效: {exc}") from exc

    entries = data.get("models") if isinstance(data, dict) else None
    if not isinstance(entries, list):
        raise AgentRequestError("Ollama 返回的数据缺少 models 列表")
    names: list[str] = []
    seen: set[str] = set()
    for entry in entries:
        if isinstance(entry, dict):
            raw_name = entry.get("name") or entry.get("model")
        elif isinstance(entry, str):
            raw_name = entry
        else:
            raw_name = None
        if not isinstance(raw_name, str):
            continue
        name = raw_name.strip()
        if name and name not in seen:
            seen.add(name)
            names.append(name)
    return names


def fetch_glm_models(
    base_url: str,
    api_key: str,
    *,
    timeout: float = GLM_MODEL_LIST_TIMEOUT,
) -> list[str]:
    """Return the model names available on a Zhipu AI (GLM) platform.

    Query ``GET /models`` with the session API key. Without a key or when the
    request fails, offer built-in suggestions; the user may also type a model.

    :param base_url: Zhipu AI base URL (e.g. ``https://open.bigmodel.cn/api/paas/v4``).
    :param api_key: Zhipu AI API key used for authentication.
    :param timeout: Maximum seconds to wait for the server response.
    :return: Server model IDs when available, otherwise built-in suggestions.
    :raises AgentRequestError: If the base URL is invalid.
    """

    root = base_url.strip().rstrip("/")
    if not root.startswith(("http://", "https://")):
        raise AgentRequestError("服务地址必须以 http:// 或 https:// 开头")
    if not api_key.strip():
        return list(GLM_KNOWN_MODELS)

    # Normalize the endpoint: the base URL typically already ends with
    # /api/paas/v4, but we tolerate variants.
    if root.endswith("/chat/completions"):
        root = root[: -len("/chat/completions")]
    endpoint = f"{root}/models"

    headers: dict[str, str] = {"Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    request = urllib.request.Request(endpoint, headers=headers, method="GET")
    remote_names: list[str] = []
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read(MAX_RESPONSE_BYTES + 1)
        if len(body) > MAX_RESPONSE_BYTES:
            raise AgentRequestError("GLM 模型列表响应超过 4 MiB 限制")
        data = json.loads(body.decode("utf-8"))
        # The Zhipu response wraps models under a "data" key, each entry
        # having an "id" field.  We also tolerate a flat list of strings
        # or a bare dict of name→info for robustness.
        entries: Any = None
        if isinstance(data, dict):
            entries = data.get("data") or data.get("models")
        if entries is None and isinstance(data, list):
            entries = data
        if isinstance(entries, list):
            for entry in entries:
                raw = entry.get("id") if isinstance(entry, dict) else (entry if isinstance(entry, str) else None)
                if isinstance(raw, str) and raw.strip():
                    remote_names.append(raw.strip())
    except urllib.error.HTTPError as exc:
        logger.debug("GLM model list request returned HTTP %d; falling back to built-in list", exc.code)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        logger.debug("GLM model list request failed: %s; falling back to built-in list", exc)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        logger.debug("GLM model list response invalid: %s; falling back to built-in list", exc)

    return list(dict.fromkeys(remote_names)) if remote_names else list(GLM_KNOWN_MODELS)
