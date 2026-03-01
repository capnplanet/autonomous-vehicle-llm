import json
import time

from autonomy.audit import SignedAuditLogger
from autonomy.edge_supervisor import EdgeSupervisor
from autonomy.localization import LocalizationEstimate
from autonomy.models import (
    Action,
    ActionType,
    CapabilityProfile,
    MissionPlan,
    VehicleDomain,
    VehicleState,
)
from autonomy.obstacle_avoidance import ClearanceAwareAvoidancePlanner
from autonomy.perception import DetectedObstacle, PerceptionFrame
from autonomy.safety_kernel import SafetyKernel
from autonomy.vehicle_adapter import SimVehicleAdapter


class StaleLocalizationEngine:
    def estimate(self, state, frame=None):
        return LocalizationEstimate(
            x=state.x,
            y=state.y,
            heading_rad=0.0,
            vx_mps=0.0,
            vy_mps=0.0,
            position_std_m=0.0,
            timestamp_s=0.0,
            fresh=False,
        )


class TargetBlockedPerception:
    def observe(self, state):
        return PerceptionFrame(
            timestamp_s=time.time(),
            obstacles=[DetectedObstacle(x=10.0, y=5.0, radius_m=1.5)],
        )


def test_policy_block_triggers_fallback_rth():
    supervisor = EdgeSupervisor(SafetyKernel(), SimVehicleAdapter())
    state = VehicleState(
        vehicle_id="veh-001",
        x=0,
        y=0,
        battery_pct=10,
        armed=True,
        connected=True,
        home_x=0,
        home_y=0,
    )
    plan = MissionPlan(
        goal="force block",
        vehicle_id="veh-001",
        actions=[Action(type=ActionType.MOVE_TO, x=10, y=10, speed_mps=2)],
    )

    final_state, events = supervisor.run_plan(state, plan)

    assert final_state.x == 0
    assert final_state.y == 0
    assert any(evt.startswith("policy_block:") for evt in events)
    assert "fallback:return_to_home" in events


def test_adapter_speed_limit_and_audit_log(tmp_path):
    adapter = SimVehicleAdapter(
        capability_profile=CapabilityProfile(
            domain=VehicleDomain.GROUND,
            max_speed_mps=1.0,
            supports_return_to_home=True,
        )
    )
    logger = SignedAuditLogger(file_path=tmp_path / "audit.log", secret="test")
    supervisor = EdgeSupervisor(SafetyKernel(), adapter, audit_logger=logger)

    state = VehicleState(
        vehicle_id="veh-001",
        x=0,
        y=0,
        battery_pct=80,
        armed=True,
        connected=True,
        home_x=0,
        home_y=0,
    )
    plan = MissionPlan(
        goal="speed violation",
        vehicle_id="veh-001",
        actions=[Action(type=ActionType.MOVE_TO, x=5, y=5, speed_mps=3)],
    )

    _, events = supervisor.run_plan(state, plan)

    assert "policy_block:adapter_speed_limit" in events
    lines = (tmp_path / "audit.log").read_text(encoding="utf-8").splitlines()
    records = [json.loads(line) for line in lines]
    assert records[0]["event_type"] == "policy_block"
    assert records[1]["event_type"] == "fallback"


def test_stale_localization_triggers_fallback():
    supervisor = EdgeSupervisor(
        SafetyKernel(),
        SimVehicleAdapter(),
        localization_engine=StaleLocalizationEngine(),
    )
    state = VehicleState(
        vehicle_id="veh-001",
        x=2,
        y=1,
        battery_pct=80,
        armed=True,
        connected=True,
        home_x=0,
        home_y=0,
    )
    plan = MissionPlan(
        goal="stale localization",
        vehicle_id="veh-001",
        actions=[Action(type=ActionType.MOVE_TO, x=5, y=5, speed_mps=2)],
    )

    final_state, events = supervisor.run_plan(state, plan)

    assert any(evt.startswith("policy_block:localization_stale") for evt in events)
    assert "fallback:return_to_home" in events
    assert final_state.x == 0
    assert final_state.y == 0


def test_obstacle_avoidance_reroutes_move_target():
    supervisor = EdgeSupervisor(
        SafetyKernel(),
        SimVehicleAdapter(),
        perception_pipeline=TargetBlockedPerception(),
        avoidance_planner=ClearanceAwareAvoidancePlanner(min_clearance_m=2.0, sidestep_m=3.0),
    )
    state = VehicleState(
        vehicle_id="veh-001",
        x=0,
        y=0,
        battery_pct=80,
        armed=True,
        connected=True,
        home_x=0,
        home_y=0,
    )
    plan = MissionPlan(
        goal="avoid obstacle",
        vehicle_id="veh-001",
        actions=[Action(type=ActionType.MOVE_TO, x=10, y=5, speed_mps=2)],
    )

    final_state, events = supervisor.run_plan(state, plan)

    assert "exec:move_to" in events
    assert (final_state.x, final_state.y) == (13.0, 8.0)
