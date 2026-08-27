#!/usr/bin/env bash
set -Eeuo pipefail

DEPLOY_DIR="$(dirname "$(readlink -f "$0")")"
cd "$DEPLOY_DIR"

if [[ ! -r .env ]]; then
  printf '%s\n' '找不到可读的 .env 文件。' >&2
  exit 1
fi

ENV_CCOBRIDGE_API_KEY=""
ENV_LITELLM_MASTER_KEY=""
ENV_OLLAMA_API_BASE=""
while IFS='=' read -r variable_name variable_value; do
  case "$variable_name" in
    CCOBRIDGE_API_KEY) ENV_CCOBRIDGE_API_KEY="$variable_value" ;;
    LITELLM_MASTER_KEY) ENV_LITELLM_MASTER_KEY="$variable_value" ;;
    OLLAMA_API_BASE) ENV_OLLAMA_API_BASE="$variable_value" ;;
  esac
done < .env

if [[ -n "$ENV_CCOBRIDGE_API_KEY" && -n "$ENV_LITELLM_MASTER_KEY" \
  && "$ENV_CCOBRIDGE_API_KEY" != "$ENV_LITELLM_MASTER_KEY" ]]; then
  printf '%s\n' 'CCOBRIDGE_API_KEY 与 LITELLM_MASTER_KEY 不能设置为不同值。' >&2
  exit 1
fi
CCOBRIDGE_API_KEY="${ENV_CCOBRIDGE_API_KEY:-$ENV_LITELLM_MASTER_KEY}"
: "${CCOBRIDGE_API_KEY:?CCOBRIDGE_API_KEY 未设置}"
OLLAMA_API_BASE="${ENV_OLLAMA_API_BASE:-http://127.0.0.1:11434}"

GATEWAY_URL="${GATEWAY_URL:-http://127.0.0.1:4000}"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf -- "$TMP_DIR"' EXIT
AUTH_HEADER_FILE="$TMP_DIR/authorization-header"
umask 077
printf 'Authorization: Bearer %s\n' "$CCOBRIDGE_API_KEY" > "$AUTH_HEADER_FILE"

printf '%s\n' '[1/6] 检查 Ollama 与模型...'
curl -fsS --max-time 10 "${OLLAMA_API_BASE%/}/api/tags" -o "$TMP_DIR/ollama-tags.json"
if ! grep -Eq '"models"[[:space:]]*:[[:space:]]*\[[[:space:]]*\{' "$TMP_DIR/ollama-tags.json"; then
  printf '%s\n' 'Ollama 中没有找到任何已安装模型。' >&2
  exit 1
fi

printf '%s\n' '[2/6] 检查 Gateway 就绪状态...'
curl -fsS --max-time 10 "$GATEWAY_URL/health/readiness" -o "$TMP_DIR/health.json"

printf '%s\n' '[3/6] 检查动态模型列表...'
curl -fsS --max-time 15 \
  -H "@$AUTH_HEADER_FILE" \
  "$GATEWAY_URL/v1/models" -o "$TMP_DIR/models.json"
if ! grep -Eq '"id"[[:space:]]*:' "$TMP_DIR/models.json"; then
  printf '%s\n' '/v1/models 未返回任何模型。' >&2
  exit 1
fi

VERIFY_MODEL="${CCOBRIDGE_VERIFY_MODEL:-}"
if [[ -z "$VERIFY_MODEL" ]] && grep -Eq '"id"[[:space:]]*:[[:space:]]*"qwen-code"' "$TMP_DIR/models.json"; then
  VERIFY_MODEL='qwen-code'
fi
if [[ -z "$VERIFY_MODEL" ]]; then
  VERIFY_MODEL="$(sed -n 's/.*"id"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' "$TMP_DIR/models.json" | head -n 1)"
fi
if [[ -z "$VERIFY_MODEL" ]]; then
  printf '%s\n' '无法从 /v1/models 选择验收模型。' >&2
  exit 1
fi
JSON_MODEL="$(printf '%s' "$VERIFY_MODEL" | sed 's/[\\"]/\\&/g')"

printf '[4/6] 检查 OpenAI Chat Completions（模型 %s）...\n' "$VERIFY_MODEL"
curl -fsS --max-time 600 \
  -H "@$AUTH_HEADER_FILE" \
  -H 'Content-Type: application/json' \
  -d "{\"model\":\"${JSON_MODEL}\",\"messages\":[{\"role\":\"user\",\"content\":\"只回复 READY\"}],\"max_tokens\":32,\"stream\":false}" \
  "$GATEWAY_URL/v1/chat/completions" -o "$TMP_DIR/chat.json"
if ! grep -q '"choices"' "$TMP_DIR/chat.json"; then
  printf '%s\n' 'Chat Completions 响应格式不正确。' >&2
  exit 1
fi

printf '%s\n' '[5/6] 检查 OpenAI Responses...'
curl -fsS --max-time 600 \
  -H "@$AUTH_HEADER_FILE" \
  -H 'Content-Type: application/json' \
  -d "{\"model\":\"${JSON_MODEL}\",\"input\":\"只回复 READY\",\"max_output_tokens\":32}" \
  "$GATEWAY_URL/v1/responses" -o "$TMP_DIR/responses.json"
if ! grep -Eq '"object"[[:space:]]*:[[:space:]]*"response"' "$TMP_DIR/responses.json"; then
  printf '%s\n' 'Responses API 响应格式不正确。' >&2
  exit 1
fi

printf '%s\n' '[6/6] 检查 Anthropic Messages 和中途 system 兼容...'
curl -fsS --max-time 600 \
  -H "@$AUTH_HEADER_FILE" \
  -H 'Content-Type: application/json' \
  -H 'anthropic-version: 2023-06-01' \
  -d "{\"model\":\"${JSON_MODEL}\",\"max_tokens\":32,\"stream\":false,\"system\":[{\"type\":\"text\",\"text\":\"TOP_SYSTEM_SENTINEL\"}],\"messages\":[{\"role\":\"user\",\"content\":\"先记住要求\"},{\"role\":\"assistant\",\"content\":\"好的\"},{\"role\":\"system\",\"content\":[{\"type\":\"text\",\"text\":\"MID_SYSTEM_SENTINEL\",\"cache_control\":{\"type\":\"ephemeral\"}}]},{\"role\":\"user\",\"content\":\"只回复 READY\"}]}" \
  "$GATEWAY_URL/v1/messages" -o "$TMP_DIR/messages.json"
if grep -q 'System message must be at the beginning' "$TMP_DIR/messages.json"; then
  printf '%s\n' '仍出现 Qwen system message Jinja 错误。' >&2
  exit 1
fi
if ! grep -Eq '"type"[[:space:]]*:[[:space:]]*"message"' "$TMP_DIR/messages.json"; then
  printf '%s\n' 'Anthropic Messages 响应格式不正确：' >&2
  cat "$TMP_DIR/messages.json" >&2
  exit 1
fi

printf '%s\n' '自动验收全部通过。下一步请运行 Claude Code 的 Read/Write/Edit/Bash 实际工具测试。'
