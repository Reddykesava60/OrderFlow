# Pre-Launch Quality Assurance (QA) & UAT Guide

Moving from a deployed application to a "customer-ready" application is the most critical phase for a startup. Real companies do not just test the "happy path" (where everything works perfectly); they spend 80% of their testing time on **edge cases and failures**.

Because your application handles **real money** and **real inventory**, you must execute this User Acceptance Testing (UAT) checklist on your live production environment (using Razorpay Test Mode) before onboarding your first paying restaurant.

---

## 1. Multi-Tenant Data Isolation (Critical)
The absolute worst bug in a SaaS startup is Restaurant A seeing Restaurant B's data.
- `[ ]` **Cross-Tenant Ordering**: Open Restaurant A's menu in an incognito window. Change the URL slug to Restaurant B. Verify the cart crashes or resets and does not allow checking out Restaurant A's items at Restaurant B.
- `[ ]` **Dashboard Isolation**: Create an Owner account for Restaurant A and an Owner account for Restaurant B. Log into Restaurant A. Try to manually manipulate the URL to access `/admin/core/restaurant/<Restaurant B's ID>/`. Verify you get a 403 Forbidden or 404 Not Found.
- `[ ]` **KDS Isolation**: Open the Kitchen Display System for Restaurant A. Place an order on Restaurant B's website. Verify the order *only* rings on Restaurant B's KDS.

## 2. Concurrency & Race Conditions (Inventory Locking)
You must ensure that if you only have 1 Burger left, two customers cannot buy it at the exact same second.
- `[ ]` **Double Checkout**: Set an item's inventory to `1`. Open the checkout page on two different devices (Phone and Laptop). Press the "Pay" button on both devices at the exact same millisecond. 
- `[ ]` **Expected Result**: One device proceeds to Razorpay. The other device gets a "Stock Error: Item out of stock" and the cart is rejected.

## 3. Webhook & Payment Resilience
Never trust the frontend. The frontend can be closed, internet can drop, or the user's phone can die right after they pay.
- `[ ]` **The "Dead Phone" Test**: Add items to your cart and proceed to Razorpay. Complete the test payment successfully. **Immediately** close the browser tab *before* Razorpay redirects you back to the success page. 
- `[ ]` **Expected Result**: Your background Celery workers should receive the Razorpay Webhook in the background, verify the signature, process the payment, generate the receipt, and ring the KDS automatically without the user ever returning to the website.
- `[ ]` **Idempotency Test**: Go to the Razorpay Dashboard and manually click "Resend Webhook" for a successful order 5 times in a row. 
- `[ ]` **Expected Result**: The first webhook processes the order. The next 4 webhooks are ignored by the system (`payment_webhook_already_processed`), preventing double-counting the revenue.

## 4. The Order Lifecycle (Kitchen & Customer)
- `[ ]` **KDS Disconnect**: Disconnect your kitchen iPad/Laptop from the WiFi. Place an order on your phone. Reconnect the kitchen device to the WiFi. 
- `[ ]` **Expected Result**: The KDS should automatically poll and rebuild the cache, displaying the missed order immediately.
- `[ ]` **Order Cancellation**: Have the kitchen mark an order as `CANCELLED` on the KDS. 
- `[ ]` **Expected Result**: The stock should immediately return to the inventory, and a background task should trigger a Refund request to Razorpay.

## 5. Expiration & Abandoned Carts
- `[ ]` **The Abandoned Cart Test**: Add items to your cart, go to Razorpay, but do not pay. Just leave the Razorpay window open.
- `[ ]` **Expected Result**: 15 minutes later, your Celery `expire_single_payment_task` should automatically query Razorpay, see it was abandoned, mark the order as `EXPIRED`, and release the locked inventory back to the restaurant.

## 6. Financial Ledger & Reconciliation
Because we built a strict double-entry ledger, money cannot be created or destroyed.
- `[ ]` **Zero-Sum Validation**: At the end of a testing day, go to your Django Admin and look at the `JournalEntry` table. 
- `[ ]` **Expected Result**: Ensure that all entries balance perfectly (total debits equal total credits) and that the `PlatformFeeRecord` precisely matches the fees accrued in the ledger.

> [!IMPORTANT]
> **How to execute this:** Do not test this locally! Test this on your **Live Railway Production Server**. Ensure your Razorpay API keys in the production environment are set to `TEST` mode keys. Use Razorpay's test cards to simulate successful and failed payments. Once all boxes are checked, swap the keys to `LIVE` mode and open your doors!
