from __future__ import annotations

import time

from autonomy.localization import FusedTelemetryLocalizationEngine
from autonomy.models import VehicleState
from autonomy.perception import PerceptionFrame


def _state() -> VehicleState:
    return VehicleState(
        vehicle_id="veh-001",
        x=0.0,
        y=0.0,
        battery_pct=95.0,
        armed=True,
        connected=True,
        heading_rad=0.1,
        vx_mps=0.0,
        vy_mps=0.0,
        position_std_m=1.0,
    )


def test_fused_localization_prefers_gps_and_imu_signals():
    engine = FusedTelemetryLocalizationEngine(gps_blend_weight=0.75, max_staleness_s=1.0)
    frame = PerceptionFrame(
        timestamp_s=time.time(),
        telemetry={
            "x": 1.0,
            "y": 1.0,
            "gps_x": 8.0,
            "gps_y": 4.0,
            "imu_vx_mps": 1.5,
            "imu_vy_mps": -0.2,
            "heading_rad": 0.3,
            "position_std_m": 0.6,
        },
    )

    estimate = engine.estimate(_state(), frame)

    assert round(estimate.x, 3) == 6.0
    assert round(estimate.y, 3) == 3.0
    assert estimate.vx_mps == 1.5
    assert estimate.vy_mps == -0.2
    assert estimate.heading_rad == 0.3
    assert estimate.position_std_m == 0.6
    assert estimate.fresh is True


def test_fused_localization_marks_stale_frame_not_fresh():
    engine = FusedTelemetryLocalizationEngine(gps_blend_weight=0.8, max_staleness_s=0.1)
    frame = PerceptionFrame(
        timestamp_s=time.time() - 1.0,
        telemetry={"x": 2.0, "y": 3.0},
    )

    estimate = engine.estimate(_state(), frame)

    assert estimate.fresh is False
