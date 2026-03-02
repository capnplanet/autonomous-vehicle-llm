import json
import os
import time
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
from .vehicle_adapter import GroundHttpVehicleAdapter, GroundVehicleAdapter, VehicleAdapter


def _build_planner() -> tuple[object, str]:
    if os.getenv("HF_TOKEN") and (os.getenv("HF_MODEL_ID") or os.getenv("HF_ENDPOINT_URL")):
        return HuggingFacePlanner(), "huggingface"
    return CloudPlanner(), "stub"


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * pct
    low = int(rank)
    high = min(low + 1, len(ordered) - 1)
    frac = rank - low
    return ordered[low] * (1.0 - frac) + ordered[high] * frac


def run_demo() -> None:
    run_demo_with_options()


def run_demo_with_options(
    use_transport_primary: bool = True,
    enable_failover: bool = True,
    transport_config_path: str = "config/transport.default.json",
) -> None:
    planner, _planner_kind = _build_planner()
    verifier = PlanVerifier()
    policy = load_policy_config(Path("config/policy.default.json"))
    safety_kernel = SafetyKernel(config=policy)
    if use_transport_primary:
        transport_config = load_transport_config(Path(transport_config_path))
        primary_adapter: VehicleAdapter = GroundHttpVehicleAdapter(HttpCommandTransport(transport_config))
    else:
        primary_adapter = GroundVehicleAdapter()
    failover_adapter: VehicleAdapter | None = GroundVehicleAdapter() if enable_failover else None
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


def run_benchmark(
    runs: int,
    goal: str,
    output_path: str | None = None,
    vehicle_id: str = "veh-001",
    use_transport_primary: bool = True,
    enable_failover: bool = True,
    strict_pass: bool = False,
    require_transport_success: bool = False,
    transport_config_path: str = "config/transport.default.json",
) -> tuple[dict[str, object], Path | None]:
    if require_transport_success and not use_transport_primary:
        raise ValueError("require_transport_success requires transport primary mode")

    planner, planner_kind = _build_planner()
    verifier = PlanVerifier()
    policy = load_policy_config(Path("config/policy.default.json"))
    safety_kernel = SafetyKernel(config=policy)
    if use_transport_primary:
        transport_config = load_transport_config(Path(transport_config_path))
        primary_adapter: VehicleAdapter = GroundHttpVehicleAdapter(HttpCommandTransport(transport_config))
    else:
        primary_adapter = GroundVehicleAdapter()
    failover_adapter: VehicleAdapter | None = GroundVehicleAdapter() if enable_failover else None
    supervisor = EdgeSupervisor(
        safety_kernel=safety_kernel,
        adapter=primary_adapter,
        failover_adapter=failover_adapter,
    )

    run_records: list[dict[str, object]] = []
    plan_latencies_ms: list[float] = []
    exec_latencies_ms: list[float] = []
    verifier_passes = 0
    executions_succeeded = 0
    strict_successes = 0
    planner_errors = 0

    for index in range(runs):
        record: dict[str, object] = {
            "run": index + 1,
            "goal": goal,
            "vehicle_id": vehicle_id,
        }

        state = VehicleState(
            vehicle_id=vehicle_id,
            x=0,
            y=0,
            battery_pct=100,
            armed=False,
            connected=True,
            home_x=0,
            home_y=0,
        )

        plan_start = time.perf_counter()
        try:
            plan = planner.build_plan(goal=goal, vehicle_id=vehicle_id)
        except Exception as exc:  # noqa: BLE001
            planner_errors += 1
            record.update(
                {
                    "planner_status": "error",
                    "planner_error": str(exc),
                    "planning_latency_ms": (time.perf_counter() - plan_start) * 1000.0,
                }
            )
            run_records.append(record)
            continue

        planning_latency_ms = (time.perf_counter() - plan_start) * 1000.0
        plan_latencies_ms.append(planning_latency_ms)

        ok, errors = verifier.verify(plan)
        record["planning_latency_ms"] = planning_latency_ms
        record["planner_status"] = "ok"
        record["plan_action_count"] = len(plan.actions)
        record["verifier_ok"] = ok
        record["verifier_errors"] = errors

        if not ok:
            run_records.append(record)
            continue

        verifier_passes += 1

        exec_start = time.perf_counter()
        final_state, events = supervisor.run_plan(state, plan)
        exec_latency_ms = (time.perf_counter() - exec_start) * 1000.0
        exec_latencies_ms.append(exec_latency_ms)

        policy_blocks = [event for event in events if event.startswith("policy_block:")]
        system_faults = [event for event in events if event.startswith("system_fault:")]
        failover_uses = [event for event in events if event.startswith("failover_adapter_used:")]
        exec_actions = [event for event in events if event.startswith("exec:")]
        success = len(system_faults) == 0 and final_state.connected
        if success:
            executions_succeeded += 1

        transport_primary_ok = not use_transport_primary or len(failover_uses) == 0
        strict_success = (
            ok
            and len(system_faults) == 0
            and len(policy_blocks) == 0
            and len(exec_actions) == len(plan.actions)
            and final_state.connected
            and (transport_primary_ok if require_transport_success or strict_pass else True)
        )
        if strict_success:
            strict_successes += 1

        record.update(
            {
                "execution_latency_ms": exec_latency_ms,
                "execution_success": success,
                "strict_success": strict_success,
                "event_count": len(events),
                "exec_action_count": len(exec_actions),
                "policy_block_count": len(policy_blocks),
                "failover_use_count": len(failover_uses),
                "system_fault_count": len(system_faults),
                "transport_primary_ok": transport_primary_ok,
                "final_battery_pct": final_state.battery_pct,
                "events": events,
            }
        )
        run_records.append(record)

    summary: dict[str, object] = {
        "planner": planner_kind,
        "execution_mode": {
            "use_transport_primary": use_transport_primary,
            "enable_failover": enable_failover,
            "strict_pass": strict_pass,
            "require_transport_success": require_transport_success,
        },
        "runs": runs,
        "goal": goal,
        "planner_error_count": planner_errors,
        "planner_error_rate": planner_errors / runs if runs else 0.0,
        "verifier_pass_count": verifier_passes,
        "verifier_pass_rate": verifier_passes / runs if runs else 0.0,
        "execution_success_count": executions_succeeded,
        "execution_success_rate": executions_succeeded / runs if runs else 0.0,
        "strict_success_count": strict_successes,
        "strict_success_rate": strict_successes / runs if runs else 0.0,
        "planning_latency_ms": {
            "avg": (sum(plan_latencies_ms) / len(plan_latencies_ms)) if plan_latencies_ms else 0.0,
            "p95": _percentile(plan_latencies_ms, 0.95),
            "max": max(plan_latencies_ms) if plan_latencies_ms else 0.0,
        },
        "execution_latency_ms": {
            "avg": (sum(exec_latencies_ms) / len(exec_latencies_ms)) if exec_latencies_ms else 0.0,
            "p95": _percentile(exec_latencies_ms, 0.95),
            "max": max(exec_latencies_ms) if exec_latencies_ms else 0.0,
        },
        "records": run_records,
    }

    written_path: Path | None = None
    if output_path:
        written_path = Path(output_path)
        written_path.parent.mkdir(parents=True, exist_ok=True)
        written_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    return summary, written_path


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
