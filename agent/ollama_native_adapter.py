"""OpenAI-client facade for Ollama's native ``/api/chat`` protocol.

The agent loop intentionally speaks one internal message/tool dialect.  This
adapter keeps that narrow waist intact while translating requests and responses
at the provider edge.  It is selected only for the first-class ``ollama``
provider; generic custom endpoints continue to use their declared wire format.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
from types import SimpleNamespace
import time
from typing import Any, Iterable, Iterator, Mapping, Sequence
from urllib.parse import urlsplit, urlunsplit


DEFAULT_OLLAMA_NATIVE_BASE_URL = "http://127.0.0.1:11434"
_MAX_RESPONSE_BYTES = 64 * 1024 * 1024
_NO_AUTH_MARKERS = frozenset({"", "no-key-required", "ollama", "ollama-local"})


class OllamaNativeError(RuntimeError):
    """Sanitized native-Ollama protocol or HTTP failure."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


def normalize_ollama_native_base_url(value: str) -> str:
    """Return an Ollama server root, accepting a pasted ``/v1`` URL."""

    candidate = str(value or "").strip() or DEFAULT_OLLAMA_NATIVE_BASE_URL
    parsed = urlsplit(candidate)
    if (
        parsed.scheme.lower() not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("invalid_ollama_native_base_url")
    path = (parsed.path or "").rstrip("/")
    if path.endswith("/v1"):
        path = path[:-3]
    return urlunsplit(
        (parsed.scheme.lower(), parsed.netloc, path.rstrip("/"), "", "")
    ).rstrip("/")


def _bare_model(value: Any) -> str:
    model = str(value or "").strip()
    if model.lower().startswith("ollama/"):
        return model.split("/", 1)[1]
    return model


def _json_arguments(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except (TypeError, ValueError):
            return {}
        if isinstance(decoded, Mapping):
            return dict(decoded)
    return {}


def _text_and_images(content: Any) -> tuple[str, list[str]]:
    if isinstance(content, str):
        return content, []
    if content is None:
        return "", []
    if not isinstance(content, Sequence) or isinstance(content, (bytes, bytearray)):
        return str(content), []

    text: list[str] = []
    images: list[str] = []
    for part in content:
        if not isinstance(part, Mapping):
            continue
        part_type = str(part.get("type") or "").strip().lower()
        if part_type in {"text", "input_text"}:
            value = part.get("text")
            if isinstance(value, str):
                text.append(value)
            continue
        if part_type not in {"image_url", "input_image"}:
            continue
        image_value = part.get("image_url")
        if isinstance(image_value, Mapping):
            image_value = image_value.get("url")
        if not isinstance(image_value, str):
            image_value = part.get("image") or part.get("url")
        if not isinstance(image_value, str) or not image_value.startswith("data:"):
            # The local adapter never dereferences remote image URLs.  Upstream
            # image routing is responsible for materializing approved content.
            continue
        try:
            _meta, encoded = image_value.split(",", 1)
            base64.b64decode(encoded, validate=True)
        except (ValueError, TypeError):
            continue
        images.append(encoded)
    return "\n".join(text), images


def convert_openai_messages_to_ollama(
    messages: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Convert persisted OpenAI-format history into native Ollama messages."""

    converted: list[dict[str, Any]] = []
    tool_names: dict[str, str] = {}
    for raw in messages:
        if not isinstance(raw, Mapping):
            continue
        role = str(raw.get("role") or "").strip().lower()
        if role == "developer":
            role = "system"
        if role not in {"system", "user", "assistant", "tool"}:
            continue
        content, images = _text_and_images(raw.get("content"))
        item: dict[str, Any] = {"role": role, "content": content}
        if images and role in {"user", "assistant"}:
            item["images"] = images

        if role == "assistant":
            thinking = raw.get("reasoning_content")
            if thinking is None:
                thinking = raw.get("reasoning")
            if isinstance(thinking, str) and thinking:
                item["thinking"] = thinking
            native_calls: list[dict[str, Any]] = []
            calls = raw.get("tool_calls")
            if isinstance(calls, Sequence) and not isinstance(calls, (str, bytes)):
                for index, call in enumerate(calls):
                    if not isinstance(call, Mapping):
                        continue
                    function = call.get("function")
                    if not isinstance(function, Mapping):
                        continue
                    name = str(function.get("name") or "").strip()
                    if not name:
                        continue
                    call_id = str(call.get("id") or "").strip()
                    if call_id:
                        tool_names[call_id] = name
                    native_calls.append(
                        {
                            "type": "function",
                            "function": {
                                "index": index,
                                "name": name,
                                "arguments": _json_arguments(function.get("arguments")),
                            },
                        }
                    )
            if native_calls:
                item["tool_calls"] = native_calls

        if role == "tool":
            tool_name = str(raw.get("tool_name") or raw.get("name") or "").strip()
            if not tool_name:
                tool_name = tool_names.get(str(raw.get("tool_call_id") or "").strip(), "")
            if not tool_name:
                raise ValueError("ollama_tool_result_missing_name")
            item["tool_name"] = tool_name

        converted.append(item)
    return converted


def _native_tools(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    result: list[dict[str, Any]] = []
    for tool in value:
        if not isinstance(tool, Mapping):
            continue
        function = tool.get("function")
        if not isinstance(function, Mapping):
            continue
        name = str(function.get("name") or "").strip()
        if not name:
            continue
        parameters = function.get("parameters")
        if not isinstance(parameters, Mapping):
            parameters = {"type": "object", "properties": {}}
        result.append(
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": str(function.get("description") or ""),
                    "parameters": dict(parameters),
                },
            }
        )
    return result


def build_ollama_native_payload(kwargs: Mapping[str, Any]) -> dict[str, Any]:
    """Translate ``chat.completions.create`` kwargs into ``/api/chat`` JSON."""

    model = _bare_model(kwargs.get("model"))
    if not model:
        raise ValueError("ollama_model_required")
    raw_messages = kwargs.get("messages")
    if not isinstance(raw_messages, Sequence) or isinstance(raw_messages, (str, bytes)):
        raise ValueError("ollama_messages_required")

    payload: dict[str, Any] = {
        "model": model,
        "messages": convert_openai_messages_to_ollama(raw_messages),
        "stream": bool(kwargs.get("stream", False)),
    }

    tool_choice = kwargs.get("tool_choice")
    tools = _native_tools(kwargs.get("tools"))
    if tool_choice != "none" and tools:
        payload["tools"] = tools

    options: dict[str, Any] = {}
    extra_body = kwargs.get("extra_body")
    if isinstance(extra_body, Mapping):
        raw_options = extra_body.get("options")
        if isinstance(raw_options, Mapping):
            options.update(dict(raw_options))
        if "think" in extra_body:
            payload["think"] = extra_body.get("think")
        if "keep_alive" in extra_body:
            payload["keep_alive"] = extra_body.get("keep_alive")
        if "format" in extra_body:
            payload["format"] = extra_body.get("format")

    max_tokens = kwargs.get("max_completion_tokens")
    if max_tokens is None:
        max_tokens = kwargs.get("max_tokens")
    if isinstance(max_tokens, int) and not isinstance(max_tokens, bool) and max_tokens > 0:
        options["num_predict"] = max_tokens
    for source, target in (
        ("temperature", "temperature"),
        ("top_p", "top_p"),
        ("seed", "seed"),
        ("stop", "stop"),
    ):
        if kwargs.get(source) is not None:
            options[target] = kwargs.get(source)
    if options:
        payload["options"] = options

    if "think" not in payload:
        effort = str(kwargs.get("reasoning_effort") or "").strip().lower()
        if effort == "none":
            payload["think"] = False
        elif effort in {"low", "medium", "high"}:
            payload["think"] = effort
        elif effort in {"xhigh", "max"}:
            payload["think"] = "high"

    response_format = kwargs.get("response_format")
    if "format" not in payload and isinstance(response_format, Mapping):
        format_type = response_format.get("type")
        if format_type == "json_object":
            payload["format"] = "json"
        elif format_type == "json_schema":
            schema_wrapper = response_format.get("json_schema")
            if isinstance(schema_wrapper, Mapping) and isinstance(
                schema_wrapper.get("schema"), Mapping
            ):
                payload["format"] = dict(schema_wrapper["schema"])

    return payload


def _tool_call_id(salt: str, index: int, name: str, arguments: str) -> str:
    material = f"{salt}\x00{index}\x00{name}\x00{arguments}".encode(
        "utf-8", errors="replace"
    )
    return "call_" + hashlib.sha256(material).hexdigest()[:24]


def _openai_tool_calls(value: Any, *, salt: str) -> list[SimpleNamespace] | None:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return None
    result: list[SimpleNamespace] = []
    for index, call in enumerate(value):
        if not isinstance(call, Mapping):
            continue
        function = call.get("function")
        if not isinstance(function, Mapping):
            continue
        name = str(function.get("name") or "").strip()
        if not name:
            continue
        arguments = json.dumps(
            _json_arguments(function.get("arguments")),
            separators=(",", ":"),
            ensure_ascii=False,
        )
        result.append(
            SimpleNamespace(
                index=index,
                id=_tool_call_id(salt, index, name, arguments),
                type="function",
                function=SimpleNamespace(name=name, arguments=arguments),
            )
        )
    return result or None


def _usage(value: Mapping[str, Any]) -> SimpleNamespace | None:
    prompt = value.get("prompt_eval_count")
    completion = value.get("eval_count")
    if not isinstance(prompt, int) and not isinstance(completion, int):
        return None
    prompt_tokens = prompt if isinstance(prompt, int) and prompt >= 0 else 0
    completion_tokens = completion if isinstance(completion, int) and completion >= 0 else 0
    return SimpleNamespace(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=prompt_tokens + completion_tokens,
    )


def _finish_reason(payload: Mapping[str, Any], *, has_tools: bool) -> str | None:
    if has_tools:
        return "tool_calls"
    if not payload.get("done"):
        return None
    reason = str(payload.get("done_reason") or "stop").strip().lower()
    if reason in {"length", "max_tokens"}:
        return "length"
    return "stop"


def _completion(payload: Mapping[str, Any], *, request_id: str) -> SimpleNamespace:
    message = payload.get("message")
    if not isinstance(message, Mapping):
        raise OllamaNativeError("Ollama returned an invalid chat response.")
    tool_calls = _openai_tool_calls(message.get("tool_calls"), salt=request_id)
    content = message.get("content")
    if not isinstance(content, str):
        content = ""
    thinking = message.get("thinking")
    if not isinstance(thinking, str):
        thinking = None
    normalized_message = SimpleNamespace(
        role="assistant",
        content=content,
        tool_calls=tool_calls,
        reasoning_content=thinking,
    )
    return SimpleNamespace(
        id=request_id,
        object="chat.completion",
        created=int(time.time()),
        model=str(payload.get("model") or ""),
        choices=[
            SimpleNamespace(
                index=0,
                message=normalized_message,
                finish_reason=_finish_reason(payload, has_tools=bool(tool_calls)),
                logprobs=None,
            )
        ],
        usage=_usage(payload),
    )


def _chunk(payload: Mapping[str, Any], *, request_id: str) -> SimpleNamespace:
    message = payload.get("message")
    if not isinstance(message, Mapping):
        message = {}
    tool_calls = _openai_tool_calls(message.get("tool_calls"), salt=request_id)
    content = message.get("content")
    thinking = message.get("thinking")
    delta = SimpleNamespace(
        role="assistant",
        content=content if isinstance(content, str) and content else None,
        reasoning_content=(
            thinking if isinstance(thinking, str) and thinking else None
        ),
        tool_calls=tool_calls,
    )
    return SimpleNamespace(
        id=request_id,
        object="chat.completion.chunk",
        created=int(time.time()),
        model=str(payload.get("model") or ""),
        choices=[
            SimpleNamespace(
                index=0,
                delta=delta,
                finish_reason=_finish_reason(payload, has_tools=bool(tool_calls)),
                logprobs=None,
            )
        ],
        usage=None,
    )


def _usage_chunk(payload: Mapping[str, Any], *, request_id: str) -> SimpleNamespace:
    return SimpleNamespace(
        id=request_id,
        object="chat.completion.chunk",
        created=int(time.time()),
        model=str(payload.get("model") or ""),
        choices=[],
        usage=_usage(payload),
    )


def _response_json(response: Any) -> Mapping[str, Any]:
    content = bytes(response.content)
    if len(content) > _MAX_RESPONSE_BYTES:
        raise OllamaNativeError("Ollama returned an oversized chat response.")
    try:
        payload = json.loads(content)
    except (TypeError, ValueError) as exc:
        raise OllamaNativeError("Ollama returned invalid JSON.") from exc
    if not isinstance(payload, Mapping):
        raise OllamaNativeError("Ollama returned an invalid chat response.")
    if payload.get("error"):
        raise OllamaNativeError("Ollama rejected the chat request.")
    return payload


class _OllamaStream(Iterator[SimpleNamespace]):
    def __init__(self, context: Any, response: Any, *, request_id: str) -> None:
        self._context = context
        self.response = response
        self._request_id = request_id
        self._closed = False
        self._iterator = self._iterate()

    def __iter__(self) -> "_OllamaStream":
        return self

    def __next__(self) -> SimpleNamespace:
        return next(self._iterator)

    def _iterate(self) -> Iterator[SimpleNamespace]:
        total = 0
        try:
            for line in self.response.iter_lines():
                if not line:
                    continue
                encoded = line.encode("utf-8", errors="replace")
                total += len(encoded)
                if total > _MAX_RESPONSE_BYTES:
                    raise OllamaNativeError("Ollama returned an oversized chat stream.")
                try:
                    payload = json.loads(line)
                except (TypeError, ValueError) as exc:
                    raise OllamaNativeError("Ollama returned invalid streaming JSON.") from exc
                if not isinstance(payload, Mapping):
                    raise OllamaNativeError("Ollama returned an invalid chat stream.")
                if payload.get("error"):
                    raise OllamaNativeError("Ollama rejected the chat request.")
                message = payload.get("message")
                has_delta = isinstance(message, Mapping) and any(
                    message.get(key) for key in ("content", "thinking", "tool_calls")
                )
                if has_delta or payload.get("done"):
                    yield _chunk(payload, request_id=self._request_id)
                if payload.get("done") and _usage(payload) is not None:
                    yield _usage_chunk(payload, request_id=self._request_id)
        finally:
            self.close()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._context.__exit__(None, None, None)


class _OllamaCompletions:
    def __init__(self, client: "OllamaNativeClient") -> None:
        self._client = client

    def create(self, **kwargs: Any) -> Any:
        return self._client._create(**kwargs)


class _OllamaChat:
    def __init__(self, client: "OllamaNativeClient") -> None:
        self.completions = _OllamaCompletions(client)


class OllamaNativeClient:
    """Small sync facade matching ``OpenAI.chat.completions``."""

    def __init__(
        self,
        *,
        api_key: str = "",
        base_url: str = DEFAULT_OLLAMA_NATIVE_BASE_URL,
        default_headers: Mapping[str, str] | None = None,
        timeout: Any = None,
        http_client: Any = None,
        **_ignored: Any,
    ) -> None:
        import httpx

        self.api_key = str(api_key or "")
        self.base_url = normalize_ollama_native_base_url(base_url)
        self._custom_headers = dict(default_headers or {})
        if self.api_key.strip().lower() not in _NO_AUTH_MARKERS and not any(
            key.lower() == "authorization" for key in self._custom_headers
        ):
            self._custom_headers["Authorization"] = f"Bearer {self.api_key.strip()}"
        self._client = http_client or httpx.Client(
            follow_redirects=False,
            trust_env=False,
            timeout=timeout,
        )
        self._owns_client = True
        self.chat = _OllamaChat(self)

    def is_closed(self) -> bool:
        return bool(getattr(self._client, "is_closed", False))

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def _create(self, **kwargs: Any) -> Any:
        payload = build_ollama_native_payload(kwargs)
        request_id = "chatcmpl-ollama-" + hashlib.sha256(
            f"{time.time_ns()}:{payload['model']}".encode("utf-8")
        ).hexdigest()[:24]
        endpoint = f"{self.base_url}/api/chat"
        timeout = kwargs.get("timeout")
        if payload.get("stream"):
            context = self._client.stream(
                "POST",
                endpoint,
                json=payload,
                headers=self._custom_headers or None,
                timeout=timeout,
                follow_redirects=False,
            )
            response = context.__enter__()
            try:
                if response.status_code >= 400:
                    raise OllamaNativeError(
                        "Ollama rejected the chat request.",
                        status_code=response.status_code,
                    )
            except Exception:
                context.__exit__(None, None, None)
                raise
            return _OllamaStream(context, response, request_id=request_id)

        response = self._client.post(
            endpoint,
            json=payload,
            headers=self._custom_headers or None,
            timeout=timeout,
            follow_redirects=False,
        )
        if response.status_code >= 400:
            raise OllamaNativeError(
                "Ollama rejected the chat request.", status_code=response.status_code
            )
        return _completion(_response_json(response), request_id=request_id)


_ASYNC_END = object()


def _next_or_end(iterator: Iterator[Any]) -> Any:
    try:
        return next(iterator)
    except StopIteration:
        return _ASYNC_END


class _AsyncOllamaStream:
    def __init__(self, stream: Iterator[Any]) -> None:
        self._stream = stream

    def __aiter__(self) -> "_AsyncOllamaStream":
        return self

    async def __anext__(self) -> Any:
        value = await asyncio.to_thread(_next_or_end, self._stream)
        if value is _ASYNC_END:
            raise StopAsyncIteration
        return value


class _AsyncOllamaCompletions:
    def __init__(self, sync_client: OllamaNativeClient) -> None:
        self._sync_client = sync_client

    async def create(self, **kwargs: Any) -> Any:
        result = await asyncio.to_thread(
            self._sync_client.chat.completions.create, **kwargs
        )
        if kwargs.get("stream"):
            return _AsyncOllamaStream(result)
        return result


class _AsyncOllamaChat:
    def __init__(self, sync_client: OllamaNativeClient) -> None:
        self.completions = _AsyncOllamaCompletions(sync_client)


class AsyncOllamaNativeClient:
    """Async-compatible facade backed by the bounded sync adapter."""

    def __init__(self, sync_client: OllamaNativeClient) -> None:
        self._sync = sync_client
        self._real_client = sync_client
        self.api_key = sync_client.api_key
        self.base_url = sync_client.base_url
        self.chat = _AsyncOllamaChat(sync_client)

    def close(self) -> None:
        self._sync.close()

    def is_closed(self) -> bool:
        return self._sync.is_closed()
