#!/usr/bin/env bash
set -Eeuo pipefail

BUNDLE_ROOT="$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)"
INSTALL_DIR="$(readlink -m "${INSTALL_DIR:-/opt/ccobridge}")"
IMAGE_ARCHIVE="$BUNDLE_ROOT/image/ccobridge-1.1.0-linux-amd64.tar"

if [[ "$INSTALL_DIR" == "/" ]]; then
  printf '%s\n' 'Refusing to use the filesystem root as INSTALL_DIR.' >&2
  exit 1
fi

if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
  printf 'Run this installer as root: sudo %q\n' "$0" >&2
  exit 1
fi

case "$(uname -m)" in
  x86_64|amd64) ;;
  *)
    printf 'Unsupported architecture: %s (linux/amd64 is required).\n' "$(uname -m)" >&2
    exit 1
    ;;
esac

for command_name in docker curl sha256sum sort ss; do
  if ! command -v "$command_name" >/dev/null 2>&1; then
    printf 'Missing required command: %s\n' "$command_name" >&2
    exit 1
  fi
done

if ! docker info >/dev/null 2>&1; then
  printf '%s\n' 'Docker is unavailable.' >&2
  exit 1
fi
if ! docker compose version >/dev/null 2>&1; then
  printf '%s\n' 'The Docker Compose plugin is unavailable.' >&2
  exit 1
fi

EXISTING_CONTAINER_WORKDIR=""
EXISTING_CONTAINER_RUNNING="false"
if docker inspect ccobridge >/dev/null 2>&1; then
  EXISTING_CONTAINER_WORKDIR="$(
    docker inspect \
      --format '{{index .Config.Labels "com.docker.compose.project.working_dir"}}' \
      ccobridge
  )"
  EXISTING_CONTAINER_RUNNING="$(
    docker inspect --format '{{.State.Running}}' ccobridge
  )"
  if [[ "$EXISTING_CONTAINER_WORKDIR" != "$INSTALL_DIR" ]]; then
    printf '%s\n' \
      'A container named ccobridge exists outside the requested installation directory.' >&2
    exit 1
  fi
fi
if ss -ltn | grep -Eq ':4000[[:space:]]'; then
  if [[ "$EXISTING_CONTAINER_RUNNING" != "true" ]]; then
    printf '%s\n' 'TCP port 4000 is already in use by another service.' >&2
    exit 1
  fi
fi
if [[ ! -r "$IMAGE_ARCHIVE" ]]; then
  printf 'Image archive not found: %s\n' "$IMAGE_ARCHIVE" >&2
  exit 1
fi

printf '%s\n' '[1/6] Verifying bundle files...'
(cd "$BUNDLE_ROOT" && sha256sum -c SHA256SUMS)

printf '%s\n' '[2/6] Checking the host Ollama service and installed models...'
OLLAMA_TAGS="$(mktemp)"
OLLAMA_VERSION_FILE="$(mktemp)"
trap 'rm -f -- "$OLLAMA_TAGS" "$OLLAMA_VERSION_FILE"' EXIT
curl -fsS --max-time 10 http://127.0.0.1:11434/api/version -o "$OLLAMA_VERSION_FILE"
OLLAMA_VERSION="$(sed -n 's/.*"version"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' "$OLLAMA_VERSION_FILE")"
MINIMUM_OLLAMA_VERSION='0.13.3'
if [[ -z "$OLLAMA_VERSION" ]] \
  || [[ "$(printf '%s\n' "$MINIMUM_OLLAMA_VERSION" "$OLLAMA_VERSION" | sort -V | head -n 1)" != "$MINIMUM_OLLAMA_VERSION" ]]; then
  printf 'Ollama %s or newer is required; detected: %s\n' \
    "$MINIMUM_OLLAMA_VERSION" "${OLLAMA_VERSION:-unknown}" >&2
  exit 1
fi
curl -fsS --max-time 10 http://127.0.0.1:11434/api/tags -o "$OLLAMA_TAGS"
if ! grep -Eq '"models"[[:space:]]*:[[:space:]]*\[[[:space:]]*\{' "$OLLAMA_TAGS"; then
  printf '%s\n' 'Ollama has no installed models; installation stopped.' >&2
  exit 1
fi

printf '%s\n' '[3/6] Loading the offline Docker image...'
docker load -i "$IMAGE_ARCHIVE"

printf 'Installing into %s...\n' "$INSTALL_DIR"
install -d -m 0755 "$INSTALL_DIR"
install -m 0644 "$BUNDLE_ROOT/deploy/compose.yaml" "$INSTALL_DIR/compose.yaml"
for script_name in start stop logs verify uninstall; do
  install -m 0755 "$BUNDLE_ROOT/deploy/${script_name}.sh" "$INSTALL_DIR/${script_name}.sh"
done
install -m 0644 "$BUNDLE_ROOT/BUILD-INFO.txt" "$INSTALL_DIR/BUILD-INFO.txt"

if [[ ! -e "$INSTALL_DIR/.env" ]]; then
  printf '%s\n' '[4/6] Generating the shared API key...'
  umask 077
  RANDOM_HEX="$(od -An -N24 -tx1 /dev/urandom | tr -d ' \n')"
  {
    printf 'CCOBRIDGE_API_KEY=sk-%s\n' "$RANDOM_HEX"
    printf '%s\n' 'OLLAMA_API_BASE=http://127.0.0.1:11434'
    if grep -Eq '"(name|model)"[[:space:]]*:[[:space:]]*"qwen3\.8:latest"' "$OLLAMA_TAGS"; then
      printf '%s\n' 'CCOBRIDGE_MODEL_ALIASES={"qwen-code":"qwen3.8:latest"}'
    else
      printf '%s\n' 'CCOBRIDGE_MODEL_ALIASES={}'
    fi
  } > "$INSTALL_DIR/.env"
  chmod 0600 "$INSTALL_DIR/.env"
elif [[ -f "$INSTALL_DIR/.env" ]]; then
  chmod 0600 "$INSTALL_DIR/.env"
  printf '%s\n' '[4/6] Preserving the existing .env and API key.'
else
  printf '%s\n' 'The existing .env path is not a regular file.' >&2
  exit 1
fi

printf '%s\n' '[5/6] Starting the gateway without pulling images...'
(cd "$INSTALL_DIR" && docker compose --env-file .env up -d --pull never)

printf '%s\n' '[6/6] Waiting for readiness and running acceptance checks...'
for _attempt in $(seq 1 60); do
  if curl -fsS --max-time 3 http://127.0.0.1:4000/health/liveliness >/dev/null 2>&1; then
    break
  fi
  sleep 2
done
if ! curl -fsS --max-time 3 http://127.0.0.1:4000/health/liveliness >/dev/null; then
  (cd "$INSTALL_DIR" && docker compose logs --tail 200) >&2
  printf '%s\n' 'The gateway did not become ready before the timeout.' >&2
  exit 1
fi

"$INSTALL_DIR/verify.sh"

printf '\n%s\n' 'Installation complete.'
printf 'Gateway (on this server): %s\n' 'http://127.0.0.1:4000'
printf '%s\n' "Remote clients: replace 127.0.0.1 with this server's trusted-network address."
printf '%s\n' 'Models: query authenticated GET /v1/models for installed models and aliases.'
printf 'API key: stored in %s/.env with mode 0600; it is not printed.\n' "$INSTALL_DIR"
printf 'Management directory: %s\n' "$INSTALL_DIR"
