# Real-Time Kitchen Display

The Kitchen Display System has one hard requirement that shapes its whole
design: **a kitchen tablet must never silently miss an order**, even
through a dropped WiFi connection, a Redis blip, or a tab left in the
background overnight. Everything here is built around that guarantee, with
a deliberately "push tells you to pull" pattern rather than trusting the
push channel to carry the actual data.

## The two channels, and why neither is trusted alone

| Channel | Carries | Role |
|---|---|---|
| WebSocket (`/ws/kds/`, `kitchen/consumers.py`) | A tiny "something changed, go refetch" signal | Speed — gets the tablet to react within roughly a second |
| REST poll (`GET /api/kds/poll/`, `KDSPollView`) | The full, authoritative current state | Correctness — this is the only thing that ever actually updates what's on screen |

The WebSocket message is intentionally close to content-free — it's a
trigger, not a payload. The client always responds to it by calling the
REST poll endpoint and rebuilding its view from that response. This means
a missed or garbled WebSocket frame can never cause stale data to be
displayed — at worst, it causes a slightly delayed refresh, which the
fallback behavior below also covers.

## What triggers a push

`kitchen/services.py` exposes two broadcaster functions, both called by
`ordering`'s payment/order code immediately **after** a database
transaction commits (not from inside it — see
[Order & Payment Lifecycle](./04-order-and-payment-lifecycle.md) for why
that ordering matters):

- `trigger_kds_refresh(restaurant_id)` — bumps a per-restaurant cache
  version key and sends a `kds.refresh` event to that restaurant's Redis
  channel group (`kds_{restaurant_id}`).
- `broadcast_payment_update(restaurant_id, payment_id, state, order_id)` —
  a more specific payment-state event, used so the front-end can react to
  payment status without necessarily reloading the entire ticket list.

Both functions wrap their Redis calls in broad `try/except` blocks that log
a warning and otherwise do nothing on failure. This is deliberate: **a
Redis outage must never be able to fail an order's payment confirmation**.
Worst case, the kitchen finds out about an order a little later than
instantly (the fallback paths below still catch it); the payment itself is
never put at risk for the sake of a real-time nicety.

## What the tablet actually does (`kds.html` + Alpine.js)

There is **no fixed polling interval**. Instead:

1. On page load, it polls once immediately to hydrate.
2. It opens a WebSocket to `/ws/kds/`. Every `refresh` message it receives
   triggers a poll — debounced by 3 seconds (plus a small random jitter)
   so a burst of events doesn't cause a burst of redundant requests.
3. If the WebSocket drops, it automatically reconnects after 3 seconds,
   as long as the tab is visible.
4. If the browser tab becomes visible again after being backgrounded (the
   tablet was asleep, or the app was switched away from), it immediately
   polls **and** checks whether the WebSocket is still connected,
   reconnecting if not.

That visibility-change handler is what makes "tablet loses WiFi overnight,
reconnects in the morning" a non-event: the moment it's visible and back
online, it gets the full current picture without anyone needing to do
anything.

## The WebSocket consumer itself

`KDSWebsocketConsumer` (`kitchen/consumers.py`) only accepts connections
from an authenticated `STAFF` or `OWNER` user who belongs to a restaurant.
On connect, it joins two Redis groups:

- `kds_{restaurant_id}` — the shared group every device for that
  restaurant listens on.
- `user_{user_id}` — a per-user group used by
  `broadcast_user_disconnect()`, so that if an account's role is revoked
  or access is otherwise invalidated, every open session for that specific
  user can be force-disconnected immediately.

## What the REST poll endpoint actually returns

`KDSPollView` queries strictly for active orders (`UNPAID`, `PREP_STARTED`, `READY`) for the staff member's
restaurant (optionally scoped further by a `StaffFilter`, if the staff
account is restricted to a subset of menu items), with prep status
computed per item/add-on. It is the single source of truth the tablet
renders from — the WebSocket message never carries enough information to
update the screen on its own.

## Next

[Background Jobs](./08-background-jobs.md) covers the Celery side of the
system — what runs on a schedule, and how it survives a worker crashing
mid-task.
