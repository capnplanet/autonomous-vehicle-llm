from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from .errors import AdapterExecutionError


class SignedBundleUpdater:
    def __init__(
        self,
        trust_store_path: str,
        state_path: str,
        keyring_path: str,
        pinset_path: str,
        rollout_policy_path: str,
    ) -> None:
        self.trust_store_path = Path(trust_store_path)
        self.state_path = Path(state_path)
        self.keyring_path = Path(keyring_path)
        self.pinset_path = Path(pinset_path)
        self.rollout_policy_path = Path(rollout_policy_path)

    def apply_bundle_file(self, bundle_path: str) -> dict[str, object]:
        bundle = json.loads(Path(bundle_path).read_text(encoding="utf-8"))
        metadata = bundle.get("metadata")
        payload = bundle.get("payload")
        signature = bundle.get("signature")
        if not isinstance(metadata, dict) or not isinstance(payload, dict) or not isinstance(signature, dict):
            raise AdapterExecutionError("invalid bundle structure")

        version_raw = metadata.get("version")
        if not isinstance(version_raw, int):
            raise AdapterExecutionError("bundle version missing or invalid")

        state = self._load_state()
        if version_raw <= int(state.get("last_version", 0)):
            raise AdapterExecutionError("bundle version is not newer than current state")

        self._verify_signature(metadata, payload, signature)
        self._apply_payload(payload)
        self._update_state(metadata, payload, signature)
        return {"applied_version": version_raw}

    def _verify_signature(
        self,
        metadata: dict[str, object],
        payload: dict[str, object],
        signature: dict[str, object],
    ) -> None:
        algorithm = str(signature.get("algorithm", ""))
        if algorithm.lower() != "ed25519":
            raise AdapterExecutionError("unsupported bundle signature algorithm")

        kid = signature.get("kid")
        sig_value = signature.get("value")
        if not isinstance(kid, str) or not isinstance(sig_value, str):
            raise AdapterExecutionError("bundle signature metadata missing")

        trust_store = self._load_trust_store()
        keys = trust_store.get("keys", {})
        descriptor = keys.get(kid) if isinstance(keys, dict) else None
        if not isinstance(descriptor, dict):
            raise AdapterExecutionError("unknown bundle signing key id")

        key_algo = str(descriptor.get("algorithm", ""))
        if key_algo.lower() != "ed25519":
            raise AdapterExecutionError("unsupported trust store key algorithm")

        public_key_b64 = descriptor.get("public_key_b64")
        if not isinstance(public_key_b64, str):
            raise AdapterExecutionError("trust store key is missing public key")

        signed_content = {
            "metadata": metadata,
            "payload": payload,
        }
        canonical = json.dumps(signed_content, sort_keys=True, separators=(",", ":"))

        try:
            public_key = Ed25519PublicKey.from_public_bytes(base64.b64decode(public_key_b64, validate=True))
            signature_bytes = base64.b64decode(sig_value, validate=True)
            public_key.verify(signature_bytes, canonical.encode("utf-8"))
        except (ValueError, InvalidSignature) as exc:
            raise AdapterExecutionError("bundle signature verification failed") from exc

    def _apply_payload(self, payload: dict[str, object]) -> None:
        keyring = payload.get("keyring")
        pinset = payload.get("pinset")
        rollout_policy = payload.get("rollout_policy")

        if isinstance(keyring, dict):
            self._write_json(self.keyring_path, keyring)
        if isinstance(pinset, dict):
            self._write_json(self.pinset_path, pinset)
        if isinstance(rollout_policy, dict):
            self._write_json(self.rollout_policy_path, rollout_policy)

    def _load_state(self) -> dict[str, object]:
        if not self.state_path.exists():
            return {"last_version": 0, "last_bundle_hash": "", "chain_hash": ""}
        return json.loads(self.state_path.read_text(encoding="utf-8"))

    def _load_trust_store(self) -> dict[str, object]:
        if not self.trust_store_path.exists():
            raise AdapterExecutionError("bundle trust store file not found")
        return json.loads(self.trust_store_path.read_text(encoding="utf-8"))

    def _update_state(
        self,
        metadata: dict[str, object],
        payload: dict[str, object],
        signature: dict[str, object],
    ) -> None:
        prev_state = self._load_state()
        canonical_bundle = json.dumps(
            {
                "metadata": metadata,
                "payload": payload,
                "signature": signature,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        bundle_hash = hashlib.sha256(canonical_bundle.encode("utf-8")).hexdigest()
        chain_seed = f"{prev_state.get('chain_hash', '')}:{bundle_hash}"
        chain_hash = hashlib.sha256(chain_seed.encode("utf-8")).hexdigest()

        new_state = {
            "last_version": metadata.get("version", 0),
            "last_bundle_hash": bundle_hash,
            "chain_hash": chain_hash,
        }
        self._write_json(self.state_path, new_state)

    def _write_json(self, path: Path, value: dict[str, object]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, indent=2), encoding="utf-8")
