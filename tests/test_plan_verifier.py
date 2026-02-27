from autonomy.cloud_planner import CloudPlanner
from autonomy.models import Action, ActionType, MissionPlan
from autonomy.plan_verifier import PlanVerifier


def test_planner_plan_is_valid():
    planner = CloudPlanner()
    verifier = PlanVerifier()

    plan = planner.build_plan("patrol", "veh-001")
    ok, errors = verifier.verify(plan)

    assert ok
    assert errors == []


def test_verifier_rejects_missing_arm_or_disarm():
    verifier = PlanVerifier()
    plan = MissionPlan(
        goal="bad",
        vehicle_id="veh-1",
        actions=[Action(type=ActionType.MOVE_TO, x=1, y=1, speed_mps=1)],
    )

    ok, errors = verifier.verify(plan)

    assert not ok
    assert "first action must be arm" in errors
    assert "last action must be disarm" in errors
