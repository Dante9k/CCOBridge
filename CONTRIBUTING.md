# Contributing to CCOBridge

Thank you for helping improve the project. Small, focused pull requests with tests and clear operational impact are the easiest to review.

## Before you start

- Search existing issues and pull requests to avoid duplicate work.
- Open an issue before making a behavior, API, security, packaging, or dependency change.
- Never include access keys, prompts, internal addresses, customer data, or machine-specific paths in an issue, log, fixture, or commit.
- Keep the gateway focused: Ollama protocol compatibility, authentication, model
  aliases, Agent interoperability, and reproducible offline delivery belong here;
  model tuning, GPU repair, billing, and identity platforms do not.

## Development environment

The source supports Python 3.11 or newer. Full integration tests require Linux, Docker with `linux/amd64` support, Compose v2, and host networking.

Install the development linter:

```bash
python3 -m pip install ruff==0.16.3
```

Run the fast checks:

```bash
make check
```

Run the Docker integration suite when changing proxy, LiteLLM, Ollama, container, or packaging behavior:

```bash
make integration
```

## Code standards

- Format and lint Python with Ruff using `pyproject.toml`.
- Check Bash with ShellCheck and keep `set -Eeuo pipefail` in executable scripts.
- Prefer the Python standard library in build and deployment scripts so offline servers need no extra packages.
- Preserve streaming semantics and never log request or response bodies.
- Preserve native Ollama model-name passthrough and keep alias resolution explicit.
- Do not claim that the gateway adds model capabilities that Ollama or the selected
  model does not provide.
- Fail explicitly when content cannot be preserved safely; never silently discard prompt or tool data.
- Pin production image versions and verify the digest in `BASE-IMAGE.lock`.
- Add or update tests for every observable behavior change.
- Update both English and Chinese user documentation when commands or configuration change.

## Pull requests

Use a conventional, imperative title such as `fix: preserve duplicate system blocks`. In the description, explain the problem, the chosen behavior, security implications, tests performed, and documentation changes.

Every pull request must pass CI. Maintainers may ask for an integration run before merging changes that affect the deliverable image.

## License

By submitting a contribution, you agree that it is licensed under the repository's [Apache License 2.0](LICENSE).
