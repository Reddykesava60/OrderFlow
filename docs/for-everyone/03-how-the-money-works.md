# How the Money Works

Every restaurant on Dineflow needs to trust that the platform's record of
their earnings is exactly right, down to the rupee, forever. This page
explains how that trust is earned — without requiring you to read any code.

## The two parties splitting every payment

When a customer pays ₹500 for an order, that ₹500 doesn't belong entirely to
the restaurant or entirely to the platform. It's split:

```
Customer pays ₹500
        │
        ▼
 ┌─────────────────────┐
 │   Razorpay (gateway) │   ← actually moves the money
 └──────────┬───────────┘
            │
            ▼
   ┌────────────────┐
   │  ₹500 received  │
   └───┬────────┬────┘
       │        │
   Platform   Restaurant
     fee        balance
   (e.g. ₹15)  (e.g. ₹485)
```

The platform's commission (the **platform fee**) can be configured as a percentage, a fixed amount per order, or a hybrid of both — with a sensible default that applies to everyone unless explicitly overridden for a specific restaurant. The rest is the restaurant's money,
tracked as their **balance** inside Dineflow.

## Why "we trust the database" isn't good enough

Most simple apps would just store a single number per restaurant — "current
balance: ₹48,500" — and update it whenever a payment comes in. The problem
with that approach: if a bug, a double-processed webhook, or a manual
mistake ever changes that number incorrectly, there's no way to know *what*
went wrong, *when*, or how to fix it. The number is just... wrong, with no
paper trail.

Dineflow instead uses the same method real banks and accountants use:
**double-entry bookkeeping**.

## What double-entry bookkeeping actually means here

Every single financial event creates a permanent, unchangeable record with
at least two halves that must always add up to exactly zero. For our ₹500
order:

| What happened | Amount |
|---|---|
| Cash received from the customer | +₹500 |
| Platform's commission | −₹15 |
| Money owed to the restaurant | −₹485 |

Add those three numbers together: `500 − 15 − 485 = 0`. They must always
sum to zero — that's the rule that makes the whole system trustworthy. If
they don't add up to zero, Dineflow refuses to save the record at all,
rather than silently saving something wrong.

These records are also **append-only**: once written, they are never edited
or deleted, even by mistake or by an administrator. If something needs to
be corrected (like a refund), Dineflow doesn't erase the original record —
it adds a new, separate record that reverses it. This means there's always
a complete, honest history of everything that happened, even the mistakes.

## What a restaurant owner actually sees

Restaurant owners don't need to read raw bookkeeping entries. Dineflow
keeps a running, always-up-to-date **balance** for each restaurant
(updated the instant a payment is confirmed) and produces a
**monthly statement** summarizing total orders, total revenue, and the
platform fee owed for that month — so reconciling the books is a glance,
not an audit.

## What happens with a refund

If an order needs to be refunded, Dineflow doesn't just delete the original
payment record. It creates a new, separate set of records that exactly
reverse the original transaction — reducing the restaurant's balance and the
platform's fee revenue by the same amounts that were originally added. The
original payment record stays in place untouched, so the full history (the
original charge *and* the refund) remains visible.

## Next

Continue to [FAQ](./04-faq.md) for quick answers to common questions, or
jump to the [Glossary](../00-glossary.md) for any term that didn't get
explained along the way.
