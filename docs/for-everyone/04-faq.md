# FAQ

Quick answers to questions people tend to ask once they understand the
basics. For anything deeper, the [Glossary](../00-glossary.md) and the
engineering docs cover the technical detail.

---

**Can two restaurants on Dineflow ever see each other's data?**
No. Every restaurant's menu, orders, customers, staff accounts, and money
are isolated from every other restaurant's. This is enforced at multiple
layers, including the database itself, not just by the app's screens
hiding things.

**What happens if a customer's internet drops right after they pay?**
Nothing is lost. Dineflow doesn't rely on the customer's phone staying
connected to find out a payment succeeded — it relies on a direct,
secure notification from the payment provider. The order gets confirmed
and sent to the kitchen even if the customer never sees the "success"
screen.

**What if two customers try to buy the very last item at the same time?**
Exactly one of them gets it. The other is told it's sold out before being
asked to pay, never after.

**What happens to an order if nobody pays?**
If a customer starts checkout but abandons it, the order is automatically
cancelled after a short window and any reserved stock is released back to
the menu.

**Can a restaurant accidentally get charged the wrong commission?**
No — the commission rate used for an order is locked in and recorded
permanently at the moment the order is paid. Even if the platform's default
commission rate changes later, that order's historical record still shows
the rate that actually applied to it.

**What happens if the kitchen tablet loses power or WiFi?**
When it comes back online, it automatically refreshes itself with the
complete, current list of orders. Nothing is permanently missed.

**Can someone edit or delete a financial record after the fact?**
No. Financial records are append-only — corrections are made by adding a
new, reversing record, never by editing or deleting history.

**Does the restaurant need its own payment gateway account?**
Not necessarily. By default, every restaurant uses the platform's own
shared payment account. A restaurant can optionally connect its own
account if it wants to receive funds more directly — both paths are
supported.

**What payment methods are supported?**
Cash (collected in person, recorded in the system) and UPI (paid instantly
through the customer's banking app via Razorpay). The system is also built
to support an optional "pay later" tab-style account for known, trusted
customers.

**Where do I go if I need the technical detail behind any of this?**
Start at the [engineering documentation](../engineering/01-architecture-overview.md).
