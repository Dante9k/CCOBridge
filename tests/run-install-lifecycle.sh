#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VERSION="${1:-1.1.0}"
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
for source_path in Dockerfile gateway/proxy.py scripts/build-offline.sh tests/run-integration.sh; do
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
cp -- "$OFFLINE_INSTALL_DIR/.env" "$ENV_SNAPSHOT"

[[ "$(docker inspect --format '{{.HostConfig.RestartPolicy.Name}}' ccobridge)" == \
  "unless-stopped" ]]
[[ "$(docker inspect --format '{{.HostConfig.NetworkMode}}' ccobridge)" == "host" ]]
[[ "$(docker inspect --format '{{.Config.User}}' ccobridge)" == "10001:10001" ]]

"$OFFLINE_INSTALL_DIR/verify.sh"
INSTALL_DIR="$OFFLINE_INSTALL_DIR" "$BUNDLE_ROOT/deploy/install.sh" --offline
cmp --silent "$ENV_SNAPSHOT" "$OFFLINE_INSTALL_DIR/.env"

"$OFFLINE_INSTALL_DIR/uninstall.sh"
if docker inspect "$GATEWAY_CONTAINER" >/dev/null 2>&1; then
  printf '%s\n' 'Uninstall left the gateway container behind.' >&2
  exit 1
fi
[[ -r "$OFFLINE_INSTALL_DIR/.env" ]]
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
