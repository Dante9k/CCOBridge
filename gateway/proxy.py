"""Authenticated, streaming compatibility gateway for Ollama-powered agents.

OpenAI-compatible endpoints take the shortest path to Ollama. Anthropic Messages
uses the pinned LiteLLM process for protocol conversion after CCOBridge normalizes
system content. Request and response bodies are never logged.
"""

from __future__ import annotations

import hmac
import json
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from urllib.parse import urlsplit

import httpx
from starlette.applications import Starlette
from starlette.background import BackgroundTask
from starlette.datastructures import Headers
from starlette.requests import Request
from starlette.responses import JSONResponse, StreamingResponse
from starlette.routing import Route

from gateway.config import (
    AliasConfigurationError,
    load_model_aliases,
    resolve_model,
)
from gateway.models import ModelDiscoveryError, openai_models_from_tags
from gateway.normalize import (
    SystemMessageNormalizationError,
    normalize_anthropic_system_messages,
)

HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
}
CLIENT_AUTH_HEADERS = {"authorization", "x-api-key"}
OPENAI_FORWARD_PATHS = (
    "/v1/chat/completions",
    "/v1/completions",
    "/v1/responses",
    "/v1/embeddings",
)


def _strip_request_headers(
    headers: Headers, *, strip_authentication: bool
) -> list[tuple[bytes, bytes]]:
    blocked = HOP_BY_HOP_HEADERS | {"host", "content-length"}
    if strip_authentication:
        blocked |= CLIENT_AUTH_HEADERS
    return [
        (key, value)
        for key, value in headers.raw
        if key.decode("latin-1").lower() not in blocked
    ]


def _strip_response_headers(headers: httpx.Headers) -> dict[str, str]:
    blocked = HOP_BY_HOP_HEADERS | {"content-length"}
    return {key: value for key, value in headers.items() if key.lower() not in blocked}


def _openai_error(
    message: str,
    status_code: int,
    *,
    error_type: str = "invalid_request_error",
) -> JSONResponse:
    headers = {"WWW-Authenticate": "Bearer"} if status_code == 401 else None
    return JSONResponse(
        status_code=status_code,
        headers=headers,
        content={
            "error": {
                "message": message,
                "type": error_type,
                "param": None,
                "code": None,
            }
        },
    )


def _anthropic_error(
    message: str,
    status_code: int,
    *,
    error_type: str = "invalid_request_error",
) -> JSONResponse:
    headers = {"WWW-Authenticate": "Bearer"} if status_code == 401 else None
    return JSONResponse(
        status_code=status_code,
        headers=headers,
        content={"type": "error", "error": {"type": error_type, "message": message}},
    )


def _normalize_ollama_base(raw_value: str) -> str:
    value = raw_value.rstrip("/")
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise RuntimeError("OLLAMA_API_BASE must be an absolute HTTP(S) URL")
    if parsed.query or parsed.fragment:
        raise RuntimeError("OLLAMA_API_BASE cannot contain a query or fragment")
    return value


def _runtime_api_key() -> str:
    primary = os.getenv("CCOBRIDGE_API_KEY")
    legacy = os.getenv("LITELLM_MASTER_KEY")
    if primary and legacy and primary != legacy:
        raise RuntimeError(
            "CCOBRIDGE_API_KEY and LITELLM_MASTER_KEY must match when both are set"
        )
    api_key = primary or legacy
    if not api_key:
        raise RuntimeError("CCOBRIDGE_API_KEY is required")
    if not api_key.startswith("sk-") or len(api_key) < 16:
        raise RuntimeError(
            "CCOBRIDGE_API_KEY must start with 'sk-' and contain at least 16 characters"
        )
    return api_key


def _is_authorized(request: Request) -> bool:
    expected = request.app.state.api_key
    candidates: list[str] = []

    authorization = request.headers.get("authorization", "")
    scheme, separator, credentials = authorization.partition(" ")
    if separator and scheme.lower() == "bearer" and credentials:
        candidates.append(credentials)

    anthropic_key = request.headers.get("x-api-key")
    if anthropic_key:
        candidates.append(anthropic_key)

    return any(hmac.compare_digest(candidate, expected) for candidate in candidates)


def _require_authorization(
    request: Request, *, anthropic: bool = False
) -> JSONResponse | None:
    if _is_authorized(request):
        return None
    message = "Invalid or missing API key"
    if anthropic:
        return _anthropic_error(message, 401, error_type="authentication_error")
    return _openai_error(message, 401, error_type="authentication_error")


def _rewrite_model(payload: Any, aliases: dict[str, str]) -> tuple[Any, bool]:
    if not isinstance(payload, dict):
        return payload, False
    model = payload.get("model")
    if not isinstance(model, str):
        return payload, False
    resolved = resolve_model(model, aliases)
    if resolved == model:
        return payload, False
    rewritten = dict(payload)
    rewritten["model"] = resolved
    return rewritten, True


def _streaming_response(upstream: httpx.Response) -> StreamingResponse:
    return StreamingResponse(
        upstream.aiter_raw(),
        status_code=upstream.status_code,
        headers=_strip_response_headers(upstream.headers),
        background=BackgroundTask(upstream.aclose),
    )


@asynccontextmanager
async def lifespan(app: Starlette) -> AsyncIterator[None]:
    try:
        aliases = load_model_aliases(os.getenv("CCOBRIDGE_MODEL_ALIASES"))
    except AliasConfigurationError as exc:
        raise RuntimeError(str(exc)) from exc

    app.state.api_key = _runtime_api_key()
    app.state.aliases = aliases
    app.state.ollama_base = _normalize_ollama_base(
        os.getenv("OLLAMA_API_BASE", "http://127.0.0.1:11434")
    )
    timeout = httpx.Timeout(connect=10, read=None, write=60, pool=10)
    app.state.ollama_client = httpx.AsyncClient(timeout=timeout, follow_redirects=False)
    app.state.litellm_client = httpx.AsyncClient(
        timeout=timeout, follow_redirects=False
    )
    try:
        yield
    finally:
        await app.state.ollama_client.aclose()
        await app.state.litellm_client.aclose()


async def home(request: Request) -> JSONResponse:
    return JSONResponse(
        {
            "name": "CCOBridge",
            "version": os.getenv("GATEWAY_VERSION", "development"),
            "status": "ok",
        }
    )


async def liveliness(request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok"})


async def readiness(request: Request) -> JSONResponse:
    internal_port = os.getenv("INTERNAL_LITELLM_PORT", "4001")
    try:
        ollama_response = await request.app.state.ollama_client.get(
            f"{request.app.state.ollama_base}/api/tags"
        )
        ollama_response.raise_for_status()
        models = openai_models_from_tags(
            ollama_response.json(), request.app.state.aliases
        )
        if not models:
            raise ModelDiscoveryError("Ollama has no installed models")

        litellm_response = await request.app.state.litellm_client.get(
            f"http://127.0.0.1:{internal_port}/health/liveliness"
        )
        litellm_response.raise_for_status()
    except (httpx.HTTPError, json.JSONDecodeError, ModelDiscoveryError):
        return JSONResponse({"status": "unavailable"}, status_code=503)
    return JSONResponse({"status": "ready"})


async def _discover_models(request: Request) -> list[dict[str, Any]] | JSONResponse:
    try:
        response = await request.app.state.ollama_client.get(
            f"{request.app.state.ollama_base}/api/tags"
        )
        response.raise_for_status()
        return openai_models_from_tags(response.json(), request.app.state.aliases)
    except (httpx.HTTPError, json.JSONDecodeError, ModelDiscoveryError):
        return _openai_error(
            "Ollama model discovery is unavailable", 502, error_type="gateway_error"
        )


async def list_models(request: Request) -> JSONResponse:
    unauthorized = _require_authorization(request)
    if unauthorized:
        return unauthorized
    models = await _discover_models(request)
    if isinstance(models, JSONResponse):
        return models
    return JSONResponse({"object": "list", "data": models})


async def retrieve_model(request: Request) -> JSONResponse:
    unauthorized = _require_authorization(request)
    if unauthorized:
        return unauthorized
    models = await _discover_models(request)
    if isinstance(models, JSONResponse):
        return models
    model_id = request.path_params["model_id"]
    for model in models:
        if model["id"] == model_id:
            return JSONResponse(model)
    return _openai_error(
        f"Model {model_id!r} was not found", 404, error_type="not_found_error"
    )


async def forward_openai(request: Request) -> StreamingResponse | JSONResponse:
    unauthorized = _require_authorization(request)
    if unauthorized:
        return unauthorized

    raw_body = await request.body()
    try:
        payload = json.loads(raw_body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return _openai_error("Request body must be valid UTF-8 JSON", 400)

    payload, changed = _rewrite_model(payload, request.app.state.aliases)
    content = (
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if changed
        else raw_body
    )
    target = f"{request.app.state.ollama_base}{request.url.path}"
    if request.url.query:
        target = f"{target}?{request.url.query}"
    upstream_request = request.app.state.ollama_client.build_request(
        request.method,
        target,
        headers=_strip_request_headers(request.headers, strip_authentication=True),
        content=content,
    )
    try:
        upstream = await request.app.state.ollama_client.send(
            upstream_request, stream=True
        )
    except httpx.HTTPError:
        return _openai_error(
            "The Ollama service is unavailable", 502, error_type="gateway_error"
        )
    return _streaming_response(upstream)


async def forward_anthropic(request: Request) -> StreamingResponse | JSONResponse:
    unauthorized = _require_authorization(request, anthropic=True)
    if unauthorized:
        return unauthorized

    raw_body = await request.body()
    try:
        payload = json.loads(raw_body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return _anthropic_error("Request body must be valid UTF-8 JSON", 400)

    try:
        payload, normalized = normalize_anthropic_system_messages(payload)
    except SystemMessageNormalizationError as exc:
        return _anthropic_error(str(exc), 400)
    payload, rewritten = _rewrite_model(payload, request.app.state.aliases)
    content = (
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if normalized or rewritten
        else raw_body
    )

    internal_port = os.getenv("INTERNAL_LITELLM_PORT", "4001")
    target = f"http://127.0.0.1:{internal_port}/v1/messages"
    if request.url.query:
        target = f"{target}?{request.url.query}"
    headers = _strip_request_headers(request.headers, strip_authentication=True)
    headers.append(
        (b"authorization", f"Bearer {request.app.state.api_key}".encode("latin-1"))
    )
    upstream_request = request.app.state.litellm_client.build_request(
        request.method,
        target,
        headers=headers,
        content=content,
    )
    try:
        upstream = await request.app.state.litellm_client.send(
            upstream_request, stream=True
        )
    except httpx.HTTPError:
        return _anthropic_error(
            "The internal LiteLLM service is unavailable",
            502,
            error_type="api_error",
        )
    return _streaming_response(upstream)


async def not_found(request: Request) -> JSONResponse:
    return _openai_error(
        f"Unsupported endpoint: {request.url.path}",
        404,
        error_type="not_found_error",
    )


routes = [
    Route("/", home, methods=["GET"]),
    Route("/health/liveliness", liveliness, methods=["GET"]),
    Route("/health/readiness", readiness, methods=["GET"]),
    Route("/v1/models", list_models, methods=["GET"]),
    Route("/v1/models/{model_id:path}", retrieve_model, methods=["GET"]),
    Route("/v1/messages", forward_anthropic, methods=["POST"]),
    *(Route(path, forward_openai, methods=["POST"]) for path in OPENAI_FORWARD_PATHS),
    Route(
        "/{path:path}",
        not_found,
        methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    ),
]

app = Starlette(routes=routes, lifespan=lifespan)
