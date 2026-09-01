#!/usr/bin/env bash
set -Eeuo pipefail

DEPLOY_DIR="$(dirname "$(readlink -f "$0")")"
IMAGE="ccobridge:1.2.0"
USER_FILE="$DEPLOY_DIR/config/users.json"

usage() {
  cat <<'EOF'
Usage:
  sudo ./users.sh add <name>
  sudo ./users.sh list
  sudo ./users.sh disable <user-id-or-name>
  sudo ./users.sh enable <user-id-or-name>
  sudo ./users.sh rotate <user-id-or-name>

New and rotated API keys are displayed once. Only their SHA-256 digests are stored.
EOF
}

case "${1:-}" in
  add|disable|enable|rotate)
    if [[ $# -ne 2 ]]; then
      usage >&2
      exit 2
    fi
    ;;
  list)
    if [[ $# -ne 1 ]]; then
      usage >&2
      exit 2
    fi
    ;;
  *)
    usage >&2
    exit 2
    ;;
esac

if [[ ! -f "$USER_FILE" || -L "$USER_FILE" ]]; then
  printf 'User-key file is missing or unsafe: %s\n' "$USER_FILE" >&2
  exit 1
fi
if ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
  printf 'Required image is unavailable: %s\n' "$IMAGE" >&2
  exit 1
fi

docker run --rm \
  --network none \
  --pull never \
  --user 10001:10001 \
  --entrypoint python \
  --volume "$DEPLOY_DIR/config:/etc/ccobridge" \
  "$IMAGE" \
  -m gateway.userctl --file /etc/ccobridge/users.json "$@"
