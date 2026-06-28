# Production Log Audit — Issue Analysis & Resolution Report

This report covers the four production-log issues investigated before go-live, the
permission-enforcement bug discovered during the audit, and the historical data audit
confirming no unauthorized actions occurred in production.

---

## Issue 1 — Webhook replay-protection timestamp missing
**Status: ✅ FIXED**

**Root cause:** `_parse_webhook_timestamp` looked for the timestamp in HTTP headers only.
Razorpay delivers the timestamp as a Unix epoch in the JSON payload's `created_at` field,
not as a header. Every Razorpay webhook logged the "missing timestamp — allowing for
backward compatibility" warning and skipped freshness checking entirely.

**Fix:** `_parse_webhook_timestamp` now accepts the parsed JSON payload alongside headers
and reads `payload.get("created_at")` for Razorpay webhooks, falling back to header
lookup for other providers.

**File:** `ordering/payments/services.py`

---

## Issue 2 — Razorpay event ID sourced from wrong location
**Status: ✅ FIXED**

**Root cause:** `RazorpayProvider.parse_webhook` extracted `provider_event_id` from
`payload.get("id")` (the JSON body). Razorpay actually delivers the event ID via the
`X-Razorpay-Event-Id` HTTP header. The body's `id` field is the *event payload* ID,
not the *event delivery* ID used for deduplication.

**Fix:** `parse_webhook` now reads `provider_event_id` from
`headers.get("x-razorpay-event-id")`, matching the case-normalization convention used
by `_safe_webhook_headers` elsewhere in the service layer.

**File:** `ordering/payments/providers.py`

**Test fixtures updated:** `_signed_headers()` in `ordering/tests.py` now accepts an
optional `event_id` parameter and includes the `X-Razorpay-Event-Id` header, matching
real Razorpay delivery behavior. Three call sites updated.

---

## Issue 3 — `payment.failed` event not handled
**Status: ✅ FIXED**

**Root cause:** The event-kind mapping in `RazorpayProvider.parse_webhook` only mapped
`payment.captured` → `payment_paid`. The `payment.failed` event from Razorpay was
unrecognized and silently dropped, preventing the payment state machine from
transitioning to FAILED and leaving orders stuck in UNPAID indefinitely.

**Fix:** Added `payment.failed` → `payment_failed` to the event-kind mapping.

**File:** `ordering/payments/providers.py`

---

## Issue 4 — Permission mixin enforcement ordering (CashCollectionMixin, OrderCompletionMixin, OwnerRequiredMixin)
**Status: ✅ FIXED**

**Root cause:** All three permission mixins called `super().dispatch()` **first** (which
executed the full view body, including database writes), and only checked permissions
**after** the response was already generated. An unauthorized staff member's request would
trigger side effects (ledger entries, status transitions, audit log writes) before the
403 was returned.

**Fix:** Permission and authentication checks now run **before** `super().dispatch()`.
The view body never executes for an unauthorized request. Each mixin duplicates
`ActiveStaffMixin`'s base guards (`is_authenticated`, `is_active`,
superuser/no-restaurant) to ensure safe operation regardless of MRO.

**File:** `core/mixins.py`

**Tests added:** `core/test_mixins.py` — 7 tests covering:
- Unauthorized requests return 403 with no DB side effects (cash, order, owner)
- Authorized requests succeed and produce expected side effects
- Unverified MFA owner is redirected without side effects

---

## Historical Data Audit

Performed against **production database** (Supabase, `aws-1-ap-south-1.pooler.supabase.com`).

### Cash Collections (`CashCollectionMixin`)
**Checked 27 entries, found 0 unauthorized.**

Methodology: `RestaurantLedger.created_by` is NULL on all entries (see follow-up below),
so each of the 27 `DEBIT_CASH_COLLECTED` ledger entries was joined to its corresponding
`CASH_COLLECTED` `PaymentEvent` to recover the acting staff user. Cross-referenced with
`OwnerAuditLog` to verify permission state at time of action. One user (`r1s1`) had
`allow_cash_collection` toggled from `False` to `True` on June 12, 2026 — confirmed 0
cash collections prior to that change.

### Order Status Changes (`OrderCompletionMixin`)
**Cannot verify from existing data.**

`Order`, `OrderItem`, and `OrderItemAddOn` have no actor/user field — the database does
not record who triggered status transitions. This is a known gap (see follow-ups).

### Owner Dashboard Actions (`OwnerRequiredMixin`)
**Checked 12 entries, found 0 unauthorized (mutations only).**

All 12 `OwnerAuditLog` entries were performed by users with `OWNER` role at the time.
Read-only `GET` requests to owner views are not logged and cannot be audited.

### Django Admin Blind Spot
**Confirmed.** Permission fields (`allow_cash_collection`, `allow_order_completion`,
`role`) can be changed by a superuser through Django Admin, bypassing `OwnerAuditLog`
entirely. These changes are recorded only in Django's built-in `LogEntry` table. This is
a permanent limitation of the current audit trail design.

---

## Follow-Up Items (Not Fixed in This Change)

### 1. Ledger Missing `created_by`
`RestaurantLedgerService.record_cash_payment()` does not thread the acting user through
to `RestaurantLedger.created_by`, leaving it NULL on every cash-collection entry. Auditing
requires a join through `PaymentEvent`. **Scope:** Modify the financial write path to
accept and persist `created_by`. Constrained out of this ticket to avoid touching the
ledger/financial-write path.

### 2. Order Status Audit Trail
`OrderCompletionMixin` endpoints have no actor field anywhere (`Order`, `OrderItem`,
`OrderItemAddOn`). There is currently no record of who started prep or completed an item.
**Scope:** Add `prep_started_by` / `completed_by` ForeignKeys to `OrderItem`, or
implement a dedicated status-transition audit log. Low-medium effort, touching
`kitchen/views.py` and `ordering/models.py`.

### 3. ActiveStaffMixin Refactor
All three permission mixins now duplicate the same four `ActiveStaffMixin` checks
verbatim. Worth refactoring `ActiveStaffMixin` to expose a reusable `_check_base_access()`
method so there's one place to update, not three. Low effort, non-blocking.
