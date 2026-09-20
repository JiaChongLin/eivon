# Operations guide

## Local deployment

Use `eivon init` to create the data directory and setup token, then run `eivon serve`. SQLite is the default for a single local instance. Set `EIVON_DATABASE_URL=postgresql+psycopg://…` and a shared `EIVON_SECRET_KEY` for a multi-process deployment.

Run `eivon migrate` before starting API and worker processes. The command applies the numbered schema boundary and prints the resulting version.

## Separate workers

Set `EIVON_INLINE_WORKER=false` for the API process and run `eivon worker` in one or more worker containers. Workers use database leases and ordered event writes; they also reconcile durable evaluation Jobs after a restart. A lease expiry closes the Run with an explicit side-effect warning; operators should inspect external systems before rerunning.

To repeat the local concurrency check used for the release evidence, run it from a checkout with the development environment:

```bash
PYTHONPATH=src .venv/bin/python scripts/stress_leases.py --runs 128 --workers 8
```

The command creates an isolated SQLite queue, has independent database connections claim it concurrently, and then checks stale-lease fencing. The report must show `claims == unique_claims == runs`, `duplicate_claims == 0`, an empty `errors` list, and all four fencing assertions true. This is a local SQLite measurement; production PostgreSQL capacity and restore rehearsal still depend on the deployment environment.

## Extension trust

Python extensions execute with deployment privileges by default. Set `EIVON_EXTENSION_RUNNER=process` to run each extension call in a short-lived child process with timeout/cancellation termination and a JSON result boundary. The process runner is a boundary, not a kernel sandbox: use a dedicated worker container/user and OS controls for untrusted connectors. Only install reviewed packages. HTTP adapters require `EIVON_OUTBOUND_HOSTS`; credentials are encrypted at rest and redacted from connector results.

## Backups and upgrades

Stop API and worker processes before restoring. For a local SQLite deployment:

```bash
eivon backup /secure/backups/eivon-$(date +%Y%m%d-%H%M).tar.gz
eivon restore /secure/backups/eivon-20260920-1200.tar.gz --force
eivon migrate
```

The archive contains a consistent SQLite backup made with the SQLite backup API, the private artifacts directory and a schema manifest. Restore rejects path traversal, symbolic links and a schema newer than the running binary. For PostgreSQL, `eivon backup /secure/backups/eivon.dump` invokes `pg_dump --format=custom`, and `eivon restore /secure/backups/eivon.dump --force` invokes `pg_restore --clean --if-exists --no-owner`. Back up the database and private `EIVON_DATA_DIR` together, and verify a restore in a disposable environment before upgrading production. Health probes are `/health/live` and `/health/ready`.
