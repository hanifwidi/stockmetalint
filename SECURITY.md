# Security policy

## Supported versions

| Version | Supported |
|---|---|
| 0.1.x | Yes |

## Reporting a vulnerability

Please **do not open a public issue**. Use GitHub's private vulnerability reporting for this
repository (**Security → Report a vulnerability**). Include a synthetic reproducer; never attach
real contributor media, metadata or credentials.

Expect an acknowledgement within 7 days. Fixes are released as patch versions and credited
unless you prefer otherwise.

## Scope

In scope: path traversal or symlink escape, writing outside the requested output, overwriting
inputs, CSV/formula or terminal injection, crashes or unbounded memory on crafted input, any
network access, and leaking local paths.

The security design is documented in [docs/security-model.md](docs/security-model.md).
