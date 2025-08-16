import asyncio
import time
from dataclasses import dataclass

@dataclass
class SnapshotMeta:
    snapshot_id: str
    ts_ms: int
    fields: list[str]

@dataclass
class Snapshot:
    meta: SnapshotMeta
    data: dict[str, dict[str, float]]  # switch_id -> metric -> value

class SnapshotStore:
    def __init__(self):
        self._lock = asyncio.Lock()
        self._snap: Snapshot | None = None

    async def set(self, snap: Snapshot) -> None:
        async with self._lock:
            self._snap = snap

    async def get(self) -> Snapshot | None:
        # lock-free read would be okay if we guarantee atomic assignment;
        # here we keep it simple and consistent.
        async with self._lock:
            return self._snap

    async def age_ms(self) -> int | None:
        s = await self.get()
        if not s:
            return None
        return int(time.time() * 1000) - s.meta.ts_ms
