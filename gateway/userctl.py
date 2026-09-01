"""Offline-safe CLI for managing hashed CCOBridge user keys."""

from __future__ import annotations

import argparse
import json
import os
import secrets
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from gateway.auth import KeyConfigurationError, hash_api_key, load_key_records

UTC = timezone.utc  # noqa: UP017 - the offline management CLI supports Python 3.10.


def _empty_document() -> dict[str, Any]:
    return {"version": 1, "users": []}


def _read_document(path: Path) -> dict[str, Any]:
    if not path.exists():
        return _empty_document()
    load_key_records(path)
    return json.loads(path.read_text(encoding="utf-8"))


def _write_document(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=".users.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(document, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o600)
        load_key_records(temporary)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _find_user(users: list[dict[str, Any]], identifier: str) -> dict[str, Any]:
    matches = [
        user
        for user in users
        if user.get("id") == identifier
        or str(user.get("name", "")).casefold() == identifier.casefold()
    ]
    if len(matches) != 1:
        raise KeyConfigurationError(f"user was not found: {identifier}")
    return matches[0]


def _new_key() -> str:
    return f"sk-{secrets.token_hex(24)}"


def _add(path: Path, name: str) -> None:
    document = _read_document(path)
    normalized_name = name.strip()
    if not normalized_name:
        raise KeyConfigurationError("user name cannot be empty")
    if any(
        str(user.get("name", "")).casefold() == normalized_name.casefold()
        for user in document["users"]
    ):
        raise KeyConfigurationError(f"user name already exists: {normalized_name}")
    api_key = _new_key()
    user = {
        "id": f"usr_{secrets.token_hex(8)}",
        "name": normalized_name,
        "role": "user",
        "key_hash": hash_api_key(api_key),
        "enabled": True,
        "created_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    }
    document["users"].append(user)
    _write_document(path, document)
    load_key_records(path)
    print(f"User ID: {user['id']}")
    print(f"API key (shown once): {api_key}")


def _list(path: Path) -> None:
    records = load_key_records(path) if path.exists() else ()
    print("ID\tNAME\tSTATUS\tCREATED_AT")
    for record in records:
        status = "enabled" if record.enabled else "disabled"
        print(
            f"{record.principal.key_id}\t{record.principal.name}\t"
            f"{status}\t{record.created_at}"
        )


def _set_enabled(path: Path, identifier: str, enabled: bool) -> None:
    document = _read_document(path)
    user = _find_user(document["users"], identifier)
    user["enabled"] = enabled
    _write_document(path, document)
    load_key_records(path)
    print(f"{user['id']} is now {'enabled' if enabled else 'disabled'}.")


def _rotate(path: Path, identifier: str) -> None:
    document = _read_document(path)
    user = _find_user(document["users"], identifier)
    api_key = _new_key()
    user["key_hash"] = hash_api_key(api_key)
    user["enabled"] = True
    _write_document(path, document)
    load_key_records(path)
    print(f"User ID: {user['id']}")
    print(f"New API key (shown once): {api_key}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--file", default="/etc/ccobridge/users.json", help="user-key JSON path"
    )
    subcommands = parser.add_subparsers(dest="command", required=True)
    add_parser = subcommands.add_parser("add", help="create a user and key")
    add_parser.add_argument("name")
    subcommands.add_parser("list", help="list users without key material")
    for command in ("disable", "enable", "rotate"):
        command_parser = subcommands.add_parser(command)
        command_parser.add_argument("identifier", help="user ID or exact name")
    args = parser.parse_args()
    path = Path(args.file)
    try:
        if args.command == "add":
            _add(path, args.name)
        elif args.command == "list":
            _list(path)
        elif args.command == "disable":
            _set_enabled(path, args.identifier, False)
        elif args.command == "enable":
            _set_enabled(path, args.identifier, True)
        elif args.command == "rotate":
            _rotate(path, args.identifier)
    except (KeyConfigurationError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
