from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from autonomy.edge_supervisor import EdgeSupervisor
from autonomy.localization import FusedTelemetryLocalizationEngine
from autonomy.models import Action, ActionType, MissionPlan, VehicleState
from autonomy.perception import TelemetryPerceptionPipeline, TelemetrySchemaValidator
from autonomy.plan_verifier import PlanVerifier
from autonomy.replay import DeterministicTelemetryReplay
from autonomy.safety_kernel import SafetyKernel
from autonomy.trace import MissionTraceRunner
from autonomy.vehicle_adapter import SimVehicleAdapter


def _state() -> VehicleState:
    return VehicleState(
        vehicle_id="veh-001",
        x=0.0,
        y=0.0,
        battery_pct=95.0,
        armed=False,
        connected=True,
        home_x=0.0,
        home_y=0.0,
    )


def _valid_plan() -> MissionPlan:
    return MissionPlan(
        goal="trace test",
        vehicle_id="veh-001",
        actions=[
            Action(type=ActionType.ARM),
            Action(type=ActionType.DISARM),
        ],
    )


def test_trace_runner_writes_executed_artifact(tmp_path):
    runner = MissionTraceRunner(
        supervisor=EdgeSupervisor(SafetyKernel(), SimVehicleAdapter()),
        verifier=PlanVerifier(),
    )
    output = tmp_path / "trace.json"

    artifact = runner.run(
        scenario="nominal",
        initial_state=_state(),
        plan=_valid_plan(),
        output_path=output,
    )

    assert artifact.status == "executed"
    assert output.exists()
    written = json.loads(output.read_text(encoding="utf-8"))
    assert written["status"] == "executed"
    assert "exec:arm" in written["events"]


def test_trace_runner_rejects_invalid_plan(tmp_path):
    runner = MissionTraceRunner(
        supervisor=EdgeSupervisor(SafetyKernel(), SimVehicleAdapter()),
        verifier=PlanVerifier(),
    )
    invalid_plan = MissionPlan(
        goal="invalid",
        vehicle_id="veh-001",
        actions=[Action(type=ActionType.ARM)],
    )

    artifact = runner.run(
        scenario="invalid",
        initial_state=_state(),
        plan=invalid_plan,
        output_path=tmp_path / "invalid.json",
    )

    assert artifact.status == "rejected"
    assert "last action must be disarm" in artifact.errors


def test_trace_runner_reports_replay_consumption(tmp_path):
    now = datetime.now(UTC)
    events = [
        {
            "vehicle_id": "veh-001",
            "timestamp": now.isoformat(),
            "x": 0.0,
            "y": 0.0,
            "battery_pct": 95.0,
            "armed": False,
            "connected": True,
        },
        {
            "vehicle_id": "veh-001",
            "timestamp": (now + timedelta(seconds=1)).isoformat(),
            "x": 0.0,
            "y": 0.0,
            "battery_pct": 95.0,
            "armed": True,
            "connected": True,
        },
    ]
    replay = DeterministicTelemetryReplay(events)
    validator = TelemetrySchemaValidator("specs/events/telemetry.schema.json")
    pipeline = TelemetryPerceptionPipeline(replay.next_event, validator)
    supervisor = EdgeSupervisor(
        SafetyKernel(),
        SimVehicleAdapter(),
        perception_pipeline=pipeline,
        localization_engine=FusedTelemetryLocalizationEngine(max_staleness_s=5.0),
    )
    runner = MissionTraceRunner(supervisor=supervisor, verifier=PlanVerifier())

    artifact = runner.run(
        scenario="replay-count",
        initial_state=_state(),
        plan=_valid_plan(),
        replay=replay,
        output_path=tmp_path / "replay.json",
    )

    assert artifact.status == "executed"
    assert artifact.telemetry_events_total == 2
    assert artifact.telemetry_events_consumed == 2
    assert replay.remaining() == 0
