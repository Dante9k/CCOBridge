#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VERSION="1.2.0"
IMAGE="ccobridge:${VERSION}"
BASE_TAG="ghcr.io/berriai/litellm:v1.94.0"
DIST_DIR="$ROOT_DIR/dist"
BUILD_DIR="$ROOT_DIR/build"
STAGE_DIR="$BUILD_DIR/ccobridge-offline-${VERSION}"
IMAGE_ARCHIVE_NAME="ccobridge-${VERSION}-linux-amd64.tar"
BUNDLE_NAME="ccobridge-offline-${VERSION}-linux-amd64.tar.gz"
GATEWAY_SOURCE="${GATEWAY_SOURCE:-}"
CREATED_AT="$(date -u +'%Y-%m-%dT%H:%M:%SZ')"

for command_name in docker curl git python3 sha256sum tar; do
  if ! command -v "$command_name" >/dev/null 2>&1; then
    printf 'Missing required command: %s\n' "$command_name" >&2
    exit 1
  fi
done

mkdir -p "$DIST_DIR" "$BUILD_DIR"
case "$STAGE_DIR" in
  "$BUILD_DIR"/ccobridge-offline-*) ;;
  *)
    printf 'Unsafe staging directory: %s\n' "$STAGE_DIR" >&2
    exit 1
    ;;
esac
rm -rf -- "$STAGE_DIR"
mkdir -p "$STAGE_DIR/image" "$STAGE_DIR/deploy" "$STAGE_DIR/client" "$STAGE_DIR/docs"

printf '%s\n' '[1/7] Pulling the pinned LiteLLM release...'
docker pull --platform linux/amd64 "$BASE_TAG"
BASE_REPO_DIGEST="$(docker image inspect --format '{{index .RepoDigests 0}}' "$BASE_TAG")"
BASE_DIGEST="${BASE_REPO_DIGEST#*@}"
LOCKED_DIGEST="$(sed -n 's/^digest=//p' "$ROOT_DIR/BASE-IMAGE.lock")"
SOURCE_REVISION="$(git -C "$ROOT_DIR" rev-parse --verify HEAD)"
SOURCE_DIRTY="false"
if ! git -C "$ROOT_DIR" diff --quiet \
  || ! git -C "$ROOT_DIR" diff --cached --quiet; then
  SOURCE_DIRTY="true"
fi

if [[ "$BASE_DIGEST" != sha256:* ]]; then
  printf 'Could not resolve the base image digest: %s\n' "$BASE_REPO_DIGEST" >&2
  exit 1
fi
if [[ "$BASE_DIGEST" != "$LOCKED_DIGEST" ]]; then
  printf 'Base image digest differs from BASE-IMAGE.lock: %s != %s\n' \
    "$BASE_DIGEST" "$LOCKED_DIGEST" >&2
  exit 1
fi

printf '%s\n' '[2/7] Building ccobridge for linux/amd64...'
docker build \
  --platform linux/amd64 \
  --build-arg "LITELLM_BASE_IMAGE=${BASE_REPO_DIGEST}" \
  --build-arg "LITELLM_BASE_DIGEST=${BASE_DIGEST}" \
  --build-arg "GATEWAY_VERSION=${VERSION}" \
  --build-arg "GATEWAY_REVISION=${SOURCE_REVISION}" \
  --build-arg "GATEWAY_CREATED=${CREATED_AT}" \
  --build-arg "GATEWAY_SOURCE=${GATEWAY_SOURCE}" \
  -t "$IMAGE" \
  "$ROOT_DIR"

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

printf '%s\n' '[3/7] Running local integration tests...'
"$ROOT_DIR/tests/run-integration.sh" "$IMAGE"

printf '%s\n' '[4/7] Exporting the Docker image...'
docker save --output "$STAGE_DIR/image/$IMAGE_ARCHIVE_NAME" "$IMAGE"

SOURCE_LIST="$(mktemp)"
git -C "$ROOT_DIR" ls-files -z --cached > "$SOURCE_LIST"
tar -C "$ROOT_DIR" --null --files-from="$SOURCE_LIST" -cf - \
  | tar -C "$STAGE_DIR" -xf -
rm -f -- "$SOURCE_LIST"

for script_path in \
  client/claude-ccobridge.sh \
  deploy/install.sh \
  deploy/diagnose.sh \
  deploy/logs.sh \
  deploy/start.sh \
  deploy/stop.sh \
  deploy/uninstall.sh \
  deploy/usage.sh \
  deploy/users.sh \
  deploy/verify.sh \
  scripts/build-offline.sh \
  scripts/check-public-release.py \
  tests/run-install-lifecycle.sh \
  tests/run-integration.sh; do
  chmod 0755 "$STAGE_DIR/$script_path"
done

IMAGE_ID="$(docker image inspect --format '{{.Id}}' "$IMAGE")"
{
  printf 'gateway_version=%s\n' "$VERSION"
  printf 'gateway_image=%s\n' "$IMAGE"
  printf 'gateway_image_id=%s\n' "$IMAGE_ID"
  printf 'source_revision=%s\n' "$SOURCE_REVISION"
  printf 'source_dirty=%s\n' "$SOURCE_DIRTY"
  printf 'source_url=%s\n' "$GATEWAY_SOURCE"
  printf '%s\n' 'target_platform=linux/amd64'
  printf 'litellm_base=%s\n' "$BASE_TAG"
  printf 'litellm_base_digest=%s\n' "$BASE_DIGEST"
  printf 'built_at=%s\n' "$CREATED_AT"
} >"$STAGE_DIR/BUILD-INFO.txt"

printf '%s\n' '[5/7] Creating and checking the offline bundle...'
CHECKSUM_TMP="$(mktemp)"
trap 'rm -f -- "$CHECKSUM_TMP"' EXIT
(
  cd "$STAGE_DIR"
  find . -type f ! -name SHA256SUMS -print0 \
    | sort -z \
    | xargs -0 sha256sum > "$CHECKSUM_TMP"
  mv -- "$CHECKSUM_TMP" SHA256SUMS
  sha256sum -c SHA256SUMS
)

tar -C "$BUILD_DIR" -czf "$DIST_DIR/$BUNDLE_NAME" "$(basename "$STAGE_DIR")"
(
  cd "$DIST_DIR"
  sha256sum "$BUNDLE_NAME" > "${BUNDLE_NAME}.sha256"
  sha256sum -c "${BUNDLE_NAME}.sha256"
)

printf '%s\n' '[6/7] Proving that the saved image can be reloaded...'
BACKUP_TAG="ccobridge:reload-backup-${VERSION}"
docker tag "$IMAGE" "$BACKUP_TAG"
docker image rm "$IMAGE" >/dev/null
docker load -i "$STAGE_DIR/image/$IMAGE_ARCHIVE_NAME" >/dev/null
RELOADED_ID="$(docker image inspect --format '{{.Id}}' "$IMAGE")"
if [[ "$RELOADED_ID" != "$IMAGE_ID" ]]; then
  printf 'Reloaded image ID mismatch: %s != %s\n' "$RELOADED_ID" "$IMAGE_ID" >&2
  exit 1
fi
docker image rm "$BACKUP_TAG" >/dev/null

printf '%s\n' '[7/7] Running tests against the reloaded image...'
"$ROOT_DIR/tests/run-integration.sh" "$IMAGE"

rm -rf -- "$STAGE_DIR"

printf '\nCreated:\n  %s\n  %s\n' \
  "$DIST_DIR/$BUNDLE_NAME" \
  "$DIST_DIR/${BUNDLE_NAME}.sha256"
