# Operations Runbook

## Monitoring & Observability

### Sentry (Error Tracking)
Order-Flow integrates deeply with Sentry (`sentry-sdk`).
- **Captures**: Unhandled Django exceptions, Celery task failures, and Redis connection drops.
- **PII Scrubbing**: `send_default_pii=False` is set to ensure customer phone numbers and payment intent payloads are scrubbed before transmission.

### Prometheus Metrics
`django-prometheus` instruments the application.
- **Endpoint**: Internally available at `/metrics` (blocked from public access by Nginx).
- **Key Metrics**: 
  - `django_http_requests_total_by_view_transport_method`
  - `django_db_query_duration_seconds`
  - `celery_task_status`

## Common Operational Tasks

### Creating the Platform Admin
To access the Django Admin (`/platform-admin/`) to manage tenants:
```bash
python manage.py createsuperuser
```

### Manual Payment Reconciliation
If a restaurant reports a customer was charged but the order isn't showing as paid, a webhook was likely dropped by the provider.
You can manually trigger reconciliation for a specific order:
```python
# Django Shell
from ordering.models import Order
from ordering.payments.services import PaymentReconciliationService

order = Order.objects.get(order_number=123, restaurant__slug='my-rest')
payment = order.payment_transactions.order_by('-created_at').first()
PaymentReconciliationService().reconcile_payment(payment)
```
*Note: The system automatically does this every 15 minutes for recent pending payments.*

### Releasing Stuck Inventory
If Celery Beat goes down, stock reservations might get stuck.
Run the management command manually:
```bash
python manage.py release_expired_reservations
```

### Forcing KDS Refresh
If KDS screens are out of sync:
```python
# Django Shell
from kitchen.services import trigger_kds_refresh
trigger_kds_refresh(restaurant_id='uuid-here')
```

## Incident Response

### Redis Goes Down
- **Impact**: KDS real-time updates stop. Rate limiting fails open. Celery tasks stop processing.
- **Mitigation**: The core ordering and checkout flow will **continue to work**. KDS clients will fallback to 10-second HTTP polling (`/api/kds/poll/`). Restore Redis as soon as possible.

### PostgreSQL Goes Down
- **Impact**: Complete system outage.
- **Mitigation**: Daphne will return 500s. Rely on DB provider backups/failover.

### Payment Gateway Outage
- **Impact**: Digital checkouts fail.
- **Mitigation**: Platform admins can toggle `admin_upi_enabled=False` on affected `RestaurantConfig` objects to hide the digital payment option and force Cash/Post-Payment temporarily.
