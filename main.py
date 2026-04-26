import asyncio
import time
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

app = FastAPI()

RATE_LIMIT_RULES = {
    ("free", "ai"):   {"limit": 5,   "window": 60},
    ("free", "read"): {"limit": 30,  "window": 60},
    ("paid", "ai"):   {"limit": 30,  "window": 60},
    ("paid", "read"): {"limit": 120, "window": 60},
}

ROUTE_ENDPOINT_TYPES = {
    ("POST", "/ai/generate"):  "ai",
    ("POST", "/ai/summarise"): "ai",
    ("GET",  "/data/list"):    "read",
    ("GET",  "/data/export"):  "read",
}

store = {}
store_lock = asyncio.Lock()


@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    route_key = (request.method, request.url.path)
    endpoint_type = ROUTE_ENDPOINT_TYPES.get(route_key)

    if endpoint_type is None:
        return await call_next(request)

    raw_tier = request.headers.get("X-User-Tier", "").strip().lower()
    tier = raw_tier if raw_tier in ("free", "paid") else "free"

    user_id = request.headers.get("X-User-Id", request.client.host if request.client else "anonymous")
    store_key = (user_id, tier, endpoint_type)

    rule = RATE_LIMIT_RULES[(tier, endpoint_type)]
    limit = rule["limit"]
    window = rule["window"]

    now = time.time()

    async with store_lock:
        if store_key not in store:
            store[store_key] = {"count": 0, "window_start": now}

        entry = store[store_key]

        if now - entry["window_start"] >= window:
            entry["count"] = 0
            entry["window_start"] = now

        if entry["count"] >= limit:
            retry_after = max(0, int(window - (now - entry["window_start"])))
            return JSONResponse(
                status_code=429,
                content={
                    "error": "rate_limit_exceeded",
                    "limit": limit,
                    "window_seconds": window,
                    "retry_after_seconds": retry_after,
                },
            )

        entry["count"] += 1

    return await call_next(request)


@app.post("/ai/generate")
async def ai_generate():
    return {"ok": True}


@app.post("/ai/summarise")
async def ai_summarise():
    return {"ok": True}


@app.get("/data/list")
async def data_list():
    return {"ok": True}


@app.get("/data/export")
async def data_export():
    return {"ok": True}
