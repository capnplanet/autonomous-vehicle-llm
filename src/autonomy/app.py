import os
from pathlib import Path
from datetime import UTC, datetime

from .audit import SignedAuditLogger
from .cloud_planner import CloudPlanner
from .edge_supervisor import EdgeSupervisor
from .hf_planner import HuggingFacePlanner
from .localization import FusedTelemetryLocalizationEngine
from .obstacle_avoidance import ClearanceAwareAvoidancePlanner
from .models import VehicleState
from .plan_verifier import PlanVerifier
from .policy import load_policy_config, load_transport_config
from .perception import TelemetryPerceptionPipeline, TelemetrySchemaValidator
from .replay import DeterministicTelemetryReplay
from .scenarios import available_trace_scenarios
from .safety_kernel import SafetyKernel
from .trace import MissionTraceArtifact, MissionTraceRunner
from .transport import HttpCommandTransport
from .vehicle_adapter import GroundHttpVehicleAdapter, GroundVehicleAdapter


def run_demo() -> None:
    if os.getenv("HF_TOKEN") and (os.getenv("HF_MODEL_ID") or os.getenv("HF_ENDPOINT_URL")):
        planner = HuggingFacePlanner()
    else:
        planner = CloudPlanner()
    verifier = PlanVerifier()
    policy = load_policy_config(Path("config/policy.default.json"))
    transport_config = load_transport_config(Path("config/transport.default.json"))
    safety_kernel = SafetyKernel(config=policy)
    primary_adapter = GroundHttpVehicleAdapter(HttpCommandTransport(transport_config))
    failover_adapter = GroundVehicleAdapter()
    audit_logger = SignedAuditLogger(file_path=Path("logs/audit.log"), secret="dev-secret")
    supervisor = EdgeSupervisor(
        safety_kernel=safety_kernel,
        adapter=primary_adapter,
        failover_adapter=failover_adapter,
        audit_logger=audit_logger,
    )

    state = VehicleState(
        vehicle_id="veh-001",
        x=0,
        y=0,
        battery_pct=100,
        armed=False,
        connected=True,
        home_x=0,
        home_y=0,
    )

    plan = planner.build_plan(goal="patrol sector alpha", vehicle_id=state.vehicle_id)
    ok, errors = verifier.verify(plan)
    if not ok:
        print("Plan rejected:")
        for error in errors:
            print(f"- {error}")
        return

    final_state, events = supervisor.run_plan(state, plan)

    print("Execution events:")
    for event in events:
        print(f"- {event}")

    print("Final state:")
    print(final_state)


def list_trace_scenarios() -> list[str]:
    return sorted(available_trace_scenarios().keys())


def run_trace_scenario(
    scenario_name: str,
    output_path: str | None = None,
) -> tuple[MissionTraceArtifact, Path]:
    scenarios = available_trace_scenarios()
    scenario = scenarios.get(scenario_name)
    if scenario is None:
        names = ", ".join(sorted(scenarios.keys()))
        raise ValueError(f"unknown scenario '{scenario_name}'. Available scenarios: {names}")

    replay = DeterministicTelemetryReplay(scenario.telemetry_events)
    policy = load_policy_config(Path("config/policy.default.json"))
    safety_kernel = SafetyKernel(config=policy)
    perception = TelemetryPerceptionPipeline(
        telemetry_source=replay.next_event,
        schema_validator=TelemetrySchemaValidator("specs/events/telemetry.schema.json"),
    )
    supervisor = EdgeSupervisor(
        safety_kernel=safety_kernel,
        adapter=GroundVehicleAdapter(),
        perception_pipeline=perception,
        localization_engine=FusedTelemetryLocalizationEngine(max_staleness_s=policy.max_sensor_staleness_s),
        avoidance_planner=ClearanceAwareAvoidancePlanner(
            min_clearance_m=policy.min_obstacle_standoff_m,
            sidestep_m=3.0,
        ),
    )
    runner = MissionTraceRunner(supervisor=supervisor, verifier=PlanVerifier())

    if output_path is None:
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        path = Path("logs") / "traces" / f"{scenario.name}-{timestamp}.json"
    else:
        path = Path(output_path)

    artifact = runner.run(
        scenario=scenario.name,
        initial_state=scenario.initial_state,
        plan=scenario.plan,
        replay=replay,
        output_path=path,
    )
    return artifact, path
