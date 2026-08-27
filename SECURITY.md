# Security Policy

## Supported versions

Security fixes are provided for the latest `1.1.x` release. Older offline bundles
should be upgraded after a replacement release is validated in your environment.

## Reporting a vulnerability

Do not open a public issue for a suspected vulnerability, leaked credential, or sensitive log. Use GitHub's **Report a vulnerability** option in the repository Security tab. Include the affected version, impact, reproduction steps, and a minimal redacted proof of concept.

If private vulnerability reporting has not yet been enabled, contact a maintainer privately through the repository owner's verified profile. Do not post sensitive details while waiting for a private channel.

You should receive an acknowledgement within seven days. A fix timeline depends on severity, exploitability, and the need to rebuild the pinned LiteLLM image.

## Deployment security boundary

- The default deployment uses HTTP and a shared bearer key. Expose port 4000 only to trusted networks.
- Keep `/opt/ccobridge/.env` at mode `0600` and store the API key in a password manager.
- Do not publish port 11434 for client access; clients should use the authenticated gateway.
- Rotate the API key if it appears in shell history, logs, screenshots, tickets, or source control.
- Do not expose unsupported LiteLLM management endpoints; version 1.1 returns 404 for
  paths outside the documented inference and health API.
- The gateway deliberately does not log request or response bodies, but upstream LiteLLM or infrastructure settings may change logging behavior. Review logs before sharing them.
- The project does not provide TLS, user-level authorization, rate limits, or audit identity. Add those controls at a trusted internal edge when required.

Before publishing a change, run:

```bash
python3 scripts/check-public-release.py
```
