from __future__ import annotations

import json
from pathlib import Path

from .models import (
    AckConfig,
    AuthRotationConfig,
    CertAttestationConfig,
    IdempotencyConfig,
    PolicyConfig,
    RetryPolicy,
    RolloutPolicyConfig,
    TlsConfig,
    TransportConfig,
)


def load_policy_config(file_path: str | Path) -> PolicyConfig:
    path = Path(file_path)
    data = json.loads(path.read_text(encoding="utf-8"))
    return PolicyConfig(
        max_speed_mps=float(data.get("max_speed_mps", 8.0)),
        min_battery_for_motion_pct=float(data.get("min_battery_for_motion_pct", 25.0)),
        geofence_abs_xy_limit_m=float(data.get("geofence_abs_xy_limit_m", 100.0)),
    )


def load_transport_config(file_path: str | Path) -> TransportConfig:
    path = Path(file_path)
    data = json.loads(path.read_text(encoding="utf-8"))

    retry_data = data.get("retry", {})
    retry = RetryPolicy(
        max_attempts=int(retry_data.get("max_attempts", 3)),
        backoff_s=float(retry_data.get("backoff_s", 0.2)),
    )

    auth_data = data.get("auth", {})
    auth = AuthRotationConfig(
        static_token=auth_data.get("static_token"),
        rotating_tokens=list(auth_data.get("rotating_tokens", [])),
        rotate_every_requests=max(1, int(auth_data.get("rotate_every_requests", 1))),
    )

    tls_data = data.get("tls", {})
    tls = TlsConfig(
        enabled=bool(tls_data.get("enabled", True)),
        verify_peer=bool(tls_data.get("verify_peer", True)),
        ca_cert_path=tls_data.get("ca_cert_path"),
        client_cert_path=tls_data.get("client_cert_path"),
        client_key_path=tls_data.get("client_key_path"),
    )

    ack_data = data.get("ack", {})
    ack = AckConfig(
        required=bool(ack_data.get("required", True)),
        command_id_field=str(ack_data.get("command_id_field", "command_id")),
        ack_id_field=str(ack_data.get("ack_id_field", "command_id")),
        require_nonce=bool(ack_data.get("require_nonce", True)),
        nonce_field=str(ack_data.get("nonce_field", "ack_nonce")),
        nonce_window=max(1, int(ack_data.get("nonce_window", 1000))),
        require_signature=bool(ack_data.get("require_signature", True)),
        signature_field=str(ack_data.get("signature_field", "ack_signature")),
        signature_algorithm=str(ack_data.get("signature_algorithm", "ed25519")),
        signature_encoding=str(ack_data.get("signature_encoding", "base64")),
        key_id_field=str(ack_data.get("key_id_field", "ack_kid")),
        vendor_field=str(ack_data.get("vendor_field", "vendor_id")),
        keyring_path=str(ack_data.get("keyring_path", "config/ack_keyring.json")),
    )

    idem_data = data.get("idempotency", {})
    idempotency = IdempotencyConfig(
        enabled=bool(idem_data.get("enabled", True)),
        key_ttl_s=float(idem_data.get("key_ttl_s", 300.0)),
        store_path=str(idem_data.get("store_path", "logs/command_ledger.db")),
    )

    cert_data = data.get("cert_attestation", {})
    cert_attestation = CertAttestationConfig(
        required=bool(cert_data.get("required", True)),
        fingerprint_field=str(cert_data.get("fingerprint_field", "mtls_cert_fingerprint")),
        pinset_path=str(cert_data.get("pinset_path", "config/vendor_cert_pins.json")),
    )

    rollout_data = data.get("rollout_policy", {})
    rollout_path_raw = rollout_data.get("rollout_policy_path")
    if isinstance(rollout_path_raw, str):
        rollout_path = Path(rollout_path_raw)
        if rollout_path.exists():
            rollout_data = json.loads(rollout_path.read_text(encoding="utf-8"))

    rollout_policy = RolloutPolicyConfig(
        auto_rollback_enabled=bool(rollout_data.get("auto_rollback_enabled", True)),
        error_window_size=max(1, int(rollout_data.get("error_window_size", 20))),
        error_rate_threshold=float(rollout_data.get("error_rate_threshold", 0.4)),
        min_samples=max(1, int(rollout_data.get("min_samples", 5))),
        rollback_cooldown_s=float(rollout_data.get("rollback_cooldown_s", 30.0)),
    )

    return TransportConfig(
        endpoint_url=str(data["endpoint_url"]),
        timeout_s=float(data.get("timeout_s", 1.0)),
        auth=auth,
        tls=tls,
        ack=ack,
        cert_attestation=cert_attestation,
        rollout_policy=rollout_policy,
        idempotency=idempotency,
        retry=retry,
    )
