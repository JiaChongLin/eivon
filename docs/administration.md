# Workspaces and access administration

The console's Workspace selector sets the scope for resource, conversation, Run, Knowledge, evaluation and administration requests. A selection is verified against `/auth/me` before the new workspace is displayed. Switching cancels pending requests and resets page state; the selected workspace is remembered per user in browser session storage. Generated files are fetched with the same explicit workspace scope.

Settings lets an administrator rename the current workspace, create and enter a separate workspace, rotate credentials, issue/revoke API keys and inspect paginated audit events. Creating a workspace makes its creator the owner. It does not copy resources, members or secrets from the previous workspace.

## Members

Members supports adding existing accounts or creating an account with an initial password, changing roles and removing access. An existing account's name and password are not changed by adding it to another workspace. Initial passwords must have at least 12 characters.

| Role | Capabilities |
| --- | --- |
| owner / admin | Manage workspace resources, members, credentials and keys |
| editor | Read, author, publish and execute resources |
| operator | Read, execute and approve Runs |
| viewer | Read resources and authorized history |

Only the owner can assign or change an administrator role. Owner and self-role changes are rejected. Ownership transfer and a password-reset/email invitation service are not part of this interface.

Permissions are checked by the server on every request. After a role change, **Settings → Refresh access** or a page reload updates the displayed controls. Existing API keys are constrained by the account's current role as well as the permissions granted to the key. Removing a member revokes that user's keys for the workspace. It does not remove membership in other workspaces. A user whose final membership was removed can still sign out.

## Credentials and API keys

Credentials are encrypted at rest. The console accepts a new secret but never retrieves an existing value. **Rotate** replaces the value while preserving its credential ID and resource references. This applies to subsequent uses of the credential; it does not revoke a provider token externally or interrupt a request already in progress.

API keys are restricted to one workspace and a selected permission set, with an expiry of 1–365 days. Copy the secret when it is created: subsequent listings only return metadata. Revoking a key rejects subsequent API requests. An API key cannot switch workspaces and its identity response lists only its own workspace.

## API scope and session recovery

Send `x-eivon-workspace: <workspace-id>` for an explicit scope. Cookie-authenticated writes also require `x-csrf-token`. A browser session can select any workspace where the account is a member; a bearer key remains bound to its issued workspace. Without an explicit workspace, the server selects an available membership, so integrations should send the header when using cookies.

- `GET /api/v1/auth/me`: current identity and available workspaces.
- `POST /api/v1/workspaces`: create a workspace with `{ "name": "Research" }`.
- `PATCH /api/v1/workspaces/{id}`: rename the current workspace.
- `/api/v1/members`: add/list members; `PATCH` and `DELETE /members/{user_id}` change/remove membership.
- `/api/v1/credentials`: create/list credential metadata; `PUT /credentials/{id}` rotates it.
- `/api/v1/api-keys`: create/list keys; `DELETE /api-keys/{id}` revokes a key.
- `GET /api/v1/audit-events?offset=0&limit=25`: administrator-only events for the current workspace.

`GET /auth/session` retrieves the CSRF token for a valid browser cookie independently of workspace membership. `POST /auth/logout` uses that cookie and CSRF token to invalidate the browser session and clear the cookie. API keys are revoked through their dedicated endpoint.

Audit event details include action identifiers and affected resources, not credential plaintext or API key secrets. Retention/export policies and account recovery remain deployment responsibilities.
