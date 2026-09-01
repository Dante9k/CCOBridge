#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VERSION="${1:-1.2.0}"
BUNDLE="$ROOT_DIR/dist/ccobridge-offline-${VERSION}-linux-amd64.tar.gz"
FAKE_CONTAINER="ccobridge-fake-ollama-lifecycle"
GATEWAY_CONTAINER="ccobridge"

if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
  printf '%s\n' 'Run the installation lifecycle test as root.' >&2
  exit 1
fi
for command_name in curl docker grep ss stat tar; do
  if ! command -v "$command_name" >/dev/null 2>&1; then
    printf 'Missing lifecycle-test command: %s\n' "$command_name" >&2
    exit 1
  fi
done
if [[ ! -r "$BUNDLE" ]]; then
  printf 'Offline bundle not found: %s\n' "$BUNDLE" >&2
  exit 1
fi
if docker inspect "$GATEWAY_CONTAINER" >/dev/null 2>&1; then
  printf 'Refusing to replace existing container: %s\n' "$GATEWAY_CONTAINER" >&2
  exit 1
fi
if docker inspect "$FAKE_CONTAINER" >/dev/null 2>&1; then
  printf 'Refusing to replace existing container: %s\n' "$FAKE_CONTAINER" >&2
  exit 1
fi
if ss -ltn | grep -Eq ':(4000|11434)[[:space:]]'; then
  printf '%s\n' 'Ports 4000 and 11434 must both be unused for this test.' >&2
  exit 1
fi

AUDIT_ROOT="$(mktemp -d /tmp/ccobridge-install-audit.XXXXXX)"
AUDIT_ID="$(basename "$AUDIT_ROOT")"
FAKE_IMAGE="ccobridge-fake-ollama:lifecycle-${AUDIT_ID}"
EXTRACT_DIR="$AUDIT_ROOT/extract"
OFFLINE_INSTALL_DIR="$AUDIT_ROOT/offline-install"
ONLINE_INSTALL_DIR="$AUDIT_ROOT/online-install"
ENV_SNAPSHOT="$AUDIT_ROOT/env.snapshot"
USER_AUTH_HEADER="$AUDIT_ROOT/user-auth-header"

cleanup() {
  gateway_project_dir="$(
    docker inspect \
      --format '{{index .Config.Labels "com.docker.compose.project.working_dir"}}' \
      "$GATEWAY_CONTAINER" 2>/dev/null || true
  )"
  case "$gateway_project_dir" in
    "$OFFLINE_INSTALL_DIR"|"$ONLINE_INSTALL_DIR")
      docker rm -f "$GATEWAY_CONTAINER" >/dev/null 2>&1 || true
      ;;
  esac
  fake_audit_id="$(
    docker inspect \
      --format '{{index .Config.Labels "ccobridge.lifecycle.audit"}}' \
      "$FAKE_CONTAINER" 2>/dev/null || true
  )"
  if [[ "$fake_audit_id" == "$AUDIT_ID" ]]; then
    docker rm -f "$FAKE_CONTAINER" >/dev/null 2>&1 || true
  fi
  docker image rm "$FAKE_IMAGE" >/dev/null 2>&1 || true
  case "$AUDIT_ROOT" in
    /tmp/ccobridge-install-audit.*)
      rm -rf -- "$AUDIT_ROOT"
      ;;
    *)
      printf 'Refusing to remove unexpected audit directory: %s\n' \
        "$AUDIT_ROOT" >&2
      ;;
  esac
}
trap cleanup EXIT

mkdir -p "$EXTRACT_DIR"
tar -C "$EXTRACT_DIR" -xzf "$BUNDLE"
BUNDLE_ROOT="$EXTRACT_DIR/ccobridge-offline-${VERSION}"
if [[ ! -x "$BUNDLE_ROOT/deploy/install.sh" ]]; then
  printf '%s\n' 'Extracted installer is missing or not executable.' >&2
  exit 1
fi
for source_path in \
  Dockerfile \
  gateway/auth.py \
  gateway/proxy.py \
  gateway/usage.py \
  gateway/userctl.py \
  scripts/build-offline.sh \
  tests/run-integration.sh; do
  if [[ ! -r "$BUNDLE_ROOT/$source_path" ]]; then
    printf 'Offline bundle is missing source file: %s\n' "$source_path" >&2
    exit 1
  fi
done

docker build \
  --platform linux/amd64 \
  -f "$ROOT_DIR/tests/Dockerfile.fake-ollama" \
  -t "$FAKE_IMAGE" \
  "$ROOT_DIR" >/dev/null

docker run -d --rm \
  --name "$FAKE_CONTAINER" \
  --network host \
  --label "ccobridge.lifecycle.audit=$AUDIT_ID" \
  "$FAKE_IMAGE" \
  --host 0.0.0.0 \
  --port 11434 >/dev/null

for _attempt in $(seq 1 30); do
  if curl -fsS http://127.0.0.1:11434/api/version >/dev/null 2>&1; then
    break
  fi
  sleep 0.2
done
curl -fsS http://127.0.0.1:11434/api/version >/dev/null

INSTALL_DIR="$OFFLINE_INSTALL_DIR" "$BUNDLE_ROOT/deploy/install.sh"
[[ "$(stat -c '%a' "$OFFLINE_INSTALL_DIR/.env")" == "600" ]]
[[ "$(stat -c '%a' "$OFFLINE_INSTALL_DIR/config/users.json")" == "600" ]]
[[ "$(stat -c '%u:%g' "$OFFLINE_INSTALL_DIR/config/users.json")" == "10001:10001" ]]
[[ "$(stat -c '%a' "$OFFLINE_INSTALL_DIR/data")" == "700" ]]
cp -- "$OFFLINE_INSTALL_DIR/.env" "$ENV_SNAPSHOT"

[[ "$(docker inspect --format '{{.HostConfig.RestartPolicy.Name}}' ccobridge)" == \
  "unless-stopped" ]]
[[ "$(docker inspect --format '{{.HostConfig.NetworkMode}}' ccobridge)" == "host" ]]
[[ "$(docker inspect --format '{{.Config.User}}' ccobridge)" == "10001:10001" ]]

"$OFFLINE_INSTALL_DIR/verify.sh"
USER_OUTPUT="$("$OFFLINE_INSTALL_DIR/users.sh" add alice)"
USER_ID="$(printf '%s\n' "$USER_OUTPUT" | sed -n 's/^User ID: //p')"
USER_KEY="$(printf '%s\n' "$USER_OUTPUT" | sed -n 's/^API key (shown once): //p')"
[[ "$USER_ID" =~ ^usr_[0-9a-f]{16}$ ]]
[[ "$USER_KEY" == sk-* ]]
if grep -Fq "$USER_KEY" "$OFFLINE_INSTALL_DIR/config/users.json"; then
  printf '%s\n' 'A plaintext user API key was stored on disk.' >&2
  exit 1
fi
umask 077
printf 'Authorization: Bearer %s\n' "$USER_KEY" > "$USER_AUTH_HEADER"
curl -fsS \
  -H "@$USER_AUTH_HEADER" \
  -H 'Content-Type: application/json' \
  -d '{"model":"qwen-code","messages":[{"role":"user","content":"USAGE_TEST"}],"stream":false}' \
  http://127.0.0.1:4000/v1/chat/completions >/dev/null
USAGE_REPORT="$("$OFFLINE_INSTALL_DIR/usage.sh" 1 "$USER_ID")"
if ! grep -Eq '"total_tokens":[1-9][0-9]*' <<< "$USAGE_REPORT"; then
  printf '%s\n' 'Per-user token usage was not persisted.' >&2
  exit 1
fi
"$OFFLINE_INSTALL_DIR/users.sh" disable "$USER_ID" >/dev/null
USER_STATUS="$(curl -sS -o /dev/null -w '%{http_code}' \
  -H "@$USER_AUTH_HEADER" http://127.0.0.1:4000/v1/models)"
[[ "$USER_STATUS" == "401" ]]
"$OFFLINE_INSTALL_DIR/users.sh" enable "$USER_ID" >/dev/null

INSTALL_DIR="$OFFLINE_INSTALL_DIR" "$BUNDLE_ROOT/deploy/install.sh" --offline
cmp --silent "$ENV_SNAPSHOT" "$OFFLINE_INSTALL_DIR/.env"
"$OFFLINE_INSTALL_DIR/users.sh" list | grep -Fq "$USER_ID"
[[ -s "$OFFLINE_INSTALL_DIR/data/usage.sqlite3" ]]
[[ "$(stat -c '%a' "$OFFLINE_INSTALL_DIR/data/usage.sqlite3")" == "600" ]]

"$OFFLINE_INSTALL_DIR/uninstall.sh"
if docker inspect "$GATEWAY_CONTAINER" >/dev/null 2>&1; then
  printf '%s\n' 'Uninstall left the gateway container behind.' >&2
  exit 1
fi
[[ -r "$OFFLINE_INSTALL_DIR/.env" ]]
[[ -r "$OFFLINE_INSTALL_DIR/config/users.json" ]]
[[ -s "$OFFLINE_INSTALL_DIR/data/usage.sqlite3" ]]
docker image inspect "ccobridge:${VERSION}" >/dev/null

docker image rm "ccobridge:${VERSION}" >/dev/null
INSTALL_DIR="$ONLINE_INSTALL_DIR" "$ROOT_DIR/deploy/install.sh" --online
[[ "$(stat -c '%a' "$ONLINE_INSTALL_DIR/.env")" == "600" ]]
grep -Fqx 'install_mode=source-build' "$ONLINE_INSTALL_DIR/BUILD-INFO.txt"
"$ONLINE_INSTALL_DIR/verify.sh"
"$ONLINE_INSTALL_DIR/uninstall.sh"
if docker inspect "$GATEWAY_CONTAINER" >/dev/null 2>&1; then
  printf '%s\n' 'Source installation uninstall left the gateway container behind.' >&2
  exit 1
fi
[[ -r "$ONLINE_INSTALL_DIR/.env" ]]
docker image inspect "ccobridge:${VERSION}" >/dev/null

printf '%s\n' \
  'Installation lifecycle passed: offline and source install, verify, repeat, and uninstall.'
