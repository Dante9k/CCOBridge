<div align="center">

# CCOBridge

**A lightweight OpenAI and Anthropic compatibility gateway for Ollama-powered agents.**

[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)
![Platform: linux/amd64](https://img.shields.io/badge/platform-linux%2Famd64-1793d1)
![LiteLLM: v1.94.0](https://img.shields.io/badge/LiteLLM-v1.94.0-6f42c1)
![Offline deployable](https://img.shields.io/badge/deployment-offline-success)

[中文](README.zh-CN.md) · [Operations](docs/OPERATION-MANUAL.md) · [Test report](docs/TEST-REPORT.md) · [Security](SECURITY.md)

</div>

CCOBridge puts one authenticated, agent-friendly endpoint in front of the models
already installed in Ollama. Native Ollama model names are discovered at runtime,
optional aliases provide stable client contracts, and both OpenAI-compatible agents
and Claude Code can use the same gateway.

OpenAI requests take a streaming fast path directly to Ollama. Anthropic Messages
requests use a pinned LiteLLM converter and a focused compatibility layer that safely
normalizes mid-conversation system content for strict model templates. The project
ships without a database, Redis, admin UI, billing system, or external telemetry
service.

> [!IMPORTANT]
> CCOBridge improves protocol and deployment compatibility; it cannot make a model
> support tools, vision, embeddings, context sizes, or reasoning modes that the model
> itself does not support. Read the [test report](docs/TEST-REPORT.md) before treating
> a simulated result as production acceptance.

## Why not connect agents directly to Ollama?

Ollama already implements parts of the OpenAI API, and direct access is the simplest
choice for a trusted single-user machine. CCOBridge is useful when you need:

- a real shared API key instead of Ollama's ignored placeholder key;
- one protected network port while keeping port 11434 private;
- dynamic model discovery plus stable aliases such as `qwen-code`;
- Anthropic Messages for Claude Code and Anthropic SDK clients;
- strict, fail-safe system-message normalization for Qwen-style templates;
- one reproducible image and checksummed package for an isolated server; or
- repeatable compatibility tests across chat, Responses, embeddings, streaming, and
  tools.

If you need accounts, quotas, billing, a dashboard, or many upstream providers, use a
general platform such as New API or a full LiteLLM deployment instead. CCOBridge
deliberately stays between bare Ollama and those larger platforms.

## Architecture

```text
OpenAI SDK / Cursor / Continue / OpenCode / agent frameworks
                              │
                              │ OpenAI-compatible API
                              ▼
                       CCOBridge :4000
                       ├─ API-key authentication
                       ├─ dynamic models and aliases
                       ├─ OpenAI streaming fast path ───────────┐
                       └─ Anthropic normalization               │
                                      │                         │
                                      ▼                         │
                         LiteLLM v1.94.0 :4001                  │
                            (container-internal)                 │
                                      │                         │
                                      └──────────────┬──────────┘
                                                     ▼
                                      host Ollama :11434
```

The supported deployment uses Linux host networking. Ollama can remain bound to
`127.0.0.1:11434`, while authenticated clients access only CCOBridge on port 4000.

## Supported API surface

| Method | Endpoint | Implementation | Typical use |
|---|---|---|---|
| `GET` | `/v1/models` | CCOBridge + Ollama discovery | Installed models and active aliases |
| `GET` | `/v1/models/{model}` | CCOBridge | Retrieve one model |
| `POST` | `/v1/chat/completions` | Streaming pass-through to Ollama | Most OpenAI-compatible agents |
| `POST` | `/v1/responses` | Streaming pass-through to Ollama | Newer OpenAI SDKs and agents |
| `POST` | `/v1/completions` | Streaming pass-through to Ollama | Legacy completion clients |
| `POST` | `/v1/embeddings` | Streaming pass-through to Ollama | RAG and vector workflows |
| `POST` | `/v1/messages` | Normalization + LiteLLM | Claude Code and Anthropic clients |
| `GET` | `/health/liveliness` | CCOBridge | Process health |
| `GET` | `/health/readiness` | CCOBridge + upstream checks | Ollama and LiteLLM readiness |

The gateway supports both `Authorization: Bearer ...` and Anthropic's `x-api-key`
header. Health endpoints are intentionally unauthenticated for container health
checks. Unsupported paths return 404 instead of exposing LiteLLM management APIs.

Ollama `0.13.3` or newer is required because that is the first supported version with
the non-stateful OpenAI Responses endpoint. Ollama currently does not support stateful
Responses fields such as `previous_response_id`; consult the
[Ollama OpenAI compatibility documentation](https://github.com/ollama/ollama/blob/main/docs/api/openai-compatibility.mdx)
for its current field-level support.

## Quick start for API clients

Use the server's trusted-network address and the key generated during installation:

```dotenv
OPENAI_BASE_URL=http://192.0.2.10:4000/v1
OPENAI_API_KEY=<installed-api-key>
```

`192.0.2.10` is a documentation-only address. Replace it with your server address.
Some clients ask for a host URL without `/v1`; follow that client's convention.

List available native models and aliases:

```bash
curl -fsS http://192.0.2.10:4000/v1/models \
  -H 'Authorization: Bearer <installed-api-key>'
```

Call Chat Completions with any installed Ollama model name:

```bash
curl -fsS http://192.0.2.10:4000/v1/chat/completions \
  -H 'Authorization: Bearer <installed-api-key>' \
  -H 'Content-Type: application/json' \
  -d '{
    "model": "qwen3.8:latest",
    "messages": [{"role": "user", "content": "Reply with READY"}],
    "stream": false
  }'
```

Use Responses with a chat-capable model:

```bash
curl -fsS http://192.0.2.10:4000/v1/responses \
  -H 'Authorization: Bearer <installed-api-key>' \
  -H 'Content-Type: application/json' \
  -d '{"model":"qwen3.8:latest","input":"Reply with READY"}'
```

Use Embeddings with an embedding-capable model already installed in Ollama:

```bash
curl -fsS http://192.0.2.10:4000/v1/embeddings \
  -H 'Authorization: Bearer <installed-api-key>' \
  -H 'Content-Type: application/json' \
  -d '{"model":"nomic-embed-text:latest","input":"local embeddings"}'
```

## Claude Code

Claude Code uses Anthropic Messages, so its base URL does not include `/v1`:

```powershell
$env:ANTHROPIC_BASE_URL="http://192.0.2.10:4000"
$env:ANTHROPIC_AUTH_TOKEN="<installed-api-key>"
Remove-Item Env:ANTHROPIC_API_KEY -ErrorAction SilentlyContinue
claude --model qwen-code
```

The bundled helper prompts for the key without echoing it and accepts a model:

```powershell
.\client\claude-ccobridge.ps1 `
  -Gateway "http://192.0.2.10:4000" `
  -Model "qwen-code"
```

Linux or macOS:

```bash
export CCOBRIDGE_URL='http://192.0.2.10:4000'
export CCOBRIDGE_MODEL='qwen-code'
./client/claude-ccobridge.sh
```

Claude Code tool quality depends heavily on the selected model. Passing the API tests
does not guarantee reliable file editing or command execution.

## Dynamic models and aliases

`GET /v1/models` reads Ollama `/api/tags` on every request. Installing or removing an
Ollama model therefore requires no gateway restart. Native model names remain callable
unless an explicitly configured alias uses the same identifier.

Aliases are optional and configured as a JSON object:

```dotenv
CCOBRIDGE_MODEL_ALIASES={"qwen-code":"qwen3.8:latest","local-embed":"nomic-embed-text:latest"}
```

An alias is listed only when its target is installed. Alias resolution is one level by
design: values must be native Ollama model names, not other aliases. An alias shadows
a native model with the same identifier, so avoid collisions unless that override is
intentional. Invalid JSON, whitespace in identifiers, duplicate normalized names,
empty values, alias chains, and self-references fail startup.

After changing aliases, recreate the container:

```bash
cd /opt/ccobridge
sudo docker compose --env-file .env up -d --force-recreate --pull never
sudo ./verify.sh
```

The image retains `qwen-code` → `qwen3.8:latest` as its backwards-compatible default.
Set `CCOBRIDGE_MODEL_ALIASES={}` to disable all aliases.

## System-message safety

Claude Code conversations can contain a `system` entry after normal messages, while
strict templates may require every system instruction at the beginning. For
`POST /v1/messages`, CCOBridge:

1. keeps existing top-level system content first;
2. hoists in-message system content in original order;
3. supports strings and Anthropic text-block arrays;
4. preserves text-block metadata such as `cache_control`;
5. leaves user, assistant, and tool messages in their original order; and
6. returns an Anthropic-shaped HTTP 400 for non-text system blocks rather than
   silently discarding content.

This is a narrow compatibility safeguard for the currently reported
[LiteLLM system-message issue](https://github.com/BerriAI/litellm/issues/36917), not a
general prompt-rewriting feature.

## Offline installation

### Server requirements

- Ubuntu 20.04 or newer, `x86_64`;
- Docker Engine and Docker Compose v2;
- Ollama `0.13.3` or newer, managed by the host and reachable on
  `127.0.0.1:11434`;
- at least one model already installed in Ollama; and
- port 4000 restricted to trusted clients.

Transfer the release archive and adjacent checksum file, then run:

```bash
sha256sum -c ccobridge-offline-1.1.0-linux-amd64.tar.gz.sha256
tar -xzf ccobridge-offline-1.1.0-linux-amd64.tar.gz
cd ccobridge-offline-1.1.0
sudo ./deploy/install.sh
```

The installer verifies the outer and inner checksums, checks the platform, Ollama,
port 4000, and any existing container ownership, loads the bundled image without
pulling, preserves an existing `.env`, creates a
mode-`0600` API key on first install, starts Compose with `--pull never`, and runs live
acceptance checks.

Lifecycle commands are installed under `/opt/ccobridge`:

```bash
sudo /opt/ccobridge/start.sh
sudo /opt/ccobridge/stop.sh
sudo /opt/ccobridge/logs.sh
sudo /opt/ccobridge/verify.sh
sudo /opt/ccobridge/uninstall.sh
```

Uninstall removes the container while preserving the image, configuration, and key.

## Build and test

Build the release in Linux or WSL 2 with Linux containers:

```bash
./scripts/build-offline.sh
```

The builder pulls the pinned LiteLLM base, verifies its digest, builds for
`linux/amd64`, runs unit and two-container integration tests, exports the image,
generates checksums, reloads the saved image, and reruns the suite. Outputs are placed
in the ignored `dist/` directory.

Fast development checks:

```bash
python3 -m pip install ruff==0.16.3
make check
```

Full Docker integration:

```bash
make integration
```

The deterministic Fake Ollama suite covers authentication, dynamic model discovery,
aliases, Chat Completions, Responses, Embeddings, OpenAI and Anthropic streaming,
system normalization, tool definitions, tool calls, tool results, and downstream
model resolution. Fake Ollama and test keys are never included in release archives.

## Configuration reference

Runtime configuration is stored in `/opt/ccobridge/.env`:

| Variable | Required | Default | Purpose |
|---|---:|---|---|
| `CCOBRIDGE_API_KEY` | yes | none | Shared Bearer or `x-api-key` credential |
| `OLLAMA_API_BASE` | no | `http://127.0.0.1:11434` | Host Ollama API |
| `CCOBRIDGE_MODEL_ALIASES` | no | `qwen-code` alias | JSON alias map |
| `GATEWAY_PORT` | no | `4000` | Public listener under host networking |
| `INTERNAL_LITELLM_PORT` | no | `4001` | Container-internal converter listener |
| `GATEWAY_LOG_LEVEL` | no | `info` | Uvicorn log level |

`LITELLM_MASTER_KEY` is accepted as a migration fallback for version 1.0 installations.
Do not set it to a different value from `CCOBRIDGE_API_KEY`.

## Security model

CCOBridge 1.1 targets a trusted internal network. It provides a shared API key but not
TLS, per-user identity, rate limiting, SSO, or user-level audit trails. Restrict port
4000 with a host or network firewall and never expose unauthenticated Ollama port 11434
to clients.

The compatibility proxy does not log request or response bodies. It strips client
credentials before forwarding OpenAI-compatible traffic to Ollama. The installation
key is generated at runtime, stored with mode `0600`, and is not embedded in the image
or release archive.

Before publication, run:

```bash
python3 scripts/check-public-release.py
```

Read [SECURITY.md](SECURITY.md) for reporting and deployment guidance.

## Scope and limitations

- Ollama, model weights, GPU drivers, and host tuning are not bundled.
- The official offline artifact currently targets only `linux/amd64`.
- Responses compatibility is limited to the fields implemented by the installed
  Ollama version; stateful Responses are not emulated.
- Model capabilities are not fabricated. Use an embedding model for embeddings and a
  tool-capable model for agent tools.
- Alias resolution is intentionally static and one level deep.
- CCOBridge is not a multi-user management, billing, or provider-routing platform.
- This independent project is not affiliated with or endorsed by Ollama, Anthropic,
  Claude Code, OpenAI, Qwen, or BerriAI/LiteLLM.

## Documentation

| Document | English | 中文 |
|---|---|---|
| Operations and troubleshooting | [Guide](docs/OPERATION-MANUAL.md) | [操作手册](docs/OPERATION-MANUAL.zh-CN.md) |
| Validation evidence and limits | [Report](docs/TEST-REPORT.md) | [测试报告](docs/TEST-REPORT.zh-CN.md) |
| Publication privacy review | [Audit](docs/PUBLICATION-AUDIT.md) | — |
| Security reporting | [Policy](SECURITY.md) | — |
| Contribution workflow | [Contributing](CONTRIBUTING.md) | — |
| Planned work | [Roadmap](ROADMAP.md) | — |

## Contributing and license

Issues and focused pull requests are welcome. Read [CONTRIBUTING.md](CONTRIBUTING.md),
add tests for observable behavior, and never put prompts, credentials, private network
details, or machine-specific paths in public reports.

CCOBridge source is licensed under [Apache-2.0](LICENSE). Generated images contain
third-party components under their own licenses; see
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
