# CCOBridge Test Report

- Report date: 2026-09-01
- Tested release: `1.2.0`

Conclusion: simulated protocol, image recovery, source installation, and offline installation tests passed;
real-model and real-Agent acceptance remains environment-specific

## 1. Scope and claim boundary

This report verifies the CCOBridge source, `linux/amd64` image, deterministic Ollama
simulation, exported archive, installation scripts, and recovery workflow. It covers
protocol preservation and operational delivery, not model intelligence or GPU health.

The following terms are used deliberately:

- **Passed** means an automated assertion ran successfully in the recorded environment.
- **Simulated** means the upstream was Fake Ollama rather than a real model.
- **Pending** means the behavior must be accepted against the intended Ollama, model,
  Agent, network, and hardware combination.

## 2. Test environment

| Item | Tested value |
|---|---|
| Host | Windows with WSL 2 |
| Linux distribution | Ubuntu 22.04 |
| Docker Engine | 29.7.2 |
| Target platform | Linux / amd64 |
| Gateway image | `ccobridge:1.2.0` |
| Runtime identity | `10001:10001` |
| LiteLLM | `v1.94.0` |
| Base digest | `sha256:65d84a2282137b4dc73bbe184650a7c807177c533e4223b3bfbc87963fe3fabe` |
| Upstream | separate deterministic Fake Ollama container |
| Network | Linux host networking |
| Persistence | local SQLite usage aggregates; no PostgreSQL or Redis |

Fake Ollama implements the minimum deterministic surface used by the suite:

- `/api/version`, `/api/tags`, `/api/show`, and `/api/chat`;
- `/v1/chat/completions`, including SSE and tool calls;
- `/v1/completions`;
- `/v1/responses`; and
- `/v1/embeddings`.

It advertises one chat model and one embedding model and records downstream request
fields for assertions. Its test source is present in the full-source Release but is
never copied into the production image.

## 3. Static and unit checks

| Check | Evidence | Result |
|---|---|---|
| Python unit tests | 24 tests for system, aliases, models, multi-key auth, and usage | Passed |
| Ruff lint | selected bug, style, import, modernization, and simplification rules | Passed |
| Ruff format | repository Python formatting check | Passed |
| ShellCheck | client, deployment, build, integration, and lifecycle scripts | Passed |
| PSScriptAnalyzer 1.25.0 | Windows client warnings and errors | Passed |
| Privacy scan | publication candidates checked for common secrets, private IPs, and profile paths | Passed |
| Compose validation | configuration resolves with the documented environment file | Passed |

Alias tests cover blank configuration, JSON validation, whitespace normalization,
native passthrough, empty identifiers, self-references, duplicate normalized names,
whitespace in identifiers, and alias chains. Model-list tests cover dynamic native
models, installed and missing alias targets, intentional name shadowing, deterministic
ordering, timestamps, and malformed Ollama payloads.

## 4. Container integration results

| Area | Assertion | Result |
|---|---|---|
| Liveness and readiness | gateway, Ollama tags, and internal LiteLLM are ready | Passed |
| Missing authentication | protected endpoint returns OpenAI-shaped HTTP 401 | Passed |
| Bearer authentication | administrator and independent user keys authorize inference | Passed |
| Anthropic `x-api-key` | correct key retrieves an individual model | Passed |
| Dynamic discovery | native chat and embedding models are returned | Passed |
| Alias discovery | installed alias targets are advertised | Passed |
| Individual model | `/v1/models/{model}` returns the alias metadata | Passed |
| Alias routing | public chat alias resolves to the native Ollama model | Passed |
| Native routing | native Ollama model passes through unchanged | Passed |
| Credential isolation | Bearer and `x-api-key` headers do not reach Ollama | Passed |
| Digest-only user keys | configuration contains SHA-256 digests, not plaintext user keys | Passed |
| Administrator isolation | user key receives 403 from `/admin/users` and `/admin/usage` | Passed |
| Performance isolation | user key receives 403 from `/admin/performance` | Passed |
| User listing | administrator receives non-secret user metadata | Passed |
| Token attribution | Chat usage is assigned to the requesting user, model, and endpoint | Passed |
| Metering coverage | requests and metered requests are counted separately | Passed |
| Request correlation | inference response includes an unpredictable request ID and `Server-Timing` | Passed |
| Performance report | administrator receives recent timings, averages, and observed token rate | Passed |
| Performance redaction | report can hide user identifiers and contains no request or response body | Passed |
| Chat Completions | deterministic OpenAI response is preserved | Passed |
| Chat SSE | split events reconstruct the expected text | Passed |
| Completions | legacy completion response is preserved | Passed |
| Responses | response object is preserved and alias is resolved | Passed |
| Embeddings | vector array is preserved and embedding alias is resolved | Passed |
| OpenAI tools | tool schema reaches Ollama and the tool call returns intact | Passed |
| Management isolation | `/key/generate` returns 404 instead of reaching LiteLLM | Passed |
| Anthropic Messages | Anthropic message response is returned | Passed |
| Mid-system regression | downstream system roles occur only before non-system roles | Passed |
| Sentinel preservation | top and middle system sentinels both reach downstream | Passed |
| Text-block metadata | `cache_control` survives normalization | Passed |
| Unsupported system block | Anthropic-shaped HTTP 400; no downstream request | Passed |
| Anthropic SSE | text deltas reconstruct `stream-ok` | Passed |
| Anthropic tool definition | LiteLLM/Ollama receives the schema | Passed |
| Anthropic tool call | populated `tool_use` name and arguments return | Passed |
| Tool result | tool ID and result reach the next downstream request | Passed |

The integration suite uses a custom alias map with a chat and embedding alias. This
proves that the gateway does not depend on a single baked model name.

## 5. Image and offline artifact results

The release builder completed all seven stages:

1. pulled LiteLLM `v1.94.0` and matched the resolved digest to `BASE-IMAGE.lock`;
2. built `ccobridge:1.2.0` for `linux/amd64`;
3. ran the unit and two-container integration suite;
4. exported the production image with `docker save`;
5. packaged the complete tracked source and verified the inner manifest and outer
   SHA-256 file;
6. removed the primary image tag and reloaded the saved archive; and
7. reran the complete suite against the reloaded image.

| Artifact property | Result |
|---|---|
| Target architecture is amd64 | Passed |
| Container runs as non-root `10001:10001` | Passed |
| Base release and digest are locked | Passed |
| No runtime API key is baked into image configuration | Passed |
| Inner `SHA256SUMS` verifies every packaged file | Passed |
| Outer `.tar.gz.sha256` verifies the release archive | Passed |
| Reloaded image ID matches the exported image ID | Passed |
| Full post-reload integration suite | Passed |
| Complete Git-tracked source is present in the Release | Passed |
| Fake Ollama and test placeholders are excluded from the production image | Passed |

Generated deliverables:

```text
dist/ccobridge-offline-1.2.0-linux-amd64.tar.gz
dist/ccobridge-offline-1.2.0-linux-amd64.tar.gz.sha256
```

The exact gateway image ID, source revision, build time, base digest, and target
platform are stored in the release's `BUILD-INFO.txt`. The archive checksum is stored
in the adjacent `.sha256` file rather than duplicated in this source document.

## 6. Offline and source installation lifecycle

The final archive was extracted into an isolated `/tmp/ccobridge-install-audit.*`
directory and tested as root, matching the Ubuntu installer workflow. Before starting,
the test refuses to touch an existing `ccobridge` container, Fake Ollama container, or
occupied port 4000/11434. Cleanup removes only resources carrying the current audit
identity or Compose working directory.

The lifecycle assertions passed:

- package-internal checksums verified before installation;
- Fake Ollama `0.13.3` satisfied version and model preflight checks;
- the local image loaded and started with `--pull never`;
- live model, Chat Completions, Responses, and Anthropic verification passed;
- the generated `sk-...` key file had mode `0600`;
- user-key creation, automatic reload, disable, and re-enable passed;
- plaintext user keys were absent from configuration and digest-file ownership matched policy;
- per-user Chat token usage persisted in local SQLite;
- the no-inference `diagnose.sh` reported container, control-plane, and redacted
  performance data;
- host networking, `unless-stopped`, and non-root runtime identity matched policy;
- a second installation preserved `.env`, user configuration, and the usage database;
- uninstall removed the gateway container while retaining image, `.env`, users, and usage; and
- the production image was removed and rebuilt from the source tree using the pinned,
  locally cached base image;
- source-mode installation passed the same live checks and recorded
  `install_mode=source-build`; and
- audit containers, temporary image tag, ports, directory, and credential were removed.

The lifecycle script is available as `tests/run-install-lifecycle.sh`. It is included
as auditable test source in the full-source Release but is not invoked during a normal
target-server installation.

## 7. Security and privacy observations

- Public inference endpoints compare the administrator and every user-key digest in constant time.
- Both Bearer and `x-api-key` inputs are accepted; neither is forwarded to Ollama.
- Health endpoints reveal only coarse service status.
- Unsupported routes do not expose the internal LiteLLM management plane.
- CCOBridge does not log request or response bodies and disables Uvicorn access logs.
- The installer creates the administrator credential at runtime; user keys are shown
  once and only their digests are persisted.
- SQLite usage rows store identity, model, endpoint, and aggregate counts. Performance
  rows additionally store request ID, status, and timings and are capped at the latest
  1,000. Neither table stores prompts, response bodies, client IPs, or plaintext keys.
- The publication scanner found no private endpoint, user-profile path, private key,
  GitHub token, AWS access key, or long production-style `sk-...` literal.

This is not a penetration test or dependency vulnerability audit. The default profile
still uses HTTP and must remain on a trusted network. Token totals depend on usage
reported by the upstream and are not a billing ledger.

## 8. Real-environment work still required

The automated environment did not use the intended physical GPU, production Ollama
service, or real Agent applications. The following must not be represented as passed:

- real inference with the intended Qwen, Llama, embedding, vision, or other models;
- output quality, context-window behavior, throughput, and concurrent load;
- Cursor, Continue, OpenCode, LangChain, LlamaIndex, AutoGen, CrewAI, or other Agent
  application compatibility;
- Claude Code Read, Write, Edit, Bash, and multi-round project workflows;
- model-specific tool, reasoning, vision, and embedding capabilities;
- recovery after a real host or Docker daemon restart; and
- production firewall, TLS edge, and network policy.

## 9. Production acceptance criteria

For each Agent and model combination:

1. record the Agent, Ollama, model, and CCOBridge versions;
2. run `/opt/ccobridge/verify.sh` with the intended model;
3. verify normal and streaming chat;
4. verify every required tool and a multi-round tool result;
5. verify Responses or Embeddings when the Agent uses them;
6. review redacted logs for protocol or template errors;
7. restart Docker or the host and confirm automatic recovery; and
8. confirm clients reach authenticated port 4000 and cannot reach Ollama port 11434.

## 10. Conclusion

CCOBridge `1.2.0` passed the defined static, unit, simulated protocol, multi-key
authentication, administrator isolation, token attribution, privacy-safe performance
timing, streaming, tools, image recovery, checksum, source installation, offline
installation, repeated installation, and uninstall tests.
The result supports publishing a controlled release candidate. Production approval
still depends on real-model and real-Agent acceptance in the target environment.
