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

## Browser acceptance checks

After installing the Python development dependencies in `.venv`:

```sh
npm ci --prefix console
npm run build --prefix console
cd console
npx playwright install chromium
npm run test:e2e
```

The tests launch a disposable API/database on `127.0.0.1:18787` and stop it on completion. They never connect to an existing instance. On a workstation with Chrome installed, set `EIVON_TEST_CHROME` to its executable path to use that browser instead of downloading Playwright Chromium. Failure screenshots and traces are written under `console/test-results/` (ignored by Git). The GitHub Actions workflow runs backend tests, the frontend build and browser acceptance checks.

The browser suite currently covers workflow authoring/execution and UI-authored Agents with multi-turn conversations, approvals, file downloads and cancellation. `scripts/browser_model.py` is a deterministic HTTP transport fixture loaded only by `scripts/serve_e2e.py`; it is not part of the production runtime.
