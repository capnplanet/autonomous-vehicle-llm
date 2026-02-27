from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path


@dataclass(slots=True)
class AuditRecord:
    timestamp: str
    event_type: str
    payload: dict[str, str | float | int | bool]
    prev_hash: str
    signature: str


class SignedAuditLogger:
    def __init__(self, file_path: str | Path, secret: str) -> None:
        self.file_path = Path(file_path)
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        self._secret = secret.encode("utf-8")
        self._last_hash = self._load_last_hash()

    def _load_last_hash(self) -> str:
        if not self.file_path.exists():
            return ""
        lines = self.file_path.read_text(encoding="utf-8").splitlines()
        if not lines:
            return ""
        last = json.loads(lines[-1])
        return str(last.get("signature", ""))

    def log(self, event_type: str, payload: dict[str, str | float | int | bool]) -> AuditRecord:
        timestamp = datetime.now(UTC).isoformat()
        canonical_payload = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        content = f"{timestamp}|{event_type}|{canonical_payload}|{self._last_hash}"
        signature = hmac.new(self._secret, content.encode("utf-8"), hashlib.sha256).hexdigest()

        record = AuditRecord(
            timestamp=timestamp,
            event_type=event_type,
            payload=payload,
            prev_hash=self._last_hash,
            signature=signature,
        )

        with self.file_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(asdict(record), separators=(",", ":")) + "\n")

        self._last_hash = signature
        return record
