.PHONY: dev run-data run-metrics compose

dev:
\tpython3.11 -m venv .venv && . .venv/bin/activate && pip install --upgrade pip -r requirements.txt

run-data:
\t. .venv/bin/activate && python data_server/app.py

run-metrics:
\t. .venv/bin/activate && uvicorn metrics_server.app:app --host 127.0.0.1 --port 8080

compose:
\tdocker compose up --build
