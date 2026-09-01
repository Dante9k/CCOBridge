#!/usr/bin/env bash
set -Eeuo pipefail

DEPLOY_DIR="$(dirname "$(readlink -f "$0")")"
cd "$DEPLOY_DIR"

usage() {
  cat <<'EOF'
用法：sudo ./diagnose.sh [--benchmark OLLAMA_MODEL]

默认执行无推理开销的状态、资源、控制面延迟和近期请求计时检查。
指定 --benchmark 后，会额外发送两个最多生成 32 Token 的测试请求：
  sudo ./diagnose.sh --benchmark qwen3.8:latest

OLLAMA_MODEL 必须是 Ollama 原生模型名，不是 CCOBridge 别名。
EOF
}

BENCHMARK_MODEL=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --benchmark)
      if [[ $# -lt 2 ]]; then
        printf '%s\n' '--benchmark 缺少 Ollama 原生模型名。' >&2
        usage >&2
        exit 2
      fi
      BENCHMARK_MODEL="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      printf '未知参数：%s\n' "$1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [[ -n "$BENCHMARK_MODEL" \
  && ! "$BENCHMARK_MODEL" =~ ^[[:alnum:]_.:/+-]+$ ]]; then
  printf '%s\n' '模型名包含不支持的字符。' >&2
  exit 2
fi
if [[ ! -r .env ]]; then
  printf '%s\n' '找不到可读的 .env 文件。' >&2
  exit 1
fi
for command_name in curl docker ss; do
  if ! command -v "$command_name" >/dev/null 2>&1; then
    printf '缺少命令：%s\n' "$command_name" >&2
    exit 1
  fi
done

ADMIN_KEY=""
LEGACY_KEY=""
OLLAMA_API_BASE=""
while IFS='=' read -r variable_name variable_value; do
  case "$variable_name" in
    CCOBRIDGE_API_KEY) ADMIN_KEY="$variable_value" ;;
    LITELLM_MASTER_KEY) LEGACY_KEY="$variable_value" ;;
    OLLAMA_API_BASE) OLLAMA_API_BASE="$variable_value" ;;
  esac
done < .env
ADMIN_KEY="${ADMIN_KEY:-$LEGACY_KEY}"
: "${ADMIN_KEY:?CCOBRIDGE_API_KEY 未设置}"
OLLAMA_API_BASE="${OLLAMA_API_BASE:-http://127.0.0.1:11434}"
OLLAMA_API_BASE="${OLLAMA_API_BASE%/}"
GATEWAY_URL="${GATEWAY_URL:-http://127.0.0.1:4000}"
GATEWAY_URL="${GATEWAY_URL%/}"

TMP_DIR="$(mktemp -d)"
trap 'rm -rf -- "$TMP_DIR"' EXIT
umask 077
printf 'Authorization: Bearer %s\n' "$ADMIN_KEY" > "$TMP_DIR/auth-header"

timed_get() {
  local label="$1"
  local url="$2"
  local output_path="$3"
  shift 3
  local result=""
  if result="$(curl -sS --connect-timeout 3 --max-time 15 \
    -o "$output_path" \
    -w 'HTTP=%{http_code} connect=%{time_connect}s first_byte=%{time_starttransfer}s total=%{time_total}s' \
    "$@" "$url")"; then
    printf '%-24s %s\n' "$label" "$result"
  else
    printf '%-24s FAILED (%s)\n' "$label" "$result"
  fi
}

printf '%s\n' '=== CCOBridge 性能诊断（不会输出密钥、请求正文或响应正文） ==='
printf '时间：%s\n' "$(date -u +'%Y-%m-%dT%H:%M:%SZ')"

printf '\n%s\n' '[1/6] 容器状态'
if docker inspect ccobridge >/dev/null 2>&1; then
  docker inspect --format \
    'name={{.Name}} running={{.State.Running}} status={{.State.Status}} health={{if .State.Health}}{{.State.Health.Status}}{{else}}not-configured{{end}} restarts={{.RestartCount}} started={{.State.StartedAt}} image={{.Config.Image}}' \
    ccobridge
else
  printf '%s\n' '未找到名为 ccobridge 的容器。'
fi

printf '\n%s\n' '[2/6] 端口监听'
if ! ss -ltn | awk 'NR == 1 || /:4000[[:space:]]|:11434[[:space:]]/'; then
  printf '%s\n' '无法读取监听端口。'
fi

printf '\n%s\n' '[3/6] 主机和推理资源'
uptime 2>/dev/null || true
free -h 2>/dev/null || true
docker stats --no-stream \
  --format 'container={{.Name}} cpu={{.CPUPerc}} memory={{.MemUsage}} net={{.NetIO}} pids={{.PIDs}}' \
  ccobridge 2>/dev/null || true
if command -v ollama >/dev/null 2>&1; then
  printf '%s\n' '-- ollama ps --'
  ollama ps 2>/dev/null || true
fi
if command -v nvidia-smi >/dev/null 2>&1; then
  printf '%s\n' '-- GPU --'
  nvidia-smi \
    --query-gpu=index,name,utilization.gpu,memory.used,memory.total,temperature.gpu \
    --format=csv,noheader 2>/dev/null || true
fi

printf '\n%s\n' '[4/6] 无推理开销的控制面延迟'
timed_get 'Ollama /api/version' \
  "$OLLAMA_API_BASE/api/version" "$TMP_DIR/ollama-version.json"
timed_get 'Ollama /api/tags' \
  "$OLLAMA_API_BASE/api/tags" "$TMP_DIR/ollama-tags.json"
timed_get 'Gateway readiness' \
  "$GATEWAY_URL/health/readiness" "$TMP_DIR/readiness.json"
timed_get 'Gateway /v1/models' \
  "$GATEWAY_URL/v1/models" "$TMP_DIR/models.json" -H "@$TMP_DIR/auth-header"

printf '\n%s\n' '[5/6] 最近请求计时（用户身份已脱敏）'
if curl -fsS --connect-timeout 3 --max-time 15 \
  -H "@$TMP_DIR/auth-header" \
  "$GATEWAY_URL/admin/performance?limit=20&redact_users=true" \
  -o "$TMP_DIR/performance.json"; then
  printf '%s\n' 'performance_report_begin'
  sed 's/{/{\n/g; s/},/},\n/g' "$TMP_DIR/performance.json"
  printf '%s\n' 'performance_report_end'
else
  printf '%s\n' '无法读取性能报告；请确认网关已升级到支持 /admin/performance 的版本。'
fi

printf '\n%s\n' '[6/6] 可选模型基准'
if [[ -z "$BENCHMARK_MODEL" ]]; then
  printf '%s\n' '未运行。需要时执行：sudo ./diagnose.sh --benchmark qwen3.8:latest'
else
  JSON_MODEL="$BENCHMARK_MODEL"
  printf '模型：%s；每个路径最多生成 32 Token。网关请求先执行，随后执行 Ollama 直连。\n' \
    "$BENCHMARK_MODEL"

  curl -sS --connect-timeout 3 --max-time 600 \
    -D "$TMP_DIR/gateway-headers" \
    -o "$TMP_DIR/gateway-response.json" \
    -w 'Gateway inference        HTTP=%{http_code} connect=%{time_connect}s first_byte=%{time_starttransfer}s total=%{time_total}s\n' \
    -H "@$TMP_DIR/auth-header" \
    -H 'Content-Type: application/json' \
    -d "{\"model\":\"${JSON_MODEL}\",\"messages\":[{\"role\":\"user\",\"content\":\"Reply with READY only.\"}],\"max_tokens\":32,\"stream\":false}" \
    "$GATEWAY_URL/v1/chat/completions" || true
  grep -Eai '^(server-timing|x-ccobridge-request-id):' \
    "$TMP_DIR/gateway-headers" 2>/dev/null | tr -d '\r' || true

  curl -sS --connect-timeout 3 --max-time 600 \
    -o "$TMP_DIR/ollama-response.json" \
    -w 'Ollama direct           HTTP=%{http_code} connect=%{time_connect}s first_byte=%{time_starttransfer}s total=%{time_total}s\n' \
    -H 'Content-Type: application/json' \
    -d "{\"model\":\"${JSON_MODEL}\",\"messages\":[{\"role\":\"user\",\"content\":\"Reply with READY only.\"}],\"stream\":false,\"options\":{\"num_predict\":32}}" \
    "$OLLAMA_API_BASE/api/chat" || true
fi

cat <<'EOF'

=== 怎么判断 ===
- Ollama 控制面也慢、GPU/内存饱和或 ollama ps 显示排队：优先排查宿主机/Ollama。
- upstream_headers_ms 或 first_byte_ms 很高：通常是模型冷加载、排队或长提示词预填充。
- first_byte_ms 正常，但 total_ms 高、observed_output_tokens_per_second 低：通常是模型生成慢。
- Ollama 直连明显快、网关请求仍慢：保留 x-ccobridge-request-id，并查看 ./logs.sh。
- 第一次慢、紧接着第二次快：通常是模型从磁盘加载到内存/显存，不是网关卡死。

注意：非流式请求的 HTTP first_byte 要等完整响应；判断首 Token 请优先看流式请求的 first_byte_ms。
EOF
