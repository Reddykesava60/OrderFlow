# KDS & Real-Time Architecture

The Kitchen Display System (KDS) is a critical component that requires real-time synchronization across multiple iPads/Tablets in the kitchen without overwhelming the database with polling requests.

## Real-Time Stack
- **ASGI Server**: Uvicorn / Daphne running behind Nginx.
- **Django Channels**: Manages persistent WebSocket connections.
- **Channels Redis**: The backing layer for cross-process channel groups.

## Event-Driven Updates
The KDS domain heavily relies on the internal `EventBus`. 

1. **Order Paid**: The `sales` domain transitions the order to `PENDING` and publishes `OrderPaidEvent`. 
2. **KDS Broadcaster**: A handler in the `kitchen` domain listens to `OrderPaidEvent` and prepares a localized JSON payload.
3. **Targeted Redis Group**: The broadcaster sends the payload to the specific Restaurant's Redis group (e.g., `Group(f"kds_{restaurant_id}")`).
4. **WebSocket Delivery**: Django Channels pushes the event down to all connected kitchen devices for that specific restaurant.

## Payload Efficiency
To ensure the tablets do not crash or stall, the KDS payload is optimized:
- **Diff Broadcasting**: Instead of sending the entire list of 100+ orders, the server only broadcasts the precise differential update.
  - `{"type": "TICKET_CREATED", "payload": {...}}`
  - `{"type": "ITEM_UPDATED", "item_id": "uuid", "new_state": "PREPARING"}`
- **Client-Side Merging**: The frontend (Alpine.js / React) maintains the state in-memory and merges the differential updates, ensuring instant UI reflection.

## Fault Tolerance
- **Reconnection Logic**: If a kitchen tablet drops WiFi, the WebSocket automatically attempts reconnection with an exponential backoff.
- **State Hydration**: Upon successful reconnection, the tablet makes a standard REST API call `GET /api/kitchen/{restaurant_id}/active-tickets` to hydrate the full state and ensure no diffs were missed during the downtime.
