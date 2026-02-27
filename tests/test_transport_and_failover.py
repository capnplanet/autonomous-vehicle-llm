from autonomy.edge_supervisor import EdgeSupervisor
from autonomy.errors import AdapterExecutionError
from autonomy.models import Action, ActionType, MissionPlan, VehicleState
from autonomy.safety_kernel import SafetyKernel
from autonomy.transport import CommandTransport
from autonomy.vehicle_adapter import GroundHttpVehicleAdapter, GroundVehicleAdapter


class FailingTransport(CommandTransport):
    def send_command(self, vehicle_id: str, payload: dict[str, object]) -> None:
        raise AdapterExecutionError("simulated transport failure")


class SuccessTransport(CommandTransport):
    def __init__(self):
        self.calls = 0

    def send_command(self, vehicle_id: str, payload: dict[str, object]) -> None:
        self.calls += 1


def test_transport_adapter_executes_when_transport_succeeds():
    adapter = GroundHttpVehicleAdapter(SuccessTransport())
    state = VehicleState(
        vehicle_id="veh-1",
        x=0,
        y=0,
        battery_pct=100,
        armed=False,
        connected=True,
        home_x=0,
        home_y=0,
    )

    next_state = adapter.execute(state, Action(type=ActionType.ARM))

    assert next_state.armed is True


def test_supervisor_uses_failover_adapter_on_transport_failure():
    primary = GroundHttpVehicleAdapter(FailingTransport())
    failover = GroundVehicleAdapter()
    supervisor = EdgeSupervisor(SafetyKernel(), adapter=primary, failover_adapter=failover)
    state = VehicleState(
        vehicle_id="veh-1",
        x=0,
        y=0,
        battery_pct=100,
        armed=False,
        connected=True,
        home_x=0,
        home_y=0,
    )
    plan = MissionPlan(
        goal="test",
        vehicle_id="veh-1",
        actions=[Action(type=ActionType.ARM)],
    )

    final_state, events = supervisor.run_plan(state, plan)

    assert final_state.armed is True
    assert "failover_adapter_used:arm" in events
    assert "exec:arm" in events
