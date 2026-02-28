from pathlib import Path

from autonomy.policy import load_policy_config, load_transport_config


def test_load_policy_config(tmp_path: Path):
    path = tmp_path / "policy.json"
    path.write_text(
        '{"max_speed_mps": 6, "min_battery_for_motion_pct": 40, "geofence_abs_xy_limit_m": 80}',
        encoding="utf-8",
    )

    cfg = load_policy_config(path)

    assert cfg.max_speed_mps == 6
    assert cfg.min_battery_for_motion_pct == 40
    assert cfg.geofence_abs_xy_limit_m == 80


def test_load_transport_config(tmp_path: Path):
    path = tmp_path / "transport.json"
    path.write_text(
        """
        {
            "endpoint_url": "https://vendor.example",
            "timeout_s": 0.5,
            "auth": {
                "rotating_tokens": ["a", "b"],
                "rotate_every_requests": 2
            },
            "tls": {
                "enabled": true,
                "verify_peer": false
            },
            "ack": {
                "required": true,
                "command_id_field": "cmd_id",
                "ack_id_field": "ack.command_id",
                "require_nonce": true,
                "nonce_field": "ack_nonce",
                "nonce_window": 50,
                "require_signature": true,
                "signature_field": "ack_sig",
                "signature_algorithm": "ed25519",
                "signature_encoding": "base64",
                "key_id_field": "kid",
                "vendor_field": "vendor",
                "keyring_path": "config/test_keyring.json"
            },
            "idempotency": {
                "enabled": true,
                "key_ttl_s": 90,
                "store_path": "logs/test-ledger.db"
            },
            "cert_attestation": {
                "required": true,
                "fingerprint_field": "cert_fp",
                "pinset_path": "config/test_pins.json"
            },
            "rollout_policy": {
                "auto_rollback_enabled": true,
                "error_window_size": 10,
                "error_rate_threshold": 0.5,
                "min_samples": 4,
                "rollback_cooldown_s": 15
            },
            "retry": {
                "max_attempts": 4,
                "backoff_s": 0.1
            }
        }
        """,
        encoding="utf-8",
    )

    cfg = load_transport_config(path)

    assert cfg.endpoint_url == "https://vendor.example"
    assert cfg.auth.rotating_tokens == ["a", "b"]
    assert cfg.auth.rotate_every_requests == 2
    assert cfg.tls.enabled is True
    assert cfg.tls.verify_peer is False
    assert cfg.ack.command_id_field == "cmd_id"
    assert cfg.ack.ack_id_field == "ack.command_id"
    assert cfg.ack.require_nonce is True
    assert cfg.ack.nonce_field == "ack_nonce"
    assert cfg.ack.nonce_window == 50
    assert cfg.ack.require_signature is True
    assert cfg.ack.signature_field == "ack_sig"
    assert cfg.ack.signature_algorithm == "ed25519"
    assert cfg.ack.signature_encoding == "base64"
    assert cfg.ack.key_id_field == "kid"
    assert cfg.ack.vendor_field == "vendor"
    assert cfg.ack.keyring_path == "config/test_keyring.json"
    assert cfg.idempotency.key_ttl_s == 90
    assert cfg.idempotency.store_path == "logs/test-ledger.db"
    assert cfg.cert_attestation.required is True
    assert cfg.cert_attestation.fingerprint_field == "cert_fp"
    assert cfg.cert_attestation.pinset_path == "config/test_pins.json"
    assert cfg.rollout_policy.auto_rollback_enabled is True
    assert cfg.rollout_policy.error_window_size == 10
    assert cfg.rollout_policy.error_rate_threshold == 0.5
    assert cfg.rollout_policy.min_samples == 4
    assert cfg.rollout_policy.rollback_cooldown_s == 15
    assert cfg.retry.max_attempts == 4


def test_load_transport_config_rollout_policy_from_file(tmp_path: Path):
    rollout_file = tmp_path / "rollout_policy.json"
    rollout_file.write_text(
        '{"auto_rollback_enabled": true, "error_window_size": 3, "error_rate_threshold": 0.34, "min_samples": 2, "rollback_cooldown_s": 7}',
        encoding="utf-8",
    )

    path = tmp_path / "transport.json"
    path.write_text(
        f'{{"endpoint_url":"https://vendor.example","rollout_policy":{{"rollout_policy_path":"{rollout_file}"}}}}',
        encoding="utf-8",
    )

    cfg = load_transport_config(path)

    assert cfg.rollout_policy.error_window_size == 3
    assert cfg.rollout_policy.error_rate_threshold == 0.34
    assert cfg.rollout_policy.min_samples == 2
