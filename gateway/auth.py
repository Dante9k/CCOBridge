"""Local multi-key authentication without storing user secrets in plaintext."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

KEY_ID_PATTERN = re.compile(r"^usr_[0-9a-f]{16}$")
KEY_HASH_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")


class KeyConfigurationError(ValueError):
    """The local user-key file is unavailable or unsafe to use."""


@dataclass(frozen=True, slots=True)
class Principal:
    """Authenticated local identity."""

    key_id: str
    name: str
    role: str


@dataclass(frozen=True, slots=True)
class KeyRecord:
    """Validated key metadata loaded from disk."""

    principal: Principal
    key_hash: str
    enabled: bool
    created_at: str


def hash_api_key(api_key: str) -> str:
    """Return the stable digest stored for a high-entropy API key."""

    return f"sha256:{hashlib.sha256(api_key.encode('utf-8')).hexdigest()}"


def validate_api_key(api_key: str) -> None:
    """Reject malformed credentials before they reach runtime configuration."""

    if not api_key.startswith("sk-") or len(api_key) < 16:
        raise KeyConfigurationError(
            "API keys must start with 'sk-' and contain at least 16 characters"
        )


def _validate_name(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise KeyConfigurationError("user names must be non-empty strings")
    name = value.strip()
    if len(name) > 64 or any(ord(character) < 32 for character in name):
        raise KeyConfigurationError(
            "user names must contain at most 64 printable characters"
        )
    return name


def load_key_records(path: Path) -> tuple[KeyRecord, ...]:
    """Load and strictly validate the versioned user-key document."""

    try:
        raw = path.read_text(encoding="utf-8")
        document: Any = json.loads(raw)
    except FileNotFoundError as exc:
        raise KeyConfigurationError(f"user-key file was not found: {path}") from exc
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise KeyConfigurationError(
            f"user-key file is not valid UTF-8 JSON: {path}"
        ) from exc

    if not isinstance(document, dict) or document.get("version") != 1:
        raise KeyConfigurationError("user-key file must use schema version 1")
    users = document.get("users")
    if not isinstance(users, list):
        raise KeyConfigurationError("user-key file must contain a users array")

    records: list[KeyRecord] = []
    seen_ids: set[str] = set()
    seen_names: set[str] = set()
    seen_hashes: set[str] = set()
    for index, value in enumerate(users):
        if not isinstance(value, dict):
            raise KeyConfigurationError(f"users[{index}] must be an object")
        allowed_fields = {"id", "name", "role", "key_hash", "enabled", "created_at"}
        if set(value) - allowed_fields:
            raise KeyConfigurationError(f"users[{index}] contains unsupported fields")
        key_id = value.get("id")
        if not isinstance(key_id, str) or not KEY_ID_PATTERN.fullmatch(key_id):
            raise KeyConfigurationError(f"users[{index}].id is invalid")
        name = _validate_name(value.get("name"))
        role = value.get("role", "user")
        if role != "user":
            raise KeyConfigurationError(f"users[{index}].role must be 'user'")
        key_hash = value.get("key_hash")
        if not isinstance(key_hash, str) or not KEY_HASH_PATTERN.fullmatch(key_hash):
            raise KeyConfigurationError(f"users[{index}].key_hash is invalid")
        enabled = value.get("enabled")
        if not isinstance(enabled, bool):
            raise KeyConfigurationError(f"users[{index}].enabled must be boolean")
        created_at = value.get("created_at")
        if not isinstance(created_at, str) or not created_at:
            raise KeyConfigurationError(f"users[{index}].created_at is invalid")
        if (
            key_id in seen_ids
            or name.casefold() in seen_names
            or key_hash in seen_hashes
        ):
            raise KeyConfigurationError(
                "user IDs, names, and key hashes must be unique"
            )

        seen_ids.add(key_id)
        seen_names.add(name.casefold())
        seen_hashes.add(key_hash)
        records.append(
            KeyRecord(
                principal=Principal(key_id=key_id, name=name, role=role),
                key_hash=key_hash,
                enabled=enabled,
                created_at=created_at,
            )
        )
    return tuple(records)


class KeyStore:
    """Authenticate an admin key plus reloadable, hashed user keys."""

    def __init__(self, admin_key: str, path: str | None) -> None:
        validate_api_key(admin_key)
        self._admin_hash = hash_api_key(admin_key)
        self._path = Path(path) if path else None
        self._signature: tuple[int, int] | None = None
        self._records: tuple[KeyRecord, ...] = ()
        if self._path is not None:
            self._reload(force=True)

    def _reload(self, *, force: bool = False) -> None:
        if self._path is None:
            return
        try:
            stat = self._path.stat()
        except OSError as exc:
            raise KeyConfigurationError(
                f"cannot inspect user-key file: {self._path}"
            ) from exc
        signature = (stat.st_mtime_ns, stat.st_size)
        if not force and signature == self._signature:
            return
        records = load_key_records(self._path)
        if any(
            hmac.compare_digest(record.key_hash, self._admin_hash) for record in records
        ):
            raise KeyConfigurationError("a user key duplicates the administrator key")
        self._records = records
        self._signature = signature

    def authenticate(self, candidates: list[str]) -> Principal | None:
        """Return the matching identity while comparing every configured digest."""

        self._reload()
        matched: Principal | None = None
        for candidate in candidates:
            candidate_hash = hash_api_key(candidate)
            if hmac.compare_digest(candidate_hash, self._admin_hash):
                matched = Principal("admin", "Administrator", "admin")
            for record in self._records:
                if record.enabled and hmac.compare_digest(
                    candidate_hash, record.key_hash
                ):
                    matched = record.principal
        return matched

    def users(self) -> list[dict[str, Any]]:
        """Return non-secret user metadata for the administrator API."""

        self._reload()
        return [
            {
                "id": record.principal.key_id,
                "name": record.principal.name,
                "role": record.principal.role,
                "enabled": record.enabled,
                "created_at": record.created_at,
            }
            for record in self._records
        ]


def runtime_admin_key() -> str:
    """Load the primary key while retaining the 1.0 environment alias."""

    primary = os.getenv("CCOBRIDGE_API_KEY")
    legacy = os.getenv("LITELLM_MASTER_KEY")
    if primary and legacy and primary != legacy:
        raise KeyConfigurationError(
            "CCOBRIDGE_API_KEY and LITELLM_MASTER_KEY must match when both are set"
        )
    api_key = primary or legacy
    if not api_key:
        raise KeyConfigurationError("CCOBRIDGE_API_KEY is required")
    validate_api_key(api_key)
    return api_key
