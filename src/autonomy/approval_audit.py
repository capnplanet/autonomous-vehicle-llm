from __future__ import annotations

import base64
import hmac
import hashlib
import json
import secrets
import time
from pathlib import Path

from .errors import AdapterExecutionError


class CanaryApprovalAuditLedger:
    def __init__(
        self,
        file_path: str,
        seal_key_path: str | None = None,
        verify_every_writes: int = 10,
    ) -> None:
        self.file_path = Path(file_path)
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        self.seal_key_path = Path(seal_key_path) if seal_key_path else self.file_path.with_suffix(".seal.key")
        self.seal_key = self._load_or_create_seal_key(self.seal_key_path)
        self.verify_every_writes = max(1, verify_every_writes)
        self._append_count = self._line_count()

    def append(self, environment: str, bundle_hash: str, approver: str, reason: str, status: str) -> dict[str, object]:
        previous_hash = self._last_hash()
        record: dict[str, object] = {
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
        record["seal"] = self._seal_record(record)

        with self.file_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, separators=(",", ":")) + "\n")

        self._append_count += 1
        if self._append_count % self.verify_every_writes == 0:
            self.verify_chain()

        return record

    def verify_chain(self) -> dict[str, object]:
        if not self.file_path.exists():
            return {"records": 0, "verified_at": time.time()}

        expected_prev_hash = ""
        records = 0
        for line in self.file_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            records += 1
            entry = json.loads(line)
            if not isinstance(entry, dict):
                raise AdapterExecutionError("approval audit entry is invalid")

            prev_hash = str(entry.get("prev_hash", ""))
            if prev_hash != expected_prev_hash:
                raise AdapterExecutionError("approval audit hash chain mismatch")

            actual_record_hash = str(entry.get("record_hash", ""))
            unsigned_entry = dict(entry)
            unsigned_entry.pop("record_hash", None)
            unsigned_entry.pop("seal", None)
            canonical = json.dumps(unsigned_entry, sort_keys=True, separators=(",", ":"))
            expected_record_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
            if actual_record_hash != expected_record_hash:
                raise AdapterExecutionError("approval audit record hash mismatch")

            seal = str(entry.get("seal", ""))
            expected_seal = self._seal_record({**unsigned_entry, "record_hash": actual_record_hash})
            if not hmac.compare_digest(seal, expected_seal):
                raise AdapterExecutionError("approval audit seal mismatch")

            expected_prev_hash = actual_record_hash

        return {"records": records, "verified_at": time.time()}

    def _last_hash(self) -> str:
        if not self.file_path.exists():
            return ""
        lines = self.file_path.read_text(encoding="utf-8").splitlines()
        if not lines:
            return ""
        last = json.loads(lines[-1])
        return str(last.get("record_hash", ""))

    def _seal_record(self, record: dict[str, object]) -> str:
        canonical = json.dumps(record, sort_keys=True, separators=(",", ":"))
        return hmac.new(self.seal_key, canonical.encode("utf-8"), hashlib.sha256).hexdigest()

    def _load_or_create_seal_key(self, path: Path) -> bytes:
        if path.exists():
            raw = path.read_text(encoding="utf-8").strip()
            try:
                return base64.b64decode(raw, validate=True)
            except ValueError as exc:
                raise AdapterExecutionError("invalid approval audit seal key file") from exc

        path.parent.mkdir(parents=True, exist_ok=True)
        key = secrets.token_bytes(32)
        path.write_text(base64.b64encode(key).decode("utf-8"), encoding="utf-8")
        try:
            path.chmod(0o600)
        except OSError:
            pass
        return key

    def _line_count(self) -> int:
        if not self.file_path.exists():
            return 0
        return len([line for line in self.file_path.read_text(encoding="utf-8").splitlines() if line.strip()])
