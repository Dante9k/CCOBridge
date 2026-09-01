#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request
from typing import Any


def request(
    url: str,
    *,
    method: str = "GET",
    payload: Any | None = None,
    headers: dict[str, str] | None = None,
    timeout: int = 30,
) -> tuple[int, bytes, dict[str, str]]:
    data = None
    final_headers = dict(headers or {})
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        final_headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=final_headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return response.status, response.read(), dict(response.headers)
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(), dict(exc.headers)


def request_json(*args: Any, **kwargs: Any) -> tuple[int, Any]:
    status, body, _headers = request(*args, **kwargs)
    return status, json.loads(body)


def text_contains(value: Any, needle: str) -> bool:
    if isinstance(value, str):
        return needle in value
    if isinstance(value, dict):
        return any(text_contains(item, needle) for item in value.values())
    if isinstance(value, list):
        return any(text_contains(item, needle) for item in value)
    return False


def wait_for_health(base_url: str) -> None:
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        try:
            status, _body, _headers = request(
                f"{base_url}/health/liveliness", timeout=2
            )
            if status == 200:
                return
        except OSError:
            pass
        time.sleep(1)
    raise AssertionError("Gateway did not become healthy")


def latest_capture(fake_url: str, path: str | None = None) -> dict[str, Any]:
    status, payload = request_json(f"{fake_url}/__captures")
    assert status == 200, payload
    captures = payload["captures"]
    if path is not None:
        captures = [item for item in captures if item.get("_test_path") == path]
    assert captures, f"Fake Ollama did not receive a request for {path or 'any path'}"
    return captures[-1]


def capture_count(fake_url: str) -> int:
    status, payload = request_json(f"{fake_url}/__captures")
    assert status == 200, payload
    return len(payload["captures"])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gateway", default="http://127.0.0.1:14000")
    parser.add_argument("--fake-ollama", default="http://127.0.0.1:11435")
    parser.add_argument("--key", default="sk-local-integration-test")
    parser.add_argument("--user-key", default="sk-local-user-test")
    args = parser.parse_args()

    wait_for_health(args.gateway)
    auth = {"Authorization": f"Bearer {args.key}"}
    user_auth = {"Authorization": f"Bearer {args.user_key}"}
    anthropic_headers = {
        **auth,
        "anthropic-version": "2023-06-01",
    }

    status, readiness = request_json(f"{args.gateway}/health/readiness")
    assert status == 200, readiness
    assert readiness["status"] == "ready", readiness

    status, unauthorized = request_json(f"{args.gateway}/v1/models")
    assert status == 401, unauthorized
    assert unauthorized["error"]["type"] == "authentication_error", unauthorized

    status, models = request_json(f"{args.gateway}/v1/models", headers=auth)
    assert status == 200, models
    model_ids = {model.get("id") for model in models["data"]}
    assert {
        "qwen3.8:latest",
        "nomic-embed-text:latest",
        "qwen-code",
        "local-embed",
    } <= model_ids, models

    status, model = request_json(
        f"{args.gateway}/v1/models/qwen-code", headers={"x-api-key": args.key}
    )
    assert status == 200, model
    assert model["id"] == "qwen-code", model

    status, users = request_json(f"{args.gateway}/admin/users", headers=auth)
    assert status == 200, users
    assert any(user.get("name") == "alice" for user in users["data"]), users
    status, forbidden = request_json(f"{args.gateway}/admin/users", headers=user_auth)
    assert status == 403, forbidden

    status, chat = request_json(
        f"{args.gateway}/v1/chat/completions",
        method="POST",
        headers=user_auth,
        payload={
            "model": "qwen-code",
            "messages": [{"role": "user", "content": "CHAT_TEST"}],
            "stream": False,
        },
    )
    assert status == 200, chat
    assert chat["choices"][0]["message"]["content"] == "FAKE_OK", chat
    chat_capture = latest_capture(args.fake_ollama, "/v1/chat/completions")
    assert chat_capture["model"] == "qwen3.8:latest", chat_capture
    assert chat_capture["_test_authorization"] is None, chat_capture
    assert chat_capture["_test_x_api_key"] is None, chat_capture

    status, native_chat = request_json(
        f"{args.gateway}/v1/chat/completions",
        method="POST",
        headers=auth,
        payload={
            "model": "qwen3.8:latest",
            "messages": [{"role": "user", "content": "NATIVE_MODEL_TEST"}],
        },
    )
    assert status == 200, native_chat
    assert latest_capture(args.fake_ollama, "/v1/chat/completions")["model"] == (
        "qwen3.8:latest"
    )

    status, completion = request_json(
        f"{args.gateway}/v1/completions",
        method="POST",
        headers=auth,
        payload={"model": "qwen-code", "prompt": "COMPLETION_TEST"},
    )
    assert status == 200, completion
    assert completion["choices"][0]["text"] == "FAKE_OK", completion
    completion_capture = latest_capture(args.fake_ollama, "/v1/completions")
    assert completion_capture["model"] == "qwen3.8:latest", completion_capture

    status, responses = request_json(
        f"{args.gateway}/v1/responses",
        method="POST",
        headers=auth,
        payload={"model": "qwen-code", "input": "RESPONSES_TEST"},
    )
    assert status == 200, responses
    assert responses["object"] == "response", responses
    response_capture = latest_capture(args.fake_ollama, "/v1/responses")
    assert response_capture["model"] == "qwen3.8:latest", response_capture

    status, embeddings = request_json(
        f"{args.gateway}/v1/embeddings",
        method="POST",
        headers=auth,
        payload={"model": "local-embed", "input": "EMBEDDING_TEST"},
    )
    assert status == 200, embeddings
    assert embeddings["data"][0]["embedding"] == [0.1, 0.2, 0.3], embeddings
    embedding_capture = latest_capture(args.fake_ollama, "/v1/embeddings")
    assert embedding_capture["model"] == "nomic-embed-text:latest", embedding_capture

    status, openai_stream, openai_stream_headers = request(
        f"{args.gateway}/v1/chat/completions",
        method="POST",
        headers=auth,
        payload={
            "model": "qwen-code",
            "messages": [{"role": "user", "content": "STREAM_TEST"}],
            "stream": True,
        },
    )
    assert status == 200, openai_stream
    assert "text/event-stream" in {
        key.lower(): value for key, value in openai_stream_headers.items()
    }.get("content-type", ""), openai_stream_headers
    assert "stream-" in openai_stream.decode() and "ok" in openai_stream.decode()

    status, openai_tool = request_json(
        f"{args.gateway}/v1/chat/completions",
        method="POST",
        headers=auth,
        payload={
            "model": "qwen-code",
            "messages": [{"role": "user", "content": "USE_TOOL"}],
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": "get_weather",
                        "description": "Get weather for a city",
                        "parameters": {
                            "type": "object",
                            "properties": {"city": {"type": "string"}},
                            "required": ["city"],
                        },
                    },
                }
            ],
        },
    )
    assert status == 200, openai_tool
    assert openai_tool["choices"][0]["message"]["tool_calls"][0]["function"] == {
        "name": "get_weather",
        "arguments": '{"city":"Shanghai"}',
    }, openai_tool
    openai_tool_capture = latest_capture(args.fake_ollama, "/v1/chat/completions")
    assert openai_tool_capture["tools"][0]["function"]["name"] == "get_weather"

    status, unsupported = request_json(
        f"{args.gateway}/key/generate", method="POST", headers=auth, payload={}
    )
    assert status == 404, unsupported
    assert unsupported["error"]["type"] == "not_found_error", unsupported

    system_payload = {
        "model": "qwen-code",
        "max_tokens": 64,
        "stream": False,
        "system": [{"type": "text", "text": "TOP_SYSTEM_SENTINEL"}],
        "messages": [
            {"role": "user", "content": "first"},
            {"role": "assistant", "content": "second"},
            {
                "role": "system",
                "content": [
                    {
                        "type": "text",
                        "text": "MID_SYSTEM_SENTINEL",
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
            },
            {"role": "user", "content": "third"},
        ],
    }
    status, messages = request_json(
        f"{args.gateway}/v1/messages",
        method="POST",
        headers=anthropic_headers,
        payload=system_payload,
    )
    assert status == 200, messages
    assert messages["type"] == "message", messages

    capture = latest_capture(args.fake_ollama, "/api/chat")
    assert capture["model"] == "qwen3.8:latest", capture
    assert text_contains(capture, "TOP_SYSTEM_SENTINEL"), capture
    assert text_contains(capture, "MID_SYSTEM_SENTINEL"), capture
    roles = [message.get("role") for message in capture.get("messages", [])]
    seen_non_system = False
    for role in roles:
        if role != "system":
            seen_non_system = True
        if role == "system" and seen_non_system:
            raise AssertionError(f"System message was not at the beginning: {roles}")

    before = capture_count(args.fake_ollama)
    status, invalid = request_json(
        f"{args.gateway}/v1/messages",
        method="POST",
        headers=anthropic_headers,
        payload={
            "model": "qwen-code",
            "max_tokens": 16,
            "messages": [
                {
                    "role": "system",
                    "content": [{"type": "image", "source": {"data": "x"}}],
                },
                {"role": "user", "content": "hello"},
            ],
        },
    )
    assert status == 400, invalid
    assert invalid["error"]["type"] == "invalid_request_error", invalid
    assert capture_count(args.fake_ollama) == before

    status, stream_body, stream_headers = request(
        f"{args.gateway}/v1/messages",
        method="POST",
        headers=anthropic_headers,
        payload={
            "model": "qwen-code",
            "max_tokens": 32,
            "stream": True,
            "messages": [{"role": "user", "content": "STREAM_TEST"}],
        },
    )
    stream_text = stream_body.decode("utf-8")
    assert status == 200, stream_text
    normalized_stream_headers = {
        key.lower(): value for key, value in stream_headers.items()
    }
    assert "text/event-stream" in normalized_stream_headers.get("content-type", ""), (
        stream_headers
    )
    assert "content_block_delta" in stream_text, stream_text
    text_deltas: list[str] = []
    for line in stream_text.splitlines():
        if not line.startswith("data: "):
            continue
        event_payload = json.loads(line.removeprefix("data: "))
        delta = event_payload.get("delta", {})
        if delta.get("type") == "text_delta":
            text_deltas.append(delta.get("text", ""))
    assert "".join(text_deltas) == "stream-ok", stream_text

    status, tool_message = request_json(
        f"{args.gateway}/v1/messages",
        method="POST",
        headers=anthropic_headers,
        payload={
            "model": "qwen-code",
            "max_tokens": 64,
            "stream": False,
            "tools": [
                {
                    "name": "get_weather",
                    "description": "Get weather for a city",
                    "input_schema": {
                        "type": "object",
                        "properties": {"city": {"type": "string"}},
                        "required": ["city"],
                    },
                }
            ],
            "messages": [{"role": "user", "content": "USE_TOOL"}],
        },
    )
    assert status == 200, tool_message
    tool_blocks = [
        block for block in tool_message["content"] if block.get("type") == "tool_use"
    ]
    assert len(tool_blocks) == 1, tool_message
    tool_block = tool_blocks[0]
    assert tool_block["name"] == "get_weather", tool_block
    assert tool_block["input"] == {"city": "Shanghai"}, tool_block

    status, tool_result = request_json(
        f"{args.gateway}/v1/messages",
        method="POST",
        headers=anthropic_headers,
        payload={
            "model": "qwen-code",
            "max_tokens": 64,
            "stream": False,
            "messages": [
                {"role": "user", "content": "USE_TOOL"},
                {"role": "assistant", "content": [tool_block]},
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": tool_block["id"],
                            "content": "sunny",
                        }
                    ],
                },
            ],
        },
    )
    assert status == 200, tool_result
    result_capture = latest_capture(args.fake_ollama, "/api/chat")
    assert text_contains(result_capture, tool_block["id"]), result_capture
    assert text_contains(result_capture, "sunny"), result_capture

    status, forbidden_usage = request_json(
        f"{args.gateway}/admin/usage", headers=user_auth
    )
    assert status == 403, forbidden_usage
    usage = None
    for _attempt in range(20):
        status, usage = request_json(
            f"{args.gateway}/admin/usage?days=1&user=usr_0123456789abcdef",
            headers=auth,
        )
        assert status == 200, usage
        if usage["totals"]["requests"] >= 1:
            break
        time.sleep(0.1)
    assert usage is not None
    assert usage["totals"]["requests"] >= 1, usage
    assert usage["totals"]["metered_requests"] >= 1, usage
    assert usage["totals"]["input_tokens"] >= 12, usage
    assert usage["totals"]["output_tokens"] >= 2, usage

    print(
        "Integration tests passed: auth, dynamic models, aliases, OpenAI endpoints, "
        "Anthropic normalization, streaming, tools, multi-key auth, and usage"
    )


if __name__ == "__main__":
    main()
