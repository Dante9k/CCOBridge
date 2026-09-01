#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IMAGE="${1:-ccobridge:1.2.0}"
CONTAINER_NAME="ccobridge-integration"
FAKE_IMAGE="ccobridge-fake-ollama:test"
FAKE_CONTAINER_NAME="ccobridge-fake-ollama-integration"
CONTAINER_LOG="$(mktemp)"
FAKE_LOG="$(mktemp)"
RUNTIME_DIR="$(mktemp -d /tmp/ccobridge-integration.XXXXXX)"
USER_KEY="sk-local-user-test"

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
  case "$RUNTIME_DIR" in
    /tmp/ccobridge-integration.*) rm -rf -- "$RUNTIME_DIR" ;;
  esac
}
trap cleanup EXIT

PYTHONPATH="$ROOT_DIR" python3 -m unittest discover -s "$ROOT_DIR/tests" -p 'test_*.py'

mkdir -p "$RUNTIME_DIR/config" "$RUNTIME_DIR/data"
chmod 0777 "$RUNTIME_DIR/data"
USER_KEY_HASH="$(printf '%s' "$USER_KEY" | sha256sum | cut -d ' ' -f 1)"
printf '%s\n' \
  "{\"version\":1,\"users\":[{\"id\":\"usr_0123456789abcdef\",\"name\":\"alice\",\"role\":\"user\",\"key_hash\":\"sha256:${USER_KEY_HASH}\",\"enabled\":true,\"created_at\":\"2026-08-31T00:00:00Z\"}]}" \
  > "$RUNTIME_DIR/config/users.json"

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
  -e CCOBRIDGE_KEYS_FILE=/etc/ccobridge/users.json \
  -e CCOBRIDGE_USAGE_DB=/var/lib/ccobridge/usage.sqlite3 \
  -e 'CCOBRIDGE_MODEL_ALIASES={"qwen-code":"qwen3.8:latest","local-embed":"nomic-embed-text:latest"}' \
  -v "$RUNTIME_DIR/config:/etc/ccobridge:ro" \
  -v "$RUNTIME_DIR/data:/var/lib/ccobridge" \
  "$IMAGE" >/dev/null

python3 "$ROOT_DIR/tests/integration_test.py" --user-key "$USER_KEY"
TEST_PASSED=1
