import asyncio
import csv
import io
import logging
import time

import httpx

from .store import Snapshot, SnapshotMeta, SnapshotStore

class Poller:
    def __init__(self, upstream_url: str, poll_ms: int, store: SnapshotStore):
        self.upstream_url = upstream_url
        self.poll_ms = poll_ms
        self.store = store
        self._log = logging.getLogger(__name__)
        self._client: httpx.AsyncClient | None = None
        self._task: asyncio.Task | None = None
        self._stopping = asyncio.Event()
        self._etag: str | None = None
        self.last_cycle_ms: int | None = None
        self.fail_count: int = 0

    async def start(self):
        self._client = httpx.AsyncClient(timeout=5.0)
        self._task = asyncio.create_task(self._run())

    async def stop(self):
        self._stopping.set()
        if self._task:
            await self._task
        if self._client:
            await self._client.aclose()

    async def _run(self):
        assert self._client is not None
        while not self._stopping.is_set():
            t0 = time.time()
            status = 0
            fetch_ms = parse_ms = apply_ms = 0
            try:
                headers: dict[str, str] = {}
                if self._etag:
                    headers["If-None-Match"] = self._etag
                r = await self._client.get(self.upstream_url, headers=headers)
                status = r.status_code
                fetch_ms = int((time.time() - t0) * 1000)

                if r.status_code == 304:
                    # unchanged
                    apply_ms = 0
                elif r.status_code == 200:
                    csv_text = r.text
                    t_parse = time.time()
                    snap = self._parse_csv(csv_text, r.headers)
                    parse_ms = int((time.time() - t_parse) * 1000)
                    t_apply = time.time()
                    await self.store.set(snap)
                    apply_ms = int((time.time() - t_apply) * 1000)
                    self._etag = r.headers.get("ETag")
                    self.fail_count = 0
                else:
                    self.fail_count += 1
            except Exception as e:
                self.fail_count += 1
                self._log.error(
                    "poll error",
                    extra={"event": "poll.error", "extra_fields": {"error": repr(e)}},
                )
            finally:
                self.last_cycle_ms = int((time.time() - t0) * 1000)
                self._log.info(
                    "poll",
                    extra={
                        "event": "poll.run",
                        "extra_fields": {
                            "status": status,
                            "fetch_ms": fetch_ms,
                            "parse_ms": parse_ms,
                            "apply_ms": apply_ms,
                            "cycle_ms": self.last_cycle_ms,
                            "retry": self.fail_count,
                        },
                    },
                )
                await asyncio.sleep(self.poll_ms / 1000.0)

    def _parse_csv(self, csv_text: str, headers: httpx.Headers) -> Snapshot:
        ts_ms = int(headers.get("X-Snapshot-Ts", "0"))
        etag = headers.get("ETag", "")
        reader = csv.reader(io.StringIO(csv_text))
        first = next(reader)
        if not first or first[0] != "switch_id":
            raise ValueError("CSV header missing 'switch_id'")
        fields: list[str] = first[1:]
        data: dict[str, dict[str, float]] = {}
        for row in reader:
            if not row:
                continue
            sw = row[0]
            vals: dict[str, float] = {}
            for idx, name in enumerate(fields):
                try:
                    vals[name] = float(row[1 + idx])
                except (ValueError, IndexError):
                    vals[name] = 0.0
            data[sw] = vals
        meta = SnapshotMeta(snapshot_id=etag or "0", ts_ms=ts_ms, fields=fields)
        return Snapshot(meta=meta, data=data)
