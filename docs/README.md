# Order-Flow Technical Documentation

> **Comprehensive engineering documentation for the Order-Flow restaurant ordering & kitchen display platform.**

---

## Table of Contents

| Document | Description |
|----------|-------------|
| [Architecture Overview](architecture.md) | System design, component map, data flow, and design decisions |
| [Data Model Reference](data-model.md) | Complete database schema, entity relationships, and indexes |
| [API Reference](api-reference.md) | All HTTP and WebSocket endpoints with request/response contracts |
| [Payment System](payment-system.md) | Payment lifecycle, provider integration, state machine, and reconciliation |
| [Security Architecture](security.md) | Authentication, authorization, encryption, rate limiting, and threat mitigations |
| [Deployment Guide](deployment.md) | Infrastructure topology, Docker, Railway, environment variables, and SSL |
| [Operations Runbook](runbook.md) | Monitoring, incident response, Celery tasks, and troubleshooting |

---

## Quick Reference

| Property | Value |
|----------|-------|
| **Framework** | Django 5.2 + Channels (ASGI) |
| **Language** | Python 3.12 |
| **Database** | PostgreSQL 15 |
| **Cache / Broker** | Redis 7 |
| **Task Queue** | Celery |
| **WebSocket** | Django Channels + Redis Channel Layer |
| **Payment Providers** | Razorpay, Cashfree, PhonePe (provider-agnostic gateway) |
| **Object Storage** | Supabase Storage (S3-compatible) |
| **Error Tracking** | Sentry |
| **Reverse Proxy** | Nginx |
| **Containerization** | Docker (multi-stage) |

---

*Last synced with codebase: 2026-07-16*
