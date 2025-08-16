# -------- General --------
# Load variables from .env if present (DATA_SWITCHES, POLL_MS, etc.)
-include .env
export

VENV ?= .venv
PY   ?= $(VENV)/bin/python
PIP  ?= $(VENV)/bin/pip
UVICORN ?= $(VENV)/bin/uvicorn

# Defaults for metrics server (override in .env or inline: `make run-metrics UPSTREAM_URL=...`)
UPSTREAM_URL ?= http://127.0.0.1:9001/counters
POLL_MS ?= 1500
LOG_LEVEL ?= INFO

.PHONY: dev deps run-data run-metrics compose clean-venv

# Create venv and install deps
dev: $(VENV)/bin/activate

deps: $(VENV)/bin/activate

$(VENV)/bin/activate:
	python3.11 -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements.txt

# -------- Run (venv) --------
# Data generator (Flask) – run as a package module so relative imports work
run-data: $(VENV)/bin/activate
	$(PY) -m data_server.app

# Metrics API (FastAPI) – uvicorn ASGI server
run-metrics: $(VENV)/bin/activate
	env UPSTREAM_URL="$(UPSTREAM_URL)" POLL_MS="$(POLL_MS)" LOG_LEVEL="$(LOG_LEVEL)" \
	$(UVICORN) metrics_server.app:app --host 127.0.0.1 --port 8080

# -------- Docker Compose --------
compose:
	docker compose up --build

# -------- Misc --------
clean-venv:
	rm -rf $(VENV)
