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


def _build_signed_bundle(private_key: Ed25519PrivateKey, version: int) -> dict[str, object]:
    metadata = {"version": version, "issued_at": "2026-02-28T00:00:00Z"}
    payload = {
        "keyring": {"vendors": {"vendor-x": {"keys": {}, "revoked": [], "active_kid": ""}}},
        "pinset": {"vendors": {"vendor-x": {"allowed": ["sha256:x"], "revoked": []}}},
        "rollout_policy": {"auto_rollback_enabled": True, "error_window_size": 5},
    }
    canonical = json.dumps({"metadata": metadata, "payload": payload}, sort_keys=True, separators=(",", ":"))
    signature = base64.b64encode(private_key.sign(canonical.encode("utf-8"))).decode("utf-8")
    return {
        "metadata": metadata,
        "payload": payload,
        "signature": {
            "kid": "ctrl-1",
            "algorithm": "ed25519",
            "value": signature,
        },
    }


def test_signed_bundle_updater_applies_and_tracks_state(tmp_path):
    private_key = Ed25519PrivateKey.generate()

    trust_store = tmp_path / "trust.json"
    trust_store.write_text(
        json.dumps(
            {
                "keys": {
                    "ctrl-1": {
                        "algorithm": "ed25519",
                        "public_key_b64": _public_key_b64(private_key),
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    bundle_path = tmp_path / "bundle.json"
    bundle_path.write_text(json.dumps(_build_signed_bundle(private_key, version=1)), encoding="utf-8")

    updater = SignedBundleUpdater(
        trust_store_path=str(trust_store),
        state_path=str(tmp_path / "state.json"),
        keyring_path=str(tmp_path / "ack_keyring.json"),
        pinset_path=str(tmp_path / "pins.json"),
        rollout_policy_path=str(tmp_path / "rollout_policy.json"),
    )

    result = updater.apply_bundle_file(str(bundle_path))

    assert result["applied_version"] == 1
    state = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
    assert state["last_version"] == 1
    assert state["chain_hash"]


def test_signed_bundle_updater_rejects_replayed_or_bad_signature(tmp_path):
    private_key = Ed25519PrivateKey.generate()

    trust_store = tmp_path / "trust.json"
    trust_store.write_text(
        json.dumps(
            {
                "keys": {
                    "ctrl-1": {
                        "algorithm": "ed25519",
                        "public_key_b64": _public_key_b64(private_key),
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    bundle = _build_signed_bundle(private_key, version=2)
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

    tampered = _build_signed_bundle(private_key, version=3)
    tampered["payload"]["rollout_policy"]["error_window_size"] = 99
    bundle_path.write_text(json.dumps(tampered), encoding="utf-8")

    with pytest.raises(AdapterExecutionError, match="verification failed"):
        updater.apply_bundle_file(str(bundle_path))
