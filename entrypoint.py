"""Run LiteLLM internally and the compatibility proxy as PID 1 supervisor."""

from __future__ import annotations

import os
import shutil
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

STOP_REQUESTED = False


def _request_stop(_signum: int, _frame: object) -> None:
    global STOP_REQUESTED
    STOP_REQUESTED = True


def _wait_for_port(
    process: subprocess.Popen[bytes], port: int, timeout: int = 90
) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(
                f"LiteLLM exited during startup with code {process.returncode}"
            )
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1):
                return
        except OSError:
            time.sleep(0.5)
    raise TimeoutError(f"LiteLLM did not listen on 127.0.0.1:{port} within {timeout}s")


def _stop(process: subprocess.Popen[bytes] | None) -> None:
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=15)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def main() -> int:
    config_path = Path(
        os.getenv("LITELLM_CONFIG_PATH", "/app/ccobridge/litellm-config.yaml")
    )
    if not config_path.is_file():
        print(f"Configuration file not found: {config_path}", file=sys.stderr)
        return 2

    litellm = shutil.which("litellm")
    if not litellm:
        print("LiteLLM executable not found in the base image", file=sys.stderr)
        return 2

    api_key = os.getenv("CCOBRIDGE_API_KEY") or os.getenv("LITELLM_MASTER_KEY")
    if not api_key:
        print("CCOBRIDGE_API_KEY is required", file=sys.stderr)
        return 2
    if (
        os.getenv("CCOBRIDGE_API_KEY")
        and os.getenv("LITELLM_MASTER_KEY")
        and os.environ["CCOBRIDGE_API_KEY"] != os.environ["LITELLM_MASTER_KEY"]
    ):
        print(
            "CCOBRIDGE_API_KEY and LITELLM_MASTER_KEY must match when both are set",
            file=sys.stderr,
        )
        return 2
    os.environ["CCOBRIDGE_API_KEY"] = api_key
    os.environ["LITELLM_MASTER_KEY"] = api_key

    internal_port = int(os.getenv("INTERNAL_LITELLM_PORT", "4001"))
    gateway_host = os.getenv("GATEWAY_HOST", "0.0.0.0")
    gateway_port = int(os.getenv("GATEWAY_PORT", "4000"))
    if not 1 <= internal_port <= 65535 or not 1 <= gateway_port <= 65535:
        print("Gateway ports must be between 1 and 65535", file=sys.stderr)
        return 2
    if internal_port == gateway_port:
        print("Gateway and internal LiteLLM ports must differ", file=sys.stderr)
        return 2
    log_level = os.getenv("GATEWAY_LOG_LEVEL", "info")

    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, _request_stop)

    litellm_process: subprocess.Popen[bytes] | None = None
    proxy_process: subprocess.Popen[bytes] | None = None
    try:
        litellm_process = subprocess.Popen(
            [
                litellm,
                "--config",
                str(config_path),
                "--host",
                "127.0.0.1",
                "--port",
                str(internal_port),
                "--num_workers",
                "1",
            ]
        )
        _wait_for_port(litellm_process, internal_port)

        proxy_process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "gateway.proxy:app",
                "--app-dir",
                "/app/ccobridge",
                "--host",
                gateway_host,
                "--port",
                str(gateway_port),
                "--workers",
                "1",
                "--log-level",
                log_level,
                "--no-access-log",
            ]
        )

        while not STOP_REQUESTED:
            if litellm_process.poll() is not None:
                print(
                    "LiteLLM exited unexpectedly with code "
                    f"{litellm_process.returncode}",
                    file=sys.stderr,
                )
                return litellm_process.returncode or 1
            if proxy_process.poll() is not None:
                print(
                    "Compatibility proxy exited unexpectedly with code "
                    f"{proxy_process.returncode}",
                    file=sys.stderr,
                )
                return proxy_process.returncode or 1
            time.sleep(0.5)
        return 0
    except (RuntimeError, TimeoutError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    finally:
        _stop(proxy_process)
        _stop(litellm_process)


if __name__ == "__main__":
    raise SystemExit(main())
