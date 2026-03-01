from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass

from .models import VehicleState
from .perception import PerceptionFrame


@dataclass(slots=True)
class LocalizationEstimate:
    x: float
    y: float
    heading_rad: float
    vx_mps: float
    vy_mps: float
    position_std_m: float
    timestamp_s: float
    fresh: bool = True


class LocalizationEngine(ABC):
    @abstractmethod
    def estimate(self, state: VehicleState, frame: PerceptionFrame | None = None) -> LocalizationEstimate:
        raise NotImplementedError


class PassThroughLocalizationEngine(LocalizationEngine):
    def estimate(self, state: VehicleState, frame: PerceptionFrame | None = None) -> LocalizationEstimate:
        if frame is not None:
            timestamp = frame.timestamp_s
        else:
            timestamp = time.time()

        return LocalizationEstimate(
            x=state.x,
            y=state.y,
            heading_rad=state.heading_rad,
            vx_mps=state.vx_mps,
            vy_mps=state.vy_mps,
            position_std_m=state.position_std_m,
            timestamp_s=timestamp,
            fresh=True,
        )


class FusedTelemetryLocalizationEngine(LocalizationEngine):
    def __init__(self, gps_blend_weight: float = 0.8, max_staleness_s: float = 1.0) -> None:
        self.gps_blend_weight = min(max(gps_blend_weight, 0.0), 1.0)
        self.max_staleness_s = max(0.0, max_staleness_s)

    def estimate(self, state: VehicleState, frame: PerceptionFrame | None = None) -> LocalizationEstimate:
        now = time.time()
        if frame is None:
            return LocalizationEstimate(
                x=state.x,
                y=state.y,
                heading_rad=state.heading_rad,
                vx_mps=state.vx_mps,
                vy_mps=state.vy_mps,
                position_std_m=state.position_std_m,
                timestamp_s=now,
                fresh=False,
            )

        telemetry = frame.telemetry
        gps_x = self._number(telemetry.get("gps_x"), default=self._number(telemetry.get("x"), default=state.x))
        gps_y = self._number(telemetry.get("gps_y"), default=self._number(telemetry.get("y"), default=state.y))
        imu_vx = self._number(telemetry.get("imu_vx_mps"), default=state.vx_mps)
        imu_vy = self._number(telemetry.get("imu_vy_mps"), default=state.vy_mps)
        heading = self._number(telemetry.get("heading_rad"), default=state.heading_rad)
        position_std = self._number(telemetry.get("position_std_m"), default=state.position_std_m)

        fused_x = (self.gps_blend_weight * gps_x) + ((1.0 - self.gps_blend_weight) * state.x)
        fused_y = (self.gps_blend_weight * gps_y) + ((1.0 - self.gps_blend_weight) * state.y)
        age_s = max(0.0, now - frame.timestamp_s)

        return LocalizationEstimate(
            x=fused_x,
            y=fused_y,
            heading_rad=heading,
            vx_mps=imu_vx,
            vy_mps=imu_vy,
            position_std_m=max(0.0, position_std),
            timestamp_s=frame.timestamp_s,
            fresh=age_s <= self.max_staleness_s,
        )

    def _number(self, value: object, default: float) -> float:
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
        return float(default)
