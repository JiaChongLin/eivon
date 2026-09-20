# Contributing to Eivon

Eivon is a domain-independent, self-hosted agent workbench. Keep the core free of business-specific entities and dependencies. Domain integrations belong in extensions or separate Bundle packages.

## Development

```bash
python -m venv .venv
.venv/bin/pip install -e '.[dev,postgres]'
.venv/bin/pytest -q
.venv/bin/ruff check src tests examples
cd console && npm install && npm run build
# Before publishing a release
python scripts/export_release.py /tmp/eivon-release
```

## Contract rules

- Public resources are versioned and published immutably. Do not make running code read mutable drafts.
- Every execution must carry workspace, principal, Agent release and ordered Run events.
- Authorization is enforced by the server at execution time. UI visibility is not authorization.
- Do not add keyword routing trees for domain behavior. Use extension metadata and model-assisted selection.
- Never log credentials, passwords, full authorization headers, or arbitrary user payloads.
- Changes to public API schemas require a migration note and contract tests.

## Pull requests

Include the user-visible behavior, migration impact, exact validation commands, and security considerations. New extensions should include a synthetic test domain and avoid private production data.
