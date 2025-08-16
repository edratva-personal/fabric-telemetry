# Fabric Telemetry

A small, UFM-style **fabric telemetry** exercise with two services:

- **data_server (Flask, :9001)** – simulates switch metrics and serves a **CSV matrix** at `/counters`.
- **metrics_server (FastAPI, :8080)** – polls `/counters`, caches the latest snapshot, and serves:
  - `GET /telemetry/GetMetric?switch_id=&metric=`
  - `GET /telemetry/ListMetrics`
  - `GET /stats` (roll-up latency stats)
  - `GET /healthz`

## Why two services?

This mirrors a realistic producer/consumer split. You can test failure modes (timeouts, jitter, 500s), polling cadence vs. query cadence, staleness, and non-blocking behavior under concurrent requests.

---

## Repo layout

```
fabric-telemetry/
├─ data_server/                 # Flask simulator
│  ├─ app.py
│  ├─ simulator.py
│  ├─ config.py
│  └─ Dockerfile                # see Appendix A if missing
├─ metrics_server/              # FastAPI metrics API
│  ├─ app.py
│  ├─ poller.py
│  ├─ store.py
│  ├─ logging.py
│  ├─ stats.py
│  └─ Dockerfile                # see Appendix A if missing
├─ scripts/
│  └─ demo.sh                   # (optional) demo helpers
├─ requirements.txt
├─ docker-compose.yml
├─ Makefile
├─ .env.example
└─ README.md
```

---

## Requirements

- **Python 3.11** (Ubuntu 20.04 users: install via deadsnakes PPA)
- **pip**
- **Docker** & **Docker Compose** (optional, for containerized run)
- **curl** (for quick tests), **jq** (optional)

---

## Run (venv)

```bash
# one-time setup
python3.11 -m venv .venv && source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt

# terminal A — data server (Flask)
python -m data_server.app

# terminal B — metrics server (FastAPI)
UPSTREAM_URL=http://127.0.0.1:9001/counters uvicorn metrics_server.app:app --host 127.0.0.1 --port 8080
```

With **Makefile**:
```bash
make dev
make run-data
make run-metrics
```

---

## Run (Docker)

```bash
docker compose up --build
```

- Host access:
  - Data server: http://127.0.0.1:9001/counters
  - Metrics server: http://127.0.0.1:8080/…
- Inside Docker, the metrics server uses `UPSTREAM_URL=http://data-server:9001/counters` (service DNS name).

Stop & clean:
```bash
docker compose down
```

> If you don’t have the Dockerfiles yet, copy them from **Appendix A** below.

---

## Try it

```bash
# CSV snapshot (from data server)
curl -s http://127.0.0.1:9001/counters | head

# All metrics (from metrics server)
curl -s 'http://127.0.0.1:8080/telemetry/ListMetrics' | jq

# One metric
curl -s 'http://127.0.0.1:8080/telemetry/GetMetric?switch_id=sw-000&metric=bandwidth_gbps' | jq

# Stats (p50/p95/p99 per endpoint, last ~1000 samples)
curl -s 'http://127.0.0.1:8080/stats' | jq
```

---

## API reference

### data_server (Flask, :9001)

- **GET `/counters`** → `text/csv`
  - Headers:
    - `ETag`: snapshot id (string)
    - `X-Snapshot-Ts`: epoch ms
    - `Cache-Control: no-store`
  - Supports `If-None-Match` (returns **304** if unchanged)
  - **CSV format** (matrix; first row = header):
    ```
    switch_id,bandwidth_gbps,latency_us,packet_errors
    sw-000,122.4,11.2,0
    sw-001,118.7,10.8,1
    ...
    ```

### metrics_server (FastAPI, :8080)

- **GET `/telemetry/ListMetrics`** → JSON
  - Headers: `X-Data-Age-Ms`, `ETag`
  - Response:
    ```json
    {
      "snapshot_id": "1749",
      "age_ms": 820,
      "fields": ["bandwidth_gbps","latency_us","packet_errors"],
      "items": [
        {"switch_id":"sw-000","bandwidth_gbps":122.4,"latency_us":11.2,"packet_errors":0}
      ]
    }
    ```

- **GET `/telemetry/GetMetric?switch_id=sw-000&metric=bandwidth_gbps`** → JSON
  - Headers: `X-Data-Age-Ms`, `ETag`
  - Errors: **404** if `switch_id` or `metric` unknown; **503** if no snapshot yet.
  - Response:
    ```json
    {"switch_id":"sw-000","metric":"bandwidth_gbps","value":122.4,"snapshot_id":"1749","age_ms":820}
    ```

- **GET `/stats`** → JSON roll-up latencies (p50/p95/p99, max, count) for `ListMetrics` and `GetMetric`, plus poller stats.

- **GET `/healthz`** → `{ "ok": true }`

---

## Configuration (env vars)

### Data server

| Var              | Default | Unit | Purpose |
|---               |---      |---   |---|
| `DATA_SWITCHES`  | `64`    | —    | Number of simulated switches |
| `DATA_INTERVAL_SEC` | `10` | s    | Snapshot generation interval |
| `FAULT_500_PCT`  | `0`     | %    | Chance that `/counters` returns 500 (fault injection) |
| `FAULT_SLOW_MS`  | `0`     | ms   | Extra delay on ~20% of requests (jitter) |
| `BIND_HOST`      | `0.0.0.0` | —  | Bind host (dev default) |
| `PORT`           | `9001`  | —    | Port |

### Metrics server

| Var           | Default                              | Unit | Purpose |
|---            |---                                   |---   |---|
| `UPSTREAM_URL`| `http://127.0.0.1:9001/counters`     | URL  | Where to pull CSV (Compose uses `http://data-server:9001/counters`) |
| `POLL_MS`     | `1500`                               | ms   | Poll cadence (should be **<** data interval) |
| `LOG_LEVEL`   | `INFO`                               | —    | `DEBUG` \| `INFO` \| `WARN` \| `ERROR` |
| `BIND_HOST`   | `0.0.0.0`                            | —    | Bind host |
| `PORT`        | `8080`                               | —    | Port |

> Copy `.env.example` to `.env` and edit if you like. The Makefile auto-loads `.env`.

**Note on config typing & validation:** For simplicity in this exercise, config values are read via small helpers (e.g., `int_env`) and validated minimally. In a production service, you could wrap all config in a **dataclass** or a **Pydantic `BaseSettings`** model to: enforce types and ranges (e.g., clamp `FAULT_500_PCT` to `[0,100]`, ensure `DATA_INTERVAL_SEC >= 1`), provide automatic defaults and `.env` loading, and generate clearer documentation.

---

## Observability

Both services log **structured JSON (NDJSON)** to stdout.

- **data_server events**
  - `gen.tick` — generator cycles (tick_ms, interval_ms, skew_ms, snapshot_id)
  - `http.access` — `/counters` latency, bytes_sent, age_ms
  - `gen.inject_fault` — when a 500 or delay is injected

- **metrics_server events**
  - `startup` / `shutdown`
  - `poll.run` — poll timing (fetch_ms / parse_ms / apply_ms / cycle_ms), status, retry count
  - `poll.error` — any exceptions while polling
  - `http.access` — per-request latency + current `age_ms` of data

**Percentiles** (`/stats`): p50/p95/p99/max over a rolling window (~1000 recent samples) for the two main endpoints.

---

## Performance goals (to measure later)

- `/telemetry/GetMetric`: **p95 ≤ ~5–7 ms** locally at ~100 concurrent requests; p99 reasonable; near-zero errors.
- Stable latency while the poller runs (non-blocking behavior).
- On upstream slowness/outage: keep serving last snapshot with **staleness** (`X-Data-Age-Ms`), no stalls.

> Use `/stats` for a quick view, or a load tool like `hey`. (You can add a `scripts/bench.sh` later.)

---

## Troubleshooting

- **`ModuleNotFoundError: flask`**
  Activate the venv and install deps:  
  `source .venv/bin/activate && pip install -r requirements.txt`

- **Relative import errors** in `data_server/app.py`
  Run as a **module**: `python -m data_server.app` (recommended), or switch the imports to absolute.

- **`UPSTREAM_URL` inside Docker**
  Use `http://data-server:9001/counters` (service name) — not `127.0.0.1`.

- **Ports already in use**
  Something else is bound to 9001/8080. Stop it or change `PORT`.

- **No data yet (503)** from metrics server
  Wait for the first poll (POLL_MS) and the simulator’s first tick (DATA_INTERVAL_SEC). Then retry.

---

## Limitations

- In-memory only (no persistence/history).
- Single node, single snapshot (latest only).
- CSV over HTTP for simplicity.
- Minimal access controls.

---

## Ideas for improvement

**Throughput**
- `uvicorn --loop uvloop`, reuse a single `httpx.AsyncClient`, enable `orjson`.
- Offload large CSV parse to a threadpool; or switch the simulator to JSON/NDJSON.

**Fault-tolerance**
- Exponential backoff with jitter on poll failures; circuit breaker.
- `MAX_STALE_MS` policy (503 when too stale).
- Health/readiness endpoints + restart policy.

**Scalability**
- Stateless metrics servers behind a load balancer; shared cache (Redis).
- Shard by `switch_id`; paginate `ListMetrics`.
- Streaming (SSE/WebSocket) for near-real-time updates.
- Prometheus `/metrics` (histograms for request/poll/freshness) + Grafana.

---

## License / visibility

This repo is intended for interview evaluation. Keep it **Private** and share with reviewers as collaborators.

---

## Appendix A — Dockerfiles (copy if not already present)

**`data_server/Dockerfile`**
```dockerfile
FROM python:3.11-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY data_server/ ./data_server/
EXPOSE 9001
USER nobody
CMD ["gunicorn", "-w", "1", "-b", "0.0.0.0:9001", "data_server.app:create_app()"]
```

**`metrics_server/Dockerfile`**
```dockerfile
FROM python:3.11-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY metrics_server/ ./metrics_server/
EXPOSE 8080
USER nobody
CMD ["uvicorn", "metrics_server.app:app", "--host", "0.0.0.0", "--port", "8080"]
```
