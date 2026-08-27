from __future__ import annotations

import unittest

from gateway.models import ModelDiscoveryError, openai_models_from_tags


class ModelDiscoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tags = {
            "models": [
                {
                    "name": "qwen3.8:latest",
                    "model": "qwen3.8:latest",
                    "modified_at": "2026-08-27T00:00:00Z",
                },
                {
                    "name": "nomic-embed-text:latest",
                    "modified_at": "invalid",
                },
            ]
        }

    def test_native_models_and_installed_aliases_are_exposed(self) -> None:
        models = openai_models_from_tags(
            self.tags,
            {
                "qwen-code": "qwen3.8:latest",
                "embed": "nomic-embed-text:latest",
                "missing": "not-installed:latest",
            },
        )

        self.assertEqual(
            [model["id"] for model in models],
            [
                "embed",
                "nomic-embed-text:latest",
                "qwen-code",
                "qwen3.8:latest",
            ],
        )
        model_by_id = {model["id"]: model for model in models}
        self.assertEqual(model_by_id["nomic-embed-text:latest"]["created"], 0)
        self.assertEqual(model_by_id["qwen-code"]["owned_by"], "ccobridge")

    def test_configured_alias_wins_over_a_conflicting_native_name(self) -> None:
        models = openai_models_from_tags(
            self.tags, {"qwen3.8:latest": "nomic-embed-text:latest"}
        )
        matching = [model for model in models if model["id"] == "qwen3.8:latest"]
        self.assertEqual(len(matching), 1)
        self.assertEqual(matching[0]["owned_by"], "ccobridge")

    def test_rejects_malformed_ollama_responses(self) -> None:
        for payload in ({}, {"models": None}, {"models": ["bad"]}):
            with self.subTest(payload=payload), self.assertRaises(ModelDiscoveryError):
                openai_models_from_tags(payload, {})


if __name__ == "__main__":
    unittest.main()
