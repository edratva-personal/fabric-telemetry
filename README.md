# Fabric Telemetry

Two small services modeled after NVIDIA UFM’s split between **telemetry producers** and **consumers**:

- **data_server (Flask, :9001)** → simulates fabric switch metrics and serves a CSV **matrix** at `/counters`.
- **metrics_server (FastAPI, :8080)** → polls `/counters`, keeps the latest snapshot in memory, and serves:
  - `GET /telemetry/GetMetric?switch_id=&metric=`
  - `GET /telemetry/ListMetrics`
  - `GET /stats` (latency percentiles & poller stats)
  - `GET /health`

---

## Prerequisites (Ubuntu 20.04+)

> Quick setup for a fresh machine. If you already have these, skip.

### System tools
```bash
sudo apt-get update
sudo apt-get install -y curl git jq ca-certificates gnupg lsb-release software-properties-common
```

### Python 3.11 + venv
```bash
# Add Deadsnakes PPA for Python 3.11 on Ubuntu 20.04
sudo add-apt-repository -y ppa:deadsnakes/ppa
sudo apt-get update
sudo apt-get install -y python3.11 python3.11-venv python3.11-dev
```

### Docker Engine + Compose v2 (recommended)
```bash
# Install Docker’s official repo
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo $UBUNTU_CODENAME) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# Optional: run docker without sudo
sudo usermod -aG docker $USER
newgrp docker
docker compose version   # verify Compose v2 is available
```

---

## Running locally & with Docker

### Local (venv)

1) Create venv & install deps
```bash
python3.11 -m venv .venv && source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

2) **Configure via `.env` (recommended)** — this sets both services’ runtime knobs:
```bash
cp .env.example .env
# edit .env if needed; defaults are sensible:
# DATA_SWITCHES=64
# DATA_INTERVAL_SEC=10
# FAULT_500_PCT=0
# FAULT_SLOW_MS=0
# UPSTREAM_URL=http://127.0.0.1:9001/counters
# POLL_MS=1500
# LOG_LEVEL=INFO

# export everything in this shell:
set -a; source .env; set +a
```

3) Start **data server** (Terminal A)
```bash
python -m data_server.app
# listens on 0.0.0.0:9001; CSV at /counters
```

4) Start **metrics server** (Terminal B)
```bash
# in a new shell: set -a; source .env; set +a
uvicorn metrics_server.app:app --host 0.0.0.0 --port 8080
```

5) Try it
```bash
curl -s http://127.0.0.1:8080/health
curl -s http://127.0.0.1:8080/telemetry/ListMetrics | jq '.fields, .items[0]'
curl -s 'http://127.0.0.1:8080/telemetry/GetMetric?switch_id=sw-000&metric=cpu_util_pct' | jq
```

> Tip: For quick demos, set `DATA_INTERVAL_SEC=3` and `POLL_MS=1000` in `.env`.

---

### Docker (Compose v2)
```bash
docker compose up --build
# Try it from host
curl -s http://127.0.0.1:8080/health
```

---

## How it works

### Telemetry generation (producer)

The **data_server** periodically synthesizes a snapshot for `N` switches (default **64**), producing **8 metrics** per switch:

- `bandwidth_gbps`, `latency_us`, `packet_errors`
- `cpu_util_pct`, `mem_util_pct`
- `buffer_occupancy_pct`, `egress_drops_per_s`
- `temperature_c`

Every tick it emits a CSV “matrix”:

```
switch_id,bandwidth_gbps,latency_us,packet_errors,cpu_util_pct,mem_util_pct,buffer_occupancy_pct,egress_drops_per_s,temperature_c
sw-000,121.5,11.2,0,34.1,59.8,28.6,1,46.7
sw-001,118.3,9.9,1,36.5,64.2,31.0,0,47.9
...
```

HTTP response headers carry **freshness & identity**:
- `ETag`: snapshot ID (pollers use `If-None-Match` → 304 when unchanged)
- `X-Snapshot-Ts` (epoch ms)
- `Cache-Control: no-store`

Fault injection options:
- `FAULT_500_PCT` → percentage of requests to fail with 500
- `FAULT_SLOW_MS` → extra latency on ~20% of requests

### Data handling & REST server (consumer)

The **metrics_server** runs an async **poller**:
- Sends `If-None-Match` to avoid re-downloading unchanged data (sees fast **304**).
- On **200 OK**, parses CSV and builds `{ switch_id -> { metric -> value } }`.
- Swaps in a new in-memory **Snapshot** atomically (guarded by an `asyncio.Lock`).
- On errors, continues serving the **last good snapshot** (with increasing staleness).

API endpoints:
- `GET /telemetry/ListMetrics` → full table (flattened list of rows)
- `GET /telemetry/GetMetric?switch_id=&metric=` → single value
- `GET /stats` → p50/p95/p99/max per endpoint + poller timing/retry counters
- `GET /health` → liveness

> **Why FastAPI here?** The consumer does background polling and handles potentially many simultaneous requests. **FastAPI (ASGI)** + **Uvicorn** fits this **async I/O** pattern and yields excellent concurrency with minimal code.

### Serving stack: Gunicorn (Flask) & Uvicorn (FastAPI)

- **Flask data_server → Gunicorn (WSGI)**  
  Command (Docker):  
  `gunicorn -w 1 -b 0.0.0.0:9001 data_server.app:create_app()`  
  One worker is enough for the generator; you can scale workers if needed.

- **FastAPI metrics_server → Uvicorn (ASGI)**  
  Command (Docker):  
  `uvicorn metrics_server.app:app --host 0.0.0.0 --port 8080`  
  Add `--workers N` to utilize multiple CPU cores under heavy load.

Both servers emit structured JSON logs (NDJSON) to stdout.

---

## Repository layout

```
fabric-telemetry/
├─ data_server/                 # Flask producer
│  ├─ app.py
│  ├─ simulator.py
│  └─ Dockerfile
├─ metrics_server/              # FastAPI consumer
│  ├─ app.py
│  ├─ poller.py
│  ├─ store.py
│  ├─ logging.py
│  └─ stats.py
├─ requirements.txt
├─ docker-compose.yml
├─ Makefile
├─ .env.example
└─ README.md
```

---

## API reference

### data_server (Flask, :9001)
- **GET `/counters`** → `text/csv`  
  Headers: `ETag`, `X-Snapshot-Ts`, `Cache-Control: no-store`  
  Supports `If-None-Match` → **304** when unchanged.

### metrics_server (FastAPI, :8080)
- **GET `/telemetry/ListMetrics`** → JSON  
  Headers: `X-Data-Age-Ms`, `ETag`  
  Payload: `{ snapshot_id, age_ms, fields[], items[] }`

- **GET `/telemetry/GetMetric?switch_id=...&metric=...`** → JSON  
  Headers: `X-Data-Age-Ms`, `ETag`  
  Errors: **404** (bad switch/metric), **503** (no snapshot yet)

- **GET `/stats`** → JSON  
  `endpoints` (p50/p95/p99/max/count), `poll_last_cycle_ms`, `poll_retry_count`, `uptime_s`

- **GET `/health`** → `{ "ok": true }`

---

## Observability

**Structured JSON logs (NDJSON)** to stdout:

- *data_server* events: `gen.tick`, `http.access`, `gen.inject_fault`
- *metrics_server* events: `startup`, `shutdown`, `poll.run`, `poll.error`, `http.access`

`/stats` computes `p50`/`p95`/`p99` over a rolling window (~1000) for the two main endpoints and exposes basic poller stats (cycle time, retries).

---

## Performance notes

- **Generator frequency vs. poll cadence.**  
  Keep `POLL_MS` lower than `DATA_INTERVAL_SEC*1000` to benefit from **304** responses between updates. Example: generator every **10s**, poll every **1.5s** → pattern of `200, 304, 304, …`.

- **“Many generator threads?”**  
  The producer is intentionally single-threaded per process to avoid write races. If you add multiple generator threads or multiple Gunicorn workers:
  - Ensure updates are **atomic** (e.g., build a full snapshot in a local variable, then swap).
  - If you run multiple **workers** for the data server, each worker produces its **own** stream; load balancers may serve different snapshots across requests. That’s fine for a demo, but for consistency you’d centralize generation or back it with a shared store (Redis).

- **“Too many requests?”**  
  - **GetMetric** is O(1) lookups in memory and very cheap; it scales with the number of workers.  
  - **ListMetrics** serializes the whole snapshot; large switch counts inflate payload size and JSON encoding time. Under heavy load:
    - Add **more Uvicorn workers** (`--workers N`) to use multiple CPU cores.
    - Consider **pagination** or **field filtering** to reduce response size.
    - Prefer **binary/cached** representations (see “Ideas to scale”).

- **CPU vs. I/O bound.**  
  FastAPI + Uvicorn shines with I/O-bound concurrency (many simultaneous clients). For CPU-heavy work (big JSON dumps, parsing), add workers and/or push heavy tasks off the main loop.

---

## Performance targets (local ballpark)

- `/telemetry/GetMetric`: **p95 ≲ ~5–7 ms** at ~100 concurrent requests on a laptop-class CPU.
- `/telemetry/ListMetrics`: increases with switch count and fields; consider paging past a few thousand switches.

---

## Limitations (explicit)

- In-memory only (no persistence/history)
- Single latest snapshot per process (no time-series)
- No auth / RBAC
- JSON/CSV only; no Prometheus or streaming yet

---

## Ideas to scale / harden

**Throughput & latency**
- Run multiple **Uvicorn workers**; pin worker count to CPU cores.
- Use **orjson** for faster JSON, **uvloop** for event loop performance.
- **Cache** the `ListMetrics` JSON blob and only rebuild on snapshot changes.
- **Pagination** / server-side filtering to cap payload sizes.
- Pre-parse CSV off the main loop or switch to a **binary wire format** (e.g., protobuf/Arrow).

**Fault tolerance**
- Add **exponential backoff + jitter** on poll failures; cap with a **MAX_STALE_MS** policy (return 503 if data is too old).
- **Circuit breaker** around the upstream to avoid thundering herds after outages.
- Health/readiness endpoints that check **snapshot freshness** (not just liveness).

**Scalability & architecture**
- Make the data server **stateless** and persist snapshots in a shared cache (Redis/Memcached) or object store; have metrics servers read from there.
- **Sharding**: split switches across multiple producers; compose the view in the consumer.
- **Streaming**: add SSE/WebSocket or gRPC streaming to push updates instead of polling.
- Move from CSV to **newline-delimited JSON** or protobuf for lower parse overhead.

**Observability & ops**
- Add **Prometheus** `/metrics` and prebuilt **Grafana** dashboards (poll cadence, staleness, request rate, latency percentiles).
- Structured logs already exist; add **request IDs** and correlate poll → serve.

**Security & policy**
- **Rate limiting** and **auth** (e.g., bearer tokens) on the metrics server.
- Input validation / schema versioning for the CSV.
