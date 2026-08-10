from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Iterator


class RunState:
    def __init__(self, root: Path) -> None:
        self.root = root

    def was_sent(self, run_date: date) -> bool:
        record = self._record_path(run_date)
        if not record.exists():
            return False
        try:
            return json.loads(record.read_text(encoding="utf-8")).get("status") == "sent"
        except (json.JSONDecodeError, OSError):
            return False

    @contextmanager
    def acquire(self, run_date: date) -> Iterator[None]:
        self.root.mkdir(parents=True, exist_ok=True)
        lock_path = self.root / f"{run_date.isoformat()}.lock"
        try:
            handle = lock_path.open("x", encoding="utf-8")
        except FileExistsError as exc:
            raise RuntimeError("같은 날짜 작업이 이미 실행 중입니다.") from exc
        try:
            handle.write(str(datetime.now(timezone.utc)))
            handle.close()
            yield
        finally:
            handle.close()
            lock_path.unlink(missing_ok=True)

    def mark_sent(
        self,
        run_date: date,
        source_url: str,
        resource_urls: list[str],
        message_hashes: list[str],
    ) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        target = self._record_path(run_date)
        temporary = target.with_suffix(".tmp")
        payload = {
            "status": "sent",
            "sent_at": datetime.now(timezone.utc).isoformat(),
            "source_url": source_url,
            "resource_urls": resource_urls,
            "message_hashes": message_hashes,
        }
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(target)

    def _record_path(self, run_date: date) -> Path:
        return self.root / f"{run_date.isoformat()}.json"

