# RESEARCH NOTES — 2026-09-24

External facts checked during planning.

## Python

- Stable latest feature line: Python 3.14; Python 3.15 final is scheduled for 2026-10-01.
- Python 3.11 and 3.12 are security-supported; 3.13/3.14 are bugfix-supported.
- Python 3.10 reaches end of life in October 2026.

Sources:
- https://devguide.python.org/versions/
- https://www.python.org/downloads/

## Python Packaging

PyPA documents `pyproject.toml`, `src` layout for CLI examples, and `[project.scripts]` for console entry points.

Sources:
- https://packaging.python.org/en/latest/guides/creating-command-line-tools/
- https://packaging.python.org/en/latest/guides/writing-pyproject-toml/

## PyPI Name

`qualitygate` already exists on PyPI as another project. The public distribution therefore needs a different name even if the product/Repo retains a related brand.

Source:
- https://pypi.org/project/qualitygate/

## PyPI Publishing

Trusted Publishing uses OIDC and avoids long-lived API tokens. A dedicated GitHub Actions release workflow is recommended.

Sources:
- https://docs.pypi.org/trusted-publishers/
- https://docs.pypi.org/trusted-publishers/security-model/

## GitHub Public Project Health

GitHub recognizes/recommends files including LICENSE, CONTRIBUTING, CODE_OF_CONDUCT and SECURITY for public community profiles.

Sources:
- https://docs.github.com/en/communities/setting-up-your-project-for-healthy-contributions/about-community-profiles-for-public-repositories
- https://docs.github.com/en/communities/setting-up-your-project-for-healthy-contributions/creating-a-default-community-health-file

## SARIF

GitHub accepts SARIF 2.1.0 from third-party static analysis tools and can expose uploaded findings as code scanning alerts.

Source:
- https://docs.github.com/en/code-security/how-tos/find-and-fix-code-vulnerabilities/integrate-with-existing-tools/upload-sarif-file

## Landscape

MegaLinter demonstrates strong demand for local/CI code-quality aggregation, but its value proposition is broad linter orchestration. CODE_QUALITY_GENERAL should differentiate around evidence-backed regression rules and agent-era executable engineering memory rather than trying to duplicate every standard linter.

Source:
- https://github.com/oxsecurity/megalinter

## GitHub Code Quality — current landscape

GitHub Code Quality became generally available on 2026-07-20. It uses deterministic CodeQL findings for maintainability/reliability, supports coverage gating and offers AI-powered detection/autofix as separate usage. GitHub documents deterministic language support for C#, Go, Java, JavaScript, Python, Ruby and TypeScript.

Sources:
- https://github.blog/changelog/2026-06-16-github-code-quality-generally-available-july-20-2026/
- https://docs.github.com/en/code-security/concepts/code-quality/code-quality
