# The Life of an Order

This walks through exactly what happens, step by step, from a customer
sitting down at a table to their food arriving — including what happens when
things go wrong, because in the real world, things go wrong often.

## The happy path

1. **The customer scans a QR code** on their table, which opens that
   restaurant's menu on their phone. No app download, no account needed.
2. **They build a cart** — picking items, add-ons, and spice levels — and
   hit checkout.
3. **They choose how to pay**: cash at the table, or UPI (India's
   phone-to-phone instant payment system) right from their phone.
4. **If paying by UPI**, they're handed off to Razorpay's secure payment
   screen, approve the payment in their banking app, and are sent back to
   Dineflow.
5. **The kitchen sees the order appear on their screen within a second or
   two** of payment being confirmed — no waiter needs to walk it over.
6. **Kitchen staff tap through the order** as they start cooking each item
   and mark it done.
7. **The customer can watch their order's status update live** on their
   phone the whole time.

## Why "payment confirmed" isn't as simple as it sounds

This is the part that looks trivial from the customer's side but is the
single most carefully engineered part of the system. Here's why:

When a customer pays by UPI, there are actually **two messages** that can
tell Dineflow "this payment succeeded":

- A message from the customer's own phone, right after they approve the
  payment (fast, but it's just the phone reporting on itself — not proof).
- A secure, signed notification sent directly from Razorpay to Dineflow's
  servers, confirming the bank actually moved the money (slower, but this
  is the one that's actually trustworthy).

Dineflow treats the second one — the direct notification from Razorpay — as
the *only* one that's allowed to actually mark an order as paid and send it
to the kitchen. The first one is just used to make the customer's screen
feel responsive while we wait for the real confirmation.

This matters because of a real, common scenario in India's UPI network:
a payment can briefly *appear* to fail (the customer's bank app times out)
and then **actually succeed a minute or two later** once the banking
network catches up. If Dineflow had trusted the "it failed" message
permanently, the restaurant would have a customer who paid but whose food
never got cooked. Instead, Dineflow is built to accept a late "actually, it
succeeded" message and recover the order automatically — see
[Order & Payment Lifecycle](../engineering/04-order-and-payment-lifecycle.md)
for the technical detail.

## What happens if a customer never finishes paying

If someone adds items to their cart, gets sent to the payment screen, and
then just... closes the tab — Dineflow doesn't leave that inventory locked
up forever. After a short window, the system automatically cancels the
unpaid order and releases anything it was holding in reserve, so other
customers can order those same items.

## What happens if the kitchen tablet loses WiFi

Kitchen staff don't need to worry about missing an order if their tablet
briefly disconnects. The moment it reconnects, it automatically re-fetches
the complete, current list of active orders — so nothing is silently
missed.

## What happens if an item sells out mid-order

If a dish runs out of stock while a customer is mid-checkout, Dineflow
checks the actual remaining stock at the exact moment of payment, not just
when the customer added it to their cart. If it's gone, the customer is
told before they're charged — never after.

## Next

Continue to [How the Money Works](./03-how-the-money-works.md) to see what
happens to a payment after the kitchen gets the ticket.
