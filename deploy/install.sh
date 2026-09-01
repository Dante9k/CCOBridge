#!/usr/bin/env bash
set -Eeuo pipefail

VERSION="1.2.0"
IMAGE="ccobridge:${VERSION}"
BASE_TAG="ghcr.io/berriai/litellm:v1.94.0"
BUNDLE_ROOT="$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)"
INSTALL_DIR="$(readlink -m "${INSTALL_DIR:-/opt/ccobridge}")"
IMAGE_ARCHIVE="$BUNDLE_ROOT/image/ccobridge-${VERSION}-linux-amd64.tar"
INSTALL_MODE="auto"
BUILD_INFO_SOURCE=""
BUILD_INFO_TMP=""
USER_KEY_TMP=""

usage() {
  cat <<'EOF'
Usage: sudo ./deploy/install.sh [--auto|--online|--offline]

  --auto     Load a bundled image when present; otherwise build from source.
  --online   Build from this source tree using the pinned LiteLLM base image.
  --offline  Require and load the bundled Docker image without network access.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --auto) INSTALL_MODE="auto" ;;
    --online) INSTALL_MODE="online" ;;
    --offline) INSTALL_MODE="offline" ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      printf 'Unknown installer option: %s\n' "$1" >&2
      usage >&2
      exit 2
      ;;
  esac
  shift
done

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

if [[ "$INSTALL_MODE" == "auto" ]]; then
  if [[ -r "$IMAGE_ARCHIVE" ]]; then
    INSTALL_MODE="offline"
  elif [[ -r "$BUNDLE_ROOT/Dockerfile" && -r "$BUNDLE_ROOT/BASE-IMAGE.lock" ]]; then
    INSTALL_MODE="online"
  else
    printf '%s\n' \
      'Neither a bundled image nor a complete CCOBridge source tree was found.' >&2
    exit 1
  fi
fi

for command_name in docker curl sort ss; do
  if ! command -v "$command_name" >/dev/null 2>&1; then
    printf 'Missing required command: %s\n' "$command_name" >&2
    exit 1
  fi
done
if [[ "$INSTALL_MODE" == "offline" ]] \
  && ! command -v sha256sum >/dev/null 2>&1; then
  printf '%s\n' 'Missing required command: sha256sum' >&2
  exit 1
fi

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

OLLAMA_TAGS="$(mktemp)"
OLLAMA_VERSION_FILE="$(mktemp)"
cleanup() {
  rm -f -- "$OLLAMA_TAGS" "$OLLAMA_VERSION_FILE"
  if [[ -n "$BUILD_INFO_TMP" ]]; then
    rm -f -- "$BUILD_INFO_TMP"
  fi
  if [[ -n "$USER_KEY_TMP" ]]; then
    rm -f -- "$USER_KEY_TMP"
  fi
}
trap cleanup EXIT

if [[ "$INSTALL_MODE" == "offline" ]]; then
  if [[ ! -r "$IMAGE_ARCHIVE" ]]; then
    printf 'Offline image archive not found: %s\n' "$IMAGE_ARCHIVE" >&2
    exit 1
  fi
  if [[ ! -r "$BUNDLE_ROOT/SHA256SUMS" ]]; then
    printf 'Offline checksum manifest not found: %s\n' "$BUNDLE_ROOT/SHA256SUMS" >&2
    exit 1
  fi
  printf '%s\n' '[1/6] Verifying the offline bundle...'
  (cd "$BUNDLE_ROOT" && sha256sum -c SHA256SUMS)
else
  for source_path in Dockerfile BASE-IMAGE.lock entrypoint.py gateway litellm-config.yaml; do
    if [[ ! -e "$BUNDLE_ROOT/$source_path" ]]; then
      printf 'Incomplete source tree; missing: %s\n' "$source_path" >&2
      exit 1
    fi
  done
  printf '%s\n' '[1/6] Validating the source build inputs...'
fi

printf '%s\n' '[2/6] Checking the host Ollama service and installed models...'
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

if [[ "$INSTALL_MODE" == "offline" ]]; then
  printf '%s\n' '[3/6] Loading the bundled Docker image...'
  docker load -i "$IMAGE_ARCHIVE"
  BUILD_INFO_SOURCE="$BUNDLE_ROOT/BUILD-INFO.txt"
  if [[ ! -r "$BUILD_INFO_SOURCE" ]]; then
    printf 'Offline build information not found: %s\n' "$BUILD_INFO_SOURCE" >&2
    exit 1
  fi
else
  printf '%s\n' '[3/6] Building the Docker image from source...'
  LOCKED_DIGEST="$(sed -n 's/^digest=//p' "$BUNDLE_ROOT/BASE-IMAGE.lock")"
  if [[ ! "$LOCKED_DIGEST" =~ ^sha256:[0-9a-f]{64}$ ]]; then
    printf 'Invalid base image digest in BASE-IMAGE.lock: %s\n' "$LOCKED_DIGEST" >&2
    exit 1
  fi
  PINNED_BASE_IMAGE="${BASE_TAG}@${LOCKED_DIGEST}"
  if ! docker image inspect "$PINNED_BASE_IMAGE" >/dev/null 2>&1; then
    printf 'Pinned base image is not cached; downloading %s...\n' "$PINNED_BASE_IMAGE"
    if ! docker pull --platform linux/amd64 "$PINNED_BASE_IMAGE"; then
      printf '%s\n' \
        'The pinned base image could not be downloaded. For an air-gapped host, use the offline GitHub Release bundle.' >&2
      exit 1
    fi
  fi

  SOURCE_REVISION="unknown"
  if command -v git >/dev/null 2>&1 \
    && git -C "$BUNDLE_ROOT" rev-parse --verify HEAD >/dev/null 2>&1; then
    SOURCE_REVISION="$(git -C "$BUNDLE_ROOT" rev-parse --verify HEAD)"
  fi
  CREATED_AT="$(date -u +'%Y-%m-%dT%H:%M:%SZ')"
  SOURCE_URL="${GATEWAY_SOURCE:-https://github.com/Dante9k/CCOBridge}"
  docker build \
    --platform linux/amd64 \
    --build-arg "LITELLM_BASE_IMAGE=${PINNED_BASE_IMAGE}" \
    --build-arg "LITELLM_BASE_DIGEST=${LOCKED_DIGEST}" \
    --build-arg "GATEWAY_VERSION=${VERSION}" \
    --build-arg "GATEWAY_REVISION=${SOURCE_REVISION}" \
    --build-arg "GATEWAY_CREATED=${CREATED_AT}" \
    --build-arg "GATEWAY_SOURCE=${SOURCE_URL}" \
    -t "$IMAGE" \
    "$BUNDLE_ROOT"

  IMAGE_ARCH="$(docker image inspect --format '{{.Architecture}}' "$IMAGE")"
  if [[ "$IMAGE_ARCH" != "amd64" ]]; then
    printf 'Unexpected image architecture: %s\n' "$IMAGE_ARCH" >&2
    exit 1
  fi
  if docker image inspect --format '{{json .Config.Env}}' "$IMAGE" \
    | grep -Eq '(CCOBRIDGE_API_KEY|LITELLM_MASTER_KEY)=sk-[[:alnum:]]'; then
    printf '%s\n' 'A runtime API key was found in image configuration.' >&2
    exit 1
  fi

  BUILD_INFO_TMP="$(mktemp)"
  IMAGE_ID="$(docker image inspect --format '{{.Id}}' "$IMAGE")"
  {
    printf 'gateway_version=%s\n' "$VERSION"
    printf 'gateway_image=%s\n' "$IMAGE"
    printf 'gateway_image_id=%s\n' "$IMAGE_ID"
    printf 'source_revision=%s\n' "$SOURCE_REVISION"
    printf 'source_url=%s\n' "$SOURCE_URL"
    printf '%s\n' 'install_mode=source-build'
    printf '%s\n' 'target_platform=linux/amd64'
    printf 'litellm_base=%s\n' "$BASE_TAG"
    printf 'litellm_base_digest=%s\n' "$LOCKED_DIGEST"
    printf 'built_at=%s\n' "$CREATED_AT"
  } > "$BUILD_INFO_TMP"
  BUILD_INFO_SOURCE="$BUILD_INFO_TMP"
fi

printf 'Installing into %s...\n' "$INSTALL_DIR"
install -d -m 0755 "$INSTALL_DIR"
install -m 0644 "$BUNDLE_ROOT/deploy/compose.yaml" "$INSTALL_DIR/compose.yaml"
for script_name in start stop logs verify uninstall users usage; do
  install -m 0755 "$BUNDLE_ROOT/deploy/${script_name}.sh" "$INSTALL_DIR/${script_name}.sh"
done
install -m 0644 "$BUILD_INFO_SOURCE" "$INSTALL_DIR/BUILD-INFO.txt"

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

for persistent_directory in config data; do
  persistent_path="$INSTALL_DIR/$persistent_directory"
  if [[ -L "$persistent_path" ]] \
    || [[ -e "$persistent_path" && ! -d "$persistent_path" ]]; then
    printf 'Persistent path must be a real directory: %s\n' "$persistent_path" >&2
    exit 1
  fi
  install -d -m 0700 -o 10001 -g 10001 "$persistent_path"
done

USER_KEY_FILE="$INSTALL_DIR/config/users.json"
if [[ -L "$USER_KEY_FILE" ]] \
  || [[ -e "$USER_KEY_FILE" && ! -f "$USER_KEY_FILE" ]]; then
  printf 'User-key path must be a regular file: %s\n' "$USER_KEY_FILE" >&2
  exit 1
fi
if [[ ! -e "$USER_KEY_FILE" ]]; then
  USER_KEY_TMP="$(mktemp)"
  printf '%s\n' '{"version":1,"users":[]}' > "$USER_KEY_TMP"
  install -m 0600 -o 10001 -g 10001 "$USER_KEY_TMP" "$USER_KEY_FILE"
  rm -f -- "$USER_KEY_TMP"
  USER_KEY_TMP=""
else
  chown 10001:10001 "$USER_KEY_FILE"
  chmod 0600 "$USER_KEY_FILE"
fi

printf '%s\n' '[5/6] Starting the gateway without pulling runtime images...'
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
printf 'Install mode: %s\n' "$INSTALL_MODE"
printf 'Gateway (on this server): %s\n' 'http://127.0.0.1:4000'
printf '%s\n' "Remote clients: replace 127.0.0.1 with this server's trusted-network address."
printf '%s\n' 'Models: query authenticated GET /v1/models for installed models and aliases.'
printf 'API key: stored in %s/.env with mode 0600; it is not printed.\n' "$INSTALL_DIR"
printf 'Management directory: %s\n' "$INSTALL_DIR"
