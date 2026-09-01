from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from gateway.auth import Principal
from gateway.usage import UsageAccumulator, UsageStore


class UsageAccumulatorTests(unittest.TestCase):
    def test_reads_openai_json_usage(self) -> None:
        usage = UsageAccumulator("application/json")
        usage.feed(
            b'{"usage":{"prompt_tokens":12,"completion_tokens":3,"total_tokens":15}}'
        )
        usage.finish()
        self.assertTrue(usage.metered)
        self.assertEqual((usage.input_tokens, usage.output_tokens), (12, 3))
        self.assertEqual(usage.total_tokens, 15)

    def test_combines_anthropic_stream_usage(self) -> None:
        usage = UsageAccumulator("text/event-stream")
        usage.feed(
            b'event: message_start\ndata: {"message":{"usage":{"input_tokens":9,'
            b'"output_tokens":1}}}\n\n'
        )
        usage.feed(b'event: message_delta\ndata: {"usage":{"output_tokens":4}}\n\n')
        usage.finish()
        self.assertTrue(usage.metered)
        self.assertEqual((usage.input_tokens, usage.output_tokens), (9, 4))
        self.assertEqual(usage.total_tokens, 13)

    def test_marks_missing_usage_as_unmetered(self) -> None:
        usage = UsageAccumulator("text/event-stream")
        usage.feed(b'data: {"choices":[]}\n\ndata: [DONE]\n\n')
        usage.finish()
        self.assertFalse(usage.metered)


class UsageStoreTests(unittest.TestCase):
    def test_aggregates_without_storing_request_content(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "usage.sqlite3"
            store = UsageStore(str(path))
            try:
                principal = Principal("usr_0123456789abcdef", "alice", "user")
                usage = UsageAccumulator("application/json")
                usage.feed(
                    b'{"usage":{"input_tokens":5,"output_tokens":2,"total_tokens":7}}'
                )
                usage.finish()

                store.record(principal, "qwen-code", "/v1/messages", 200, usage)
                store.record(principal, "qwen-code", "/v1/messages", 200, usage)
                report = store.report(1, principal.key_id)

                self.assertEqual(report["totals"]["requests"], 2)
                self.assertEqual(report["totals"]["input_tokens"], 10)
                self.assertEqual(report["totals"]["output_tokens"], 4)
                self.assertEqual(report["totals"]["total_tokens"], 14)
                self.assertEqual(report["data"][0]["user_name"], "alice")
                self.assertNotIn("content", report["data"][0])
            finally:
                store.close()


if __name__ == "__main__":
    unittest.main()
