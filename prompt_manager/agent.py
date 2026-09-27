"""OpenAI-compatible chat transport and bounded tool definitions for the Agent."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any


PROVIDER_DEFAULTS: dict[str, tuple[str, str]] = {
    "openai": ("https://api.openai.com/v1", "gpt-4o-mini"),
    "ollama": ("http://localhost:11434/v1", "qwen2.5:7b"),
    "gemini": ("https://generativelanguage.googleapis.com/v1beta/openai/", "gemini-2.0-flash"),
}
MAX_RESPONSE_BYTES = 4 * 1024 * 1024
OLLAMA_MODEL_LIST_TIMEOUT = 10.0

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
) -> AgentResponse:
    """Send a chat completion request to an OpenAI-compatible provider.

    :param base_url: Provider base URL, with or without a trailing ``/v1``.
    :param model: Provider model identifier.
    :param api_key: Session key; may be empty for local Ollama servers.
    :param messages: OpenAI chat messages including any prior tool results.
    :param timeout: Maximum time to wait for the provider response.
    :return: Assistant text and validated-shape tool call records.
    :raises AgentRequestError: If the endpoint, response, or HTTP request fails.
    """

    root = base_url.strip().rstrip("/")
    if not root.startswith(("http://", "https://")):
        raise AgentRequestError("服务地址必须以 http:// 或 https:// 开头")
    if not model.strip():
        raise AgentRequestError("请在设置中填写 Agent 模型名称")
    endpoint = root if root.endswith("/chat/completions") else f"{root}/chat/completions"
    payload = json.dumps({"model": model.strip(), "messages": messages, "tools": AGENT_TOOLS, "tool_choice": "auto"}).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    request = urllib.request.Request(endpoint, data=payload, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read(MAX_RESPONSE_BYTES + 1)
        if len(body) > MAX_RESPONSE_BYTES:
            raise AgentRequestError("Agent 响应超过 4 MiB 限制")
        data = json.loads(body.decode("utf-8"))
        choice = data["choices"][0]["message"]
        calls = choice.get("tool_calls") or []
        if not isinstance(calls, list):
            raise ValueError("tool_calls 格式无效")
        return AgentResponse(str(choice.get("content") or ""), calls)
    except urllib.error.HTTPError as exc:
        detail = exc.read(2048).decode("utf-8", errors="replace")
        raise AgentRequestError(f"模型服务返回 HTTP {exc.code}: {detail}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise AgentRequestError(f"无法连接模型服务: {exc}") from exc
    except (UnicodeDecodeError, json.JSONDecodeError, KeyError, IndexError, TypeError, ValueError) as exc:
        raise AgentRequestError(f"模型服务返回的数据格式无效: {exc}") from exc


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