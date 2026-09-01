# Security Policy

## Supported versions

Security fixes are provided for the latest `1.2.x` release. Older offline bundles
should be upgraded after a replacement release is validated in your environment.

## Reporting a vulnerability

Do not open a public issue for a suspected vulnerability, leaked credential, or sensitive log. Use GitHub's **Report a vulnerability** option in the repository Security tab. Include the affected version, impact, reproduction steps, and a minimal redacted proof of concept.

If private vulnerability reporting has not yet been enabled, contact a maintainer privately through the repository owner's verified profile. Do not post sensitive details while waiting for a private channel.

You should receive an acknowledgement within seven days. A fix timeline depends on severity, exploitability, and the need to rebuild the pinned LiteLLM image.

## Deployment security boundary

- The default deployment uses HTTP and local bearer keys. Expose port 4000 only to trusted networks.
- Keep `/opt/ccobridge/.env` and `config/users.json` at mode `0600`; keep `config/`
  and `data/` at mode `0700`.
- Store the administrator and one-time user keys in a password manager. The gateway
  stores only user-key SHA-256 digests and cannot recover a lost user key.
- Do not publish port 11434 for client access; clients should use the authenticated gateway.
- Disable or rotate an affected user key if it appears in shell history, logs,
  screenshots, tickets, or source control. Rotate the administrator key if it leaks.
- Do not expose unsupported LiteLLM management endpoints; version 1.2 returns 404 for
  paths outside the documented inference and health API.
- The gateway deliberately does not log request or response bodies, but upstream LiteLLM or infrastructure settings may change logging behavior. Review logs before sharing them.
- Token aggregates contain user names, model names, and activity counts but never
  prompts or response bodies. Protect and back up `data/usage.sqlite3` accordingly.
- The project does not provide TLS, rate limits, quotas, SSO, or billing. Add those
  controls at a trusted internal edge when required.

Before publishing a change, run:

```bash
python3 scripts/check-public-release.py
```
