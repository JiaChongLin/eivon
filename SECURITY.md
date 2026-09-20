# Security policy

Please report security issues privately to the repository maintainers rather than opening a public issue. Include the affected version, a minimal reproduction and the impact.

Eivon is self-hosted software. Operators are responsible for protecting the data directory, setup token, secret key, database, outbound allowlist and extension code. Python extensions are trusted deployment code; they are not a sandbox.

The server deliberately: hashes passwords with scrypt, stores sessions in HttpOnly SameSite cookies, requires CSRF tokens for cookie writes, encrypts credentials at rest, scopes resources by workspace, uses immutable release snapshots, validates tool schemas at execution time, and restricts outbound HTTP destinations to a deployment allowlist.

Do not expose the setup token, data directory or debug worker interface to untrusted users. Rotate `EIVON_SECRET_KEY` only with a documented credential migration; changing it without re-encryption makes stored credentials unreadable.
