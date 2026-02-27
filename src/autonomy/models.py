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
class TransportConfig:
    endpoint_url: str
    timeout_s: float = 1.0
    auth_token: str | None = None
    retry: RetryPolicy = field(default_factory=RetryPolicy)
