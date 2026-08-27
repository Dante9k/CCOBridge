#!/usr/bin/env bash
set -Eeuo pipefail

if ! command -v claude >/dev/null 2>&1; then
  printf '%s\n' 'Claude Code executable not found in PATH.' >&2
  exit 127
fi

export ANTHROPIC_BASE_URL="${CCOBRIDGE_URL:-http://127.0.0.1:4000}"
if [[ -z "${ANTHROPIC_AUTH_TOKEN:-}" ]]; then
  if [[ ! -t 0 ]]; then
    printf '%s\n' 'ANTHROPIC_AUTH_TOKEN is unset and no interactive terminal is available.' >&2
    exit 2
  fi
  read -r -s -p 'API key: ' ANTHROPIC_AUTH_TOKEN
  printf '\n'
  if [[ -z "$ANTHROPIC_AUTH_TOKEN" ]]; then
    printf '%s\n' 'API key cannot be empty.' >&2
    exit 2
  fi
  export ANTHROPIC_AUTH_TOKEN
fi
unset ANTHROPIC_API_KEY

exec claude --model "${CCOBRIDGE_MODEL:-qwen-code}" "$@"
