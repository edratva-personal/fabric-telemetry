import math
from collections import deque

class RollingStats:
    """Keep last N latencies (ms) per endpoint and compute p50/p95/p99 on demand."""
    def __init__(self, capacity: int = 1000):
        self.capacity = capacity
        self.map: dict[str, deque[int]] = {}

    def add(self, key: str, latency_ms: int):
        dq = self.map.setdefault(key, deque(maxlen=self.capacity))
        dq.append(latency_ms)

    def percentiles(self, key: str) -> dict[str, float]:
        dq = self.map.get(key, deque())
        if not dq:
            return {"p50": 0.0, "p95": 0.0, "p99": 0.0, "max": 0.0, "count": 0}
        arr = sorted(dq)
        n = len(arr)

        def pick(p: float) -> float:
            if n == 0:
                return 0.0
            idx = max(0, min(n - 1, math.ceil(p * n) - 1))
            return float(arr[idx])

        return {
            "p50": pick(0.50),
            "p95": pick(0.95),
            "p99": pick(0.99),
            "max": float(arr[-1]),
            "count": n,
        }
