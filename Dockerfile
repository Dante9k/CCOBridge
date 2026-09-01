ARG LITELLM_BASE_IMAGE=ghcr.io/berriai/litellm:v1.94.0
FROM ${LITELLM_BASE_IMAGE}

ARG GATEWAY_VERSION=1.2.0
ARG GATEWAY_REVISION=unknown
ARG GATEWAY_CREATED
ARG GATEWAY_SOURCE
ARG LITELLM_BASE_DIGEST=unknown

LABEL org.opencontainers.image.title="CCOBridge" \
      org.opencontainers.image.description="Lightweight OpenAI and Anthropic compatibility gateway for Ollama agents" \
      org.opencontainers.image.version="${GATEWAY_VERSION}" \
      org.opencontainers.image.revision="${GATEWAY_REVISION}" \
      org.opencontainers.image.created="${GATEWAY_CREATED}" \
      org.opencontainers.image.source="${GATEWAY_SOURCE}" \
      org.opencontainers.image.url="${GATEWAY_SOURCE}" \
      org.opencontainers.image.authors="CCOBridge contributors" \
      org.opencontainers.image.vendor="CCOBridge contributors" \
      org.opencontainers.image.licenses="Apache-2.0" \
      org.opencontainers.image.base.name="ghcr.io/berriai/litellm:v1.94.0" \
      org.opencontainers.image.base.digest="${LITELLM_BASE_DIGEST}"

USER root
WORKDIR /app/ccobridge

COPY gateway/ /app/ccobridge/gateway/
COPY litellm-config.yaml /app/ccobridge/litellm-config.yaml
COPY entrypoint.py /app/ccobridge/entrypoint.py

RUN python -m compileall -q /app/ccobridge \
    && chmod -R a=rX /app/ccobridge

ENV HOME=/tmp \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    GATEWAY_VERSION=${GATEWAY_VERSION} \
    GATEWAY_HOST=0.0.0.0 \
    GATEWAY_PORT=4000 \
    INTERNAL_LITELLM_PORT=4001 \
    CCOBRIDGE_MODEL_ALIASES={"qwen-code":"qwen3.8:latest"} \
    CCOBRIDGE_KEYS_FILE=/etc/ccobridge/users.json \
    CCOBRIDGE_USAGE_DB=/var/lib/ccobridge/usage.sqlite3 \
    LITELLM_CONFIG_PATH=/app/ccobridge/litellm-config.yaml \
    LITELLM_DISABLE_TELEMETRY=1 \
    DO_NOT_TRACK=1

USER 10001:10001
EXPOSE 4000

HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=4 \
  CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:'+os.getenv('GATEWAY_PORT','4000')+'/health/liveliness', timeout=3).read()"

ENTRYPOINT ["python", "/app/ccobridge/entrypoint.py"]
