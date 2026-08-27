"""Normalize Anthropic system messages before LiteLLM sees the request."""

from __future__ import annotations

from copy import deepcopy
from typing import Any


class SystemMessageNormalizationError(ValueError):
    """The request contains a system content block we cannot preserve safely."""


def _as_text_blocks(value: Any, location: str) -> list[dict[str, Any]]:
    if isinstance(value, str):
        return [{"type": "text", "text": value}]

    if not isinstance(value, list):
        raise SystemMessageNormalizationError(
            f"{location} must be a string or an array of Anthropic text blocks"
        )

    blocks: list[dict[str, Any]] = []
    for index, block in enumerate(value):
        if not isinstance(block, dict):
            raise SystemMessageNormalizationError(
                f"{location}[{index}] must be an Anthropic text block object"
            )
        if block.get("type") != "text" or not isinstance(block.get("text"), str):
            block_type = block.get("type", "missing")
            raise SystemMessageNormalizationError(
                f"{location}[{index}] has unsupported system block type "
                f"{block_type!r}; "
                "only text blocks can be moved safely"
            )
        blocks.append(deepcopy(block))
    return blocks


def normalize_anthropic_system_messages(
    payload: Any,
) -> tuple[Any, bool]:
    """Hoist in-message system entries into Anthropic's top-level system field.

    Existing top-level system blocks remain first. Non-system messages retain their
    original order and representation. The input object is not modified.
    """

    if not isinstance(payload, dict):
        return payload, False

    messages = payload.get("messages")
    if not isinstance(messages, list):
        return payload, False

    hoisted: list[dict[str, Any]] = []
    remaining: list[Any] = []

    for index, message in enumerate(messages):
        if isinstance(message, dict) and message.get("role") == "system":
            if "content" not in message:
                raise SystemMessageNormalizationError(
                    f"messages[{index}] system message is missing content"
                )
            hoisted.extend(
                _as_text_blocks(message["content"], f"messages[{index}].content")
            )
        else:
            remaining.append(deepcopy(message))

    if not hoisted:
        return payload, False

    existing: list[dict[str, Any]] = []
    if "system" in payload and payload["system"] is not None:
        existing = _as_text_blocks(payload["system"], "system")

    normalized = deepcopy(payload)
    normalized["system"] = existing + hoisted
    normalized["messages"] = remaining
    return normalized, True
