from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path


class CanaryApprovalAuditLedger:
    def __init__(self, file_path: str) -> None:
        self.file_path = Path(file_path)
        self.file_path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, environment: str, bundle_hash: str, approver: str, reason: str, status: str) -> dict[str, object]:
        previous_hash = self._last_hash()
        record = {
            "ts": time.time(),
            "environment": environment,
            "bundle_hash": bundle_hash,
            "approver": approver,
            "reason": reason,
            "status": status,
            "prev_hash": previous_hash,
        }
        canonical = json.dumps(record, sort_keys=True, separators=(",", ":"))
        record_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        record["record_hash"] = record_hash

        with self.file_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, separators=(",", ":")) + "\n")

        return record

    def _last_hash(self) -> str:
        if not self.file_path.exists():
            return ""
        lines = self.file_path.read_text(encoding="utf-8").splitlines()
        if not lines:
            return ""
        last = json.loads(lines[-1])
        return str(last.get("record_hash", ""))
