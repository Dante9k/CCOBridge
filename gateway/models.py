"""Convert Ollama model metadata into the OpenAI models representation."""

from __future__ import annotations

from datetime import datetime
from typing import Any


class ModelDiscoveryError(ValueError):
    """Ollama returned a model-list response that cannot be represented safely."""


def _created_timestamp(value: Any) -> int:
    if not isinstance(value, str):
        return 0
    try:
        return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp())
    except ValueError:
        return 0


def openai_models_from_tags(
    payload: Any, aliases: dict[str, str]
) -> list[dict[str, Any]]:
    """Build a deterministic OpenAI model list from Ollama ``/api/tags`` data.

    Aliases are exposed only when their target is currently installed. A configured
    alias intentionally shadows a native model with the same identifier.
    """

    if not isinstance(payload, dict) or not isinstance(payload.get("models"), list):
        raise ModelDiscoveryError("Ollama /api/tags returned an invalid response")

    discovered: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(payload["models"]):
        if not isinstance(item, dict):
            raise ModelDiscoveryError(f"Ollama model entry {index} is not an object")
        model_id = item.get("model") or item.get("name")
        if not isinstance(model_id, str) or not model_id:
            raise ModelDiscoveryError(
                f"Ollama model entry {index} has no usable model identifier"
            )
        discovered[model_id] = {
            "id": model_id,
            "object": "model",
            "created": _created_timestamp(item.get("modified_at")),
            "owned_by": "ollama",
        }

    advertised = dict(discovered)
    for alias in sorted(aliases):
        target = aliases[alias]
        if target not in discovered:
            continue
        advertised[alias] = {
            "id": alias,
            "object": "model",
            "created": discovered[target]["created"],
            "owned_by": "ccobridge",
        }
    return [advertised[model_id] for model_id in sorted(advertised)]
