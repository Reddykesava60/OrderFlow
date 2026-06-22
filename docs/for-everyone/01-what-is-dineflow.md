# What Is Dineflow?

## In one sentence

Dineflow is software that lets a restaurant take orders and payments from a
customer's phone, send those orders straight to the kitchen screen, and keep
an exact, tamper-proof record of every rupee that moves.

## The problem it solves

Picture a restaurant without Dineflow:

- A waiter writes orders on paper and walks them to the kitchen.
- Payments are cash in a drawer, or a card machine with its own separate
  record that nobody cross-checks against the till.
- At the end of the month, the owner has no easy way to know exactly how
  much they made, how much they owe a platform commission on, or whether
  every paid order actually got cooked.

Dineflow replaces all of that with one connected system:

```
Customer's phone  →  Dineflow  →  Kitchen screen
                         ↓
                  Tamper-proof money records
```

## Who uses it, and how

| Person | What they do in Dineflow |
|---|---|
| **Customer** | Scans a QR code at their table, browses the menu on their phone, pays by cash or UPI, and gets a live status of their order. |
| **Kitchen staff** | Watches a screen (the "KDS" — Kitchen Display System) that shows every paid order as a ticket, and taps to mark items as being prepared or done. |
| **Restaurant owner / manager** | Manages the menu, staff accounts, and pricing through a dashboard; reviews sales and reconciles payments. |
| **Platform operator** (the company running Dineflow itself) | Hosts the system for many restaurants at once, and earns a small commission on each order. |

## What makes it a "restaurant operating system" rather than just an ordering app

A few things that are easy to take for granted, but are actually the hard
part of building this kind of system:

- **One restaurant's data never leaks into another's.** Dineflow serves many
  restaurants from one shared system ("multi-tenant"), but each one's menu,
  orders, staff, and money are walled off from the others.
- **Money is never trusted on the basis of "the app said it worked."**
  Payments are only considered final once the payment provider (Razorpay)
  itself confirms it, through a secure server-to-server notification — not
  just because a customer's browser displayed a success message.
- **Stock can't be oversold.** If there's only one plate of a dish left and
  two people try to order it at the exact same second, exactly one of them
  succeeds. This is enforced at the database level, not just in the app's
  logic.
- **The books always balance.** Every payment is recorded using the same
  double-entry bookkeeping method banks use, so it's mathematically
  impossible for money to be lost or duplicated in the records (see
  [How the Money Works](./03-how-the-money-works.md)).

## What it's built on (for context, not action)

Dineflow is a web application written in Python (using the Django
framework), backed by a PostgreSQL database, with a real-time layer
(Redis + WebSockets) for instant kitchen updates, and Razorpay as the
payment processor. None of that detail matters for using the product — it's
here so the term "the backend" means something concrete later in this
documentation.

## Next

Continue to [The Life of an Order](./02-life-of-an-order.md) to see how all
of this fits together from the moment a customer scans a QR code.
