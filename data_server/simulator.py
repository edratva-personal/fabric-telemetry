import math
import random
from time import time

MetricRow = dict[str, float]
Snapshot  = tuple[int, int, list[str], dict[str, MetricRow]]  # (snapshot_id, ts_ms, fields, rows)

def _fmt_id(i: int) -> str:
    return f"sw-{i:03d}"

def _poisson_small(lam: float) -> int:
    """Return a small non-negative count (≈ Poisson for small lambda)."""
    L = math.exp(-lam)
    k = 0
    p = 1.0
    while p > L:
        k += 1
        p *= random.random()
    return max(0, k - 1)

def _clip(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))

def generate_snapshot(n_switches: int, prev_id: int) -> Snapshot:
    """
    Generate a synthetic telemetry snapshot with 8 metrics:
      - bandwidth_gbps: ~N(120,15), clipped ≥0
      - latency_us: ~N(10,2) with 3% spikes (50–150), clipped ≥1
      - packet_errors: small Poisson with 1% bursts (5–30)
      - cpu_util_pct: ~N(35,10) with 5% spikes (80–100), clip 0–100
      - mem_util_pct: ~N(60,15), clip 0–100
      - buffer_occupancy_pct: ~N(30,15) with 8% microbursts (70–100), clip 0–100
      - egress_drops_per_s: mostly small Poisson(1.0), 2% bursts (100–1000)
      - temperature_c: ~N(45,3) + 0.06*cpu_util_pct, clip 30–90
    """
    snapshot_id = prev_id + 1
    ts_ms = int(time() * 1000)

    fields = [
        "bandwidth_gbps",
        "latency_us",
        "packet_errors",
        "cpu_util_pct",
        "mem_util_pct",
        "buffer_occupancy_pct",
        "egress_drops_per_s",
        "temperature_c",
    ]

    rows: dict[str, MetricRow] = {}
    for i in range(n_switches):
        # 1) Bandwidth
        bw = max(0.0, random.gauss(120.0, 15.0))

        # 2) Latency with occasional spikes
        if random.random() < 0.03:
            lat = random.uniform(50.0, 150.0)
        else:
            lat = max(1.0, random.gauss(10.0, 2.0))

        # 3) Packet errors: mostly tiny counts, rare bursts
        if random.random() < 0.01:
            pkt_errs = random.randint(5, 30)
        else:
            pkt_errs = _poisson_small(0.6)

        # 4) CPU utilization with occasional high spikes
        if random.random() < 0.05:
            cpu = random.uniform(80.0, 100.0)
        else:
            cpu = _clip(random.gauss(35.0, 10.0), 0.0, 100.0)

        # 5) Memory utilization
        mem = _clip(random.gauss(60.0, 15.0), 0.0, 100.0)

        # 6) Buffer occupancy with microbursts
        if random.random() < 0.08:
            buf = random.uniform(70.0, 100.0)
        else:
            buf = _clip(random.gauss(30.0, 15.0), 0.0, 100.0)

        # 7) Egress drops: correlate a bit with high buffers, but keep it simple
        if random.random() < 0.02:
            drops = random.uniform(100.0, 1000.0)
        else:
            lam = 1.0 + (buf / 100.0) * 0.5
            drops = float(_poisson_small(lam))

        # 8) Temperature correlates with CPU a bit
        temp = _clip(random.gauss(45.0, 3.0) + 0.06 * cpu, 30.0, 90.0)

        rows[_fmt_id(i)] = {
            "bandwidth_gbps": round(bw, 2),
            "latency_us": round(lat, 2),
            "packet_errors": float(pkt_errs),
            "cpu_util_pct": round(cpu, 2),
            "mem_util_pct": round(mem, 2),
            "buffer_occupancy_pct": round(buf, 2),
            "egress_drops_per_s": round(drops, 2),
            "temperature_c": round(temp, 2),
        }

    return (snapshot_id, ts_ms, fields, rows)
