# Dineflow Documentation

Dineflow is the software that runs a restaurant's entire ordering operation: a
customer scans a QR code, orders and pays from their phone, the kitchen sees
the ticket instantly, and the restaurant's money is tracked down to the rupee.

This documentation is organized by **who you are**, not by which file happens
to be easiest to write. Pick your folder and ignore the rest.

## Where to go

| You are... | Go to | What you'll find |
|---|---|---|
| Curious about what this product does, with no technical background | [`for-everyone/`](./for-everyone/01-what-is-dineflow.md) | Plain-language explanations, no code, no jargon |
| An engineer joining the team or reviewing the system | [`engineering/`](./engineering/01-architecture-overview.md) | Architecture, data model, code map, API reference |
| Responsible for deploying, launching, or running this in production | [`operations/`](./operations/01-deployment-guide.md) | Deployment steps, checklists, incident playbooks |

If a word trips you up anywhere, check the [Glossary](./00-glossary.md) —
it's shared across all three sections.

For a summary of recent feature additions, operational improvements, and UI changes, please see the [Changelog](./CHANGELOG.md).

## Reading order by audience

**Founder, support staff, or anyone non-technical** — read in this order:
1. [What is Dineflow?](./for-everyone/01-what-is-dineflow.md)
2. [The Life of an Order](./for-everyone/02-life-of-an-order.md)
3. [How the Money Works](./for-everyone/03-how-the-money-works.md)
4. [FAQ](./for-everyone/04-faq.md)

**New engineer** — read in this order:
1. [Architecture Overview](./engineering/01-architecture-overview.md)
2. [Codebase Map](./engineering/02-codebase-map.md)
3. [Data Model](./engineering/03-data-model.md)
4. [Order & Payment Lifecycle](./engineering/04-order-and-payment-lifecycle.md)
5. [Financial Ledger](./engineering/05-financial-ledger.md)
6. [Payments & Webhooks](./engineering/06-payments-and-webhooks.md)
7. [Real-Time Kitchen Display](./engineering/07-realtime-kitchen-display.md)
8. [Background Jobs](./engineering/08-background-jobs.md)
9. [API Reference](./engineering/09-api-reference.md)
10. [Security](./engineering/10-security.md)
11. [Local Development Setup](./engineering/11-local-development-setup.md)

**Whoever is deploying or operating this in production**:
1. [Deployment Guide](./operations/01-deployment-guide.md)
2. [Production Readiness Checklist](./operations/02-production-readiness-checklist.md)
3. [Incident Playbook](./operations/03-incident-playbook.md)
4. [QA & UAT Checklist](./operations/04-qa-and-uat-checklist.md)

## A note on accuracy

Every claim in these docs was checked directly against the source code as of
this writing, not copied from memory or from older documentation. If the code
changes, these docs will drift — please update the relevant page in the same
pull request that changes the behavior it describes.
