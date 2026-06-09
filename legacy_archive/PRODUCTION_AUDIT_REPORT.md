# Order-Flow Production Audit Report

Last updated: 2026-05-14

## Scope
- Backend modules: core, ordering, ordering/payments, kitchen, owner.
- Frontend modules: Alpine.js checkout and KDS templates.
- Infrastructure: Docker, Nginx, Redis, Celery-style job execution.

## Critical Findings and Status
1. Public payment status/retry endpoints previously accepted only UUIDs.
Status: Fixed by signed payment access tokens and tenant/session checks.
2. Duplicate active payment creation race when retries arrived without idempotency.
Status: Fixed by checking active transactions under row lock.
3. Webhook replay risk due to payload-only dedupe.
Status: Fixed by provider event ID dedupe and timestamp freshness validation where available.
4. WebSocket origin boundary lacked an ASGI validator.
Status: Fixed with AllowedHostsOriginValidator in ASGI pipeline.
5. Stale documentation referenced legacy webhook module and endpoint paths.
Status: Fixed across architecture, API, security, onboarding, and map documents.

## High-Priority Residual Risks
1. Legacy Razorpay verify flow and unified payment orchestration both exist; ownership boundaries should be converged in one release.
2. CORS policy is currently implied via same-origin deployment; formal CORS middleware policy can be added if cross-origin clients are introduced.
3. Test suite currently blocked by external test database bouncer configuration in this environment.

## Module-by-Module Assessment
- Payments: transaction-safe, replay-hardened, token-gated polling/retry, queue-ready webhook pipeline.
- Post-payment customers: PIN verification, row-locked balance updates, credit limit checks, atomic ledger entries.
- KDS: tenant-scoped channel groups, authenticated sockets, origin validation, refresh + payment update events.
- RBAC: mixin-driven owner/staff authorization, staff flags, owner-only control paths.
- Multi-tenant isolation: restaurant scoping enforced in domain queries and payment/public endpoint guards.

## Recommended Next Release
1. Consolidate legacy and new payment verify paths into one entrypoint.
2. Add formal CORS allow-list settings and tests.
3. Add end-to-end integration tests for webhook replay + payment status token expiry.
4. Add SLO dashboards for webhook processing latency and payment reconciliation lag.
