#!/usr/bin/env bash
set -Eeuo pipefail

DEPLOY_DIR="$(dirname "$(readlink -f "$0")")"
cd "$DEPLOY_DIR"

if [[ ! -r .env ]]; then
  printf '%s\n' '找不到可读的 .env 文件。' >&2
  exit 1
fi

ADMIN_KEY=""
LEGACY_KEY=""
while IFS='=' read -r variable_name variable_value; do
  case "$variable_name" in
    CCOBRIDGE_API_KEY) ADMIN_KEY="$variable_value" ;;
    LITELLM_MASTER_KEY) LEGACY_KEY="$variable_value" ;;
  esac
done < .env
ADMIN_KEY="${ADMIN_KEY:-$LEGACY_KEY}"
: "${ADMIN_KEY:?CCOBRIDGE_API_KEY 未设置}"

DAYS="${1:-30}"
USER_ID="${2:-}"
if [[ ! "$DAYS" =~ ^[0-9]+$ ]] || ((DAYS < 1 || DAYS > 365)); then
  printf '%s\n' 'Usage: sudo ./usage.sh [days:1-365] [admin|usr_<id>]' >&2
  exit 2
fi
if [[ -n "$USER_ID" && ! "$USER_ID" =~ ^(admin|usr_[0-9a-f]{16})$ ]]; then
  printf '%s\n' 'User filter must be admin or a usr_<id> value from users.sh list.' >&2
  exit 2
fi

GATEWAY_URL="${GATEWAY_URL:-http://127.0.0.1:4000}"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf -- "$TMP_DIR"' EXIT
umask 077
printf 'Authorization: Bearer %s\n' "$ADMIN_KEY" > "$TMP_DIR/auth-header"

QUERY="days=$DAYS"
if [[ -n "$USER_ID" ]]; then
  QUERY="$QUERY&user=$USER_ID"
fi
curl -fsS --max-time 30 \
  -H "@$TMP_DIR/auth-header" \
  "$GATEWAY_URL/admin/usage?$QUERY"
printf '\n'
