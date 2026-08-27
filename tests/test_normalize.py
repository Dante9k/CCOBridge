from __future__ import annotations

import unittest

from gateway.normalize import (
    SystemMessageNormalizationError,
    normalize_anthropic_system_messages,
)


class NormalizeTests(unittest.TestCase):
    def test_non_object_payload_returns_original_object(self) -> None:
        payload = ["not", "an", "object"]
        result, changed = normalize_anthropic_system_messages(payload)
        self.assertFalse(changed)
        self.assertIs(result, payload)

    def test_no_system_message_returns_original_object(self) -> None:
        payload = {"messages": [{"role": "user", "content": "hello"}]}
        result, changed = normalize_anthropic_system_messages(payload)
        self.assertFalse(changed)
        self.assertIs(result, payload)

    def test_hoists_system_messages_and_preserves_order(self) -> None:
        payload = {
            "system": "top",
            "messages": [
                {"role": "user", "content": "one"},
                {"role": "assistant", "content": "two"},
                {
                    "role": "system",
                    "content": [
                        {
                            "type": "text",
                            "text": "middle",
                            "cache_control": {"type": "ephemeral"},
                        }
                    ],
                },
                {"role": "user", "content": "three"},
            ],
        }

        result, changed = normalize_anthropic_system_messages(payload)

        self.assertTrue(changed)
        self.assertEqual(
            [block["text"] for block in result["system"]], ["top", "middle"]
        )
        self.assertEqual(
            [message["role"] for message in result["messages"]],
            ["user", "assistant", "user"],
        )
        self.assertEqual(result["system"][1]["cache_control"], {"type": "ephemeral"})
        self.assertEqual(payload["messages"][2]["role"], "system")

    def test_hoists_string_system_messages_in_order(self) -> None:
        payload = {
            "messages": [
                {"role": "system", "content": "first"},
                {"role": "user", "content": "hello"},
                {"role": "system", "content": "second"},
            ]
        }

        result, changed = normalize_anthropic_system_messages(payload)

        self.assertTrue(changed)
        self.assertEqual(
            [block["text"] for block in result["system"]], ["first", "second"]
        )
        self.assertEqual(result["messages"], [{"role": "user", "content": "hello"}])

    def test_rejects_system_message_without_content(self) -> None:
        payload = {"messages": [{"role": "system"}]}
        with self.assertRaisesRegex(SystemMessageNormalizationError, "missing content"):
            normalize_anthropic_system_messages(payload)

    def test_rejects_non_text_system_block(self) -> None:
        payload = {
            "messages": [
                {
                    "role": "system",
                    "content": [{"type": "image", "source": {"data": "x"}}],
                }
            ]
        }
        with self.assertRaises(SystemMessageNormalizationError):
            normalize_anthropic_system_messages(payload)

    def test_rejects_non_text_top_level_system_block(self) -> None:
        payload = {
            "system": [{"type": "image", "source": {"data": "x"}}],
            "messages": [{"role": "system", "content": "move me"}],
        }
        with self.assertRaisesRegex(
            SystemMessageNormalizationError, "unsupported system block type"
        ):
            normalize_anthropic_system_messages(payload)


if __name__ == "__main__":
    unittest.main()
