import base64
import json

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from autonomy.bundle_updater import SignedBundleUpdater
from autonomy.errors import AdapterExecutionError


def _public_key_b64(private_key: Ed25519PrivateKey) -> str:
    raw = private_key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    return base64.b64encode(raw).decode("utf-8")


def _build_payload() -> dict[str, object]:
    return {
        "keyring": {"vendors": {"vendor-x": {"keys": {}, "revoked": [], "active_kid": ""}}},
        "pinset": {"vendors": {"vendor-x": {"allowed": ["sha256:x"], "revoked": []}}},
        "rollout_policy": {"auto_rollback_enabled": True, "error_window_size": 5},
    }


def _build_bundle(
    signers: list[tuple[str, Ed25519PrivateKey]],
    version: int,
    environment: str,
    rollout_stage: str = "global",
    canary_gate: dict[str, object] | None = None,
) -> dict[str, object]:
    metadata: dict[str, object] = {
        "version": version,
        "issued_at": "2026-02-28T00:00:00Z",
        "environment": environment,
        "rollout_stage": rollout_stage,
    }
    if canary_gate is not None:
        metadata["canary_gate"] = canary_gate

    payload = _build_payload()
    canonical = json.dumps({"metadata": metadata, "payload": payload}, sort_keys=True, separators=(",", ":"))
    signatures = [
        {
            "kid": kid,
            "algorithm": "ed25519",
            "value": base64.b64encode(private_key.sign(canonical.encode("utf-8"))).decode("utf-8"),
        }
        for kid, private_key in signers
    ]
    return {"metadata": metadata, "payload": payload, "signatures": signatures}


def _write_trust_store(path, key_map: dict[str, Ed25519PrivateKey]):
    path.write_text(
        json.dumps(
            {
                "policy": {
                    "min_signatures": 1,
                    "environments": {
                        "dev": {"min_signatures": 1, "require_canary_approval": False},
                        "staging": {"min_signatures": 2, "require_canary_approval": True},
                        "prod": {
                            "min_signatures": 3,
                            "require_canary_approval": True,
                            "canary_approval_min_approvers": 2,
                            "canary_min_soak_seconds": 600,
                            "canary_max_error_rate": 0.02,
                        },
                    },
                },
                "keys": {
                    kid: {"algorithm": "ed25519", "public_key_b64": _public_key_b64(private_key)}
                    for kid, private_key in key_map.items()
                },
            }
        ),
        encoding="utf-8",
    )


def test_env_quorum_dev_allows_single_signature(tmp_path):
    key_a = Ed25519PrivateKey.generate()
    key_b = Ed25519PrivateKey.generate()
    key_c = Ed25519PrivateKey.generate()

    trust = tmp_path / "trust.json"
    _write_trust_store(trust, {"ctrl-1": key_a, "ctrl-2": key_b, "ctrl-3": key_c})

    bundle = _build_bundle([("ctrl-1", key_a)], version=1, environment="dev", rollout_stage="global")
    bundle_path = tmp_path / "bundle.json"
    bundle_path.write_text(json.dumps(bundle), encoding="utf-8")

    updater = SignedBundleUpdater(
        trust_store_path=str(trust),
        state_path=str(tmp_path / "state.json"),
        keyring_path=str(tmp_path / "ack_keyring.json"),
        pinset_path=str(tmp_path / "pins.json"),
        rollout_policy_path=str(tmp_path / "rollout_policy.json"),
    )

    result = updater.apply_bundle_file(str(bundle_path))
    assert result["environment"] == "dev"


def test_env_quorum_prod_requires_three_signatures(tmp_path):
    key_a = Ed25519PrivateKey.generate()
    key_b = Ed25519PrivateKey.generate()
    key_c = Ed25519PrivateKey.generate()

    trust = tmp_path / "trust.json"
    _write_trust_store(trust, {"ctrl-1": key_a, "ctrl-2": key_b, "ctrl-3": key_c})

    insufficient = _build_bundle(
        [("ctrl-1", key_a), ("ctrl-2", key_b)],
        version=2,
        environment="prod",
        rollout_stage="global",
    )
    insufficient_path = tmp_path / "insufficient.json"
    insufficient_path.write_text(json.dumps(insufficient), encoding="utf-8")

    updater = SignedBundleUpdater(
        trust_store_path=str(trust),
        state_path=str(tmp_path / "state.json"),
        keyring_path=str(tmp_path / "ack_keyring.json"),
        pinset_path=str(tmp_path / "pins.json"),
        rollout_policy_path=str(tmp_path / "rollout_policy.json"),
    )

    with pytest.raises(AdapterExecutionError, match="quorum"):
        updater.apply_bundle_file(str(insufficient_path))


def test_prod_global_requires_approved_canary_soak_and_metrics(tmp_path):
    key_a = Ed25519PrivateKey.generate()
    key_b = Ed25519PrivateKey.generate()
    key_c = Ed25519PrivateKey.generate()

    trust = tmp_path / "trust.json"
    _write_trust_store(trust, {"ctrl-1": key_a, "ctrl-2": key_b, "ctrl-3": key_c})

    updater = SignedBundleUpdater(
        trust_store_path=str(trust),
        state_path=str(tmp_path / "state.json"),
        keyring_path=str(tmp_path / "ack_keyring.json"),
        pinset_path=str(tmp_path / "pins.json"),
        rollout_policy_path=str(tmp_path / "rollout_policy.json"),
    )

    canary = _build_bundle(
        [("ctrl-1", key_a), ("ctrl-2", key_b), ("ctrl-3", key_c)],
        version=3,
        environment="prod",
        rollout_stage="canary",
    )
    canary_path = tmp_path / "canary.json"
    canary_path.write_text(json.dumps(canary), encoding="utf-8")
    canary_result = updater.apply_bundle_file(str(canary_path))
    canary_hash = str(canary_result["bundle_hash"])

    global_without_metrics = _build_bundle(
        [("ctrl-1", key_a), ("ctrl-2", key_b), ("ctrl-3", key_c)],
        version=4,
        environment="prod",
        rollout_stage="global",
        canary_gate={"required": True, "source_bundle_hash": canary_hash},
    )
    global_path = tmp_path / "global.json"
    global_path.write_text(json.dumps(global_without_metrics), encoding="utf-8")

    first = updater.approve_canary_with_metadata(
        canary_hash,
        environment="prod",
        approver="ops-1",
        reason="canary healthy first review",
    )
    assert first["status"] == "pending"

    second = updater.approve_canary_with_metadata(
        canary_hash,
        environment="prod",
        approver="ops-2",
        reason="second reviewer confirms rollout",
    )
    assert second["status"] == "approved"

    with pytest.raises(AdapterExecutionError, match="soak metrics"):
        updater.apply_bundle_file(str(global_path))

    global_with_bad_metrics = _build_bundle(
        [("ctrl-1", key_a), ("ctrl-2", key_b), ("ctrl-3", key_c)],
        version=5,
        environment="prod",
        rollout_stage="global",
        canary_gate={
            "required": True,
            "source_bundle_hash": canary_hash,
            "observed_soak_seconds": 100,
            "observed_error_rate": 0.03,
        },
    )
    global_path.write_text(json.dumps(global_with_bad_metrics), encoding="utf-8")

    with pytest.raises(AdapterExecutionError, match="soak time"):
        updater.apply_bundle_file(str(global_path))

    global_with_good_metrics = _build_bundle(
        [("ctrl-1", key_a), ("ctrl-2", key_b), ("ctrl-3", key_c)],
        version=6,
        environment="prod",
        rollout_stage="global",
        canary_gate={
            "required": True,
            "source_bundle_hash": canary_hash,
            "observed_soak_seconds": 900,
            "observed_error_rate": 0.01,
        },
    )
    global_path.write_text(json.dumps(global_with_good_metrics), encoding="utf-8")

    result = updater.apply_bundle_file(str(global_path))
    assert result["rollout_stage"] == "global"
    assert result["environment"] == "prod"


def test_prod_canary_approval_requires_distinct_approvers(tmp_path):
    key_a = Ed25519PrivateKey.generate()
    key_b = Ed25519PrivateKey.generate()
    key_c = Ed25519PrivateKey.generate()

    trust = tmp_path / "trust.json"
    _write_trust_store(trust, {"ctrl-1": key_a, "ctrl-2": key_b, "ctrl-3": key_c})

    updater = SignedBundleUpdater(
        trust_store_path=str(trust),
        state_path=str(tmp_path / "state.json"),
        keyring_path=str(tmp_path / "ack_keyring.json"),
        pinset_path=str(tmp_path / "pins.json"),
        rollout_policy_path=str(tmp_path / "rollout_policy.json"),
    )

    canary = _build_bundle(
        [("ctrl-1", key_a), ("ctrl-2", key_b), ("ctrl-3", key_c)],
        version=7,
        environment="prod",
        rollout_stage="canary",
    )
    canary_path = tmp_path / "canary.json"
    canary_path.write_text(json.dumps(canary), encoding="utf-8")
    canary_result = updater.apply_bundle_file(str(canary_path))
    canary_hash = str(canary_result["bundle_hash"])

    pending = updater.approve_canary_with_metadata(
        canary_hash,
        environment="prod",
        approver="ops-1",
        reason="first approval",
    )
    assert pending["status"] == "pending"

    with pytest.raises(AdapterExecutionError, match="already approved"):
        updater.approve_canary_with_metadata(
            canary_hash,
            environment="prod",
            approver="ops-1",
            reason="duplicate approval",
        )

    approved = updater.approve_canary_with_metadata(
        canary_hash,
        environment="prod",
        approver="ops-2",
        reason="second approver",
    )
    assert approved["status"] == "approved"
    assert approved["approved_canary_bundle_hash"] == canary_hash


def test_canary_approval_audit_chain_records_pending_and_approved(tmp_path):
    key_a = Ed25519PrivateKey.generate()
    key_b = Ed25519PrivateKey.generate()
    key_c = Ed25519PrivateKey.generate()

    trust = tmp_path / "trust.json"
    _write_trust_store(trust, {"ctrl-1": key_a, "ctrl-2": key_b, "ctrl-3": key_c})
    approval_log = tmp_path / "approvals.log"

    updater = SignedBundleUpdater(
        trust_store_path=str(trust),
        state_path=str(tmp_path / "state.json"),
        keyring_path=str(tmp_path / "ack_keyring.json"),
        pinset_path=str(tmp_path / "pins.json"),
        rollout_policy_path=str(tmp_path / "rollout_policy.json"),
        approval_audit_path=str(approval_log),
    )

    canary = _build_bundle(
        [("ctrl-1", key_a), ("ctrl-2", key_b), ("ctrl-3", key_c)],
        version=9,
        environment="prod",
        rollout_stage="canary",
    )
    canary_path = tmp_path / "canary.json"
    canary_path.write_text(json.dumps(canary), encoding="utf-8")
    canary_result = updater.apply_bundle_file(str(canary_path))
    canary_hash = str(canary_result["bundle_hash"])

    updater.approve_canary_with_metadata(
        canary_hash,
        environment="prod",
        approver="ops-1",
        reason="first review",
    )
    updater.approve_canary_with_metadata(
        canary_hash,
        environment="prod",
        approver="ops-2",
        reason="second review",
    )

    lines = approval_log.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    first = json.loads(lines[0])
    second = json.loads(lines[1])

    assert first["status"] == "pending"
    assert second["status"] == "approved"
    assert first["record_hash"]
    assert second["prev_hash"] == first["record_hash"]
    assert second["record_hash"]


def test_bundle_updater_rejects_replay_and_tamper(tmp_path):
    key_a = Ed25519PrivateKey.generate()
    key_b = Ed25519PrivateKey.generate()
    key_c = Ed25519PrivateKey.generate()

    trust = tmp_path / "trust.json"
    _write_trust_store(trust, {"ctrl-1": key_a, "ctrl-2": key_b, "ctrl-3": key_c})

    updater = SignedBundleUpdater(
        trust_store_path=str(trust),
        state_path=str(tmp_path / "state.json"),
        keyring_path=str(tmp_path / "ack_keyring.json"),
        pinset_path=str(tmp_path / "pins.json"),
        rollout_policy_path=str(tmp_path / "rollout_policy.json"),
    )

    bundle = _build_bundle(
        [("ctrl-1", key_a), ("ctrl-2", key_b)],
        version=7,
        environment="staging",
        rollout_stage="canary",
    )
    path = tmp_path / "bundle.json"
    path.write_text(json.dumps(bundle), encoding="utf-8")
    updater.apply_bundle_file(str(path))

    with pytest.raises(AdapterExecutionError, match="not newer"):
        updater.apply_bundle_file(str(path))

    tampered = _build_bundle(
        [("ctrl-1", key_a), ("ctrl-2", key_b)],
        version=8,
        environment="staging",
        rollout_stage="canary",
    )
    tampered["payload"]["rollout_policy"]["error_window_size"] = 999
    path.write_text(json.dumps(tampered), encoding="utf-8")

    with pytest.raises(AdapterExecutionError, match="quorum"):
        updater.apply_bundle_file(str(path))
