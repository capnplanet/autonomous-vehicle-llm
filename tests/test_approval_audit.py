import json

import pytest

from autonomy.approval_audit import CanaryApprovalAuditLedger
from autonomy.errors import AdapterExecutionError


def test_approval_audit_chain_and_seal_verify(tmp_path):
    log_path = tmp_path / "approval.log"
    key_path = tmp_path / "approval.key"

    ledger = CanaryApprovalAuditLedger(
        file_path=str(log_path),
        seal_key_path=str(key_path),
        verify_every_writes=1,
    )

    ledger.append("prod", "bundle-a", "ops-1", "first", "pending")
    ledger.append("prod", "bundle-a", "ops-2", "second", "approved")

    result = ledger.verify_chain()
    assert result["records"] == 2
    assert key_path.exists()


def test_approval_audit_detects_tamper(tmp_path):
    log_path = tmp_path / "approval.log"
    key_path = tmp_path / "approval.key"

    ledger = CanaryApprovalAuditLedger(
        file_path=str(log_path),
        seal_key_path=str(key_path),
        verify_every_writes=100,
    )

    ledger.append("prod", "bundle-a", "ops-1", "first", "pending")
    ledger.append("prod", "bundle-a", "ops-2", "second", "approved")

    lines = log_path.read_text(encoding="utf-8").splitlines()
    first = json.loads(lines[0])
    first["reason"] = "tampered"
    lines[0] = json.dumps(first, separators=(",", ":"))
    log_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    with pytest.raises(AdapterExecutionError, match="seal mismatch|record hash mismatch"):
        ledger.verify_chain()


def test_approval_audit_fails_closed_on_startup_if_tampered(tmp_path):
    log_path = tmp_path / "approval.log"
    key_path = tmp_path / "approval.key"

    first_ledger = CanaryApprovalAuditLedger(
        file_path=str(log_path),
        seal_key_path=str(key_path),
        verify_every_writes=10,
    )
    first_ledger.append("prod", "bundle-a", "ops-1", "first", "pending")

    lines = log_path.read_text(encoding="utf-8").splitlines()
    entry = json.loads(lines[0])
    entry["approver"] = "attacker"
    lines[0] = json.dumps(entry, separators=(",", ":"))
    log_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    with pytest.raises(AdapterExecutionError, match="seal mismatch|record hash mismatch"):
        CanaryApprovalAuditLedger(
            file_path=str(log_path),
            seal_key_path=str(key_path),
            verify_every_writes=10,
        )


def test_approval_audit_detects_tamper_before_append(tmp_path):
    log_path = tmp_path / "approval.log"
    key_path = tmp_path / "approval.key"

    ledger = CanaryApprovalAuditLedger(
        file_path=str(log_path),
        seal_key_path=str(key_path),
        verify_every_writes=100,
        verify_before_append=True,
    )
    ledger.append("prod", "bundle-a", "ops-1", "first", "pending")

    lines = log_path.read_text(encoding="utf-8").splitlines()
    entry = json.loads(lines[0])
    entry["reason"] = "tampered-before-append"
    lines[0] = json.dumps(entry, separators=(",", ":"))
    log_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    with pytest.raises(AdapterExecutionError, match="seal mismatch|record hash mismatch"):
        ledger.append("prod", "bundle-a", "ops-2", "second", "approved")
