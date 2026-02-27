from autonomy.models import Action, ActionType, PolicyConfig, VehicleState
from autonomy.safety_kernel import SafetyKernel


def _state(**kwargs):
    base = dict(
        vehicle_id="veh-001",
        x=0.0,
        y=0.0,
        battery_pct=100.0,
        armed=True,
        connected=True,
        home_x=0.0,
        home_y=0.0,
    )
    base.update(kwargs)
    return VehicleState(**base)


def test_blocks_high_speed():
    kernel = SafetyKernel(PolicyConfig(max_speed_mps=5.0))
    ok, reason = kernel.precheck(
        _state(), Action(type=ActionType.MOVE_TO, x=1, y=1, speed_mps=7.0)
    )
    assert not ok
    assert reason == "speed exceeds policy"


def test_blocks_move_on_low_battery():
    kernel = SafetyKernel(PolicyConfig(min_battery_for_motion_pct=30.0))
    ok, reason = kernel.precheck(
        _state(battery_pct=20.0), Action(type=ActionType.MOVE_TO, x=1, y=1, speed_mps=2.0)
    )
    assert not ok
    assert reason == "battery below motion threshold"
