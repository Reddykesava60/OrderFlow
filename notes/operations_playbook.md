# Day 1 Launch: Operations & Scaling Playbook

When you launch a restaurant operating system, Friday nights will push your infrastructure to its limits. Because we designed this system using a decoupled, event-driven architecture, it won't crash under pressure—it will simply queue the work. 

Here is your practical playbook for handling real-world scenarios, traffic spikes, and scaling decisions.

---

## Scenario 1: The Friday Night Order Spike (Web Traffic)
**The Situation**: A massive marketing campaign drops, or it's simply a busy Friday. You have 500 customers browsing the menu and building carts simultaneously. 
**The Symptoms**: The `web` service in Railway shows high CPU usage (80%+). Pages might take a second longer to load.
**Your Action**:
- Go to Railway and scale up the **CPU and Memory** of the `web` service. 
- **Why?** The `web` service handles all the incoming HTTP requests and active WebSocket connections for the Kitchen Display Systems. 
- **What you DON'T do:** You don't need to scale the `worker` or the database yet. Reading the menu is cheap for the database.

## Scenario 2: The Razorpay Webhook Avalanche
**The Situation**: 100 people all successfully pay via UPI within the exact same 30-second window. Razorpay sends 100 `order.paid` webhooks to your server simultaneously.
**The Symptoms**: The `worker` service in Railway shows a massive spike in memory usage.
**Your Action**:
- Go to Railway and scale up the **Memory** of the `worker` service, or increase the number of replicas (e.g., run 2 workers instead of 1).
- **Why?** The `web` service accepts the webhooks instantly (taking milliseconds) and throws them into Redis. It's the `worker` that has to do the heavy lifting of calculating the double-entry ledger, confirming the stock, and broadcasting to the KDS. By scaling the worker, you clear the queue faster. The `web` service remains blazing fast for people browsing the menu.

## Scenario 3: Razorpay / Banking Network Lag
**The Situation**: The UPI banking network (NPCI) is slow. A customer scans the QR code, money leaves their bank, but the page says "Waiting for confirmation..." for 2 minutes.
**Your Action**: **Do Nothing.**
- **Why?** The system is built for this. Eventually, Razorpay will send a "Late Capture" webhook. 
- If the webhook arrives 5 minutes late, the Celery `worker` will process it, run the `FAILED -> PAID` state machine transition, deduct the stock, and push the order to the kitchen. No money is lost, and the customer's order is fulfilled.

## Scenario 4: The Dead Letter Queue (DLQ)
**The Situation**: You check your new Operations Dashboard (`/admin/ops/`) and see that `Dead Letter Queue = 3`.
**The Symptoms**: Three orders were paid for, but they never showed up on the Kitchen Display System.
**Your Action**: 
- **Don't panic.** No data is lost. The system caught a bug (e.g., perhaps a menu item price was changed mid-checkout, causing a strict validation error).
- Because of our strict financial rules, the system rolled back the database transaction and parked the raw Razorpay payload in the `WebhookLog` table with `status="DLQ"`.
- You can manually refund the customer in Razorpay, or fix the bug in your code, deploy the fix, and the webhook can be safely re-processed.

## Scenario 5: Database Connection Exhaustion
**The Situation**: Your application crashes with a `500 Internal Server Error`, and the Railway logs say `FATAL: sorry, too many clients already`.
**Your Action**:
- This happens because every Daphne thread and Celery worker requires a connection to Supabase.
- **The Fix**: Ensure your `DATABASE_URL` in Railway is using the Supabase **Transaction Connection Pooler** (usually running on port `6543`), not the direct database connection (port `5432`). The connection pooler acts like a bouncer, safely managing thousands of incoming connections and funneling them into the database without overwhelming it.

## Scenario 6: Flash Sale (Selling Out of Stock)
**The Situation**: You have exactly 5 pieces of "Special Truffle Burger" left. 50 people try to check out at the exact same second.
**Your Action**: **Do Nothing.**
- **Why?** Our `ordering/inventory/services.py` uses atomic database transactions to create `StockReservation` holds. The system will successfully reserve the 5 burgers for the first 5 people to click "Pay". The remaining 45 people will be instantly rejected with a "Sold Out" message *before* they even reach the Razorpay payment screen. Zero inventory leakage!
