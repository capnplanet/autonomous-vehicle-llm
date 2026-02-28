from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class ActionType(str, Enum):
    ARM = "arm"
    MOVE_TO = "move_to"
    HOLD = "hold"
    RETURN_TO_HOME = "return_to_home"
    DISARM = "disarm"


class VehicleDomain(str, Enum):
    GROUND = "ground"
    AERIAL = "aerial"
    MARINE = "marine"


@dataclass(slots=True)
class Action:
    type: ActionType
    x: float | None = None
    y: float | None = None
    speed_mps: float | None = None


@dataclass(slots=True)
class MissionPlan:
    goal: str
    vehicle_id: str
    actions: list[Action] = field(default_factory=list)


@dataclass(slots=True)
class VehicleState:
    vehicle_id: str
    x: float
    y: float
    battery_pct: float
    armed: bool
    connected: bool
    home_x: float = 0.0
    home_y: float = 0.0


@dataclass(slots=True)
class PolicyConfig:
    max_speed_mps: float = 8.0
    min_battery_for_motion_pct: float = 25.0
    geofence_abs_xy_limit_m: float = 100.0


@dataclass(slots=True)
class CapabilityProfile:
    domain: VehicleDomain
    max_speed_mps: float
    supports_return_to_home: bool = True


@dataclass(slots=True)
class RetryPolicy:
    max_attempts: int = 3
    backoff_s: float = 0.2


@dataclass(slots=True)
class TlsConfig:
    enabled: bool = True
    verify_peer: bool = True
    ca_cert_path: str | None = None
    client_cert_path: str | None = None
    client_key_path: str | None = None


@dataclass(slots=True)
class AuthRotationConfig:
    static_token: str | None = None
    rotating_tokens: list[str] = field(default_factory=list)
    rotate_every_requests: int = 1


@dataclass(slots=True)
class AckConfig:
    required: bool = True
    command_id_field: str = "command_id"
    ack_id_field: str = "command_id"
    require_nonce: bool = True
    nonce_field: str = "ack_nonce"
    nonce_window: int = 1000
    require_signature: bool = True
    signature_field: str = "ack_signature"
    signature_algorithm: str = "ed25519"
    signature_encoding: str = "base64"
    key_id_field: str = "ack_kid"
    vendor_field: str = "vendor_id"
    keyring_path: str = "config/ack_keyring.json"


@dataclass(slots=True)
class CertAttestationConfig:
    required: bool = True
    fingerprint_field: str = "mtls_cert_fingerprint"
    pinset_path: str = "config/vendor_cert_pins.json"


@dataclass(slots=True)
class RolloutPolicyConfig:
    auto_rollback_enabled: bool = True
    error_window_size: int = 20
    error_rate_threshold: float = 0.4
    min_samples: int = 5
    rollback_cooldown_s: float = 30.0


@dataclass(slots=True)
class IdempotencyConfig:
    enabled: bool = True
    key_ttl_s: float = 300.0
    store_path: str = "logs/command_ledger.db"


@dataclass(slots=True)
class TransportConfig:
    endpoint_url: str
    timeout_s: float = 1.0
    auth: AuthRotationConfig = field(default_factory=AuthRotationConfig)
    tls: TlsConfig = field(default_factory=TlsConfig)
    ack: AckConfig = field(default_factory=AckConfig)
    cert_attestation: CertAttestationConfig = field(default_factory=CertAttestationConfig)
    rollout_policy: RolloutPolicyConfig = field(default_factory=RolloutPolicyConfig)
    idempotency: IdempotencyConfig = field(default_factory=IdempotencyConfig)
    retry: RetryPolicy = field(default_factory=RetryPolicy)
