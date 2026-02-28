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
        canary_keyring_path: str | None = None,
        canary_pinset_path: str | None = None,
    ) -> None:
        self.trust_store_path = Path(trust_store_path)
        self.state_path = Path(state_path)
        self.keyring_path = Path(keyring_path)
        self.pinset_path = Path(pinset_path)
        self.rollout_policy_path = Path(rollout_policy_path)
        self.canary_keyring_path = Path(canary_keyring_path) if canary_keyring_path else self.keyring_path.with_suffix(
            ".canary.json"
        )
        self.canary_pinset_path = Path(canary_pinset_path) if canary_pinset_path else self.pinset_path.with_suffix(
            ".canary.json"
        )

    def apply_bundle_file(self, bundle_path: str) -> dict[str, object]:
        bundle = json.loads(Path(bundle_path).read_text(encoding="utf-8"))
        metadata = bundle.get("metadata")
        payload = bundle.get("payload")
        signatures = self._extract_signatures(bundle)
        if not isinstance(metadata, dict) or not isinstance(payload, dict) or not signatures:
            raise AdapterExecutionError("invalid bundle structure")

        version_raw = metadata.get("version")
        if not isinstance(version_raw, int):
            raise AdapterExecutionError("bundle version missing or invalid")

        state = self._load_state()
        if version_raw <= int(state.get("last_version", 0)):
            raise AdapterExecutionError("bundle version is not newer than current state")

        self._verify_signatures(metadata, payload, signatures)
        bundle_hash = self._compute_bundle_hash(metadata, payload, signatures)

        rollout_stage = str(metadata.get("rollout_stage", "global")).lower()
        if rollout_stage == "canary":
            self._apply_payload(payload, use_canary_targets=True)
            self._update_state(
                metadata=metadata,
                payload=payload,
                signatures=signatures,
                bundle_hash=bundle_hash,
                rollout_stage="canary",
            )
            return {"applied_version": version_raw, "rollout_stage": "canary", "bundle_hash": bundle_hash}

        if rollout_stage == "global":
            self._enforce_canary_gate(metadata, state)
            self._apply_payload(payload, use_canary_targets=False)
            self._update_state(
                metadata=metadata,
                payload=payload,
                signatures=signatures,
                bundle_hash=bundle_hash,
                rollout_stage="global",
            )
            return {"applied_version": version_raw, "rollout_stage": "global", "bundle_hash": bundle_hash}

        raise AdapterExecutionError("unsupported rollout stage")

    def approve_canary(self, bundle_hash: str | None = None) -> dict[str, object]:
        state = self._load_state()
        candidate = bundle_hash or str(state.get("last_canary_bundle_hash", ""))
        if not candidate:
            raise AdapterExecutionError("no canary bundle available for approval")
        state["approved_canary_bundle_hash"] = candidate
        self._write_json(self.state_path, state)
        return {"approved_canary_bundle_hash": candidate}

    def _extract_signatures(self, bundle: dict[str, object]) -> list[dict[str, object]]:
        signatures_raw = bundle.get("signatures")
        if isinstance(signatures_raw, list):
            signatures = [entry for entry in signatures_raw if isinstance(entry, dict)]
            return signatures

        signature_raw = bundle.get("signature")
        if isinstance(signature_raw, dict):
            return [signature_raw]
        return []

    def _verify_signatures(
        self,
        metadata: dict[str, object],
        payload: dict[str, object],
        signatures: list[dict[str, object]],
    ) -> None:
        trust_store = self._load_trust_store()
        keys = trust_store.get("keys", {})
        if not isinstance(keys, dict):
            raise AdapterExecutionError("invalid trust store format")

        policy = trust_store.get("policy", {})
        min_signatures = int(policy.get("min_signatures", 1)) if isinstance(policy, dict) else 1
        min_signatures = max(1, min_signatures)

        signed_content = {
            "metadata": metadata,
            "payload": payload,
        }
        canonical = json.dumps(signed_content, sort_keys=True, separators=(",", ":"))

        verified_kids: set[str] = set()
        for signature in signatures:
            algorithm = str(signature.get("algorithm", ""))
            kid = signature.get("kid")
            sig_value = signature.get("value")
            if algorithm.lower() != "ed25519" or not isinstance(kid, str) or not isinstance(sig_value, str):
                continue
            if kid in verified_kids:
                continue

            descriptor = keys.get(kid)
            if not isinstance(descriptor, dict):
                continue
            key_algo = str(descriptor.get("algorithm", ""))
            public_key_b64 = descriptor.get("public_key_b64")
            if key_algo.lower() != "ed25519" or not isinstance(public_key_b64, str):
                continue

            try:
                public_key = Ed25519PublicKey.from_public_bytes(base64.b64decode(public_key_b64, validate=True))
                signature_bytes = base64.b64decode(sig_value, validate=True)
                public_key.verify(signature_bytes, canonical.encode("utf-8"))
                verified_kids.add(kid)
            except (ValueError, InvalidSignature):
                continue

        if len(verified_kids) < min_signatures:
            raise AdapterExecutionError("bundle signature quorum not satisfied")

    def _enforce_canary_gate(self, metadata: dict[str, object], state: dict[str, object]) -> None:
        gate = metadata.get("canary_gate")
        if not isinstance(gate, dict):
            return
        required = bool(gate.get("required", False))
        if not required:
            return

        source_hash = gate.get("source_bundle_hash")
        if not isinstance(source_hash, str) or not source_hash:
            raise AdapterExecutionError("global rollout missing canary source bundle hash")

        approved_hash = str(state.get("approved_canary_bundle_hash", ""))
        if approved_hash != source_hash:
            raise AdapterExecutionError("canary gate not approved for global rollout")

    def _compute_bundle_hash(
        self,
        metadata: dict[str, object],
        payload: dict[str, object],
        signatures: list[dict[str, object]],
    ) -> str:
        canonical_bundle = json.dumps(
            {
                "metadata": metadata,
                "payload": payload,
                "signatures": signatures,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(canonical_bundle.encode("utf-8")).hexdigest()

    def _apply_payload(self, payload: dict[str, object], use_canary_targets: bool) -> None:
        keyring = payload.get("keyring")
        pinset = payload.get("pinset")
        rollout_policy = payload.get("rollout_policy")

        if isinstance(keyring, dict):
            path = self.canary_keyring_path if use_canary_targets else self.keyring_path
            self._write_json(path, keyring)
        if isinstance(pinset, dict):
            path = self.canary_pinset_path if use_canary_targets else self.pinset_path
            self._write_json(path, pinset)
        if isinstance(rollout_policy, dict) and not use_canary_targets:
            self._write_json(self.rollout_policy_path, rollout_policy)

    def _load_state(self) -> dict[str, object]:
        if not self.state_path.exists():
            return {
                "last_version": 0,
                "last_bundle_hash": "",
                "chain_hash": "",
                "last_canary_bundle_hash": "",
                "approved_canary_bundle_hash": "",
            }
        return json.loads(self.state_path.read_text(encoding="utf-8"))

    def _load_trust_store(self) -> dict[str, object]:
        if not self.trust_store_path.exists():
            raise AdapterExecutionError("bundle trust store file not found")
        return json.loads(self.trust_store_path.read_text(encoding="utf-8"))

    def _update_state(
        self,
        metadata: dict[str, object],
        payload: dict[str, object],
        signatures: list[dict[str, object]],
        bundle_hash: str,
        rollout_stage: str,
    ) -> None:
        prev_state = self._load_state()
        chain_seed = f"{prev_state.get('chain_hash', '')}:{bundle_hash}"
        chain_hash = hashlib.sha256(chain_seed.encode("utf-8")).hexdigest()

        new_state = {
            "last_version": metadata.get("version", 0),
            "last_bundle_hash": bundle_hash,
            "chain_hash": chain_hash,
            "last_canary_bundle_hash": prev_state.get("last_canary_bundle_hash", ""),
            "approved_canary_bundle_hash": prev_state.get("approved_canary_bundle_hash", ""),
        }
        if rollout_stage == "canary":
            new_state["last_canary_bundle_hash"] = bundle_hash
        if rollout_stage == "global":
            new_state["approved_canary_bundle_hash"] = ""

        self._write_json(self.state_path, new_state)

    def _write_json(self, path: Path, value: dict[str, object]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, indent=2), encoding="utf-8")
