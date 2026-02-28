from __future__ import annotations

import base64
import hashlib
import json
import ssl
import time
import uuid
from abc import ABC, abstractmethod
from collections import deque
from dataclasses import dataclass
from urllib import error, request

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from .cert_pins import VendorCertPinset
from .errors import AdapterExecutionError
from .keyring import VendorAckKeyring
from .ledger import CommandLedger
from .models import TransportConfig


class CommandTransport(ABC):
    @abstractmethod
    def send_command(self, vehicle_id: str, payload: dict[str, object]) -> None:
        raise NotImplementedError


@dataclass(slots=True)
class CommandEnvelope:
    vehicle_id: str
    command_id: str
    idempotency_key: str
    payload: dict[str, object]


class RotatingTokenProvider:
    def __init__(self, static_token: str | None, rotating_tokens: list[str], rotate_every_requests: int) -> None:
        self.static_token = static_token
        self.rotating_tokens = [token for token in rotating_tokens if token]
        self.rotate_every_requests = max(1, rotate_every_requests)
        self._request_counter = 0

    def next_token(self) -> str | None:
        if self.static_token:
            return self.static_token
        if not self.rotating_tokens:
            return None
        index = (self._request_counter // self.rotate_every_requests) % len(self.rotating_tokens)
        self._request_counter += 1
        return self.rotating_tokens[index]


class VendorMqttClient(ABC):
    @abstractmethod
    def publish(self, topic: str, message: dict[str, object], token: str | None) -> None:
        raise NotImplementedError

    @abstractmethod
    def wait_for_ack(self, correlation_id: str, timeout_s: float) -> dict[str, object] | None:
        raise NotImplementedError


class InMemoryVendorMqttClient(VendorMqttClient):
    def __init__(self) -> None:
        self.published: list[tuple[str, dict[str, object], str | None]] = []

    def publish(self, topic: str, message: dict[str, object], token: str | None) -> None:
        self.published.append((topic, message, token))

    def wait_for_ack(self, correlation_id: str, timeout_s: float) -> dict[str, object] | None:
        return {"command_id": correlation_id}


class TransportBase(CommandTransport):
    def __init__(self, config: TransportConfig) -> None:
        self.config = config
        self._token_provider = RotatingTokenProvider(
            static_token=config.auth.static_token,
            rotating_tokens=config.auth.rotating_tokens,
            rotate_every_requests=config.auth.rotate_every_requests,
        )
        self._ledger = CommandLedger(config.idempotency.store_path)
        self._keyring = VendorAckKeyring(config.ack.keyring_path)
        self._cert_pins = VendorCertPinset(config.cert_attestation.pinset_path)
        self._ack_outcomes: deque[bool] = deque(maxlen=config.rollout_policy.error_window_size)
        self._last_rollback_ts_by_vendor: dict[str, float] = {}

    def _build_envelope(self, vehicle_id: str, payload: dict[str, object]) -> CommandEnvelope:
        command_id = str(uuid.uuid4())
        canonical_payload = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        seed = f"{vehicle_id}:{canonical_payload}"
        idempotency_key = hashlib.sha256(seed.encode("utf-8")).hexdigest()
        enriched_payload = dict(payload)
        enriched_payload[self.config.ack.command_id_field] = command_id
        return CommandEnvelope(
            vehicle_id=vehicle_id,
            command_id=command_id,
            idempotency_key=idempotency_key,
            payload=enriched_payload,
        )

    def _is_duplicate(self, key: str) -> bool:
        if not self.config.idempotency.enabled:
            return False
        return self._ledger.is_duplicate_idempotency_key(key)

    def _mark_seen(self, key: str) -> None:
        if self.config.idempotency.enabled:
            self._ledger.mark_idempotency_key(key, self.config.idempotency.key_ttl_s)

    def _extract_ack_id(self, data: dict[str, object]) -> str | None:
        ack_field = self.config.ack.ack_id_field
        if "." not in ack_field:
            value = data.get(ack_field)
            return str(value) if value is not None else None

        current: object = data
        for part in ack_field.split("."):
            if not isinstance(current, dict):
                return None
            current = current.get(part)
            if current is None:
                return None
        return str(current)

    def _validate_ack(self, vehicle_id: str, data: dict[str, object], expected_command_id: str) -> None:
        if not self.config.ack.required:
            return
        ack_id = self._extract_ack_id(data)
        if ack_id != expected_command_id:
            raise AdapterExecutionError(
                f"ack correlation failed: expected {expected_command_id}, got {ack_id}"
            )

        if self.config.ack.require_nonce:
            nonce_raw = data.get(self.config.ack.nonce_field)
            if nonce_raw is None:
                raise AdapterExecutionError("ack nonce missing")
            try:
                ack_nonce = int(nonce_raw)
            except (TypeError, ValueError) as exc:
                raise AdapterExecutionError("ack nonce invalid") from exc

            last_nonce = self._ledger.get_last_ack_nonce(vehicle_id)
            if last_nonce is not None and ack_nonce <= last_nonce:
                raise AdapterExecutionError("ack replay detected")
            if last_nonce is not None and ack_nonce > last_nonce + self.config.ack.nonce_window:
                raise AdapterExecutionError("ack nonce outside window")

            self._ledger.update_last_ack_nonce(vehicle_id, ack_nonce)

        if self.config.ack.require_signature:
            self._validate_ack_signature(data)

        if self.config.cert_attestation.required:
            self._validate_cert_binding(data)

        vendor_id = data.get(self.config.ack.vendor_field)
        if isinstance(vendor_id, str):
            self._record_ack_verification_result(True, vendor_id)

    def _validate_cert_binding(self, data: dict[str, object]) -> None:
        vendor_field = self.config.ack.vendor_field
        vendor_raw = data.get(vendor_field)
        if vendor_raw is None:
            raise AdapterExecutionError("ack vendor id missing")
        vendor_id = str(vendor_raw)

        fp_field = self.config.cert_attestation.fingerprint_field
        fingerprint_raw = data.get(fp_field)
        if fingerprint_raw is None:
            raise AdapterExecutionError("mTLS certificate fingerprint missing")
        fingerprint = str(fingerprint_raw)

        self._cert_pins.assert_vendor_fingerprint_allowed(vendor_id, fingerprint)

    def _record_ack_verification_failure(self, data: dict[str, object], error_detail: str) -> None:
        vendor_raw = data.get(self.config.ack.vendor_field)
        if not isinstance(vendor_raw, str):
            return
        self._record_ack_verification_result(False, vendor_raw, error_detail)

    def _record_ack_verification_result(
        self,
        success: bool,
        vendor_id: str,
        error_detail: str | None = None,
    ) -> None:
        self._ack_outcomes.append(success)

        policy = self.config.rollout_policy
        if success or not policy.auto_rollback_enabled:
            return
        sample_count = len(self._ack_outcomes)
        if sample_count < policy.min_samples:
            return

        failure_count = sum(1 for outcome in self._ack_outcomes if not outcome)
        failure_rate = failure_count / sample_count
        if failure_rate < policy.error_rate_threshold:
            return

        now = time.time()
        last_rollback = self._last_rollback_ts_by_vendor.get(vendor_id, 0.0)
        if now - last_rollback < policy.rollback_cooldown_s:
            return

        try:
            self._cert_pins.rollback_to_previous_active(vendor_id)
            self._last_rollback_ts_by_vendor[vendor_id] = now
            self._ack_outcomes.clear()
            self._ledger.append_command_event(
                vehicle_id=f"vendor:{vendor_id}",
                command_id="rollout_guard",
                idempotency_key="rollout_guard",
                status="auto_rollback",
                detail=error_detail,
            )
        except AdapterExecutionError as rollback_exc:
            self._ledger.append_command_event(
                vehicle_id=f"vendor:{vendor_id}",
                command_id="rollout_guard",
                idempotency_key="rollout_guard",
                status="auto_rollback_failed",
                detail=str(rollback_exc),
            )

    def _validate_ack_signature(self, data: dict[str, object]) -> None:
        sig_field = self.config.ack.signature_field
        key_id_field = self.config.ack.key_id_field
        vendor_field = self.config.ack.vendor_field

        signature_raw = data.get(sig_field)
        if signature_raw is None:
            raise AdapterExecutionError("ack signature missing")
        signature = str(signature_raw)

        key_id_raw = data.get(key_id_field)
        if key_id_raw is None:
            raise AdapterExecutionError("ack key id missing")
        key_id = str(key_id_raw)

        vendor_raw = data.get(vendor_field)
        if vendor_raw is None:
            raise AdapterExecutionError("ack vendor id missing")
        vendor_id = str(vendor_raw)

        key_descriptor = self._keyring.get_key_descriptor(vendor_id, key_id)
        algorithm = key_descriptor.get("algorithm", "")
        if algorithm.lower() != self.config.ack.signature_algorithm.lower():
            raise AdapterExecutionError(
                f"ack algorithm mismatch: expected {self.config.ack.signature_algorithm}, got {algorithm}"
            )

        signed_payload = {
            key: value
            for key, value in data.items()
            if key not in {sig_field}
        }
        canonical = json.dumps(signed_payload, sort_keys=True, separators=(",", ":"))

        if self.config.ack.signature_encoding.lower() != "base64":
            raise AdapterExecutionError("unsupported signature encoding")

        try:
            signature_bytes = base64.b64decode(signature, validate=True)
            public_key_bytes = base64.b64decode(key_descriptor["public_key_b64"], validate=True)
            public_key = Ed25519PublicKey.from_public_bytes(public_key_bytes)
            public_key.verify(signature_bytes, canonical.encode("utf-8"))
        except (ValueError, InvalidSignature) as exc:
            raise AdapterExecutionError("ack signature invalid")

    def _log_event(
        self,
        vehicle_id: str,
        command_id: str,
        idempotency_key: str,
        status: str,
        detail: str | None = None,
    ) -> None:
        self._ledger.append_command_event(
            vehicle_id=vehicle_id,
            command_id=command_id,
            idempotency_key=idempotency_key,
            status=status,
            detail=detail,
        )


class HttpCommandTransport(TransportBase):
    def __init__(self, config: TransportConfig) -> None:
        super().__init__(config)

    def _build_ssl_context(self) -> ssl.SSLContext | None:
        if not self.config.tls.enabled:
            return None

        context = ssl.create_default_context(cafile=self.config.tls.ca_cert_path)
        if not self.config.tls.verify_peer:
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE

        if self.config.tls.client_cert_path:
            context.load_cert_chain(
                certfile=self.config.tls.client_cert_path,
                keyfile=self.config.tls.client_key_path,
            )
        return context

    def send_command(self, vehicle_id: str, payload: dict[str, object]) -> None:
        envelope = self._build_envelope(vehicle_id, payload)
        if self._is_duplicate(envelope.idempotency_key):
            self._log_event(
                vehicle_id=vehicle_id,
                command_id=envelope.command_id,
                idempotency_key=envelope.idempotency_key,
                status="duplicate_skip",
            )
            return

        path = f"{self.config.endpoint_url.rstrip('/')}/vehicles/{vehicle_id}/commands"
        body = json.dumps(envelope.payload).encode("utf-8")
        ssl_context = self._build_ssl_context()

        for attempt in range(1, self.config.retry.max_attempts + 1):
            headers = {
                "Content-Type": "application/json",
                "Idempotency-Key": envelope.idempotency_key,
                "X-Command-Id": envelope.command_id,
            }
            token = self._token_provider.next_token()
            if token:
                headers["Authorization"] = f"Bearer {token}"

            req = request.Request(path, data=body, headers=headers, method="POST")
            try:
                with request.urlopen(req, timeout=self.config.timeout_s, context=ssl_context) as response:
                    if 200 <= response.status < 300:
                        response_data: dict[str, object] = {}
                        raw_body = response.read().decode("utf-8")
                        if raw_body.strip():
                            response_data = json.loads(raw_body)
                        try:
                            self._validate_ack(vehicle_id, response_data, envelope.command_id)
                        except AdapterExecutionError as ack_exc:
                            self._record_ack_verification_failure(response_data, str(ack_exc))
                            raise
                        self._mark_seen(envelope.idempotency_key)
                        self._log_event(
                            vehicle_id=vehicle_id,
                            command_id=envelope.command_id,
                            idempotency_key=envelope.idempotency_key,
                            status="ack_ok",
                        )
                        return
                    raise AdapterExecutionError(f"http status {response.status}")
            except (error.HTTPError, error.URLError, TimeoutError, AdapterExecutionError) as exc:
                if attempt >= self.config.retry.max_attempts:
                    self._log_event(
                        vehicle_id=vehicle_id,
                        command_id=envelope.command_id,
                        idempotency_key=envelope.idempotency_key,
                        status="send_failed",
                        detail=str(exc),
                    )
                    raise AdapterExecutionError(f"http transport failed: {exc}") from exc
                delay = self.config.retry.backoff_s * (2 ** (attempt - 1))
                time.sleep(delay)


class MqttCommandTransport(TransportBase):
    def __init__(self, config: TransportConfig, client: VendorMqttClient | None = None) -> None:
        super().__init__(config)
        self.client = client or InMemoryVendorMqttClient()

    def send_command(self, vehicle_id: str, payload: dict[str, object]) -> None:
        envelope = self._build_envelope(vehicle_id, payload)
        if self._is_duplicate(envelope.idempotency_key):
            self._log_event(
                vehicle_id=vehicle_id,
                command_id=envelope.command_id,
                idempotency_key=envelope.idempotency_key,
                status="duplicate_skip",
            )
            return

        for attempt in range(1, self.config.retry.max_attempts + 1):
            try:
                if self.config.endpoint_url.startswith("fail://"):
                    raise AdapterExecutionError("mqtt broker unavailable")

                topic = f"vehicles/{vehicle_id}/commands"
                token = self._token_provider.next_token()
                message: dict[str, object] = {
                    "command": envelope.payload,
                    "idempotency_key": envelope.idempotency_key,
                    "command_id": envelope.command_id,
                }
                self.client.publish(topic=topic, message=message, token=token)

                ack = self.client.wait_for_ack(envelope.command_id, timeout_s=self.config.timeout_s)
                if ack is None:
                    raise AdapterExecutionError("mqtt ack timeout")
                try:
                    self._validate_ack(vehicle_id, ack, envelope.command_id)
                except AdapterExecutionError as ack_exc:
                    self._record_ack_verification_failure(ack, str(ack_exc))
                    raise
                self._mark_seen(envelope.idempotency_key)
                self._log_event(
                    vehicle_id=vehicle_id,
                    command_id=envelope.command_id,
                    idempotency_key=envelope.idempotency_key,
                    status="ack_ok",
                )
                return
            except AdapterExecutionError as exc:
                if attempt >= self.config.retry.max_attempts:
                    self._log_event(
                        vehicle_id=vehicle_id,
                        command_id=envelope.command_id,
                        idempotency_key=envelope.idempotency_key,
                        status="send_failed",
                        detail=str(exc),
                    )
                    raise
                delay = self.config.retry.backoff_s * (2 ** (attempt - 1))
                time.sleep(delay)
