# Changelog

All notable changes are documented here. This project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Independent user API keys with one-time secret display, digest-only storage,
  automatic reload, and enable, disable, and rotate operations.
- Administrator-only `/admin/users` and `/admin/usage` endpoints.
- Privacy-preserving SQLite aggregates for requests and backend-reported input,
  output, and total tokens by UTC day, user, model, and endpoint.
- Offline-capable `users.sh` and `usage.sh` management helpers.
- One installer now supports connected source builds and checksum-verified offline
  image loading through explicit or automatic mode selection.
- Release bundles now include the complete Git-tracked source tree alongside the
  prebuilt image.

### Changed

- The installation now creates and preserves protected `config/` and `data/`
  directories and treats the original runtime key as the administrator credential.
- The image and offline artifact version is now `1.2.0`.
- The installation lifecycle test now validates both source and offline deployment
  paths, user-key revocation, digest-only key storage, and persistent usage totals.

## [1.1.0] - 2026-08-27

### Added

- Dynamic discovery of every model installed in Ollama.
- Configurable JSON model aliases with startup validation.
- Authenticated OpenAI Responses, Completions, and Embeddings endpoints.
- Readiness checks covering both Ollama and the internal LiteLLM converter.
- Bearer and Anthropic `x-api-key` authentication at the CCOBridge boundary.

### Changed

- Repositioned CCOBridge as a lightweight Ollama compatibility gateway for multiple
  agents, while retaining Claude Code support.
- OpenAI-compatible requests now use a streaming fast path directly to Ollama.
- Restricted the public surface to documented inference and health endpoints instead
  of forwarding LiteLLM management paths.
- Hardened installation checks for port conflicts, existing container ownership, and
  `.env` file permissions; verification no longer executes `.env` as shell code or
  exposes its API key in process arguments.
- Raised the minimum supported Ollama version to `0.13.3` for Responses support.
- Renamed the primary runtime credential to `CCOBRIDGE_API_KEY`; the 1.0 variable is
  retained as a migration fallback.
- Updated the offline artifact and image version to `1.1.0`.

### Compatibility

- The `qwen-code` alias remains available by default when `qwen3.8:latest` is
  installed.
- Existing native Ollama model names can now be called without gateway configuration.

## [1.0.0] - 2026-08-25

### Added

- Pinned LiteLLM `v1.94.0` gateway image for `linux/amd64`.
- Anthropic `/v1/messages` middleware that safely hoists mid-conversation system text blocks.
- Ollama `ollama_chat/qwen3.8:latest` model alias exposed as `qwen-code`.
- Offline bundle builder, SHA-256 verification, one-command installer, lifecycle scripts, and Claude Code client helpers.
- Deterministic Fake Ollama integration tests for models, chat, Messages, streaming, tools, tool results, and image reload recovery.
