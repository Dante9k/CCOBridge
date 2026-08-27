#!/usr/bin/env python3
"""Deterministic Ollama API test double for offline integration tests."""

from __future__ import annotations

import argparse
import json
import threading
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

CAPTURES: list[dict[str, Any]] = []
CAPTURE_LOCK = threading.Lock()


def _timestamp() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


class Handler(BaseHTTPRequestHandler):
    server_version = "FakeOllama/1.0"

    def log_message(self, format_string: str, *args: object) -> None:
        print(f"fake-ollama: {format_string % args}", flush=True)

    def _json(self, status: int, payload: Any) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        if self.path == "/api/version":
            self._json(200, {"version": "0.13.3"})
            return
        if self.path == "/api/tags":
            self._json(
                200,
                {
                    "models": [
                        {
                            "name": "qwen3.8:latest",
                            "model": "qwen3.8:latest",
                            "size": 16500000000,
                            "modified_at": _timestamp(),
                        },
                        {
                            "name": "nomic-embed-text:latest",
                            "model": "nomic-embed-text:latest",
                            "size": 274000000,
                            "modified_at": _timestamp(),
                        },
                    ]
                },
            )
            return
        if self.path == "/__captures":
            with CAPTURE_LOCK:
                captures = list(CAPTURES)
            self._json(200, {"captures": captures})
            return
        self._json(404, {"error": "not found"})

    def do_POST(self) -> None:
        content_length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(content_length)
        try:
            payload = json.loads(raw or b"{}")
        except json.JSONDecodeError:
            self._json(400, {"error": "invalid json"})
            return

        if self.path == "/__reset":
            with CAPTURE_LOCK:
                CAPTURES.clear()
            self._json(200, {"ok": True})
            return

        if self.path == "/api/show":
            self._json(
                200,
                {
                    "capabilities": ["completion", "tools", "thinking"],
                    "model_info": {
                        "general.architecture": "qwen35",
                        "general.parameter_count": 27300000000,
                    },
                },
            )
            return

        supported_paths = {
            "/api/chat",
            "/v1/chat/completions",
            "/v1/completions",
            "/v1/responses",
            "/v1/embeddings",
        }
        if self.path not in supported_paths:
            self._json(404, {"error": "not found"})
            return

        captured = dict(payload)
        captured["_test_path"] = self.path
        captured["_test_authorization"] = self.headers.get("Authorization")
        captured["_test_x_api_key"] = self.headers.get("x-api-key")
        with CAPTURE_LOCK:
            CAPTURES.append(captured)

        if self.path == "/v1/chat/completions":
            self._openai_chat(payload)
            return
        if self.path == "/v1/completions":
            self._openai_completion(payload)
            return
        if self.path == "/v1/responses":
            self._openai_response(payload)
            return
        if self.path == "/v1/embeddings":
            self._openai_embeddings(payload)
            return

        request_text = json.dumps(payload.get("messages", []), ensure_ascii=False)
        wants_tool = bool(payload.get("tools")) and "USE_TOOL" in request_text
        wants_stream_test = "STREAM_TEST" in request_text

        if wants_tool:
            message: dict[str, Any] = {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "function": {
                            "name": "get_weather",
                            "arguments": {"city": "Shanghai"},
                        }
                    }
                ],
            }
        else:
            message = {
                "role": "assistant",
                "content": "stream-ok" if wants_stream_test else "FAKE_OK",
            }

        if payload.get("stream"):
            chunks: list[dict[str, Any]] = []
            if wants_stream_test:
                for text in ("stream-", "ok"):
                    chunks.append(
                        {
                            "model": "qwen3.8:latest",
                            "created_at": _timestamp(),
                            "message": {"role": "assistant", "content": text},
                            "done": False,
                        }
                    )
            else:
                chunks.append(
                    {
                        "model": "qwen3.8:latest",
                        "created_at": _timestamp(),
                        "message": message,
                        "done": False,
                    }
                )
            chunks.append(
                {
                    "model": "qwen3.8:latest",
                    "created_at": _timestamp(),
                    "message": {"role": "assistant", "content": ""},
                    "done": True,
                    "done_reason": "stop",
                    "prompt_eval_count": 12,
                    "eval_count": 2,
                }
            )
            body = b"".join(
                json.dumps(chunk, ensure_ascii=False).encode("utf-8") + b"\n"
                for chunk in chunks
            )
            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        self._json(
            200,
            {
                "model": "qwen3.8:latest",
                "created_at": _timestamp(),
                "message": message,
                "done": True,
                "done_reason": "stop",
                "prompt_eval_count": 12,
                "eval_count": 2,
            },
        )

    def _openai_chat(self, payload: dict[str, Any]) -> None:
        request_text = json.dumps(payload.get("messages", []), ensure_ascii=False)
        wants_tool = bool(payload.get("tools")) and "USE_TOOL" in request_text
        wants_stream_test = "STREAM_TEST" in request_text
        model = payload.get("model", "unknown")

        if wants_tool:
            message: dict[str, Any] = {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_fake_weather",
                        "type": "function",
                        "function": {
                            "name": "get_weather",
                            "arguments": '{"city":"Shanghai"}',
                        },
                    }
                ],
            }
            finish_reason = "tool_calls"
        else:
            message = {
                "role": "assistant",
                "content": "stream-ok" if wants_stream_test else "FAKE_OK",
            }
            finish_reason = "stop"

        if payload.get("stream"):
            pieces = ("stream-", "ok") if wants_stream_test else ("FAKE_OK",)
            events = []
            for piece in pieces:
                events.append(
                    "data: "
                    + json.dumps(
                        {
                            "id": "chatcmpl-fake",
                            "object": "chat.completion.chunk",
                            "created": 0,
                            "model": model,
                            "choices": [
                                {
                                    "index": 0,
                                    "delta": {"content": piece},
                                    "finish_reason": None,
                                }
                            ],
                        }
                    )
                    + "\n\n"
                )
            events.append("data: [DONE]\n\n")
            body = "".join(events).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        self._json(
            200,
            {
                "id": "chatcmpl-fake",
                "object": "chat.completion",
                "created": 0,
                "model": model,
                "choices": [
                    {
                        "index": 0,
                        "message": message,
                        "finish_reason": finish_reason,
                    }
                ],
                "usage": {
                    "prompt_tokens": 12,
                    "completion_tokens": 2,
                    "total_tokens": 14,
                },
            },
        )

    def _openai_completion(self, payload: dict[str, Any]) -> None:
        self._json(
            200,
            {
                "id": "cmpl-fake",
                "object": "text_completion",
                "created": 0,
                "model": payload.get("model", "unknown"),
                "choices": [{"index": 0, "text": "FAKE_OK", "finish_reason": "stop"}],
            },
        )

    def _openai_response(self, payload: dict[str, Any]) -> None:
        self._json(
            200,
            {
                "id": "resp_fake",
                "object": "response",
                "status": "completed",
                "model": payload.get("model", "unknown"),
                "output": [
                    {
                        "id": "msg_fake",
                        "type": "message",
                        "role": "assistant",
                        "status": "completed",
                        "content": [{"type": "output_text", "text": "FAKE_RESPONSE"}],
                    }
                ],
            },
        )

    def _openai_embeddings(self, payload: dict[str, Any]) -> None:
        self._json(
            200,
            {
                "object": "list",
                "model": payload.get("model", "unknown"),
                "data": [
                    {"object": "embedding", "index": 0, "embedding": [0.1, 0.2, 0.3]}
                ],
                "usage": {"prompt_tokens": 1, "total_tokens": 1},
            },
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=11435)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"fake-ollama listening on {args.host}:{args.port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
