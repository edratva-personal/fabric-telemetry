import json
import logging
import time

class JsonFormatter(logging.Formatter):
    def __init__(self, service: str):
        super().__init__()
        self.service = service

    def format(self, record: logging.LogRecord) -> str:
        ts = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + f".{int(time.time()*1000)%1000:03d}Z"
        payload = {
            "ts": ts,
            "level": record.levelname,
            "svc": self.service,
            "event": getattr(record, "event", "log"),
            "msg": record.getMessage(),
        }
        for k, v in getattr(record, "extra_fields", {}).items():
            payload[k] = v
        return json.dumps(payload, ensure_ascii=False)

def setup_logging(service_name: str, level_name: str = "INFO"):
    root = logging.getLogger()
    if not root.handlers:
        h = logging.StreamHandler()
        h.setFormatter(JsonFormatter(service_name))
        root.addHandler(h)
    root.setLevel(getattr(logging, level_name.upper(), logging.INFO))
