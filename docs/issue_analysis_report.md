# Updated Production Log Audit Report

Here is the updated, comprehensive audit of the permissions bypass bug, incorporating historical state checks and explicit coverage gaps.

## 1. Data Source
**CONFIRMED:** The audit was run directly against the **production database** hosted on Supabase (`aws-1-ap-south-1.pooler.supabase.com`), as resolved by the `DATABASE_URL` setting.

## 2. Cash Collections (`CashCollectionMixin`)
**Verdict: Checked 27, Found 0 unauthorized.**
* **Methodology:** Because `RestaurantLedger` entries were missing the `created_by` field (see Secondary Bug below), the script joined each of the 27 `DEBIT_CASH_COLLECTED` ledger entries with its corresponding `CASH_COLLECTED` `PaymentEvent` to recover the actual acting `staff_user`.
* **Historical State:** I cross-referenced `OwnerAuditLog` and found that one staff user (`r1s1`) had their `allow_cash_collection` permission toggled from `False` to `True` on June 12, 2026. A direct query confirmed that this user performed **0** cash collections prior to the timestamp of that permission change.

## 3. Order & Item Status Changes (`OrderCompletionMixin`)
**Verdict: Cannot Verify From Existing Data.**
* **Methodology:** I analyzed the schema for `Order` and `OrderItem`.
* **Reason:** Neither model contains an `actor`, `user`, or `by` field to track who transitioned an item to `prep_started` or `completed`. Because the database does not persist the identity of the user who triggered these endpoints, it is impossible to audit whether any unauthorized status changes went through.

## 4. Owner Dashboard Actions (`OwnerRequiredMixin`)
**Verdict: Partially Checked (Mutations only). Found 0 unauthorized.**
* **Methodology:** Analyzed 12 entries in `OwnerAuditLog`.
* **Checked:** All 12 logged sensitive actions (e.g., configuration changes, staff permission toggles) were performed by users who held the `OWNER` role at the time. 
* **Cannot Verify:** `OwnerAuditLog` is only designed to capture state-changing `POST` actions. Any unauthorized read-only access (e.g., a `STAFF` user sending a `GET` request to view `/owner/config/`) is not persisted in the database and cannot be audited.

---

### 🚩 Secondary Bug Flagged: Ledger Missing `created_by`
As discovered during the audit, `RestaurantLedgerService.record_cash_payment()` (called from `ordering/orders/services.py`) is not threading the acting user through to the ledger, leaving `RestaurantLedger.created_by` as `NULL` on every cash-collection entry. 

**Recommendation:** Because fixing this requires modifying the financial write path (which you explicitly constrained me from altering in this ticket), this should be tackled as a separate, isolated follow-up fix. 
