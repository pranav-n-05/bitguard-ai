# Security architecture

## Authentication
* **Passwords:** Argon2id (argon2-cffi defaults); policy ≥12 chars with three character classes, no account name; transparent rehash on login; constant-time-ish unknown-user path.
* **Tokens:** JWT access (15 min) and refresh (7 days) with `jti`; refresh tokens are stored server-side, **rotated on every use**; reuse of a rotated token revokes **all** of that user's sessions. Logout, password change, role change, deactivation and MFA reset revoke refresh tokens.
* **Lockout:** 5 failed logins → 15 minute lock. Login rate limit 10/min/IP.
* **MFA:** optional TOTP (RFC 6238, ±1 step) with setup/enable/disable; secret shown once at setup. (No recovery codes: an administrator can reset MFA.)
* **Browser storage:** access token in memory only; refresh token in `sessionStorage` (cleared with the tab).

## Authorisation (RBAC)
19 explicit permissions, enforced by a dependency on every protected endpoint (`app/core/rbac.py`). Test matrix: `tests/test_cases_security.py::test_rbac_matrix`.

| Permission | viewer | analyst | senior analyst | admin |
|---|---|---|---|---|
| dataset.read, intel.read, model.read, alert.read, case.read | ✓ | ✓ | ✓ | ✓ |
| intel.analyze, alert.acknowledge, case.create, evidence.attach, report.generate, dataset.upload | | ✓ | ✓ | ✓ |
| dataset.process, model.train, alert.create, alert.resolve, case.assign, audit.read | | | ✓ | ✓ |
| user.admin, config.change | | | | ✓ |

## Integrity and audit
* `audit_logs`: append-only (DB trigger), SHA-256 **hash chain** (`prev_hash`, `entry_hash`, sequential `seq`, serialised by advisory lock); verification endpoint `GET /admin/audit-logs/verify`.
* `raw_records` and `evidence_records` are append-only. Evidence stores source file/record hashes and an integrity hash over snapshot, provenance and analysis versions; `verify` recomputes them and re-hashes the source file.
* Uploaded files are stored under their SHA-256; ingestion re-verifies the hash first. Reports are hashed and verified on download. Model artifacts are hash-verified before `joblib` loading (only artifacts matching the DB record are loaded).

## Application hardening
Pydantic validation at every boundary; parameterised SQL via SQLAlchemy; XML parsing with entity resolution, DTD loading, network access and huge trees disabled (XXE/billion-laughs tested);
upload extension allow-list, path-component stripping, size limit with streaming hash; JSON body limit 1 MiB; security headers (CSP, nosniff, frame deny, referrer, permissions policy, no-store on API, HSTS in production);
CORS allow-list; error messages sanitised (problem+json with request id); rate limiting (slowapi/Redis); production refuses a default/short JWT secret.

## Explicitly not implemented (by design)
Private-key storage, wallet signing and transaction broadcasting.

## Operational guidance
Terminate TLS in front of nginx; set strong `BITGUARD_JWT_SECRET` and admin password; restrict the Postgres/Redis ports in production (the dev compose publishes them); rotate secrets by restarting (this revokes sessions only for tokens signed with the old secret); `pip-audit` and `npm audit` run in CI.
