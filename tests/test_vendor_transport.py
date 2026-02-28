import json
import base64
import uuid

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from autonomy.errors import AdapterExecutionError
from autonomy.models import (
    AckConfig,
    AuthRotationConfig,
    CertAttestationConfig,
    IdempotencyConfig,
    RetryPolicy,
    TlsConfig,
    TransportConfig,
)
from autonomy.transport import HttpCommandTransport, InMemoryVendorMqttClient, MqttCommandTransport


class _FakeResponse:
    def __init__(self, status: int, payload: dict[str, object]):
        self.status = status
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return json.dumps(self._payload).encode("utf-8")


def _public_key_b64(private_key: Ed25519PrivateKey) -> str:
    public_key = private_key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    return base64.b64encode(public_key).decode("utf-8")


def _sign_ack(payload: dict[str, object], private_key: Ed25519PrivateKey) -> str:
    signed_payload = {k: v for k, v in payload.items() if k != "ack_signature"}
    canonical = json.dumps(signed_payload, sort_keys=True, separators=(",", ":"))
    signature = private_key.sign(canonical.encode("utf-8"))
    return base64.b64encode(signature).decode("utf-8")


class _AckAwareClient(InMemoryVendorMqttClient):
    def __init__(self, private_key: Ed25519PrivateKey):
        super().__init__()
        self.last_correlation_id = None
        self._nonce = 100
        self.private_key = private_key
        self.kid = "kid-a"
        self.vendor_id = "vendor-test"
        self.cert_fingerprint = "sha256:vendor-test-fp-1"

    def wait_for_ack(self, correlation_id: str, timeout_s: float):
        self.last_correlation_id = correlation_id
        self._nonce += 1
        ack = {
            "command_id": correlation_id,
            "ack_nonce": self._nonce,
            "ack_kid": self.kid,
            "vendor_id": self.vendor_id,
            "mtls_cert_fingerprint": self.cert_fingerprint,
        }
        ack["ack_signature"] = _sign_ack(ack, self.private_key)
        return ack


def _base_config() -> TransportConfig:
    key_a = Ed25519PrivateKey.generate()
    key_b = Ed25519PrivateKey.generate()
    keyring_path = f"/tmp/autonomy-keyring-{uuid.uuid4().hex}.json"
    with open(keyring_path, "w", encoding="utf-8") as handle:
        json.dump(
            {
                "vendors": {
                    "vendor-test": {
                        "active_kid": "kid-a",
                        "keys": {
                            "kid-a": {
                                "algorithm": "ed25519",
                                "public_key_b64": _public_key_b64(key_a),
                            },
                            "kid-b": {
                                "algorithm": "ed25519",
                                "public_key_b64": _public_key_b64(key_b),
                            },
                        },
                        "revoked": [],
                    }
                }
            },
            handle,
        )

    pinset_path = f"/tmp/autonomy-pins-{uuid.uuid4().hex}.json"
    with open(pinset_path, "w", encoding="utf-8") as handle:
        json.dump(
            {
                "vendors": {
                    "vendor-test": {
                        "allowed": ["sha256:vendor-test-fp-1", "sha256:vendor-test-fp-2"],
                        "revoked": [],
                    }
                }
            },
            handle,
        )

    return TransportConfig(
        endpoint_url="https://vendor.example",
        timeout_s=0.1,
        auth=AuthRotationConfig(rotating_tokens=["tok-a", "tok-b"], rotate_every_requests=1),
        tls=TlsConfig(enabled=False),
        ack=AckConfig(
            required=True,
            command_id_field="command_id",
            ack_id_field="command_id",
            require_nonce=True,
            nonce_field="ack_nonce",
            nonce_window=100,
            require_signature=True,
            signature_field="ack_signature",
            signature_algorithm="ed25519",
            signature_encoding="base64",
            key_id_field="ack_kid",
            vendor_field="vendor_id",
            keyring_path=keyring_path,
        ),
        cert_attestation=CertAttestationConfig(
            required=True,
            fingerprint_field="mtls_cert_fingerprint",
            pinset_path=pinset_path,
        ),
        idempotency=IdempotencyConfig(
            enabled=True,
            key_ttl_s=120,
            store_path=f"/tmp/autonomy-test-{uuid.uuid4().hex}.db",
        ),
        retry=RetryPolicy(max_attempts=1, backoff_s=0),
    ), key_a, key_b


def test_http_transport_rotates_tokens_and_enforces_idempotency(monkeypatch):
    config, key_a, _ = _base_config()
    transport = HttpCommandTransport(config)

    seen_auth_headers: list[str] = []

    def fake_urlopen(req, timeout, context=None):
        seen_auth_headers.append(req.headers.get("Authorization", ""))
        command_id = json.loads(req.data.decode("utf-8"))["command_id"]
        nonce = len(seen_auth_headers)
        ack = {
            "command_id": command_id,
            "ack_nonce": nonce,
            "ack_kid": "kid-a",
            "vendor_id": "vendor-test",
            "mtls_cert_fingerprint": "sha256:vendor-test-fp-1",
        }
        ack["ack_signature"] = _sign_ack(ack, key_a)
        return _FakeResponse(202, ack)

    monkeypatch.setattr("autonomy.transport.request.urlopen", fake_urlopen)

    payload = {"type": "arm"}
    transport.send_command("veh-1", payload)
    transport.send_command("veh-1", payload)
    transport.send_command("veh-2", payload)

    assert seen_auth_headers == ["Bearer tok-a", "Bearer tok-b"]


def test_http_transport_raises_on_ack_correlation_failure(monkeypatch):
    config, key_a, _ = _base_config()
    transport = HttpCommandTransport(config)

    def fake_urlopen(req, timeout, context=None):
        ack = {
            "command_id": "different-id",
            "ack_nonce": 1,
            "ack_kid": "kid-a",
            "vendor_id": "vendor-test",
            "mtls_cert_fingerprint": "sha256:vendor-test-fp-1",
        }
        ack["ack_signature"] = _sign_ack(ack, key_a)
        return _FakeResponse(202, ack)

    monkeypatch.setattr("autonomy.transport.request.urlopen", fake_urlopen)

    with pytest.raises(AdapterExecutionError, match="ack correlation failed"):
        transport.send_command("veh-1", {"type": "arm"})


def test_mqtt_transport_ack_correlation_and_idempotency():
    config, key_a, _ = _base_config()
    config.endpoint_url = "mqtts://broker.example"
    client = _AckAwareClient(key_a)
    transport = MqttCommandTransport(config=config, client=client)

    payload = {"type": "move_to", "x": 1, "y": 2}
    transport.send_command("veh-1", payload)
    transport.send_command("veh-1", payload)

    assert len(client.published) == 1
    topic, message, token = client.published[0]
    assert topic == "vehicles/veh-1/commands"
    assert message["idempotency_key"]
    assert token == "tok-a"


def test_mqtt_transport_fails_on_bad_ack():
    config, key_a, _ = _base_config()

    class BadAckClient(InMemoryVendorMqttClient):
        def wait_for_ack(self, correlation_id: str, timeout_s: float):
            ack = {
                "command_id": "wrong",
                "ack_nonce": 1,
                "ack_kid": "kid-a",
                "vendor_id": "vendor-test",
                "mtls_cert_fingerprint": "sha256:vendor-test-fp-1",
            }
            ack["ack_signature"] = _sign_ack(ack, key_a)
            return ack

    config.endpoint_url = "mqtts://broker.example"
    transport = MqttCommandTransport(config=config, client=BadAckClient())

    with pytest.raises(AdapterExecutionError, match="ack correlation failed"):
        transport.send_command("veh-1", {"type": "arm"})


def test_http_transport_rejects_replayed_nonce(monkeypatch):
    config, key_a, _ = _base_config()
    transport = HttpCommandTransport(config)
    call_count = 0

    def fake_urlopen(req, timeout, context=None):
        nonlocal call_count
        call_count += 1
        command_id = json.loads(req.data.decode("utf-8"))["command_id"]
        ack = {
            "command_id": command_id,
            "ack_nonce": 1,
            "ack_kid": "kid-a",
            "vendor_id": "vendor-test",
            "mtls_cert_fingerprint": "sha256:vendor-test-fp-1",
        }
        ack["ack_signature"] = _sign_ack(ack, key_a)
        return _FakeResponse(202, ack)

    monkeypatch.setattr("autonomy.transport.request.urlopen", fake_urlopen)

    transport.send_command("veh-1", {"type": "arm"})
    with pytest.raises(AdapterExecutionError, match="ack replay detected"):
        transport.send_command("veh-1", {"type": "disarm"})

    assert call_count == 2


def test_durable_idempotency_across_transport_instances(monkeypatch, tmp_path):
    db_path = tmp_path / "ledger.db"
    config, key_a, _ = _base_config()
    config.idempotency.store_path = str(db_path)
    config.ack.require_nonce = False

    sent = 0

    def fake_urlopen(req, timeout, context=None):
        nonlocal sent
        sent += 1
        command_id = json.loads(req.data.decode("utf-8"))["command_id"]
        ack = {
            "command_id": command_id,
            "ack_kid": "kid-a",
            "vendor_id": "vendor-test",
            "mtls_cert_fingerprint": "sha256:vendor-test-fp-1",
        }
        ack["ack_signature"] = _sign_ack(ack, key_a)
        return _FakeResponse(202, ack)

    monkeypatch.setattr("autonomy.transport.request.urlopen", fake_urlopen)

    first = HttpCommandTransport(config)
    second = HttpCommandTransport(config)

    payload = {"type": "arm"}
    first.send_command("veh-1", payload)
    second.send_command("veh-1", payload)

    assert sent == 1


def test_http_transport_rejects_revoked_key(monkeypatch):
    config, key_a, _ = _base_config()
    keyring_data = json.loads(open(config.ack.keyring_path, encoding="utf-8").read())
    keyring_data["vendors"]["vendor-test"]["revoked"] = ["kid-a"]
    with open(config.ack.keyring_path, "w", encoding="utf-8") as handle:
        json.dump(keyring_data, handle)

    transport = HttpCommandTransport(config)

    def fake_urlopen(req, timeout, context=None):
        command_id = json.loads(req.data.decode("utf-8"))["command_id"]
        ack = {
            "command_id": command_id,
            "ack_nonce": 1,
            "ack_kid": "kid-a",
            "vendor_id": "vendor-test",
            "mtls_cert_fingerprint": "sha256:vendor-test-fp-1",
        }
        ack["ack_signature"] = _sign_ack(ack, key_a)
        return _FakeResponse(202, ack)

    monkeypatch.setattr("autonomy.transport.request.urlopen", fake_urlopen)

    with pytest.raises(AdapterExecutionError, match="revoked ack key id"):
        transport.send_command("veh-1", {"type": "arm"})


def test_http_transport_accepts_rotated_key(monkeypatch):
    config, _, key_b = _base_config()
    transport = HttpCommandTransport(config)

    def fake_urlopen(req, timeout, context=None):
        command_id = json.loads(req.data.decode("utf-8"))["command_id"]
        ack = {
            "command_id": command_id,
            "ack_nonce": 1,
            "ack_kid": "kid-b",
            "vendor_id": "vendor-test",
            "mtls_cert_fingerprint": "sha256:vendor-test-fp-1",
        }
        ack["ack_signature"] = _sign_ack(ack, key_b)
        return _FakeResponse(202, ack)

    monkeypatch.setattr("autonomy.transport.request.urlopen", fake_urlopen)

    transport.send_command("veh-1", {"type": "arm"})


def test_http_transport_rejects_unpinned_certificate(monkeypatch):
    config, key_a, _ = _base_config()
    transport = HttpCommandTransport(config)

    def fake_urlopen(req, timeout, context=None):
        command_id = json.loads(req.data.decode("utf-8"))["command_id"]
        ack = {
            "command_id": command_id,
            "ack_nonce": 1,
            "ack_kid": "kid-a",
            "vendor_id": "vendor-test",
            "mtls_cert_fingerprint": "sha256:not-pinned",
        }
        ack["ack_signature"] = _sign_ack(ack, key_a)
        return _FakeResponse(202, ack)

    monkeypatch.setattr("autonomy.transport.request.urlopen", fake_urlopen)

    with pytest.raises(AdapterExecutionError, match="certificate fingerprint not pinned"):
        transport.send_command("veh-1", {"type": "arm"})


def test_http_transport_rejects_revoked_certificate(monkeypatch):
    config, key_a, _ = _base_config()
    pinset_data = json.loads(open(config.cert_attestation.pinset_path, encoding="utf-8").read())
    pinset_data["vendors"]["vendor-test"]["revoked"] = ["sha256:vendor-test-fp-1"]
    with open(config.cert_attestation.pinset_path, "w", encoding="utf-8") as handle:
        json.dump(pinset_data, handle)

    transport = HttpCommandTransport(config)

    def fake_urlopen(req, timeout, context=None):
        command_id = json.loads(req.data.decode("utf-8"))["command_id"]
        ack = {
            "command_id": command_id,
            "ack_nonce": 1,
            "ack_kid": "kid-a",
            "vendor_id": "vendor-test",
            "mtls_cert_fingerprint": "sha256:vendor-test-fp-1",
        }
        ack["ack_signature"] = _sign_ack(ack, key_a)
        return _FakeResponse(202, ack)

    monkeypatch.setattr("autonomy.transport.request.urlopen", fake_urlopen)

    with pytest.raises(AdapterExecutionError, match="revoked vendor certificate fingerprint"):
        transport.send_command("veh-1", {"type": "arm"})
