FROM python:3.11-slim
WORKDIR /app

# (optional) SSL/certs
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# copy only the data_server code
COPY data_server/ ./data_server/

EXPOSE 9001
CMD ["gunicorn", "-w", "1", "-b", "0.0.0.0:9001", "data_server.app:create_app()"]
