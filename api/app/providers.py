from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from typing import Any, AsyncIterator
from urllib.parse import urlsplit, urlunsplit

import httpx

from .db import decrypt_secret, encrypt_secret, fetchall, fetchone, json_dump, now, execute


PRESETS = [
    {"id": "openrouter", "name": "OpenRouter", "kind": "openai", "base_url": "https://openrouter.ai/api/v1", "key_required": True},
    {"id": "groq", "name": "Groq", "kind": "openai", "base_url": "https://api.groq.com/openai/v1", "key_required": True},
    {"id": "opencode", "name": "OpenCode Zen", "kind": "openai", "base_url": "https://opencode.ai/zen/v1", "key_required": False},
    {"id": "gemini", "name": "Google Gemini", "kind": "openai", "base_url": "https://generativelanguage.googleapis.com/v1beta/openai", "key_required": True},
    {"id": "ollama", "name": "Ollama", "kind": "ollama", "base_url": "http://host.docker.internal:11434", "key_required": False},
    {"id": "qwen", "name": "Qwen / DashScope", "kind": "openai", "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1", "key_required": True},
    {"id": "claude", "name": "Anthropic Claude", "kind": "anthropic", "base_url": "https://api.anthropic.com", "key_required": True},
]


@dataclass
class ProviderChunk:
    text: str = ""
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    done: bool = False


PROXY_HOSTNAME = os.getenv("PROXY_HOSTNAME", "").strip()
SUPPORTED_PROXY_SCHEMES = {"http", "https", "socks5", "socks5h"}


class ProviderError(RuntimeError):
    def __init__(self, message: str, status_code: int | None = None):
        self.status_code = status_code
        super().__init__(message)


def seed_presets() -> None:
    for item in PRESETS:
        execute(
            "INSERT OR IGNORE INTO providers(id,name,kind,base_url,enabled,created_at) VALUES (?,?,?,?,1,?)",
            (item["id"], item["name"], item["kind"], item["base_url"], now()),
        )


def _stored_proxy(row: dict[str, Any]) -> str | None:
    stored = row.get("proxy_url")
    if not stored:
        return None
    return decrypt_secret(stored) or str(stored)


def _mask_proxy(value: str | None) -> str | None:
    if not value:
        return None
    parsed = urlsplit(value)
    host = parsed.hostname or ""
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    authority = host
    if parsed.port:
        authority = f"{authority}:{parsed.port}"
    return urlunsplit((parsed.scheme, authority, "", "", ""))


def provider_rows() -> list[dict[str, Any]]:
    rows = fetchall("SELECT id,name,kind,base_url,proxy_url,enabled,last_status,last_checked FROM providers ORDER BY name")
    for row in rows:
        row["enabled"] = bool(row["enabled"])
        secret_row = fetchone("SELECT api_key FROM providers WHERE id=?", (row["id"],)) or {}
        proxy = _stored_proxy(row)
        row["key_configured"] = bool(secret_row.get("api_key"))
        row["proxy_configured"] = bool(proxy)
        row["proxy_hint"] = _mask_proxy(proxy)
        row["proxy_url"] = None
    return rows


def provider_row(provider_id: str) -> dict[str, Any]:
    row = fetchone("SELECT * FROM providers WHERE id=?", (provider_id,))
    if not row:
        raise ProviderError(f"Провайдер не найден: {provider_id}")
    row["proxy_url"] = _stored_proxy(row)
    return row


def _api_key(row: dict[str, Any]) -> str | None:
    key = decrypt_secret(row.get("api_key"))
    if key:
        return key
    if row["id"] == "opencode":
        return "public"
    return None


def save_provider(provider_id: str, payload: dict[str, Any]) -> None:
    row = provider_row(provider_id)
    values: list[Any] = []
    assignments: list[str] = []
    if "name" in payload:
        assignments.append("name=?")
        values.append(str(payload["name"]).strip() or row["name"])
    if "base_url" in payload:
        assignments.append("base_url=?")
        values.append(str(payload["base_url"]).strip().rstrip("/"))
    if "proxy_url" in payload:
        assignments.append("proxy_url=?")
        values.append(encrypt_secret(normalize_proxy_url(payload["proxy_url"])))
    if "enabled" in payload:
        assignments.append("enabled=?")
        values.append(1 if payload["enabled"] else 0)
    if payload.get("api_key") is not None:
        assignments.append("api_key=?")
        values.append(encrypt_secret(str(payload["api_key"]).strip()) if str(payload["api_key"]).strip() else None)
    if assignments:
        values.append(provider_id)
        execute(f"UPDATE providers SET {', '.join(assignments)} WHERE id=?", tuple(values))


def _headers(row: dict[str, Any]) -> dict[str, str]:
    key = _api_key(row)
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    if row["id"] == "openrouter":
        headers["HTTP-Referer"] = "https://github.com/Quadrotez/uranus-ai"
        headers["X-Title"] = "Uranus-AI"
    return headers


def normalize_proxy_url(value: str | None) -> str | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    if "://" not in raw:
        port = raw.rsplit(":", 1)[-1]
        scheme = "socks5" if port in {"9050", "9150"} else "http"
        raw = f"{scheme}://{raw}"
    parsed = urlsplit(raw)
    if parsed.scheme.lower() not in SUPPORTED_PROXY_SCHEMES:
        raise ProviderError("Прокси должен использовать http://, https://, socks5:// или socks5h://")
    if not parsed.hostname or parsed.port is None:
        raise ProviderError("Прокси должен содержать hostname и port, например socks5://127.0.0.1:9050")
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise ProviderError("URL прокси не должен содержать path, query или fragment")
    return urlunsplit((parsed.scheme.lower(), parsed.netloc, "", "", ""))


def _proxy(row: dict[str, Any]) -> str | None:
    value = normalize_proxy_url(row.get("proxy_url"))
    if not value:
        return None
    if not PROXY_HOSTNAME:
        return value
    parsed = urlsplit(value)
    if parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        return value
    host = PROXY_HOSTNAME
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    credentials = f"{parsed.netloc.rsplit('@', 1)[0]}@" if "@" in parsed.netloc else ""
    netloc = f"{credentials}{host}:{parsed.port}"
    return urlunsplit((parsed.scheme, netloc, "", "", ""))


def _ensure_configured(row: dict[str, Any]) -> None:
    if not bool(row["enabled"]):
        raise ProviderError(f"Провайдер {row['name']} отключён в админке")
    if row["kind"] != "ollama" and not _api_key(row):
        raise ProviderError(f"API-ключ провайдера {row['name']} не настроен")


def _request_timeout() -> httpx.Timeout:
    return httpx.Timeout(connect=15.0, read=None, write=30.0, pool=30.0)


async def list_models(provider_id: str) -> list[dict[str, Any]]:
    row = provider_row(provider_id)
    _ensure_configured(row)
    base = row["base_url"].rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=20.0, proxy=_proxy(row)) as client:
            if row["kind"] == "ollama":
                response = await client.get(f"{base}/api/tags", headers=_headers(row))
                response.raise_for_status()
                return [{"id": m.get("name"), "name": m.get("name"), "provider": provider_id} for m in response.json().get("models", [])]
            if row["kind"] == "anthropic":
                return [
                    {"id": "claude-3-5-haiku-latest", "name": "Claude 3.5 Haiku", "provider": provider_id},
                    {"id": "claude-3-7-sonnet-latest", "name": "Claude 3.7 Sonnet", "provider": provider_id},
                ]
            response = await client.get(f"{base}/models", headers=_headers(row))
            response.raise_for_status()
            data = response.json()
            return [
                {"id": item.get("id"), "name": item.get("name") or item.get("id"), "provider": provider_id, "context_length": item.get("context_length"), "pricing": item.get("pricing")}
                for item in data.get("data", []) if item.get("id")
            ]
    except httpx.HTTPStatusError as exc:
        raise ProviderError(f"{row['name']} /models: HTTP {exc.response.status_code}", exc.response.status_code) from exc
    except (httpx.HTTPError, ValueError) as exc:
        raise ProviderError(f"{row['name']} /models: {exc}") from exc


def _openai_payload(model: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None, settings: dict[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "stream": True,
        "temperature": settings.get("temperature", 0.2),
        "top_p": settings.get("top_p", 0.9),
        "max_tokens": settings.get("max_tokens", 2048),
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"
    return payload


def _anthropic_messages(messages: list[dict[str, Any]]) -> tuple[str | None, list[dict[str, Any]]]:
    system = None
    result: list[dict[str, Any]] = []
    for message in messages:
        role = message.get("role")
        if role == "system":
            system = str(message.get("content") or "")
        elif role == "assistant":
            blocks: list[dict[str, Any]] = []
            if message.get("content"):
                blocks.append({"type": "text", "text": message["content"]})
            for call in message.get("tool_calls") or []:
                function = call.get("function") or {}
                try:
                    arguments = json.loads(function.get("arguments") or "{}")
                except json.JSONDecodeError:
                    arguments = {}
                blocks.append({"type": "tool_use", "id": call.get("id", ""), "name": function.get("name", ""), "input": arguments})
            result.append({"role": "assistant", "content": blocks or ""})
        elif role == "user":
            result.append({"role": "user", "content": message.get("content") or ""})
        elif role == "tool":
            result.append({"role": "user", "content": [{"type": "tool_result", "tool_use_id": message.get("tool_call_id", ""), "content": message.get("content") or ""}]})
    return system, result


def _anthropic_tools(tools: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    result = []
    for tool in tools or []:
        fn = tool.get("function", {})
        result.append({"name": fn.get("name"), "description": fn.get("description", ""), "input_schema": fn.get("parameters", {"type": "object", "properties": {}})})
    return result


def _settings() -> dict[str, Any]:
    rows = fetchall("SELECT key,value FROM settings WHERE key IN ('temperature','top_p','max_tokens')")
    values = {row["key"]: row["value"] for row in rows}
    try:
        return {"temperature": float(values.get("temperature", 0.2)), "top_p": float(values.get("top_p", 0.9)), "max_tokens": max(128, int(values.get("max_tokens", 2048)))}
    except (TypeError, ValueError):
        return {"temperature": 0.2, "top_p": 0.9, "max_tokens": 2048}


async def chat_stream(provider_id: str, model: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None) -> AsyncIterator[ProviderChunk]:
    row = provider_row(provider_id)
    _ensure_configured(row)
    settings = _settings()
    base = row["base_url"].rstrip("/")
    headers = _headers(row)
    text = ""
    buffers: dict[int, dict[str, str]] = {}

    async with httpx.AsyncClient(timeout=_request_timeout(), proxy=_proxy(row)) as client:
        if row["kind"] == "ollama":
            payload = {"model": model, "messages": messages, "stream": True, "options": {"temperature": settings["temperature"], "top_p": settings["top_p"], "num_predict": settings["max_tokens"]}}
            if tools:
                payload["tools"] = tools
            response = client.stream("POST", f"{base}/api/chat", json=payload, headers=headers)
        elif row["kind"] == "anthropic":
            system, anthro_messages = _anthropic_messages(messages)
            payload = {"model": model, "messages": anthro_messages, "max_tokens": settings["max_tokens"], "stream": True}
            if system:
                payload["system"] = system
            anthro_tools = _anthropic_tools(tools)
            if anthro_tools:
                payload["tools"] = anthro_tools
            headers = {"Content-Type": "application/json", "x-api-key": _api_key(row) or "", "anthropic-version": "2023-06-01"}
            response = client.stream("POST", f"{base}/v1/messages", json=payload, headers=headers)
        else:
            response = client.stream("POST", f"{base}/chat/completions", json=_openai_payload(model, messages, tools, settings), headers=headers)

        async with response as response:
            if response.status_code >= 400:
                body = (await response.aread()).decode(errors="replace")[:1000]
                raise ProviderError(f"{row['name']} вернул HTTP {response.status_code}: {body}", response.status_code)
            async for raw_line in response.aiter_lines():
                line = raw_line.strip()
                if not line:
                    continue
                if row["kind"] == "anthropic":
                    if not line.startswith("data:"):
                        continue
                    try:
                        event = json.loads(line[5:].strip())
                    except json.JSONDecodeError:
                        continue
                    event_type = event.get("type")
                    if event_type == "content_block_start":
                        block = event.get("content_block", {})
                        if block.get("type") == "tool_use":
                            index = int(event.get("index", len(buffers)))
                            buffers[index] = {"id": str(block.get("id", "")), "name": str(block.get("name", "")), "arguments": ""}
                    elif event_type == "content_block_delta":
                        delta = event.get("delta", {})
                        if delta.get("type") == "text_delta" and delta.get("text"):
                            text += delta["text"]
                            yield ProviderChunk(text=delta["text"])
                        elif delta.get("type") == "input_json_delta":
                            index = int(event.get("index", 0))
                            buffers.setdefault(index, {"id": "", "name": "", "arguments": ""})["arguments"] += delta.get("partial_json", "")
                    continue

                if line.startswith("data:"):
                    line = line[5:].strip()
                if line == "[DONE]":
                    break
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if row["kind"] == "ollama":
                    piece = ((event.get("message") or {}).get("content") or "")
                    if piece:
                        text += piece
                        yield ProviderChunk(text=piece)
                    for tool in (event.get("message") or {}).get("tool_calls") or []:
                        fn = tool.get("function") or {}
                        buffers[len(buffers)] = {"id": str(tool.get("id") or f"ollama-{len(buffers)}"), "name": str(fn.get("name", "")), "arguments": json_dump(fn.get("arguments") or {})}
                    continue
                choice = (event.get("choices") or [{}])[0]
                delta = choice.get("delta") or {}
                piece = delta.get("content")
                if piece:
                    text += piece
                    yield ProviderChunk(text=piece)
                for call in delta.get("tool_calls") or []:
                    index = int(call.get("index", 0))
                    buffer = buffers.setdefault(index, {"id": "", "name": "", "arguments": ""})
                    if call.get("id"):
                        buffer["id"] = call["id"]
                    function = call.get("function") or {}
                    if function.get("name"):
                        buffer["name"] = function["name"]
                    buffer["arguments"] += function.get("arguments") or ""

    tool_calls = []
    for index in sorted(buffers):
        buffer = buffers[index]
        try:
            args = json.loads(buffer["arguments"] or "{}")
        except json.JSONDecodeError:
            args = {"_raw": buffer["arguments"]}
        if buffer["name"]:
            tool_calls.append({"id": buffer["id"] or f"call-{index}", "name": buffer["name"], "arguments": args})
    yield ProviderChunk(text=text, tool_calls=tool_calls, done=True)


async def test_provider(provider_id: str, model: str | None = None) -> dict[str, Any]:
    row = provider_row(provider_id)
    try:
        models = await list_models(provider_id)
        selected = model or (models[0]["id"] if models else None)
        if not selected:
            raise ProviderError("Модель не найдена")
        response_text = ""
        async for chunk in chat_stream(provider_id, selected, [{"role": "user", "content": "Reply with exactly: Uranus-AI provider check OK"}], None):
            response_text += chunk.text
            if chunk.done:
                break
        execute("UPDATE providers SET last_status=?,last_checked=? WHERE id=?", ("ok", now(), provider_id))
        return {"ok": True, "model": selected, "text": response_text[:500]}
    except Exception as exc:
        execute("UPDATE providers SET last_status=?,last_checked=? WHERE id=?", (f"error: {exc}", now(), provider_id))
        raise
