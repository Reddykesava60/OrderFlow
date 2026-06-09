# Infrastructure Review

Audit status: FAIL

## Repository Infrastructure Evidence

No checked-in production infrastructure artifacts were found:

- No `Dockerfile`
- No `docker-compose.yml`
- No Kubernetes manifests
- No Terraform/Pulumi/CloudFormation
- No `.github/workflows`
- No `Procfile`
- No render/fly/railway deployment config
- No process supervisor config

The documentation describes Gunicorn, Daphne, Redis, Supabase, and CI/CD, but the repository does not implement that deployment model.

## Deployment Risks

### INFRA-001: Production Runtime Is Not Reproducible

Severity: High  
Impact: Releases will depend on manual operator knowledge. This increases outage and rollback risk.

Required remediation:

- Add container image build.
- Pin Python version.
- Add install, collectstatic, migrate, and startup commands.
- Add separate WSGI and ASGI process definitions.
- Add runtime environment variable schema.

### INFRA-002: No CI/CD Gate

Severity: High  
Impact: Vulnerable dependencies, failing tests, deploy check warnings, and secret leaks can ship.

Required remediation:

- Add CI for formatting, linting, tests, migrations, `manage.py check --deploy`, `pip-audit`, and secret scan.
- Block merge on critical/high vulnerabilities.
- Generate SBOM on release.

### INFRA-003: Redis Is Documented But Not Configured

Severity: High  
Evidence: README and docs mention Redis, but settings use in-memory channel layer and default local cache.

Required remediation:

- Add `channels_redis`.
- Add `REDIS_URL`.
- Configure `CHANNEL_LAYERS` and `CACHES` in production.
- Add Redis health check and alerting.

### INFRA-004: No Health Endpoints

Severity: High  
Impact: Load balancers cannot distinguish app boot, DB outage, migration failure, or partial dependency failure.

Required remediation:

- Add `/healthz/live` for process liveness.
- Add `/healthz/ready` for database, cache, and migration readiness.
- Add a lightweight WebSocket readiness check or metric.

### INFRA-005: Migration Safety Is Manual

Severity: Medium  
Impact: A bad migration can block startup or cause data loss without automated checks.

Required remediation:

- Add migration plan per release.
- Add backward-compatible expand/contract rules.
- Run migrations as a controlled pre-deploy job.
- Capture backups before destructive migrations.

## Secrets Management

Current state fails. `.env` is tracked and contains sensitive values. Production must use:

- Secret manager or platform env vars.
- Separate staging and production secrets.
- Rotation playbooks.
- Audit log for secret reads and updates.
- No service role keys in local developer repos.

## Docker And Runtime Hardening

Required baseline:

- Non-root user.
- Read-only filesystem where possible.
- No shell tools in final image unless required.
- Pinned base image digest.
- Python dependency lock with hashes.
- Separate build/runtime stages.
- Explicit memory and CPU limits.
- `PYTHONUNBUFFERED=1`.

## Network And Edge Controls

Required baseline:

- HTTPS only.
- HSTS preload after domain validation.
- Reverse proxy request body size limits.
- WebSocket idle timeout and max connection limits.
- Admin path protected by SSO, VPN, allowlist, or equivalent.
- WAF/rate limiting in front of public checkout and auth endpoints.

## Storage And Database

Risks:

- Supabase buckets are public by design for menu images and QR codes.
- Payment secrets are stored in the application database.
- RLS baseline is incomplete relative to all tenant tables.

Required remediation:

- Confirm bucket public-read is intended.
- Restrict write policies to owner/restaurant prefixes.
- Encrypt payment secrets outside ordinary model fields.
- Add backup/restore test for Supabase Postgres.
- Document point-in-time recovery and RPO/RTO.

## Rollback Readiness

Current status: Not ready.

Required:

- Immutable release artifact.
- One-command rollback.
- Migration rollback policy.
- Feature flags for payment/KDS changes.
- Release checklist with smoke tests.

## Environment Separation

Current evidence is weak. `.env` points at a Supabase instance while `DEBUG=True`. That is a dangerous mixed local/live configuration.

Required:

- `local`, `staging`, and `production` projects/databases.
- No production service role key in developer machines.
- Branch protection for production deploys.
- Distinct Razorpay test/live credentials by environment.
