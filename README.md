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
```bash
python3.11 -m venv .venv && source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt

# Terminal A — data server
python -m data_server.app

# Terminal B — metrics server
UPSTREAM_URL=http://127.0.0.1:9001/counters uvicorn metrics_server.app:app --host 0.0.0.0 --port 8080

# Try it
curl -s http://127.0.0.1:8080/health
curl -s http://127.0.0.1:8080/telemetry/ListMetrics | jq '.fields, .items[0]'
curl -s 'http://127.0.0.1:8080/telemetry/GetMetric?switch_id=sw-000&metric=cpu_util_pct' | jq
```

### Docker (Compose v2)
```bash
docker compose up --build
# Try it from host
curl -s http://127.0.0.1:8080/health
```

> Inside Compose, the metrics server uses `UPSTREAM_URL=http://data-server:9001/counters`.

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

Fault injection knobs:
- `FAULT_500_PCT` → percentage of requests to fail with 500
- `FAULT_SLOW_MS` → extra latency on ~20% of requests

### Data handling & REST server (consumer)

The **metrics_server** runs an async poller:
- Uses `If-None-Match` to avoid re-downloading unchanged data (sees **304** quickly)
- Parses CSV, builds `{ switch_id -> { metric -> value } }`
- Swaps in a new in-memory **Snapshot** atomically (protected by an `asyncio.Lock`)
- On errors, continues serving the **last good snapshot** (with increasing staleness)

API endpoints:
- `GET /telemetry/ListMetrics` → full table (flattened list of rows)
- `GET /telemetry/GetMetric?switch_id=&metric=` → single value
- `GET /stats` → p50/p95/p99/max per endpoint + poller timing/retry counters
- `GET /health` → liveness

Both servers log structured **NDJSON** to stdout (see Observability below).

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

## Configuration

Copy `.env.example` → `.env` and adjust if desired. Common knobs:

**Data server**
- `DATA_SWITCHES` (64) — number of switches
- `DATA_INTERVAL_SEC` (10) — generation period
- `FAULT_500_PCT` (0), `FAULT_SLOW_MS` (0) — fault injection
- `PORT` (9001)

**Metrics server**
- `UPSTREAM_URL` (`http://127.0.0.1:9001/counters` or `http://data-server:9001/counters` in Docker)
- `POLL_MS` (1500) — poll cadence (**<** data interval for steady 200/304 pattern)
- `LOG_LEVEL` (INFO)
- `PORT` (8080)

> Simplicity note: config is parsed with tiny helpers (e.g., `int_env`) and minimal checks. In production, you’d wrap config in a `dataclass` or **Pydantic `BaseSettings`** for stricter typing/validation and better docs.

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

## Running & development

### Makefile shortcuts
```bash
make dev          # create .venv & install deps
make run-data     # start data_server locally
make run-metrics  # start metrics_server locally
```

### Docker hot-reload (optional, dev)
Add `docker-compose.override.yml`:
```yaml
services:
  data-server:
    volumes: [ "./data_server:/app/data_server" ]
    command: >
      gunicorn --reload -b 0.0.0.0:9001 data_server.app:create_app()
  metrics-server:
    volumes: [ "./metrics_server:/app/metrics_server" ]
    command: >
      uvicorn metrics_server.app:app --host 0.0.0.0 --port 8080 --reload
```
Then `docker compose up` will hot-reload on `.py` changes.

---

## Performance notes

- Goals (local): `/telemetry/GetMetric` p95 ≲ ~5–7ms at ~100 concurrent requests; keep serving during upstream hiccups (with increasing `X-Data-Age-Ms`).
- Use `/stats` for a quick view; for load, `hey` or `wrk` scripts can be added later.

---

## Limitations (explicit)

- In-memory only (no persistence/history)
- Single latest snapshot per process (no time-series)
- No auth / RBAC
- JSON/CSV only; no Prometheus or streaming yet

---

## Ideas to scale / harden

- **Throughput:** multi-worker (`uvicorn --workers N`), `uvloop`, `orjson`; parse CSV off-loop.
- **Fault tolerance:** backoff with jitter on poll failures; circuit breaker; `MAX_STALE_MS` policy.
- **Scalability:** stateless metrics servers behind a LB; shared cache (Redis); sharding; pagination; Prometheus `/metrics`; Grafana dashboards; SSE/WebSocket for near-real-time.

---

## Submission notes

- **This repo is private.** Add reviewers as collaborators.
- The top of this README includes **exact run instructions**; you can also paste the “Reviewer quickstart” section in your submission email for convenience.
