FROM python:3.11-slim
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# copy only the metrics_server code
COPY metrics_server/ ./metrics_server/

EXPOSE 8080
CMD ["uvicorn", "metrics_server.app:app", "--host", "0.0.0.0", "--port", "8080"]
