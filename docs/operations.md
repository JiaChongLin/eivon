# Operations guide

## Local deployment

Use `eivon init` to create the data directory and setup token, then run `eivon serve`. SQLite is the default for a single local instance. Set `EIVON_DATABASE_URL=postgresql+psycopg://…` and a shared `EIVON_SECRET_KEY` for a multi-process deployment.

## Separate workers

Set `EIVON_INLINE_WORKER=false` for the API process and run `eivon worker` in one or more worker containers. Workers use database leases and ordered event writes. A lease expiry closes the Run with an explicit side-effect warning; operators should inspect external systems before rerunning.

## Extension trust

Python extensions execute with deployment privileges. Only install reviewed packages and use a separate worker image or process boundary for untrusted connectors. HTTP adapters require `EIVON_OUTBOUND_HOSTS`; credentials are encrypted at rest and redacted from connector results.

## Backups and upgrades

Back up the database and the private `EIVON_DATA_DIR` artifact/secret files together. The current bootstrap uses SQLAlchemy metadata creation; production deployments should pin the package version and add reviewed migrations before upgrading a live database. Health probes are `/health/live` and `/health/ready`.
