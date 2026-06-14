# KDS & Real-Time Architecture

The Kitchen Display System (KDS) is a critical component that requires real-time synchronization across multiple iPads/Tablets in the kitchen without overwhelming the database with polling requests.

## Real-Time Stack
- **ASGI Server**: Uvicorn / Daphne running behind Nginx.
- **Django Channels**: Manages persistent WebSocket connections.
- **Channels Redis**: The backing layer for cross-process channel groups.

## Event-Driven Updates
The KDS domain updates are triggered synchronously from the `ordering` app's mutation services using `async_to_sync` calls to the channel layer.

1. **Order State Mutation**: When `PaymentMutationService` processes a webhook or synchronous API confirmation, it commits the database transaction.
2. **KDS Broadcaster**: Immediately following the commit, `trigger_kds_refresh(restaurant_id)` and `broadcast_payment_update(restaurant_id, payment_id)` are called.
3. **Targeted Redis Group**: These functions send a payload to the specific Restaurant's Redis group (e.g., `Group(f"kds_{restaurant_id}")`).
4. **WebSocket Delivery**: Django Channels pushes the event down to all connected kitchen devices for that specific restaurant.

*Note: During payment investigations, synchronous KDS broadcasting was evaluated as a potential contributor to worker stalls. No conclusive production evidence currently proves Redis/channel-layer hangs were the root cause. Continued monitoring is recommended.*

## Payload Efficiency
To ensure the tablets do not crash or stall, the KDS payload is optimized:
- **Diff Broadcasting**: Instead of sending the entire list of 100+ orders, the server broadcasts differential updates.
  - `{"type": "kds.refresh", "action": "refresh", "order_id": "uuid"}`
  - `{"type": "payment.update", "payment_id": "uuid", "state": "paid"}`
- **Client-Side Merging**: The frontend maintains the state in-memory and merges the differential updates, ensuring instant UI reflection.

## Fault Tolerance
- **Reconnection Logic**: If a kitchen tablet drops WiFi, the WebSocket automatically attempts reconnection with an exponential backoff.
- **State Hydration**: Upon successful reconnection, the tablet makes a standard REST API call to hydrate the full state and ensure no diffs were missed during the downtime.
