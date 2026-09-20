# Database migrations

Eivon keeps the schema version in the `meta` table. Version `1` is the initial
metadata bootstrap. Version `2` adds persisted evaluation results. Version `3`
links results to durable evaluation Jobs. All versions are
applied by `eivon migrate` or application startup.

Future schema changes must add a numbered, idempotent migration and advance
`CURRENT_SCHEMA_VERSION` in `src/eivon/server/migrations.py`. The application
fails closed when it sees a newer or unknown version. Run migrations before
starting API and worker processes during an upgrade.
