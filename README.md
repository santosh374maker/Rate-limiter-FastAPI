# Context-Aware Rate Limiter

A middleware-first rate limiting layer built with FastAPI that enforces per-tier, per-endpoint-type request quotas using in-memory state only.

**Live deployment:** `https://santosh-nestack-submission.onrender.com`

---

## How to Run

Make sure you have Python 3.9 or above installed. Clone the repository, then install dependencies:

```bash
pip install -r requirements.txt
```

Start the server:

```bash
uvicorn main:app --host 0.0.0.0 --port 8000
```

The server will be available at `http://localhost:8000`. You can test it immediately using curl. For example, to hit the AI generate endpoint as a free-tier user:

```bash
curl -X POST http://localhost:8000/ai/generate \
  -H "X-User-Tier: free" \
  -H "X-User-Id: user-123"
```

After 5 requests within 60 seconds, the server will respond with HTTP 429 and a JSON body telling you how many seconds remain in the current window.

---

## Design Decisions

**Middleware as the single enforcement point.** All rate limiting logic lives inside one `@app.middleware("http")` function. Route handlers contain no awareness of limits whatsoever. This means adding a new protected route requires only one line in the `ROUTE_ENDPOINT_TYPES` dictionary — the middleware picks it up automatically.

**Route tags via a registry dictionary, not URL parsing.** The assessment explicitly prohibits reading the endpoint type from the URL string. To honour that, each route's type is declared at definition time in `ROUTE_ENDPOINT_TYPES`, which maps `(HTTP method, path)` tuples to either `"ai"` or `"read"`. The middleware performs an exact dictionary lookup — no string splitting, no prefix matching, no regex. A route that is not present in this registry passes through without any rate limiting applied, making it easy to expose health-check or internal endpoints freely.

**Fixed window reset strategy.** Each usage entry records a `window_start` timestamp alongside its counter. When a new request arrives, if the elapsed time since `window_start` exceeds the configured window (60 seconds), the counter resets to zero and the window restarts. This is simpler to reason about than a sliding window and produces deterministic, testable behaviour. The trade-off is that a user could technically fire the maximum allowed requests right at the end of one window and again right at the start of the next, effectively doubling throughput at the boundary — a known property of fixed windows acknowledged in Limitations below.

**A single asyncio lock guards the store.** Because FastAPI runs on an async event loop, two coroutines can interleave between the read and write of a counter. Wrapping the read-check-write block in a single `asyncio.Lock()` eliminates this race without the overhead of per-key locks or atomic primitives. Since the critical section is only a dictionary read and write — both sub-microsecond — the lock is held for an immeasurably short time and will not become a throughput bottleneck under realistic load.

**User identity via X-User-Id header with IP fallback.** The spec defines the rate limit key as a combination of user identifier, tier, and endpoint type but does not dictate how to derive the user identifier. Using a dedicated `X-User-Id` header is the most explicit and testable approach. When the header is absent, the middleware falls back to the client's IP address, which is a reasonable proxy for identity in an unauthenticated context.

**Tier defaults to free on any invalid or missing header.** If `X-User-Tier` is absent, empty, or contains a value other than `free` or `paid`, the middleware silently treats the caller as free tier. This is the most conservative safe default — it prevents a malformed or missing header from accidentally granting paid-level capacity.

---

## Limitations

**Fixed-window boundary burst.** As noted above, a user can issue the full quota in the last second of one window and the full quota again in the first second of the next. For a free-tier AI user this means 10 requests in two seconds at the boundary. A sliding-window or token-bucket algorithm would prevent this at the cost of more complex state management.

**In-process memory only.** The store is a plain Python dictionary that lives for the lifetime of the process. If the server restarts, all counters reset. If the application is deployed with multiple worker processes or across multiple instances (e.g., behind a load balancer), each process maintains its own independent store and there is no cross-process coordination. This means a user could hit the limit on one worker and be served normally by another. Solving this would require an external shared store such as Redis, which the assessment explicitly prohibits.

**No persistent user registry.** The middleware trusts whatever values the caller sends in `X-User-Tier` and `X-User-Id`. A production system would validate the tier against a database record for the authenticated user. Here, any caller can claim to be paid tier simply by setting the header, which is intentional given the scope of this assessment.

**Lock contention under extreme concurrency.** A global asyncio lock means all concurrent requests serialise through a single gate during the store read-write. Under very high concurrency this could become a bottleneck. Per-key locking, a concurrent hash map, or atomic counters would scale better, but introduce complexity not warranted for an in-memory single-process implementation.

**No eviction of stale keys.** The store grows monotonically. Keys for users who have not made a request in a long time remain in memory indefinitely. A background task that evicts entries whose windows have long since expired would bound memory usage in a long-running deployment.
