import asyncio
import os
import time
import logging

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from .logging import setup_logging
from .poller import Poller
from .store import SnapshotStore
from .stats import RollingStats

# Config
def int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except ValueError:
        return default

UPSTREAM_URL = os.getenv("UPSTREAM_URL", "http://127.0.0.1:9001/counters")
POLL_MS = int_env("POLL_MS", 1500)
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
BIND_HOST = os.getenv("BIND_HOST", "0.0.0.0")
PORT = int_env("PORT", 8080)

# App and State
setup_logging("metrics-api", LOG_LEVEL)
log = logging.getLogger(__name__)
app = FastAPI(title="Fabric Telemetry (metrics server)")

store = SnapshotStore()
poller = Poller(UPSTREAM_URL, POLL_MS, store)
stats = RollingStats(capacity=1000)
started_at = time.time()

# Access log + latency
@app.middleware("http")
async def access_logger(request: Request, call_next):
    t0 = time.time()
    try:
        response = await call_next(request)
        return response
    finally:
        latency_ms = int((time.time() - t0) * 1000)
        path = request.url.path
        stats.add(path, latency_ms)
        # age header if we have data
        age_ms: int | None = await store.age_ms()
        log.info(
            "access",
            extra={
                "event": "http.access",
                "extra_fields": {
                    "path": path,
                    "method": request.method,
                    "latency_ms": latency_ms,
                    "status": getattr(request.state, "status_code", None)
                    or getattr(locals().get("response", None), "status_code", None),
                    "age_ms": age_ms if age_ms is not None else -1,
                },
            },
        )

# Startup/Shutdown
@app.on_event("startup")
async def _startup():
    log.info(
        "starting poller",
        extra={
            "event": "startup",
            "extra_fields": {"upstream": UPSTREAM_URL, "poll_ms": POLL_MS},
        },
    )
    await poller.start()

@app.on_event("shutdown")
async def _shutdown():
    log.info("stopping poller", extra={"event": "shutdown"})
    await poller.stop()

# Helpers
async def _current_snapshot():
    s = await store.get()
    if not s:
        raise HTTPException(status_code=503, detail="No data yet. Try again shortly.")
    return s

def _staleness(ts_ms: int) -> int:
    return int(time.time() * 1000) - ts_ms

# Endpoints
@app.get("/telemetry/GetMetric")
async def get_metric(
    switch_id: str = Query(..., description="Switch ID, e.g., sw-000"),
    metric: str = Query(..., description="Metric name, e.g., bandwidth_gbps"),
):
    s = await _current_snapshot()
    if switch_id not in s.data:
        raise HTTPException(status_code=404, detail=f"Unknown switch_id '{switch_id}'.")
    if metric not in s.meta.fields:
        raise HTTPException(
            status_code=404, detail=f"Unknown metric '{metric}'. Available: {s.meta.fields}"
        )
    value = s.data[switch_id].get(metric)
    age_ms = _staleness(s.meta.ts_ms)
    resp = {
        "switch_id": switch_id,
        "metric": metric,
        "value": value,
        "snapshot_id": s.meta.snapshot_id,
        "age_ms": age_ms,
    }
    return JSONResponse(resp, headers={"X-Data-Age-Ms": str(age_ms), "ETag": s.meta.snapshot_id})

@app.get("/telemetry/ListMetrics")
async def list_metrics():
    s = await _current_snapshot()
    age_ms = _staleness(s.meta.ts_ms)
    items: list[dict[str, object]] = []
    for sw, vals in s.data.items():
        obj: dict[str, object] = {"switch_id": sw}
        obj.update(vals)
        items.append(obj)
    resp = {
        "snapshot_id": s.meta.snapshot_id,
        "age_ms": age_ms,
        "fields": s.meta.fields,
        "items": items,
    }
    return JSONResponse(resp, headers={"X-Data-Age-Ms": str(age_ms), "ETag": s.meta.snapshot_id})

@app.get("/stats")
async def stats_endpoint():
    now = time.time()
    uptime_s = int(now - started_at)
    # simple lat/percentiles for main endpoints
    lm = stats.percentiles("/telemetry/ListMetrics")
    gm = stats.percentiles("/telemetry/GetMetric")
    return {
        "uptime_s": uptime_s,
        "poll_last_cycle_ms": poller.last_cycle_ms,
        "poll_retry_count": poller.fail_count,
        "endpoints": {
            "ListMetrics": lm,
            "GetMetric": gm,
        },
    }

@app.get("/health")
async def health():
    return {"ok": True}
