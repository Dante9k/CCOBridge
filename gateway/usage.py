"""Privacy-preserving, local token-usage aggregation."""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from gateway.auth import Principal

MAX_JSON_RESPONSE_BYTES = 4 * 1024 * 1024
UTC = timezone.utc  # noqa: UP017 - test tooling still supports Python 3.10.
MAX_PERFORMANCE_EVENTS = 1000


@dataclass(frozen=True, slots=True)
class RequestMetrics:
    """Privacy-safe timing measurements for one proxied inference request."""

    request_id: str
    streaming: bool
    upstream_headers_ms: float
    first_byte_ms: float | None
    total_ms: float


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
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS performance_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    recorded_at TEXT NOT NULL,
                    request_id TEXT NOT NULL UNIQUE,
                    key_id TEXT NOT NULL,
                    key_name TEXT NOT NULL,
                    model TEXT NOT NULL,
                    endpoint TEXT NOT NULL,
                    status_code INTEGER NOT NULL,
                    streaming INTEGER NOT NULL,
                    upstream_headers_ms REAL NOT NULL,
                    first_byte_ms REAL,
                    total_ms REAL NOT NULL,
                    metered INTEGER NOT NULL,
                    input_tokens INTEGER NOT NULL,
                    output_tokens INTEGER NOT NULL,
                    total_tokens INTEGER NOT NULL
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
        metrics: RequestMetrics,
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
            self._connection.execute(
                """
                INSERT INTO performance_events (
                    recorded_at, request_id, key_id, key_name, model, endpoint,
                    status_code, streaming, upstream_headers_ms, first_byte_ms,
                    total_ms, metered, input_tokens, output_tokens, total_tokens
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    now.isoformat().replace("+00:00", "Z"),
                    metrics.request_id,
                    principal.key_id,
                    principal.name,
                    model,
                    endpoint,
                    status_code,
                    int(metrics.streaming),
                    round(metrics.upstream_headers_ms, 3),
                    (
                        round(metrics.first_byte_ms, 3)
                        if metrics.first_byte_ms is not None
                        else None
                    ),
                    round(metrics.total_ms, 3),
                    int(usage.metered),
                    usage.input_tokens,
                    usage.output_tokens,
                    usage.total_tokens,
                ),
            )
            self._connection.execute(
                """
                DELETE FROM performance_events
                WHERE id NOT IN (
                    SELECT id FROM performance_events
                    ORDER BY id DESC
                    LIMIT ?
                )
                """,
                (MAX_PERFORMANCE_EVENTS,),
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

    def performance_report(
        self, limit: int, *, redact_users: bool = False
    ) -> dict[str, Any]:
        """Return recent timing events and an aggregate, without request content."""

        with self._lock:
            rows = self._connection.execute(
                """
                SELECT recorded_at, request_id, key_id, key_name, model, endpoint,
                       status_code, streaming, upstream_headers_ms, first_byte_ms,
                       total_ms, metered, input_tokens, output_tokens, total_tokens
                FROM performance_events
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        fields = (
            "recorded_at",
            "request_id",
            "user_id",
            "user_name",
            "model",
            "endpoint",
            "status_code",
            "streaming",
            "upstream_headers_ms",
            "first_byte_ms",
            "total_ms",
            "metered",
            "input_tokens",
            "output_tokens",
            "total_tokens",
        )
        events = [dict(zip(fields, row, strict=True)) for row in rows]
        for event in events:
            event["streaming"] = bool(event["streaming"])
            event["metered"] = bool(event["metered"])
            if redact_users:
                event["user_id"] = "redacted"
                event["user_name"] = "redacted"
            generation_ms = (
                float(event["total_ms"]) - float(event["first_byte_ms"])
                if event["streaming"] and event["first_byte_ms"] is not None
                else float(event["total_ms"])
            )
            event["observed_output_tokens_per_second"] = (
                round(int(event["output_tokens"]) * 1000 / generation_ms, 3)
                if int(event["output_tokens"]) > 0 and generation_ms > 0
                else None
            )

        def average(field: str) -> float | None:
            values = [
                float(event[field]) for event in events if event[field] is not None
            ]
            return round(sum(values) / len(values), 3) if values else None

        throughput = [
            float(event["observed_output_tokens_per_second"])
            for event in events
            if event["observed_output_tokens_per_second"] is not None
        ]
        return {
            "object": "performance_report",
            "retained_event_limit": MAX_PERFORMANCE_EVENTS,
            "returned_events": len(events),
            "summary": {
                "average_upstream_headers_ms": average("upstream_headers_ms"),
                "average_first_byte_ms": average("first_byte_ms"),
                "average_total_ms": average("total_ms"),
                "average_observed_output_tokens_per_second": (
                    round(sum(throughput) / len(throughput), 3) if throughput else None
                ),
            },
            "data": events,
        }
