# Fabric Telemetry

Two services:
- **data_server (Flask, :9001)** → simulates switch metrics; CSV at `/counters`
- **metrics_server (FastAPI, :8080)** → polls `/counters`; serves `/telemetry/GetMetric` & `/telemetry/ListMetrics` (+ optional `/stats`)

## Run (venv)
```bash
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
# data_server: python data_server/app.py
# metrics_server: uvicorn metrics_server.app:app --host 127.0.0.1 --port 8080
