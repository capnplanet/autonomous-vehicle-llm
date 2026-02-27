import json
from pathlib import Path

from autonomy.audit import SignedAuditLogger


def test_signed_audit_logger_chains_records(tmp_path: Path):
    log_path = tmp_path / "audit.log"
    logger = SignedAuditLogger(file_path=log_path, secret="test-secret")

    first = logger.log("exec", {"vehicle_id": "v1", "detail": "arm"})
    second = logger.log("exec", {"vehicle_id": "v1", "detail": "move"})

    assert first.signature
    assert second.prev_hash == first.signature

    lines = log_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert json.loads(lines[1])["prev_hash"] == first.signature
