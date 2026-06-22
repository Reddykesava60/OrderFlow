# Glossary

Plain-English definitions for every term used across this documentation.
Sorted alphabetically. If you're reading the "for-everyone" docs, you
shouldn't need anything past the first few entries.

---

**Atomic transaction** — A group of database changes that all succeed
together or all fail together. There is no in-between state. Dineflow uses
this to guarantee, for example, that an order can never be marked "paid"
without the restaurant's balance also being updated.

**Celery** — A background job system. It lets Dineflow do slow or
unpredictable work (like talking to a payment gateway) without making a
customer's web page wait for it.

**Celery Beat** — The scheduler that triggers Celery jobs on a timer (for
example, "check for stuck payments every 5 minutes"), the way a cron job
would.

**Channels / Django Channels** — The library that lets Dineflow keep a live,
two-way connection open with a kitchen tablet, so updates appear instantly
instead of the tablet having to ask "anything new?" over and over.

**Checkout** — The process of turning a shopping cart into a real `Order`:
checking stock, calculating the final price, and creating the database
records.

**Dead Letter Queue (DLQ)** — A holding area for webhook events that failed
to process automatically after several retries. Nothing is lost — the raw
event is parked here for a human to look at.

**Double-entry ledger** — An accounting method where every transaction is
recorded as at least two balanced entries (e.g., money coming in is matched
by money owed to the restaurant and a fee owed to the platform). It's the
same method real banks and accountants use, and it makes it mathematically
impossible for money to silently appear or disappear in the books.

**Idempotency key** — A unique ID a client attaches to a request so that if
the same request is accidentally sent twice (e.g., due to a network retry),
the server recognizes it and processes it only once.

**Idempotent** — Describes an operation that produces the same result no
matter how many times it's repeated. "Processing this webhook is idempotent"
means processing it five times has the same effect as processing it once.

**Journal Entry / Journal Line** — The individual records that make up the
double-entry ledger. A `JournalEntry` is one event (e.g., "payment
captured"); its `JournalLine`s are the individual debits and credits that
make it up.

**KDS (Kitchen Display System)** — The screen in the kitchen that shows
incoming orders as tickets, replacing a paper order pad.

**Ledger** — The system of record for money. See *Double-entry ledger*.

**Migration** — A versioned, repeatable script that changes the shape of the
database (e.g., "add a new column"). Django tracks these so every
environment's database can be brought up to the same structure.

**Multi-tenant** — One single deployment of the software serves many
independent restaurants, each with its own menu, orders, staff, and money,
fully isolated from the others.

**Order state machine** — The fixed set of stages an order can be in
(`UNPAID`, `PENDING`, `PREP_STARTED`, `COMPLETED`, `CANCELLED`) and the rules
for which stage can move to which other stage.

**Payment gateway** — The third-party service (Razorpay, in Dineflow's case)
that actually moves money between a customer's bank/UPI app and the
restaurant. Dineflow never touches raw card or bank details directly.

**Payment state machine** — Similar to the order state machine, but tracking
the payment transaction itself (`pending`, `initiated`, `paid`, `failed`,
etc.) as reported by the payment gateway.

**Platform fee / commission** — The percentage (or flat amount) Dineflow
keeps from each order as its own revenue, with the rest belonging to the
restaurant.

**Race condition** — A bug that only happens when two things happen at
nearly the same instant (e.g., two customers buying the last item in stock
at the same second). Dineflow guards against these with database locks.

**Redis** — A very fast in-memory data store. Dineflow uses it as the
message queue for Celery and as the relay for real-time KDS updates.

**Reconciliation** — Double-checking Dineflow's records against the payment
gateway's records to catch anything that fell through the cracks (e.g., a
webhook that never arrived).

**Service layer** — The part of the codebase (`*/services.py` files) that
contains business logic, kept separate from the web request-handling code
(`views.py`) and the database table definitions (`models.py`).

**Settlement** — The process of actually transferring a restaurant's earned
balance to their bank account.

**Stock reservation** — A short-lived hold placed on inventory while a
customer is paying, so two people can't both "win" the last item in stock.

**Tenant** — In a multi-tenant system, one customer/business sharing the
platform — here, one restaurant.

**UUID** — A 128-bit randomly generated ID (e.g.,
`3fa85f64-5717-4562-b3fc-2c963f66afa6`) used instead of sequential numbers
like `1, 2, 3...` so IDs can't be guessed or enumerated.

**Webhook** — An automated notification sent from one server to another when
something happens. Razorpay sends Dineflow a webhook the instant a payment
succeeds or fails, rather than Dineflow having to repeatedly ask "did it
work yet?".

**WebSocket** — A network connection that stays open in both directions, so
the server can push a message to a browser/tablet the instant something
happens, instead of waiting for the browser to ask.
