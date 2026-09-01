from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from gateway.auth import (
    KeyConfigurationError,
    KeyStore,
    hash_api_key,
    load_key_records,
)


class KeyStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "users.json"
        self.user_key = "sk-user-test-1234567"
        self.path.write_text(
            json.dumps(
                {
                    "version": 1,
                    "users": [
                        {
                            "id": "usr_0123456789abcdef",
                            "name": "alice",
                            "role": "user",
                            "key_hash": hash_api_key(self.user_key),
                            "enabled": True,
                            "created_at": "2026-08-31T00:00:00Z",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

    def test_authenticates_admin_and_hashed_user(self) -> None:
        store = KeyStore("sk-admin-test-123456", str(self.path))
        admin = store.authenticate(["sk-admin-test-123456"])
        user = store.authenticate([self.user_key])

        self.assertEqual(admin.key_id, "admin")
        self.assertEqual(admin.role, "admin")
        self.assertEqual(user.key_id, "usr_0123456789abcdef")
        self.assertEqual(user.name, "alice")
        self.assertIsNone(store.authenticate(["sk-wrong-test-123456"]))

    def test_disabled_user_is_rejected_after_reload(self) -> None:
        store = KeyStore("sk-admin-test-123456", str(self.path))
        document = json.loads(self.path.read_text(encoding="utf-8"))
        document["users"][0]["enabled"] = False
        self.path.write_text(json.dumps(document, indent=2), encoding="utf-8")

        self.assertIsNone(store.authenticate([self.user_key]))

    def test_plaintext_key_and_duplicate_metadata_are_rejected(self) -> None:
        document = json.loads(self.path.read_text(encoding="utf-8"))
        document["users"][0]["key"] = self.user_key
        document["users"].append(dict(document["users"][0]))
        self.path.write_text(json.dumps(document), encoding="utf-8")
        with self.assertRaises(KeyConfigurationError):
            load_key_records(self.path)

    def test_duplicate_admin_key_is_rejected(self) -> None:
        admin_key = "sk-admin-test-123456"
        document = json.loads(self.path.read_text(encoding="utf-8"))
        document["users"][0]["key_hash"] = hash_api_key(admin_key)
        self.path.write_text(json.dumps(document), encoding="utf-8")
        with self.assertRaises(KeyConfigurationError):
            KeyStore(admin_key, str(self.path))


if __name__ == "__main__":
    unittest.main()
