import base64
import hashlib
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
    rollout_stage: str = "global",
    canary_gate: dict[str, object] | None = None,
) -> dict[str, object]:
    metadata: dict[str, object] = {
        "version": version,
        "issued_at": "2026-02-28T00:00:00Z",
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


def _bundle_hash(bundle: dict[str, object]) -> str:
    canonical = json.dumps(
        {
            "metadata": bundle["metadata"],
            "payload": bundle["payload"],
            "signatures": bundle["signatures"],
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _write_trust_store(path, key_map: dict[str, Ed25519PrivateKey], min_signatures: int):
    path.write_text(
        json.dumps(
            {
                "policy": {"min_signatures": min_signatures},
                "keys": {
                    kid: {"algorithm": "ed25519", "public_key_b64": _public_key_b64(private_key)}
                    for kid, private_key in key_map.items()
                },
            }
        ),
        encoding="utf-8",
    )


def test_bundle_updater_applies_with_quorum(tmp_path):
    key_a = Ed25519PrivateKey.generate()
    key_b = Ed25519PrivateKey.generate()
    key_c = Ed25519PrivateKey.generate()

    trust_store = tmp_path / "trust.json"
    _write_trust_store(trust_store, {"ctrl-1": key_a, "ctrl-2": key_b, "ctrl-3": key_c}, min_signatures=2)

    bundle = _build_bundle([("ctrl-1", key_a), ("ctrl-2", key_b)], version=1)
    bundle_path = tmp_path / "bundle.json"
    bundle_path.write_text(json.dumps(bundle), encoding="utf-8")

    updater = SignedBundleUpdater(
        trust_store_path=str(trust_store),
        state_path=str(tmp_path / "state.json"),
        keyring_path=str(tmp_path / "ack_keyring.json"),
        pinset_path=str(tmp_path / "pins.json"),
        rollout_policy_path=str(tmp_path / "rollout_policy.json"),
    )

    result = updater.apply_bundle_file(str(bundle_path))

    assert result["applied_version"] == 1
    assert result["rollout_stage"] == "global"


def test_bundle_updater_rejects_when_quorum_missing(tmp_path):
    key_a = Ed25519PrivateKey.generate()
    key_b = Ed25519PrivateKey.generate()

    trust_store = tmp_path / "trust.json"
    _write_trust_store(trust_store, {"ctrl-1": key_a, "ctrl-2": key_b}, min_signatures=2)

    bundle = _build_bundle([("ctrl-1", key_a)], version=2)
    bundle_path = tmp_path / "bundle.json"
    bundle_path.write_text(json.dumps(bundle), encoding="utf-8")

    updater = SignedBundleUpdater(
        trust_store_path=str(trust_store),
        state_path=str(tmp_path / "state.json"),
        keyring_path=str(tmp_path / "ack_keyring.json"),
        pinset_path=str(tmp_path / "pins.json"),
        rollout_policy_path=str(tmp_path / "rollout_policy.json"),
    )

    with pytest.raises(AdapterExecutionError, match="quorum"):
        updater.apply_bundle_file(str(bundle_path))


def test_bundle_updater_enforces_canary_approval_before_global(tmp_path):
    key_a = Ed25519PrivateKey.generate()
    key_b = Ed25519PrivateKey.generate()
    key_c = Ed25519PrivateKey.generate()

    trust_store = tmp_path / "trust.json"
    _write_trust_store(trust_store, {"ctrl-1": key_a, "ctrl-2": key_b, "ctrl-3": key_c}, min_signatures=2)

    updater = SignedBundleUpdater(
        trust_store_path=str(trust_store),
        state_path=str(tmp_path / "state.json"),
        keyring_path=str(tmp_path / "ack_keyring.json"),
        pinset_path=str(tmp_path / "pins.json"),
        rollout_policy_path=str(tmp_path / "rollout_policy.json"),
    )

    canary_bundle = _build_bundle([("ctrl-1", key_a), ("ctrl-2", key_b)], version=3, rollout_stage="canary")
    canary_path = tmp_path / "canary_bundle.json"
    canary_path.write_text(json.dumps(canary_bundle), encoding="utf-8")
    canary_result = updater.apply_bundle_file(str(canary_path))
    canary_hash = str(canary_result["bundle_hash"])

    global_bundle = _build_bundle(
        [("ctrl-2", key_b), ("ctrl-3", key_c)],
        version=4,
        rollout_stage="global",
        canary_gate={"required": True, "source_bundle_hash": canary_hash},
    )
    global_path = tmp_path / "global_bundle.json"
    global_path.write_text(json.dumps(global_bundle), encoding="utf-8")

    with pytest.raises(AdapterExecutionError, match="canary gate"):
        updater.apply_bundle_file(str(global_path))

    updater.approve_canary(canary_hash)
    final_result = updater.apply_bundle_file(str(global_path))
    assert final_result["rollout_stage"] == "global"


def test_bundle_updater_rejects_replay_and_tamper(tmp_path):
    key_a = Ed25519PrivateKey.generate()
    key_b = Ed25519PrivateKey.generate()

    trust_store = tmp_path / "trust.json"
    _write_trust_store(trust_store, {"ctrl-1": key_a, "ctrl-2": key_b}, min_signatures=2)

    bundle = _build_bundle([("ctrl-1", key_a), ("ctrl-2", key_b)], version=5)
    bundle_path = tmp_path / "bundle.json"
    bundle_path.write_text(json.dumps(bundle), encoding="utf-8")

    updater = SignedBundleUpdater(
        trust_store_path=str(trust_store),
        state_path=str(tmp_path / "state.json"),
        keyring_path=str(tmp_path / "ack_keyring.json"),
        pinset_path=str(tmp_path / "pins.json"),
        rollout_policy_path=str(tmp_path / "rollout_policy.json"),
    )

    updater.apply_bundle_file(str(bundle_path))

    with pytest.raises(AdapterExecutionError, match="not newer"):
        updater.apply_bundle_file(str(bundle_path))

    tampered = _build_bundle([("ctrl-1", key_a), ("ctrl-2", key_b)], version=6)
    tampered["payload"]["rollout_policy"]["error_window_size"] = 99
    bundle_path.write_text(json.dumps(tampered), encoding="utf-8")

    with pytest.raises(AdapterExecutionError, match="quorum"):
        updater.apply_bundle_file(str(bundle_path))
