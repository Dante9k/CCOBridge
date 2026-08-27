"""Parse and validate the small, environment-based gateway configuration."""

from __future__ import annotations

import json
from typing import Any


class AliasConfigurationError(ValueError):
    """The configured model alias map is not safe to use."""


def load_model_aliases(raw_value: str | None) -> dict[str, str]:
    """Return a validated alias-to-Ollama-model mapping.

    The environment value is a JSON object so model identifiers containing slashes,
    colons, or dots remain unambiguous. An unset or blank value enables passthrough
    without aliases.
    """

    if raw_value is None or not raw_value.strip():
        return {}

    try:
        value: Any = json.loads(raw_value)
    except json.JSONDecodeError as exc:
        raise AliasConfigurationError(
            "CCOBRIDGE_MODEL_ALIASES must be a valid JSON object"
        ) from exc

    if not isinstance(value, dict):
        raise AliasConfigurationError("CCOBRIDGE_MODEL_ALIASES must be a JSON object")

    aliases: dict[str, str] = {}
    for alias, target in value.items():
        if not isinstance(alias, str) or not alias.strip():
            raise AliasConfigurationError("model alias names must be non-empty strings")
        if not isinstance(target, str) or not target.strip():
            raise AliasConfigurationError(
                f"target for model alias {alias!r} must be a non-empty string"
            )

        normalized_alias = alias.strip()
        normalized_target = target.strip()
        if any(character.isspace() for character in normalized_alias):
            raise AliasConfigurationError(
                f"model alias {normalized_alias!r} cannot contain whitespace"
            )
        if any(character.isspace() for character in normalized_target):
            raise AliasConfigurationError(
                f"target for model alias {normalized_alias!r} cannot contain whitespace"
            )
        if normalized_alias == normalized_target:
            raise AliasConfigurationError(
                f"model alias {normalized_alias!r} must differ from its target"
            )
        if normalized_alias in aliases:
            raise AliasConfigurationError(
                f"model alias {normalized_alias!r} is configured more than once"
            )
        aliases[normalized_alias] = normalized_target

    for alias, target in aliases.items():
        if target in aliases:
            raise AliasConfigurationError(
                f"model alias {alias!r} points to alias {target!r}; "
                "alias chains are not supported"
            )

    return aliases


def resolve_model(model: str, aliases: dict[str, str]) -> str:
    """Resolve one public alias while leaving native Ollama model names unchanged."""

    return aliases.get(model, model)
