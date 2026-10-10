# Nexus Gateway — Integration Guide (v2.4)

> Status: **Current** | Audience: backend engineers integrating with Nexus Gateway
> Companion doc: 《网关与鉴权接入说明》(Chinese). 本文件为英文原文，术语以本文件为准。

---

## 1. Overview

Nexus Gateway is the company's self-developed API gateway. It provides routing,
authentication, rate limiting, and observability for internal services.

Two token types are involved:

- **AGT** (Access Gateway Token): server-to-server calls. Sent in header `X-Nx-Agt`.
- **UAT** (User Access Token): end-user calls, issued by **Authorization Code** flow.
  Sent in header `Authorization: Bearer <token>`.

## 2. Route definition

```yaml
route:
  id: orders-v1
  match: { prefix: /api/orders }
  upstream: http://orders-svc.default.svc:8080
  auth: { type: agt, required: true }
  timeout_ms: 3000
  retry: { attempts: 2, on: [502, 503, 504] }
```

- Default `timeout_ms` is **800**; default `retry.attempts` is **0** (no retry unless specified).
- Health check path for upstreams: `GET /internal/health`.

## 3. Rate limiting

| Plan | Quota (QPS per system) | Burst |
| --- | --- | --- |
| basic | 50 | 100 |
| standard | 200 | 400 |
| premium | 1000 | 2000 |

- On limit, the gateway returns HTTP **429** with error code `NX-3001` and a `Retry-After` header (seconds).
- Exceeding the burst bucket for more than 60 seconds escalates to a 10-minute circuit break.

## 4. Observability

- Trace id: the gateway injects `X-Nx-Trace-Id` on every request.
- Metrics exposed: `nx_gateway_requests_total`, `nx_gateway_upstream_latency_ms` (P99).
- Logs are retained for **14 days**; traces for **7 days**.

## 5. Error codes (reference)

| HTTP | Code | Meaning |
| --- | --- | --- |
| 401 | NX-1001 | AGT missing or malformed |
| 401 | NX-1002 | AGT expired |
| 403 | NX-2001 | app_id not authorized for this route |
| 429 | NX-3001 | Rate limited |
| 502 | NX-4001 | Upstream unreachable |
| 504 | NX-4002 | Upstream timeout |

## 6. Migration notes (v2.x)

- Token rotation has a **24-hour dual-active window** — old and new AGTs both work during it.
- Revocation takes effect within **5 minutes**.
- The deprecated header `X-Api-Key` is rejected since v2.0.

## 7. FAQ

- **Q: Where do I get an `app_id`?** After your access request is approved; it arrives by email.
- **Q: Can I use AGT from a browser?** No — AGT is for server-to-server only. Use UAT for browsers.
- **Q: How long is an AGT valid?** 30 days; rotate it within 7 days before expiry.
