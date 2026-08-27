#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IMAGE="${1:-ccobridge:1.1.0}"
CONTAINER_NAME="ccobridge-integration"
FAKE_IMAGE="ccobridge-fake-ollama:test"
FAKE_CONTAINER_NAME="ccobridge-fake-ollama-integration"
CONTAINER_LOG="$(mktemp)"
FAKE_LOG="$(mktemp)"

cleanup() {
  docker logs "$CONTAINER_NAME" >"$CONTAINER_LOG" 2>&1 || true
  docker logs "$FAKE_CONTAINER_NAME" >"$FAKE_LOG" 2>&1 || true
  docker rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || true
  docker rm -f "$FAKE_CONTAINER_NAME" >/dev/null 2>&1 || true
  if [[ "${TEST_PASSED:-0}" != "1" ]]; then
    printf '%s\n' '--- Fake Ollama log ---' >&2
    tail -n 100 "$FAKE_LOG" >&2 || true
    printf '%s\n' '--- Gateway log ---' >&2
    tail -n 200 "$CONTAINER_LOG" >&2 || true
  fi
  rm -f -- "$FAKE_LOG" "$CONTAINER_LOG"
}
trap cleanup EXIT

PYTHONPATH="$ROOT_DIR" python3 -m unittest discover -s "$ROOT_DIR/tests" -p 'test_*.py'

docker build \
  --platform linux/amd64 \
  -f "$ROOT_DIR/tests/Dockerfile.fake-ollama" \
  -t "$FAKE_IMAGE" \
  "$ROOT_DIR" >/dev/null

docker rm -f "$FAKE_CONTAINER_NAME" >/dev/null 2>&1 || true
docker run -d --rm \
  --name "$FAKE_CONTAINER_NAME" \
  --network host \
  "$FAKE_IMAGE" >/dev/null

for _attempt in $(seq 1 30); do
  if curl -fsS http://127.0.0.1:11435/api/tags >/dev/null 2>&1; then
    break
  fi
  sleep 0.2
done
if ! curl -fsS http://127.0.0.1:11435/api/tags >/dev/null; then
  printf '%s\n' 'Fake Ollama did not become ready.' >&2
  exit 1
fi

docker rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || true
docker run -d --rm \
  --name "$CONTAINER_NAME" \
  --network host \
  -e GATEWAY_PORT=14000 \
  -e INTERNAL_LITELLM_PORT=14001 \
  -e OLLAMA_API_BASE=http://127.0.0.1:11435 \
  -e CCOBRIDGE_API_KEY=sk-local-integration-test \
  -e 'CCOBRIDGE_MODEL_ALIASES={"qwen-code":"qwen3.8:latest","local-embed":"nomic-embed-text:latest"}' \
  "$IMAGE" >/dev/null

python3 "$ROOT_DIR/tests/integration_test.py"
TEST_PASSED=1
