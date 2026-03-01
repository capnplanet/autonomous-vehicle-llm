from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from .models import Action, ActionType, MissionPlan, VehicleState


@dataclass(slots=True)
class TraceScenario:
    name: str
    description: str
    initial_state: VehicleState
    plan: MissionPlan
    telemetry_events: list[dict[str, object]]


def available_trace_scenarios() -> dict[str, TraceScenario]:
    now = datetime.now(UTC)

    nominal = TraceScenario(
        name="nominal_replay",
        description="Nominal arm/move/disarm replay trace",
        initial_state=VehicleState(
            vehicle_id="veh-001",
            x=0.0,
            y=0.0,
            battery_pct=95.0,
            armed=False,
            connected=True,
            home_x=0.0,
            home_y=0.0,
        ),
        plan=MissionPlan(
            goal="nominal replay",
            vehicle_id="veh-001",
            actions=[
                Action(type=ActionType.ARM),
                Action(type=ActionType.MOVE_TO, x=8.0, y=2.0, speed_mps=2.0),
                Action(type=ActionType.RETURN_TO_HOME),
                Action(type=ActionType.DISARM),
            ],
        ),
        telemetry_events=[
            {
                "vehicle_id": "veh-001",
                "timestamp": now.isoformat(),
                "x": 0.0,
                "y": 0.0,
                "gps_x": 0.0,
                "gps_y": 0.0,
                "imu_vx_mps": 0.0,
                "imu_vy_mps": 0.0,
                "heading_rad": 0.0,
                "position_std_m": 0.4,
                "battery_pct": 95.0,
                "armed": False,
                "connected": True,
            },
            {
                "vehicle_id": "veh-001",
                "timestamp": (now + timedelta(seconds=1)).isoformat(),
                "x": 0.0,
                "y": 0.0,
                "gps_x": 8.0,
                "gps_y": 2.0,
                "imu_vx_mps": 1.5,
                "imu_vy_mps": 0.2,
                "heading_rad": 0.2,
                "position_std_m": 0.4,
                "battery_pct": 94.5,
                "armed": True,
                "connected": True,
            },
            {
                "vehicle_id": "veh-001",
                "timestamp": (now + timedelta(seconds=2)).isoformat(),
                "x": 8.0,
                "y": 2.0,
                "gps_x": 8.0,
                "gps_y": 2.0,
                "imu_vx_mps": 0.0,
                "imu_vy_mps": 0.0,
                "heading_rad": 0.2,
                "position_std_m": 0.4,
                "battery_pct": 94.3,
                "armed": True,
                "connected": True,
            },
            {
                "vehicle_id": "veh-001",
                "timestamp": (now + timedelta(seconds=3)).isoformat(),
                "x": 0.0,
                "y": 0.0,
                "gps_x": 0.0,
                "gps_y": 0.0,
                "imu_vx_mps": 0.0,
                "imu_vy_mps": 0.0,
                "heading_rad": 0.0,
                "position_std_m": 0.4,
                "battery_pct": 94.0,
                "armed": True,
                "connected": True,
            },
        ],
    )

    blocked_target = TraceScenario(
        name="blocked_target",
        description="Move target blocked by lidar obstacle, requiring reroute",
        initial_state=VehicleState(
            vehicle_id="veh-002",
            x=0.0,
            y=0.0,
            battery_pct=88.0,
            armed=True,
            connected=True,
            home_x=0.0,
            home_y=0.0,
        ),
        plan=MissionPlan(
            goal="blocked target reroute",
            vehicle_id="veh-002",
            actions=[Action(type=ActionType.MOVE_TO, x=10.0, y=5.0, speed_mps=2.0)],
        ),
        telemetry_events=[
            {
                "vehicle_id": "veh-002",
                "timestamp": now.isoformat(),
                "x": 0.0,
                "y": 0.0,
                "gps_x": 0.0,
                "gps_y": 0.0,
                "imu_vx_mps": 0.0,
                "imu_vy_mps": 0.0,
                "heading_rad": 0.0,
                "position_std_m": 0.5,
                "lidar_obstacles": [
                    {"x": 10.0, "y": 5.0, "radius_m": 1.5, "confidence": 0.9, "source": "lidar"}
                ],
                "battery_pct": 88.0,
                "armed": True,
                "connected": True,
            }
        ],
    )

    return {
        nominal.name: nominal,
        blocked_target.name: blocked_target,
    }
