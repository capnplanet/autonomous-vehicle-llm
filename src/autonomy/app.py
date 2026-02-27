from pathlib import Path

from .audit import SignedAuditLogger
from .cloud_planner import CloudPlanner
from .edge_supervisor import EdgeSupervisor
from .models import VehicleState
from .plan_verifier import PlanVerifier
from .policy import load_policy_config
from .safety_kernel import SafetyKernel
from .vehicle_adapter import GroundVehicleAdapter


def run_demo() -> None:
    planner = CloudPlanner()
    verifier = PlanVerifier()
    policy = load_policy_config(Path("config/policy.default.json"))
    safety_kernel = SafetyKernel(config=policy)
    adapter = GroundVehicleAdapter()
    audit_logger = SignedAuditLogger(file_path=Path("logs/audit.log"), secret="dev-secret")
    supervisor = EdgeSupervisor(
        safety_kernel=safety_kernel,
        adapter=adapter,
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
