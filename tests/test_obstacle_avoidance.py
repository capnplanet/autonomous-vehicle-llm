from __future__ import annotations

from autonomy.localization import LocalizationEstimate
from autonomy.mapping import GeofenceMappingService
from autonomy.models import Action, ActionType
from autonomy.obstacle_avoidance import ClearanceAwareAvoidancePlanner
from autonomy.perception import DetectedObstacle, PerceptionFrame


def _localization() -> LocalizationEstimate:
    return LocalizationEstimate(
        x=0.0,
        y=0.0,
        heading_rad=0.0,
        vx_mps=0.0,
        vy_mps=0.0,
        position_std_m=0.3,
        timestamp_s=0.0,
        fresh=True,
    )


def test_avoidance_keeps_action_when_target_is_clear():
    planner = ClearanceAwareAvoidancePlanner(min_clearance_m=2.0, sidestep_m=3.0)
    mapping = GeofenceMappingService(geofence_abs_xy_limit_m=100)
    frame = PerceptionFrame(timestamp_s=0.0, obstacles=[])
    action = Action(type=ActionType.MOVE_TO, x=10.0, y=5.0, speed_mps=2.0)

    refined = planner.refine_action(action, _localization(), frame, mapping)

    assert refined.type == ActionType.MOVE_TO
    assert refined.x == 10.0
    assert refined.y == 5.0


def test_avoidance_sidesteps_when_target_blocked():
    planner = ClearanceAwareAvoidancePlanner(min_clearance_m=2.0, sidestep_m=3.0)
    mapping = GeofenceMappingService(geofence_abs_xy_limit_m=100)
    frame = PerceptionFrame(
        timestamp_s=0.0,
        obstacles=[DetectedObstacle(x=10.0, y=5.0, radius_m=1.5)],
    )
    action = Action(type=ActionType.MOVE_TO, x=10.0, y=5.0, speed_mps=2.0)

    refined = planner.refine_action(action, _localization(), frame, mapping)

    assert refined.type == ActionType.MOVE_TO
    assert (refined.x, refined.y) != (10.0, 5.0)


def test_avoidance_returns_hold_when_no_safe_candidate():
    planner = ClearanceAwareAvoidancePlanner(min_clearance_m=2.0, sidestep_m=2.0)
    mapping = GeofenceMappingService(geofence_abs_xy_limit_m=1.0)
    frame = PerceptionFrame(
        timestamp_s=0.0,
        obstacles=[DetectedObstacle(x=0.5, y=0.5, radius_m=2.0)],
    )
    action = Action(type=ActionType.MOVE_TO, x=0.5, y=0.5, speed_mps=2.0)

    refined = planner.refine_action(action, _localization(), frame, mapping)

    assert refined.type == ActionType.HOLD
