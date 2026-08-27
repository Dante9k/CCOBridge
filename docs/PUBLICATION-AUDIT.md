# Public-release audit

Audit date: 2026-08-27
Scope: source, configuration, tests, deployment scripts, client examples, documentation, and GitHub metadata intended for publication

## Privacy and secret review

The publication candidates were checked for:

- private IPv4 endpoints;
- Windows and WSL user-profile paths;
- private-key material;
- GitHub and AWS token formats;
- long `sk-...` token literals;
- generated artifacts, local `.env` files, logs, archives, packages, and unrelated workspace material.

Environment-specific server addresses found in early drafts were removed. Network
examples now use loopback addresses for same-host access or the RFC 5737 documentation
address `192.0.2.10`. No production API key is present; the installer generates it at
runtime. The remaining fixed credentials are clearly identified test or replacement
placeholders.

`.gitignore` excludes runtime secrets, build output, release archives, editor state, binary packages, and the optional local-only exclusion file. Environment-specific workspace exclusions stay outside version control. `.dockerignore` limits the production build context to files required by the image.

Automated check:

```bash
python3 scripts/check-public-release.py
```

Result at the end of this audit: passed.

## Code and repository standards

- Python targets 3.11+ and is linted/formatted with Ruff.
- Bash uses strict mode and is checked with ShellCheck.
- Unit tests use the standard library; full tests use separate gateway and Fake Ollama containers.
- The image runs as a non-root user and includes a health check.
- Client credentials are stripped before OpenAI-compatible requests reach Ollama.
- Undocumented LiteLLM management routes are not exposed by the public gateway.
- The base image version and digest are locked.
- CI has explicit read-only permissions; release publishing is isolated to version tags with `contents: write`.
- GitHub Actions are pinned to full commit SHAs.
- Community files include license, security policy, contribution guide, code of conduct, changelog, roadmap, issue forms, and a pull request template.
- English and Chinese entry documentation state the simulated-versus-real test boundary.

## Limitations

Pattern scanning reduces accidental disclosure but is not a substitute for human review or repository history scanning. Before the first push, inspect `git status`, review the staged diff, and confirm that no earlier commits contain private material. After creating the repository, enable GitHub private vulnerability reporting, secret scanning, push protection where available, and branch protection for `main`.
