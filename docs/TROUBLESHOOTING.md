# Order-Flow Troubleshooting & Incident Response

Last updated: 2026-05-08

This document provides structured debugging workflows for the most common production incidents. Each scenario includes a diagnostic flowchart, root cause analysis, and resolution steps.

> **Note**: All commands assume Docker Compose deployment. Prefix shell commands with `docker compose exec web`.

---

## 1. Incident Severity Classification

| Severity | Definition | Response SLA | Example |
|----------|-----------|-------------|---------|
| **SEV-1** | Complete service outage | 15 minutes | Database is unreachable, all restaurants offline |
| **SEV-2** | Partial outage, payments affected | 30 minutes | Razorpay webhook verification failing |
| **SEV-3** | Degraded experience | 2 hours | KDS WebSocket disconnecting intermittently |
| **SEV-4** | Minor issue, no revenue impact | Next business day | Owner dashboard CSS rendering issue |

---

## 2. Scenario: Orders Not Appearing on KDS

```mermaid
flowchart TD
    A["🚨 Orders not showing<br/>on KDS screens"] --> B{Can you access<br/>the KDS page at all?}
    B -- No --> C{Server running?}
    C -- No --> D["Start containers:<br/>docker compose up -d"]
    C -- Yes --> E{Check ALLOWED_HOSTS<br/>in prod.py}
    B -- Yes --> F{KDS shows<br/>'Offline' badge?}
    F -- Yes --> G{Redis running?}
    G -- No --> H["Start Redis and<br/>restart Daphne"]
    G -- Yes --> I["Check CHANNEL_LAYERS<br/>config in settings"]
    F -- No --> J{Orders appear after<br/>manual page refresh?}
    J -- Yes --> K["trigger_kds_refresh() not<br/>being called after<br/>order creation"]
    J -- No --> L["Check KDSPollView<br/>for query errors<br/>in server logs"]
    K --> M["Trace ordering/services.py<br/>→ confirm payment functions<br/>must call trigger_kds_refresh()"]
```

### Resolution Steps
1. Check server logs for Python exceptions in `kitchen/views.py`.
2. Verify `trigger_kds_refresh(restaurant.id)` is called after every order state mutation.
3. Confirm the KDS cache is being properly invalidated (check `kds_version_{restaurant_id}` in cache).

---

## 3. Scenario: Customer Double-Charged

```mermaid
flowchart TD
    A["🚨 Customer reports<br/>double charge"] --> B{Check Order table<br/>for duplicate IDs}
    B -- "Two orders exist<br/>with same items" --> C{Do they share<br/>same idempotency_key?}
    C -- Yes --> D["BUG: Idempotency guard<br/>failed — escalate to SEV-1"]
    C -- No --> E["Client sent two different<br/>idempotency keys"]
    E --> F["Root Cause: Frontend<br/>generated new UUID<br/>on retry instead of<br/>reusing the original"]
    B -- "Only one order exists" --> G{Check Razorpay Dashboard<br/>for duplicate payments}
    G -- "Two payments for<br/>same order_id" --> H["Razorpay webhook<br/>delivered twice —<br/>check PaymentEvent<br/>idempotency guard"]
    G -- "Single payment" --> I["Customer confused —<br/>show receipt URL"]
```

### Resolution Steps
1. Look up the customer's order by `customer_name` and `created_at` date.
2. Cross-reference with the Razorpay Dashboard for the restaurant.
3. If a genuine duplicate exists, handle the refund manually in the Razorpay Dashboard and document the action in the admin notes.
4. The application does not process refund webhooks or mutate ledger records for refunds in the current business model.

---

## 4. Scenario: Razorpay Webhook Verification Failing

```mermaid
sequenceDiagram
    participant RZP as Razorpay
    participant OrderFlow as Order-Flow Server
    participant DB as Database

    RZP->>OrderFlow: POST /payments/razorpay/webhook/
    Note over OrderFlow: Read X-Razorpay-Signature header
    OrderFlow->>DB: Lookup Order by razorpay_order_id
    DB-->>OrderFlow: Return Order + PaymentConfig
    
    alt Signature Matches
        OrderFlow->>DB: Confirm payment, create PlatformFeeRecord
        OrderFlow-->>RZP: HTTP 200
    else Signature Mismatch
        Note over OrderFlow: HMAC verification failed
        OrderFlow-->>RZP: HTTP 400
    end
```

### Common Root Causes
1. **Webhook secret mismatch**: The `razorpay_webhook_secret` stored in `RestaurantPaymentConfig` does not match the one configured in the Razorpay Dashboard.
2. **Multiple Razorpay accounts**: The restaurant changed their Razorpay account but forgot to update the webhook secret in Order-Flow.
3. **Body encoding**: Rarely, a reverse proxy may modify the request body (e.g., re-encoding JSON), which invalidates the HMAC signature.

### Resolution
```bash
# Verify the stored webhook secret
docker compose exec web python manage.py shell
>>> from core.models import RestaurantPaymentConfig
>>> config = RestaurantPaymentConfig.objects.get(restaurant__slug='slug')
>>> print(config.razorpay_webhook_secret[:4] + '...' + config.razorpay_webhook_secret[-4:])
```
Compare this value with what's configured in the Razorpay Dashboard → Webhooks → Secret.

> **Note**: Payment secrets are masked in Django admin. Use the shell command above for debugging.

---

## 5. Scenario: Database Migration Failure in Production

```mermaid
flowchart TD
    A["🚨 Migration failed<br/>during deploy"] --> B{Was data modified?}
    B -- No --> C["Fix migration code<br/>Redeploy"]
    B -- Yes --> D{Is migration<br/>reversible?}
    D -- Yes --> E["python manage.py migrate<br/>app_name XXXX_previous"]
    D -- No --> F["Connect to DB directly<br/>Manually fix schema"]
    E --> G["Fix migration, redeploy"]
    F --> G
    G --> H["Verify: manage.py showmigrations"]
```

### Prevention
- **Always test migrations on staging** before applying to production.
- Use `RunPython(reverse_code=...)` in data migrations to make them reversible.
- Run `python manage.py sqlmigrate <app> <number>` to preview the SQL before applying.

---

## 6. Scenario: High Server CPU / Slow Response Times

```mermaid
flowchart TD
    A["🚨 Server CPU spike<br/>during peak hours"] --> B{Which process<br/>is consuming CPU?}
    B -- Daphne --> C{Check slow queries}
    C --> D["Enable Django Debug Toolbar<br/>or pg_stat_statements"]
    D --> E{N+1 query detected?}
    E -- Yes --> F["Add prefetch_related /<br/>select_related to the View"]
    E -- No --> G["Check if KDS cache<br/>is being bypassed"]
    G --> H["Verify kds_version key<br/>exists in cache"]
    B -- Daphne --> I["Too many WebSocket<br/>connections"]
    I --> J["Scale ASGI workers<br/>horizontally"]
    B -- PostgreSQL --> K["Check pg_stat_activity<br/>for long-running queries"]
    K --> L["Add missing indexes<br/>or optimize query"]
```

### Quick Diagnostic Commands
```bash
# Check active database connections
docker compose exec web python manage.py dbshell
=> SELECT count(*) FROM pg_stat_activity WHERE state = 'active';

# Check cache hit rate
docker compose exec web python manage.py shell
>>> from django.core.cache import cache
>>> cache.get("kds_version_<restaurant_uuid>")  # Should return an integer

# Check container health
docker compose ps
curl -f http://localhost/healthz/ready/

# Check Redis
docker compose exec redis redis-cli info stats
```

---

## 7. Post-Incident Review Template

After resolving any SEV-1 or SEV-2 incident, complete the following:

| Field | Description |
|-------|-------------|
| **Incident ID** | Auto-generated or manually assigned |
| **Severity** | SEV-1 / SEV-2 |
| **Duration** | Start time → Resolution time |
| **Impact** | Which restaurants / how many orders affected |
| **Root Cause** | Technical explanation |
| **Resolution** | What was done to fix it |
| **Prevention** | What will be done to prevent recurrence |
| **Action Items** | Specific JIRA tickets / code changes |
