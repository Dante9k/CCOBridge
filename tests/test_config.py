from __future__ import annotations

import unittest

from gateway.config import (
    AliasConfigurationError,
    load_model_aliases,
    resolve_model,
)


class ModelAliasTests(unittest.TestCase):
    def test_unset_configuration_enables_native_passthrough(self) -> None:
        self.assertEqual(load_model_aliases(None), {})
        self.assertEqual(load_model_aliases("  "), {})

    def test_valid_json_map_is_trimmed(self) -> None:
        aliases = load_model_aliases(
            '{" qwen-code ": " qwen3.8:latest ", "embed": "nomic:latest"}'
        )
        self.assertEqual(
            aliases,
            {"qwen-code": "qwen3.8:latest", "embed": "nomic:latest"},
        )

    def test_alias_and_native_model_resolution(self) -> None:
        aliases = {"qwen-code": "qwen3.8:latest"}
        self.assertEqual(resolve_model("qwen-code", aliases), "qwen3.8:latest")
        self.assertEqual(resolve_model("llama3.2:latest", aliases), "llama3.2:latest")

    def test_rejects_invalid_json_and_non_object_values(self) -> None:
        with self.assertRaises(AliasConfigurationError):
            load_model_aliases("not-json")
        with self.assertRaises(AliasConfigurationError):
            load_model_aliases('["qwen-code"]')

    def test_rejects_empty_or_self_referential_aliases(self) -> None:
        with self.assertRaises(AliasConfigurationError):
            load_model_aliases('{"": "qwen3.8:latest"}')
        with self.assertRaises(AliasConfigurationError):
            load_model_aliases('{"qwen-code": ""}')
        with self.assertRaises(AliasConfigurationError):
            load_model_aliases('{"qwen3.8:latest": "qwen3.8:latest"}')

    def test_rejects_whitespace_duplicates_and_alias_chains(self) -> None:
        with self.assertRaises(AliasConfigurationError):
            load_model_aliases('{"qwen code": "qwen3.8:latest"}')
        with self.assertRaises(AliasConfigurationError):
            load_model_aliases('{" qwen-code": "qwen3.8:a", "qwen-code ": "qwen3.8:b"}')
        with self.assertRaises(AliasConfigurationError):
            load_model_aliases(
                '{"qwen-code": "coding-model", "coding-model": "qwen3.8:latest"}'
            )


if __name__ == "__main__":
    unittest.main()
