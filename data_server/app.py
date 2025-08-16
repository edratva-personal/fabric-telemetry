import csv
import io
import json
import logging
import random
import threading
import time
from flask import Flask, Response, request, jsonify

from .config import (
    DATA_SWITCHES, DATA_INTERVAL_SEC, FAULT_500_PCT, FAULT_SLOW_MS,
    BIND_HOST, PORT, LOG_LEVEL
)
from .simulator import generate_snapshot, Snapshot

# Logging
class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + f".{int(time.time()*1000)%1000:03d}Z",
            "level": record.levelname,
            "svc": "data-sim",
            "event": getattr(record, "event", "log"),
            "msg": record.getMessage(),
        }
        for k, v in getattr(record, "extra_fields", {}).items():
            payload[k] = v
        return json.dumps(payload, ensure_ascii=False)

def setup_logging():
    root = logging.getLogger()
    if not root.handlers:
        h = logging.StreamHandler()
        h.setFormatter(JsonFormatter())
        root.addHandler(h)
    root.setLevel(getattr(logging, LOG_LEVEL, logging.INFO))

# App state
_lock = threading.Lock()
# Start with an empty placeholder; we generate a real snapshot at startup.
_snapshot: Snapshot = (0, 0, [], {})
_stop = threading.Event()

def _generator_loop():
    """Background loop that refreshes the snapshot every DATA_INTERVAL_SEC."""
    global _snapshot
    log = logging.getLogger(__name__)
    last_tick = time.time()
    while not _stop.is_set():
        t0 = time.time()
        with _lock:
            _snapshot = generate_snapshot(DATA_SWITCHES, _snapshot[0])
            sid, ts_ms, fields, rows = _snapshot
        tick_ms = int((time.time() - t0) * 1000)
        skew_ms = int((time.time() - last_tick - DATA_INTERVAL_SEC) * 1000)
        last_tick = time.time()
        log.info(
            "snapshot refreshed",
            extra={"event": "gen.tick", "extra_fields": {
                "tick_ms": tick_ms,
                "interval_ms": DATA_INTERVAL_SEC * 1000,
                "skew_ms": skew_ms,
                "switches": DATA_SWITCHES,
                "metrics_per_switch": len(_snapshot[2]),
                "snapshot_id": str(_snapshot[0]),
            }},
        )
        _stop.wait(DATA_INTERVAL_SEC)

def _to_csv(s: Snapshot) -> str:
    """Serialize the snapshot to a CSV matrix."""
    sid, ts_ms, fields, rows = s
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["switch_id"] + fields)
    for sw, vals in rows.items():
        w.writerow([sw] + [vals[k] for k in fields])
    return buf.getvalue()

def create_app() -> Flask:
    setup_logging()
    app = Flask(__name__)

    # Generate an initial snapshot immediately so the first request already
    # has the correct (simulator-driven) metric header and rows.
    global _snapshot
    with _lock:
        _snapshot = generate_snapshot(DATA_SWITCHES, _snapshot[0])

    # Start generator thread (only once)
    if not getattr(app, "_gen_started", False):
        t = threading.Thread(target=_generator_loop, daemon=True)
        t.start()
        app._gen_started = True  # type: ignore[attr-defined]

    @app.get("/counters")
    def counters():
        log = logging.getLogger(__name__)
        t0 = time.time()

        # Fault injection: occasional 500 or jitter delay
        if FAULT_500_PCT > 0 and random.randint(1, 100) <= FAULT_500_PCT:
            if FAULT_SLOW_MS > 0:
                time.sleep(FAULT_SLOW_MS / 1000.0)
            log.warning(
                "injecting 500",
                extra={"event": "gen.inject_fault", "extra_fields": {"fault": "500"}},
            )
            return jsonify({"error": "injected failure"}), 500

        if FAULT_SLOW_MS > 0 and random.random() < 0.2:
            # Delay ~20% of requests to simulate jitter
            time.sleep(FAULT_SLOW_MS / 1000.0)

        with _lock:
            sid, ts_ms, fields, rows = _snapshot
            etag = str(sid)

            # ETag / If-None-Match support
            inm = request.headers.get("If-None-Match")
            if inm and inm == etag:
                resp = Response(status=304)
                resp.headers["ETag"] = etag
                resp.headers["X-Snapshot-Ts"] = str(ts_ms)
                resp.headers["Cache-Control"] = "no-store"
                return resp

            csv_text = _to_csv(_snapshot)

        resp = Response(csv_text, mimetype="text/csv; charset=utf-8")
        resp.headers["ETag"] = etag
        resp.headers["X-Snapshot-Ts"] = str(ts_ms)
        resp.headers["Cache-Control"] = "no-store"

        latency_ms = int((time.time() - t0) * 1000)
        log.info(
            "serve /counters",
            extra={"event": "http.access", "extra_fields": {
                "path": "/counters",
                "status": 200,
                "latency_ms": latency_ms,
                "bytes_sent": len(csv_text),
                "age_ms": int(time.time() * 1000) - ts_ms,
                "snapshot_id": etag,
            }},
        )
        return resp

    @app.get("/health")
    def health():
        return {"ok": True}

    return app

if __name__ == "__main__":
    # Dev run: python -m data_server.app
    create_app().run(host=BIND_HOST, port=PORT)
