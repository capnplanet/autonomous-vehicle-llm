from __future__ import annotations

import base64
import hashlib
import json
import time
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from .approval_audit import CanaryApprovalAuditLedger
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
        approval_audit_path: str | None = None,
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
        default_audit_path = self.state_path.with_name("canary_approval_audit.log")
        self.approval_audit = CanaryApprovalAuditLedger(str(approval_audit_path or default_audit_path))

    def apply_bundle_file(self, bundle_path: str) -> dict[str, object]:
        bundle = json.loads(Path(bundle_path).read_text(encoding="utf-8"))
        metadata = bundle.get("metadata")
        payload = bundle.get("payload")
        signatures = self._extract_signatures(bundle)
        if not isinstance(metadata, dict) or not isinstance(payload, dict) or not signatures:
            raise AdapterExecutionError("invalid bundle structure")

        environment = str(metadata.get("environment", "dev")).lower()

        version_raw = metadata.get("version")
        if not isinstance(version_raw, int):
            raise AdapterExecutionError("bundle version missing or invalid")

        state = self._load_state()
        if version_raw <= int(state.get("last_version", 0)):
            raise AdapterExecutionError("bundle version is not newer than current state")

        trust_store = self._load_trust_store()
        env_policy = self._environment_policy(trust_store, environment)

        self._verify_signatures(
            metadata=metadata,
            payload=payload,
            signatures=signatures,
            trust_store=trust_store,
            min_signatures=env_policy["min_signatures"],
        )
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
                environment=environment,
            )
            return {
                "applied_version": version_raw,
                "rollout_stage": "canary",
                "environment": environment,
                "bundle_hash": bundle_hash,
            }

        if rollout_stage == "global":
            self._enforce_canary_gate(metadata, state, environment, env_policy)
            self._apply_payload(payload, use_canary_targets=False)
            self._update_state(
                metadata=metadata,
                payload=payload,
                signatures=signatures,
                bundle_hash=bundle_hash,
                rollout_stage="global",
                environment=environment,
            )
            return {
                "applied_version": version_raw,
                "rollout_stage": "global",
                "environment": environment,
                "bundle_hash": bundle_hash,
            }

        raise AdapterExecutionError("unsupported rollout stage")

    def approve_canary(self, bundle_hash: str | None = None, environment: str = "dev") -> dict[str, object]:
        return self.approve_canary_with_metadata(bundle_hash=bundle_hash, environment=environment)

    def approve_canary_with_metadata(
        self,
        bundle_hash: str | None = None,
        environment: str = "dev",
        approver: str = "system",
        reason: str = "",
    ) -> dict[str, object]:
        state = self._load_state()
        env = environment.lower()
        trust_store = self._load_trust_store()
        env_policy = self._environment_policy(trust_store, env)
        env_state = self._environment_state(state, env)

        candidate = bundle_hash or str(env_state.get("last_canary_bundle_hash", ""))
        if not candidate:
            raise AdapterExecutionError("no canary bundle available for approval")

        required_approvers = max(1, int(env_policy.get("canary_approval_min_approvers", 1)))
        pending = env_state.get("pending_approvals", [])
        if not isinstance(pending, list):
            pending = []

        pending_for_bundle = [
            entry
            for entry in pending
            if isinstance(entry, dict) and str(entry.get("bundle_hash", "")) == candidate
        ]
        existing_approvers = {str(entry.get("approver", "")) for entry in pending_for_bundle}
        if approver in existing_approvers:
            raise AdapterExecutionError("approver has already approved this canary bundle")

        new_approval = {
            "bundle_hash": candidate,
            "approver": approver,
            "reason": reason,
            "approved_at": time.time(),
        }
        pending.append(new_approval)
        pending_for_bundle.append(new_approval)

        unique_approvers = {str(entry.get("approver", "")) for entry in pending_for_bundle if entry.get("approver")}
        status = "pending"
        if len(unique_approvers) >= required_approvers:
            env_state["approved_canary_bundle_hash"] = candidate
            env_state["approved_at"] = time.time()
            env_state["approved_by"] = sorted(unique_approvers)
            pending = [
                entry
                for entry in pending
                if not (isinstance(entry, dict) and str(entry.get("bundle_hash", "")) == candidate)
            ]
            status = "approved"

        env_state["pending_approvals"] = pending
        self._set_environment_state(state, env, env_state)
        self._write_json(self.state_path, state)

        self.approval_audit.append(
            environment=env,
            bundle_hash=candidate,
            approver=approver,
            reason=reason,
            status=status,
        )

        return {
            "approved_canary_bundle_hash": candidate if status == "approved" else None,
            "environment": env,
            "status": status,
            "required_approvers": required_approvers,
            "current_approvers": sorted(unique_approvers),
        }

    def _extract_signatures(self, bundle: dict[str, object]) -> list[dict[str, object]]:
        signatures_raw = bundle.get("signatures")
        if isinstance(signatures_raw, list):
            return [entry for entry in signatures_raw if isinstance(entry, dict)]

        signature_raw = bundle.get("signature")
        if isinstance(signature_raw, dict):
            return [signature_raw]
        return []

    def _environment_policy(self, trust_store: dict[str, object], environment: str) -> dict[str, object]:
        policy = trust_store.get("policy", {})
        if not isinstance(policy, dict):
            policy = {}

        default_min = max(1, int(policy.get("min_signatures", 1)))
        env_config = {}
        envs = policy.get("environments", {})
        if isinstance(envs, dict):
            candidate = envs.get(environment, {})
            if isinstance(candidate, dict):
                env_config = candidate

        return {
            "min_signatures": max(1, int(env_config.get("min_signatures", default_min))),
            "require_canary_approval": bool(env_config.get("require_canary_approval", False)),
            "canary_min_soak_seconds": float(env_config.get("canary_min_soak_seconds", 0)),
            "canary_max_error_rate": float(env_config.get("canary_max_error_rate", 1.0)),
            "canary_approval_min_approvers": max(1, int(env_config.get("canary_approval_min_approvers", 1))),
        }

    def _verify_signatures(
        self,
        metadata: dict[str, object],
        payload: dict[str, object],
        signatures: list[dict[str, object]],
        trust_store: dict[str, object],
        min_signatures: int,
    ) -> None:
        keys = trust_store.get("keys", {})
        if not isinstance(keys, dict):
            raise AdapterExecutionError("invalid trust store format")

        signed_content = {"metadata": metadata, "payload": payload}
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

    def _enforce_canary_gate(
        self,
        metadata: dict[str, object],
        state: dict[str, object],
        environment: str,
        env_policy: dict[str, object],
    ) -> None:
        gate_raw = metadata.get("canary_gate")
        gate = gate_raw if isinstance(gate_raw, dict) else {}

        required_by_metadata = bool(gate.get("required", False))
        required_by_policy = bool(env_policy.get("require_canary_approval", False))
        if not required_by_metadata and not required_by_policy:
            return

        source_hash = gate.get("source_bundle_hash")
        if not isinstance(source_hash, str) or not source_hash:
            raise AdapterExecutionError("global rollout missing canary source bundle hash")

        env_state = self._environment_state(state, environment)
        approved_hash = str(env_state.get("approved_canary_bundle_hash", ""))
        if approved_hash != source_hash:
            raise AdapterExecutionError("canary gate not approved for global rollout")

        min_soak = float(env_policy.get("canary_min_soak_seconds", 0.0))
        max_error_rate = float(env_policy.get("canary_max_error_rate", 1.0))
        if min_soak > 0 or max_error_rate < 1.0:
            soak_seconds = gate.get("observed_soak_seconds")
            error_rate = gate.get("observed_error_rate")
            if soak_seconds is None or error_rate is None:
                raise AdapterExecutionError("production global rollout requires canary soak metrics")
            if float(soak_seconds) < min_soak:
                raise AdapterExecutionError("canary soak time below required threshold")
            if float(error_rate) > max_error_rate:
                raise AdapterExecutionError("canary error rate above allowed threshold")

    def _compute_bundle_hash(
        self,
        metadata: dict[str, object],
        payload: dict[str, object],
        signatures: list[dict[str, object]],
    ) -> str:
        canonical_bundle = json.dumps(
            {"metadata": metadata, "payload": payload, "signatures": signatures},
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
                "environments": {},
            }
        state = json.loads(self.state_path.read_text(encoding="utf-8"))
        if "environments" not in state:
            state["environments"] = {}
        return state

    def _load_trust_store(self) -> dict[str, object]:
        if not self.trust_store_path.exists():
            raise AdapterExecutionError("bundle trust store file not found")
        return json.loads(self.trust_store_path.read_text(encoding="utf-8"))

    def _environment_state(self, state: dict[str, object], environment: str) -> dict[str, object]:
        envs = state.get("environments", {})
        if not isinstance(envs, dict):
            envs = {}
            state["environments"] = envs
        env_state = envs.get(environment)
        if not isinstance(env_state, dict):
            env_state = {
                "last_canary_bundle_hash": "",
                "approved_canary_bundle_hash": "",
                "approved_at": None,
                "last_canary_applied_at": None,
                "approved_by": [],
                "pending_approvals": [],
            }
            envs[environment] = env_state
        return env_state

    def _set_environment_state(self, state: dict[str, object], environment: str, env_state: dict[str, object]) -> None:
        envs = state.get("environments", {})
        if not isinstance(envs, dict):
            envs = {}
            state["environments"] = envs
        envs[environment] = env_state

    def _update_state(
        self,
        metadata: dict[str, object],
        payload: dict[str, object],
        signatures: list[dict[str, object]],
        bundle_hash: str,
        rollout_stage: str,
        environment: str,
    ) -> None:
        prev_state = self._load_state()
        chain_seed = f"{prev_state.get('chain_hash', '')}:{bundle_hash}"
        chain_hash = hashlib.sha256(chain_seed.encode("utf-8")).hexdigest()

        new_state = {
            "last_version": metadata.get("version", 0),
            "last_bundle_hash": bundle_hash,
            "chain_hash": chain_hash,
            "environments": prev_state.get("environments", {}),
        }

        env_state = self._environment_state(new_state, environment)
        if rollout_stage == "canary":
            env_state["last_canary_bundle_hash"] = bundle_hash
            env_state["last_canary_applied_at"] = time.time()
        if rollout_stage == "global":
            env_state["approved_canary_bundle_hash"] = ""
            env_state["approved_at"] = None
            env_state["approved_by"] = []

        self._set_environment_state(new_state, environment, env_state)
        self._write_json(self.state_path, new_state)

    def _write_json(self, path: Path, value: dict[str, object]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, indent=2), encoding="utf-8")
