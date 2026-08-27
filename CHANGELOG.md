# Changelog

All notable changes are documented here. This project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

No unreleased changes.

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
