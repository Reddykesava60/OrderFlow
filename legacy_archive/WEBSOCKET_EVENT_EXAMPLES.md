# WebSocket Event Examples

All events are tenant-scoped to `kds_{restaurant_id}`.

## 1. Refresh Event

```json
{"action": "refresh", "order_id": "b2e6c5b4-..."}
```

When received, clients should apply jitter and poll `/api/kds/poll/`.

## 2. Payment Update Event

```json
{
  "action": "payment_update",
  "payment_id": "2c5f9de2-...",
  "state": "paid",
  "order_id": "b2e6c5b4-..."
}
```

Use this to refresh dashboard payment widgets and then fetch authoritative state from API.

## 3. Client Ping/Pong Health

Client ping:
```json
{"action": "ping"}
```

Server pong:
```json
{"action": "pong"}
```

## 4. Unauthorized Subscription Behavior
- Unauthenticated users: connection closed.
- Users without restaurant binding: connection closed.
- Users from other tenants: only own tenant group is joined.
