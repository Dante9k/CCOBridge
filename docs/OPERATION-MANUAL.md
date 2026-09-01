# CCOBridge Operations Guide

- Document version: 1.2
- Bundle: `ccobridge-offline-1.2.0-linux-amd64.tar.gz`
- Target: Ubuntu 20.04+, x86_64, Docker Engine, Docker Compose v2

## 1. Deployment model

CCOBridge exposes the models already installed in a host-managed Ollama service:

```text
OpenAI-compatible agents ── OpenAI API ──┐
                                         ├─ CCOBridge :4000 ── Ollama :11434
Claude Code ── Anthropic Messages ───────┘          │
                                                    └─ LiteLLM :4001 (internal)
```

OpenAI-compatible inference uses a direct streaming path. Anthropic Messages uses
LiteLLM for protocol conversion. Only CCOBridge port 4000 should be reachable by
clients; Ollama remains private on the host loopback interface.

## 2. Preconditions

The server must have:

- `x86_64` or `amd64` architecture;
- a running Docker service and the Compose v2 plugin;
- `curl`, `sort`, and `ss`;
- `git` for a connected source checkout, or `sha256sum` and `tar` for an offline
  Release;
- Ollama `0.13.3` or newer on `http://127.0.0.1:11434`;
- at least one installed Ollama model; and
- an available TCP port 4000, restricted to trusted networks.

Check the host before transferring the release:

```bash
uname -m
docker info >/dev/null && echo 'Docker OK'
docker compose version
curl -fsS http://127.0.0.1:11434/api/version
curl -fsS http://127.0.0.1:11434/api/tags
ss -ltn | grep ':4000 ' || echo 'Port 4000 is free'
```

The tags response must contain at least one model. Install chat, tool, vision, or
embedding models according to the Agent workflows you intend to use.

## 3. Choose an installation path

### 3.1 Connected source installation

On a server with registry access:

```bash
git clone https://github.com/Dante9k/CCOBridge.git
cd CCOBridge
sudo ./deploy/install.sh --online
```

The installer builds the image from the checked-out source. It uses the exact
LiteLLM digest in `BASE-IMAGE.lock`, reuses a locally cached base image when present,
and downloads that pinned base only when necessary.

### 3.2 Air-gapped Release transfer and verification

Transfer both files from the same release:

```text
ccobridge-offline-1.2.0-linux-amd64.tar.gz
ccobridge-offline-1.2.0-linux-amd64.tar.gz.sha256
```

Verify the outer archive before extraction:

```bash
sha256sum -c ccobridge-offline-1.2.0-linux-amd64.tar.gz.sha256
```

Do not continue after a checksum mismatch.

## 4. Install the air-gapped Release

```bash
tar -xzf ccobridge-offline-1.2.0-linux-amd64.tar.gz
cd ccobridge-offline-1.2.0
sudo ./deploy/install.sh --offline
```

The extracted Release contains the complete tracked source tree and the prebuilt
image. `sudo ./deploy/install.sh` also works in auto mode and selects the bundled
image. A source-only copy cannot bootstrap a completely isolated host unless the
pinned base image is already present in Docker.

The installer:

1. verifies every bundled file using `SHA256SUMS`;
2. checks architecture, Docker, Compose, port 4000, existing container ownership,
   Ollama version, and installed models;
3. builds `ccobridge:1.2.0` from source or loads it from the local Docker archive;
4. installs lifecycle files into `/opt/ccobridge`;
5. creates a random administrator `sk-...` API key only when `.env` does not exist;
6. creates protected user-key configuration and local usage-data directories;
7. adds the backwards-compatible `qwen-code` alias when `qwen3.8:latest` exists;
8. starts with host networking, `restart: unless-stopped`, and `--pull never`; and
9. runs model, Chat Completions, Responses, and Anthropic acceptance checks.

The installer does not print the key. Retrieve it directly from the protected server
file through an approved administrative session, store it in a password manager, and
keep the server copy at mode `0600`:

```bash
sudo stat -c '%a %n' /opt/ccobridge/.env
```

Repeated installation preserves `.env`, user-key digests, and the usage database.

## 5. Runtime configuration

The default `/opt/ccobridge/.env` contains:

```dotenv
CCOBRIDGE_API_KEY=<generated-key>
OLLAMA_API_BASE=http://127.0.0.1:11434
CCOBRIDGE_MODEL_ALIASES={"qwen-code":"qwen3.8:latest"}
```

If Qwen is not installed during first installation, the alias object is empty. Native
Ollama model identifiers need no configuration and are always available.

Configure multiple aliases as one JSON object:

```dotenv
CCOBRIDGE_MODEL_ALIASES={"qwen-code":"qwen3.8:latest","local-embed":"nomic-embed-text:latest"}
```

Alias targets must be native Ollama model identifiers. An alias whose target is not
installed is not advertised by `/v1/models`. Invalid JSON or self-referential aliases
fail container startup. A configured alias shadows a native model with the same
identifier; avoid that collision unless it is an intentional override.

Version 1.0 installations using `LITELLM_MASTER_KEY` continue to work. During key
rotation, migrate to `CCOBRIDGE_API_KEY`; never set both variables to different values.

After any configuration change:

```bash
cd /opt/ccobridge
sudo docker compose --env-file .env up -d --force-recreate --pull never
sudo ./verify.sh
```

## 6. Verify the service

```bash
docker ps --filter name=ccobridge
docker inspect --format '{{.State.Health.Status}}' ccobridge
sudo /opt/ccobridge/verify.sh
```

The verifier selects `qwen-code` when available, otherwise it selects a discovered
model. To force a particular acceptance model:

```bash
sudo CCOBRIDGE_VERIFY_MODEL='llama3.2:latest' /opt/ccobridge/verify.sh
```

The automated verifier checks readiness, model discovery, Chat Completions, Responses,
Anthropic Messages, and mid-conversation system normalization. Embeddings are covered
by the integration suite but not the server verifier because a general installation
may not contain an embedding-capable model.

View recent gateway logs:

```bash
sudo /opt/ccobridge/logs.sh
```

## 7. Configure OpenAI-compatible agents

Most clients use these values:

```dotenv
OPENAI_BASE_URL=http://192.0.2.10:4000/v1
OPENAI_API_KEY=<installed-api-key>
```

Replace the documentation address with the trusted server address. Some products call
the field `OpenAI endpoint`, `custom provider`, or `API base`, and some expect the URL
without `/v1`. Confirm the convention in the Agent's documentation.

Before configuring an Agent, inspect the authenticated model list:

```bash
curl -fsS http://192.0.2.10:4000/v1/models \
  -H 'Authorization: Bearer <installed-api-key>'
```

Use an advertised native model name or alias. Do not assume that an arbitrary OpenAI
model name exists unless you configured it as an alias.

## 8. Configure Claude Code

Claude Code's URL does not include `/v1`:

```powershell
.\client\claude-ccobridge.ps1 `
  -Gateway "http://192.0.2.10:4000" `
  -Model "qwen-code"
```

```bash
export CCOBRIDGE_URL='http://192.0.2.10:4000'
export CCOBRIDGE_MODEL='qwen-code'
./client/claude-ccobridge.sh
```

Manual current-session configuration:

```bash
export ANTHROPIC_BASE_URL='http://192.0.2.10:4000'
export ANTHROPIC_AUTH_TOKEN='<installed-api-key>'
unset ANTHROPIC_API_KEY
claude --model qwen-code
```

The helpers prompt for the key without echoing it. Literal keys in shell commands may
remain in history.

## 9. Agent acceptance procedure

API conformance and model capability are separate. Test each production Agent and
model combination in a disposable directory:

```bash
acceptance_dir="$(mktemp -d)"
cd "$acceptance_dir"
printf '%s\n' 'acceptance input' > README.txt
```

For a coding Agent, verify:

1. ordinary chat;
2. directory listing and file reading;
3. file creation and modification;
4. command or script execution;
5. multi-round tool results;
6. streaming output; and
7. recovery after Docker or server restart.

Record the Agent version, Ollama version, model digest, gateway image ID, request mode,
and redacted results. Never publish prompts or paths containing confidential data.

## 10. Per-user keys and usage reporting

The key in `.env` is the administrator credential for acceptance and management.
Create one independent key per user:

```bash
cd /opt/ccobridge
sudo ./users.sh add alice
sudo ./users.sh list
```

Save the key displayed once; `config/users.json` stores only its SHA-256 digest.
Changes reload automatically without a gateway restart:

```bash
sudo ./users.sh disable alice
sudo ./users.sh enable alice
sudo ./users.sh rotate alice
```

Rotation invalidates the old key immediately. User credentials cannot call management
endpoints. View all usage for 30 days or filter by user ID:

```bash
sudo ./usage.sh
sudo ./usage.sh 30 usr_0123456789abcdef
```

`data/usage.sqlite3` aggregates requests, successful requests, metered requests, and
input/output/total tokens by UTC day, user, model, and endpoint. It stores no request
or response body. Only backend-reported usage counts as metered, so do not use a report
with incomplete coverage for billing.

Direct management API calls require the administrator key:

```bash
curl -fsS 'http://127.0.0.1:4000/admin/usage?days=30' \
  -H 'Authorization: Bearer <admin-key>'
```

## 11. Routine operations

```bash
sudo /opt/ccobridge/start.sh
sudo /opt/ccobridge/stop.sh
sudo /opt/ccobridge/logs.sh
sudo /opt/ccobridge/verify.sh
sudo /opt/ccobridge/users.sh list
sudo /opt/ccobridge/usage.sh
```

With `restart: unless-stopped`, the container recovers after Docker or server restart.
An explicit `stop.sh` keeps it stopped until `start.sh` is run.

Ollama model installation and removal are reflected dynamically in `/v1/models` and
do not require a CCOBridge restart. Alias changes do require container recreation.

## 12. Upgrade and rollback

Keep the previous release archive and checksum until the new version passes production
acceptance. The installer preserves `/opt/ccobridge/.env`, `config/users.json`, and
`data/usage.sqlite3`.

To roll back, load the previous image and restore its matching Compose file and scripts:

```bash
sudo docker load -i ./image/ccobridge-1.0.0-linux-amd64.tar
cd /opt/ccobridge
sudo docker compose --env-file .env up -d --force-recreate --pull never
sudo ./verify.sh
```

Version 1.0 does not support dynamic model passthrough, Responses, or Embeddings through
CCOBridge; confirm that clients use its `qwen-code` contract after rollback.

## 13. Uninstall

```bash
sudo /opt/ccobridge/uninstall.sh
```

This removes the container and preserves the image, `.env`, user-key digests, and
usage database. Back up `/opt/ccobridge` before manually removing retained files.

## 14. Troubleshooting

### HTTP 401

- For an administrator client, confirm the key equals `CCOBRIDGE_API_KEY` in `.env`.
- For a user, run `sudo ./users.sh list` and confirm the identity is `enabled`.
- For a migrated 1.0 installation, confirm the legacy key is present and not conflicting.
- Remove stale OpenAI or Anthropic credential variables.
- Check for copied whitespace or quotes.

### Model not found

- Call authenticated `GET /v1/models` and use an returned identifier.
- Confirm `ollama list` contains the alias target.
- Validate `CCOBRIDGE_MODEL_ALIASES` as a JSON object.
- Recreate the container after changing aliases.

### Responses returns 404 or an unsupported-field error

- Confirm Ollama is at least `0.13.3`.
- Remember that Ollama implements only non-stateful Responses.
- Remove `previous_response_id`, `conversation`, or other unsupported fields.

### Embeddings fails

- Use an embedding-capable model, not a chat-only model.
- Call the same model directly against Ollama to separate model support from the
  gateway path.

### Ollama is unreachable

- Run `curl http://127.0.0.1:11434/api/tags` on the host.
- Check `systemctl status ollama`.
- Confirm `OLLAMA_API_BASE` and Linux host networking.
- Do not use `host.docker.internal` in the supported profile.

### Anthropic system-template error returns

- Confirm the client is reaching port 4000 rather than Ollama directly.
- Run `verify.sh` and inspect redacted logs.
- Confirm the intended image tag and ID are running.

### Tool calls are empty or unreliable

- Confirm the selected model supports tools in Ollama.
- Reproduce with a minimal tool definition through Chat Completions.
- Treat poor argument selection as a model capability issue unless the captured
  downstream request proves protocol data was lost.

### Usage does not increase

- Confirm the request used a user key and called inference rather than `/v1/models`.
- Compare `requests` with `metered_requests`; an upstream response without usage only
  increments the request count.
- Confirm the data directory belongs to `10001:10001` and inspect logs for SQLite errors.

## 15. Security checklist

- Restrict port 4000 to trusted clients.
- Keep Ollama port 11434 private.
- Keep `.env` at mode `0600`.
- Keep `config/users.json` at mode `0600` and `config/` plus `data/` at mode `0700`.
- Give each person a separate key; disable or rotate it immediately after departure or
  suspected disclosure.
- Do not publish prompt-bearing logs or environment-specific diagnostics.
- Add a trusted TLS edge before crossing an untrusted network.
- Run `scripts/check-public-release.py` before every public release.
