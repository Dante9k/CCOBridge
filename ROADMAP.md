# Roadmap

The roadmap is directional, not a promise of delivery. Security and correctness take priority over feature volume.

## 1.0 — Reproducible offline gateway

- [x] Pinned LiteLLM release and base image digest
- [x] Anthropic system-message compatibility layer
- [x] OpenAI and Anthropic API regression coverage
- [x] Streaming and tool-call round-trip coverage
- [x] Offline image export, checksum, reload proof, and installer
- [x] Public repository quality and privacy checks

## Next

- [ ] Publish reproducible release provenance and an SBOM alongside bundles
- [x] Add dynamic Ollama model discovery and configurable aliases
- [x] Add OpenAI Responses and Embeddings fast paths
- [ ] Add optional request-size and concurrency safeguards
- [ ] Publish a tested Agent compatibility matrix with redacted fixtures
- [ ] Add optional per-model capability metadata without fabricating capabilities
- [ ] Document a reference TLS reverse-proxy deployment as an optional layer

## Out of scope

- Bundling Ollama models or GPU drivers
- Repairing GPU drivers, virtualization, accelerator runtimes, or host kernel issues
- Replacing Ollama's context and model configuration
- Shipping PostgreSQL, Redis, SSO, observability, or multi-tenant billing
- Becoming a multi-provider routing or reseller platform

Open a feature request before starting roadmap work so design and compatibility expectations can be agreed first.
