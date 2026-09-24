# Security policy

## Supported versions

| Version | Supported |
|---|---|
| 0.1.x (pre-release) | yes |
| < 0.1 (`master_gate.py` era) | no — upgrade |

## Reporting a vulnerability

Please **do not** open a public issue. Use GitHub's private vulnerability
reporting ("Report a vulnerability" in the Security tab). You get an answer
within 7 days; fixes are coordinated before disclosure.

In scope: code execution from a scanned repository, path/symlink escapes out
of the scan root, secrets leaking into reports, unsafe subprocess use,
release-pipeline compromise. Design: docs/SECURITY_DESIGN.md.
