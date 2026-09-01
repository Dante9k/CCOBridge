"""Privacy-preserving, local token-usage aggregation."""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from contextlib import suppress
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from gateway.auth import Principal

MAX_JSON_RESPONSE_BYTES = 4 * 1024 * 1024
UTC = timezone.utc  # noqa: UP017 - test tooling still supports Python 3.10.


def _token_value(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


class UsageAccumulator:
    """Extract cumulative token counters from JSON, SSE, or NDJSON responses."""

    def __init__(self, content_type: str) -> None:
        normalized = content_type.lower()
        self._line_mode = "event-stream" in normalized or "ndjson" in normalized
        self._buffer = bytearray()
        self._discarded = False
        self.input_tokens = 0
        self.output_tokens = 0
        self.total_tokens = 0
        self.metered = False

    def _apply_usage(self, value: dict[str, Any]) -> None:
        input_tokens = next(
            (
                token
                for key in ("input_tokens", "prompt_tokens", "prompt_eval_count")
                if (token := _token_value(value.get(key))) is not None
            ),
            None,
        )
        output_tokens = next(
            (
                token
                for key in ("output_tokens", "completion_tokens", "eval_count")
                if (token := _token_value(value.get(key))) is not None
            ),
            None,
        )
        total_tokens = _token_value(value.get("total_tokens"))
        if input_tokens is None and output_tokens is None and total_tokens is None:
            return
        self.metered = True
        if input_tokens is not None:
            self.input_tokens = max(self.input_tokens, input_tokens)
        if output_tokens is not None:
            self.output_tokens = max(self.output_tokens, output_tokens)
        if total_tokens is not None:
            self.total_tokens = max(self.total_tokens, total_tokens)
        self.total_tokens = max(
            self.total_tokens, self.input_tokens + self.output_tokens
        )

    def _visit(self, value: Any) -> None:
        if isinstance(value, dict):
            reported_usage = value.get("usage")
            if isinstance(reported_usage, dict):
                self._apply_usage(reported_usage)
            if "prompt_eval_count" in value or "eval_count" in value:
                self._apply_usage(value)
            for child in value.values():
                self._visit(child)
        elif isinstance(value, list):
            for child in value:
                self._visit(child)

    def _parse_line(self, raw_line: bytes) -> None:
        line = raw_line.strip()
        if line.startswith(b"data:"):
            line = line.removeprefix(b"data:").strip()
        if not line or line == b"[DONE]" or line.startswith(b"event:"):
            return
        try:
            self._visit(json.loads(line))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return

    def feed(self, chunk: bytes) -> None:
        if self._discarded:
            return
        self._buffer.extend(chunk)
        if self._line_mode:
            while b"\n" in self._buffer:
                line, _, remainder = self._buffer.partition(b"\n")
                self._buffer = bytearray(remainder)
                self._parse_line(line)
            if len(self._buffer) > MAX_JSON_RESPONSE_BYTES:
                self._buffer.clear()
                self._discarded = True
        elif len(self._buffer) > MAX_JSON_RESPONSE_BYTES:
            self._buffer.clear()
            self._discarded = True

    def finish(self) -> None:
        if self._discarded or not self._buffer:
            return
        if self._line_mode:
            self._parse_line(bytes(self._buffer))
        else:
            with suppress(UnicodeDecodeError, json.JSONDecodeError):
                self._visit(json.loads(self._buffer))
        self._buffer.clear()


class UsageStore:
    """Aggregate usage per UTC day, user, model, and endpoint in SQLite."""

    def __init__(self, path: str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(self.path, check_same_thread=False)
        self._lock = threading.Lock()
        with self._connection:
            self._connection.execute("PRAGMA journal_mode=WAL")
            self._connection.execute("PRAGMA synchronous=NORMAL")
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS usage_daily (
                    day TEXT NOT NULL,
                    key_id TEXT NOT NULL,
                    key_name TEXT NOT NULL,
                    model TEXT NOT NULL,
                    endpoint TEXT NOT NULL,
                    requests INTEGER NOT NULL DEFAULT 0,
                    successful_requests INTEGER NOT NULL DEFAULT 0,
                    metered_requests INTEGER NOT NULL DEFAULT 0,
                    input_tokens INTEGER NOT NULL DEFAULT 0,
                    output_tokens INTEGER NOT NULL DEFAULT 0,
                    total_tokens INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (day, key_id, model, endpoint)
                )
                """
            )
        os.chmod(self.path, 0o600)

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def record(
        self,
        principal: Principal,
        model: str,
        endpoint: str,
        status_code: int,
        usage: UsageAccumulator,
    ) -> None:
        now = datetime.now(UTC)
        successful = int(200 <= status_code < 400)
        with self._lock, self._connection:
            self._connection.execute(
                """
                INSERT INTO usage_daily (
                    day, key_id, key_name, model, endpoint, requests,
                    successful_requests, metered_requests, input_tokens,
                    output_tokens, total_tokens, updated_at
                ) VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(day, key_id, model, endpoint) DO UPDATE SET
                    key_name = excluded.key_name,
                    requests = requests + 1,
                    successful_requests = successful_requests +
                        excluded.successful_requests,
                    metered_requests = metered_requests + excluded.metered_requests,
                    input_tokens = input_tokens + excluded.input_tokens,
                    output_tokens = output_tokens + excluded.output_tokens,
                    total_tokens = total_tokens + excluded.total_tokens,
                    updated_at = excluded.updated_at
                """,
                (
                    now.date().isoformat(),
                    principal.key_id,
                    principal.name,
                    model,
                    endpoint,
                    successful,
                    int(usage.metered),
                    usage.input_tokens,
                    usage.output_tokens,
                    usage.total_tokens,
                    now.isoformat().replace("+00:00", "Z"),
                ),
            )

    def report(self, days: int, key_id: str | None = None) -> dict[str, Any]:
        today = datetime.now(UTC).date()
        since = today - timedelta(days=days - 1)
        where = "day >= ?"
        parameters: list[Any] = [since.isoformat()]
        if key_id:
            where += " AND key_id = ?"
            parameters.append(key_id)
        with self._lock:
            rows = self._connection.execute(
                f"""
                SELECT day, key_id, key_name, model, endpoint, requests,
                       successful_requests, metered_requests, input_tokens,
                       output_tokens, total_tokens
                FROM usage_daily
                WHERE {where}
                ORDER BY day DESC, key_name, model, endpoint
                """,
                parameters,
            ).fetchall()

        fields = (
            "date",
            "user_id",
            "user_name",
            "model",
            "endpoint",
            "requests",
            "successful_requests",
            "metered_requests",
            "input_tokens",
            "output_tokens",
            "total_tokens",
        )
        data = [dict(zip(fields, row, strict=True)) for row in rows]
        count_fields = fields[5:]
        totals = {
            field: sum(int(item[field]) for item in data) for field in count_fields
        }
        return {
            "object": "usage_report",
            "period": {
                "days": days,
                "since": since.isoformat(),
                "until": today.isoformat(),
            },
            "filter": {"user_id": key_id},
            "totals": totals,
            "data": data,
        }
